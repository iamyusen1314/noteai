"""One bounded Aliyun standard-SMS dispatch; no credential or payload logging."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import os
import re
import uuid
from urllib.parse import quote

import httpx

ENDPOINT = "https://dysmsapi.aliyuncs.com"
BUDGET_ID = "website-accounts-20260912"
# Conservative reservation: current single-segment price is CNY0.045.
RESERVE_MILLI_CNY = 60
TOTAL_MILLI_CNY = 60_000
DAILY_SEND_LIMIT = 100


@dataclass(frozen=True, repr=False)
class Config:
    sign_name: str
    template_code: str
    role_name: str


@dataclass(frozen=True)
class DeliveryResult:
    state: str
    code: str = ""
    request_id: str = ""
    biz_id: str = ""


def configuration() -> Config:
    if os.environ.get("NOTEAI_OTP_MODE", "disabled") != "aliyun_sms":
        raise ValueError("SMS disabled")
    sign = os.environ.get("NOTEAI_SMS_SIGN_NAME", "").strip()
    template = os.environ.get("NOTEAI_SMS_TEMPLATE_CODE", "").strip()
    role = os.environ.get("NOTEAI_SMS_RAM_ROLE", "").strip()
    # These are deployment inputs read back from the actual approved template and
    # platform settings, not an assertion that an arbitrary template is approved.
    if (not re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9]{2,16}", sign)
            or not re.fullmatch(r"SMS_[0-9]{5,20}", template)
            or not re.fullmatch(r"[A-Za-z0-9.@_-]{1,64}", role)
            or os.environ.get("NOTEAI_SMS_PLATFORM_LIMITS") != "100:1000"
            or os.environ.get("NOTEAI_SMS_SINGLE_SEGMENT") != "1"):
        raise ValueError("SMS configuration incomplete")
    return Config(sign, template, role)


def _credentials(role_name: str):
    from alibabacloud_credentials.client import Client
    from alibabacloud_credentials.models import Config as CredentialConfig
    return Client(CredentialConfig(
        type="ecs_ram_role", role_name=role_name, enable_imds_v2=True,
        disable_imds_v1=True, metadata_token_duration=60,
    )).get_credential()


def signed_request(parameters: dict[str, str], credential, *, timestamp: str, nonce: str):
    """ACS3 canonical query follows Aliyun's published V3 signing contract."""
    encode = lambda value: quote(str(value), safe="-_.~")
    query = "&".join(f"{encode(k)}={encode(v)}" for k, v in sorted(parameters.items()))
    payload_hash = hashlib.sha256(b"").hexdigest()
    headers = {
        "host": "dysmsapi.aliyuncs.com",
        "x-acs-action": "SendSms", "x-acs-version": "2017-05-25",
        "x-acs-date": timestamp, "x-acs-signature-nonce": nonce,
        "x-acs-content-sha256": payload_hash,
    }
    if credential.security_token:
        headers["x-acs-security-token"] = credential.security_token
    signed_headers, signature = _signature(query, headers, credential.access_key_secret)
    headers["Authorization"] = (
        f"ACS3-HMAC-SHA256 Credential={credential.access_key_id},"
        f"SignedHeaders={signed_headers},Signature={signature}"
    )
    return ENDPOINT + "/?" + query, headers


def _signature(query: str, headers: dict[str, str], secret: str):
    names = sorted(headers)
    canonical_headers = "".join(f"{k}:{headers[k].strip()}\n" for k in names)
    signed_headers = ";".join(names)
    canonical = "\n".join(("POST", "/", query, canonical_headers, signed_headers, headers["x-acs-content-sha256"]))
    to_sign = "ACS3-HMAC-SHA256\n" + hashlib.sha256(canonical.encode()).hexdigest()
    return signed_headers, hmac.new(secret.encode(), to_sign.encode(), hashlib.sha256).hexdigest()


def _reference(value) -> str:
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]{12,100}", value) else ""


def send(config: Config, *, phone: str, code: str, challenge_id: str) -> DeliveryResult:
    if not re.fullmatch(r"\+861[3-9][0-9]{9}", phone) or not re.fullmatch(r"[0-9]{6}", code):
        return DeliveryResult("rejected", "INVALID_INPUT")
    # httpx's normal INFO request line includes the query/OTP. This instance has
    # no business workers; do not allow client logging to expose SMS secrets.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).disabled = True
        logging.getLogger(name).propagate = False
        logging.getLogger(name).handlers = [logging.NullHandler()]
    try:
        credential = _credentials(config.role_name)
        if not all((credential.access_key_id, credential.access_key_secret, credential.security_token)):
            return DeliveryResult("rejected", "CREDENTIAL_UNAVAILABLE")
        url, headers = signed_request({
            "PhoneNumbers": phone.removeprefix("+86"), "SignName": config.sign_name,
            "TemplateCode": config.template_code,
            "TemplateParam": json.dumps({"code": code}, separators=(",", ":")),
            "OutId": challenge_id,
        }, credential, timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), nonce=uuid.uuid4().hex)
    except Exception:
        return DeliveryResult("rejected", "CREDENTIAL_UNAVAILABLE")
    try:
        # OutId is a reference, not a provider idempotency key. Never replay.
        with httpx.Client(transport=httpx.HTTPTransport(retries=0, trust_env=False), trust_env=False,
                          follow_redirects=False, timeout=httpx.Timeout(10, connect=5)) as client:
            with client.stream("POST", url, headers=headers, content=b"") as response:
                body = bytearray()
                for chunk in response.iter_bytes(chunk_size=4096):
                    body.extend(chunk)
                    if len(body) > 16_384:
                        return DeliveryResult("unknown", "RESPONSE_TOO_LARGE")
                payload = json.loads(body)
                if not isinstance(payload, dict):
                    return DeliveryResult("unknown", "INVALID_RESPONSE")
                raw_code = payload.get("Code")
                business_code = raw_code if raw_code in {
                    "OK", "isv.BUSINESS_LIMIT_CONTROL", "isv.AMOUNT_NOT_ENOUGH",
                    "isv.SMS_SIGNATURE_ILLEGAL", "isv.SMS_TEMPLATE_ILLEGAL",
                    "isv.MOBILE_NUMBER_ILLEGAL", "isv.RAM_PERMISSION_DENY",
                    "isv.OUT_OF_SERVICE", "isv.ACCOUNT_NOT_EXISTS", "isv.ACCOUNT_ABNORMAL",
                    "isv.TEMPLATE_MISSING_PARAMETERS", "isv.INVALID_PARAMETERS",
                } else ""
                request_id, biz_id = _reference(payload.get("RequestId")), _reference(payload.get("BizId"))
                if 200 <= response.status_code < 300 and business_code == "OK" and request_id and biz_id:
                    return DeliveryResult("accepted", business_code, request_id, biz_id)
                if response.status_code < 500 and isinstance(raw_code, str) and raw_code != "OK" and request_id:
                    return DeliveryResult("rejected", business_code or "PROVIDER_REJECTED", request_id, biz_id)
                return DeliveryResult("unknown", "UNCONFIRMED_RESPONSE", request_id, biz_id)
    except Exception:
        return DeliveryResult("unknown", "TRANSPORT_OR_RESPONSE_UNKNOWN")
