#!/bin/bash
set +x
set -Eeuo pipefail
umask 077
export PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
unset \
  ALIBABA_CLOUD_ACCESS_KEY_ID \
  ALIBABA_CLOUD_ACCESS_KEY_SECRET \
  ALIBABA_CLOUD_SECURITY_TOKEN \
  ALICLOUD_ACCESS_KEY \
  ALICLOUD_SECRET_KEY \
  ALICLOUD_SECURITY_TOKEN \
  HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy NO_PROXY no_proxy

readonly EXPECTED_ROLE='@@EXPECTED_ROLE@@'
readonly EXPECTED_HOST_LABEL='@@EXPECTED_HOST_LABEL@@'
readonly PUBLIC_KEY_SHA256='@@PUBLIC_KEY_SHA256@@'
readonly PUBLIC_KEY_B64='@@PUBLIC_KEY_B64@@'
readonly BUILDER_INSTANCE_ID='i-wz99180s9ig5ecq10uaj'
readonly ACR_INSTANCE_ID='cri-xpuhaclqkxlwy47t'
readonly ACR_API_HOST='cr-vpc.cn-shenzhen.aliyuncs.com'
readonly TASK_ROOT='/run/noteai-item24-payment-token-broker-v1'

phase='preflight'
token_request_started=0
token_received=0
envelope_count=0
cleanup_complete=0
task_root_owned=0

cleanup() {
  local cleanup_error=0
  if [ "$task_root_owned" = '1' ] && { [ -e "$TASK_ROOT" ] || [ -L "$TASK_ROOT" ]; }; then
    rm -rf -- "$TASK_ROOT" || cleanup_error=1
  fi
  if [ "$task_root_owned" = '1' ] && { [ -e "$TASK_ROOT" ] || [ -L "$TASK_ROOT" ]; }; then
    cleanup_error=1
  fi
  [ "$cleanup_error" = '0' ] || return 1
  cleanup_complete=1
}

on_exit() {
  local exit_code=$? cleanup_exit=0 outcome='FAIL'
  trap - EXIT
  cleanup || cleanup_exit=$?
  if [ "$token_request_started" = '1' ] || [ "$cleanup_exit" -ne 0 ]; then
    outcome='UNKNOWN'
  fi
  if [ "$exit_code" -ne 0 ] || [ "$cleanup_exit" -ne 0 ]; then
    printf 'NOTEAI_ITEM24_PAYMENT_TOKEN_BROKER=%s phase=%s token_request_started=%s token_received=%s envelope_count=%s cleanup_complete=%s readback_required=true automatic_retry_allowed=false\n' \
      "$outcome" "$phase" "$token_request_started" "$token_received" \
      "$envelope_count" "$cleanup_complete" >&2
  fi
  if [ "$exit_code" -eq 0 ] && [ "$cleanup_exit" -ne 0 ]; then
    exit_code="$cleanup_exit"
  fi
  exit "$exit_code"
}
trap on_exit EXIT

for command_name in awk base64 grep openssl python3 sha256sum stat; do
  command -v "$command_name" >/dev/null
done
[ "$(id -u)" = '0' ]
[ "$(uname -s)" = 'Linux' ]
[ "$(uname -m)" = 'x86_64' ]
[[ "$EXPECTED_ROLE" =~ ^[A-Za-z0-9.@_-]{1,64}$ ]]
[[ "$EXPECTED_HOST_LABEL" =~ ^(API-C|Worker-C|Worker-F)$ ]]
[[ "$PUBLIC_KEY_SHA256" =~ ^[0-9a-f]{64}$ ]]
[[ "$PUBLIC_KEY_B64" =~ ^[A-Za-z0-9+/=]{700,1200}$ ]]
[ ! -e "$TASK_ROOT" ] && [ ! -L "$TASK_ROOT" ]
mkdir -m 0700 -- "$TASK_ROOT"
task_root_owned=1
[ "$(stat -c '%u:%g:%a' "$TASK_ROOT")" = '0:0:700' ]

phase='public_key_validation'
public_key_path="$TASK_ROOT/${EXPECTED_HOST_LABEL,,}.pem"
printf '%s' "$PUBLIC_KEY_B64" | base64 -d >"$public_key_path"
chmod 0600 -- "$public_key_path"
[ "$(stat -c '%u:%g:%a:%h' "$public_key_path")" = '0:0:600:1' ]
grep -Fqx -- '-----BEGIN PUBLIC KEY-----' "$public_key_path"
grep -Fqx -- '-----END PUBLIC KEY-----' "$public_key_path"
openssl pkey -pubin -in "$public_key_path" -text -noout 2>/dev/null | grep -Fq -- 'Public-Key: (3072 bit)'
[ "$(openssl pkey -pubin -in "$public_key_path" -outform DER 2>/dev/null | sha256sum | awk '{print $1}')" = "$PUBLIC_KEY_SHA256" ]

phase='single_jit_token_and_envelope'
token_request_started=1
broker_output="$({
  python3 - "$TASK_ROOT" "$EXPECTED_ROLE" "$EXPECTED_HOST_LABEL" \
    "$PUBLIC_KEY_SHA256" "$PUBLIC_KEY_B64" <<'PY'
import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import stat
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

(
    task_root,
    expected_role,
    expected_host_label,
    public_key_sha,
    public_key_b64,
) = sys.argv[1:]

builder_instance_id = "i-wz99180s9ig5ecq10uaj"
acr_instance_id = "cri-xpuhaclqkxlwy47t"
acr_api_host = "cr-vpc.cn-shenzhen.aliyuncs.com"
empty_sha256 = hashlib.sha256(b"").hexdigest()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("redirect")


opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    NoRedirect(),
)


def bounded_request(request: urllib.request.Request, *, limit: int, timeout: int) -> bytes:
    with opener.open(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError("http_status")
        payload = response.read(limit + 1)
    if not payload or len(payload) > limit:
        raise RuntimeError("response_size")
    return payload


def imds(path: str, token: str, *, limit: int = 65536) -> bytes:
    request = urllib.request.Request(
        f"http://100.100.100.200/latest/{path}",
        headers={"X-aliyun-ecs-metadata-token": token},
    )
    return bounded_request(request, limit=limit, timeout=3)


token_request = urllib.request.Request(
    "http://100.100.100.200/latest/api/token",
    method="PUT",
    headers={"X-aliyun-ecs-metadata-token-ttl-seconds": "600"},
)
imds_token = bounded_request(token_request, limit=4096, timeout=3).decode("ascii")
if not imds_token or len(imds_token) > 2048:
    raise RuntimeError("imds_token_shape")
if any(ord(character) < 33 or ord(character) > 126 for character in imds_token):
    raise RuntimeError("imds_token_shape")

observed_instance_id = imds("meta-data/instance-id", imds_token, limit=256).decode("ascii")
if observed_instance_id != builder_instance_id:
    raise RuntimeError("builder_identity")
observed_role = imds("meta-data/ram/security-credentials/", imds_token, limit=256).decode("ascii").strip()
if observed_role != expected_role:
    raise RuntimeError("role_identity")

credentials_payload = json.loads(
    imds(
        f"meta-data/ram/security-credentials/{urllib.parse.quote(observed_role, safe='')}",
        imds_token,
    ).decode("utf-8")
)
if not isinstance(credentials_payload, dict) or credentials_payload.get("Code") != "Success":
    raise RuntimeError("credential_shape")
access_key_id = credentials_payload.get("AccessKeyId")
access_key_secret = credentials_payload.get("AccessKeySecret")
security_token = credentials_payload.get("SecurityToken")
expiration = credentials_payload.get("Expiration")
if not all(isinstance(value, str) and value for value in (
    access_key_id,
    access_key_secret,
    security_token,
    expiration,
)):
    raise RuntimeError("credential_shape")
if not 8 <= len(access_key_id) <= 128:
    raise RuntimeError("credential_shape")
if not 16 <= len(access_key_secret) <= 256:
    raise RuntimeError("credential_shape")
if not 16 <= len(security_token) <= 8192:
    raise RuntimeError("credential_shape")
credential_expiration = None
if expiration.endswith("Z"):
    expiration_body = expiration[:-1]
elif expiration.endswith("+00:00"):
    expiration_body = expiration[:-6]
else:
    expiration_body = ""
for expiration_format in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
    try:
        credential_expiration = dt.datetime.strptime(expiration_body, expiration_format).replace(tzinfo=dt.timezone.utc)
        break
    except ValueError:
        pass
if credential_expiration is None:
    raise RuntimeError("credential_expiration")
now = dt.datetime.now(dt.timezone.utc)
if credential_expiration <= now + dt.timedelta(minutes=57):
    raise RuntimeError("credential_ttl")


def percent(value: str) -> str:
    return urllib.parse.quote_plus(value, safe="-_.~").replace("+", "%20").replace("*", "%2A").replace("%7E", "~")


query = {"InstanceId": acr_instance_id}
canonical_query = "&".join(
    f"{percent(key)}={percent(value)}" for key, value in sorted(query.items())
)
headers = {
    "host": acr_api_host,
    "x-acs-action": "GetAuthorizationToken",
    "x-acs-content-sha256": empty_sha256,
    "x-acs-date": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    "x-acs-security-token": security_token,
    "x-acs-signature-nonce": uuid.uuid4().hex,
    "x-acs-version": "2018-12-01",
}
header_items = sorted(headers.items())
canonical_headers = "\n".join(f"{key}:{value}" for key, value in header_items) + "\n"
signed_headers = ";".join(key for key, _ in header_items)
headers = dict(header_items)
canonical_request = (
    f"POST\n/\n{canonical_query}\n{canonical_headers}\n"
    f"{signed_headers}\n{empty_sha256}"
)
algorithm = "ACS3-HMAC-SHA256"
string_to_sign = f"{algorithm}\n{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
signature = hmac.new(
    access_key_secret.encode("utf-8"),
    string_to_sign.encode("utf-8"),
    hashlib.sha256,
).hexdigest()
headers["Authorization"] = (
    f"{algorithm} Credential={access_key_id},"
    f"SignedHeaders={signed_headers},Signature={signature}"
)
request = urllib.request.Request(
    f"https://{acr_api_host}/?{canonical_query}",
    method="POST",
    headers=headers,
)
try:
    response_payload = bounded_request(request, limit=65536, timeout=15)
except urllib.error.HTTPError as exc:
    exc.read(65537)
    raise RuntimeError("authorization_http") from None
authorization = json.loads(response_payload.decode("utf-8"))
if not isinstance(authorization, dict):
    raise RuntimeError("authorization_shape")
if authorization.get("IsSuccess") is not True or authorization.get("Code") != "success":
    raise RuntimeError("authorization_status")
request_id = authorization.get("RequestId")
expire_time = authorization.get("ExpireTime")
username = authorization.get("TempUsername")
registry_token = authorization.get("AuthorizationToken")
if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9-]{8,128}", request_id):
    raise RuntimeError("request_id_shape")
if not isinstance(expire_time, int) or expire_time <= int(now.timestamp() * 1000) + 3_420_000:
    raise RuntimeError("token_ttl")
if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9_.:@+-]{1,256}", username):
    raise RuntimeError("username_shape")
if not isinstance(registry_token, str) or not 1 <= len(registry_token.encode("utf-8")) <= 300:
    raise RuntimeError("token_shape")
if any(ord(character) < 33 or ord(character) > 126 for character in registry_token):
    raise RuntimeError("token_shape")


def validate_public_key(label: str, expected_sha: str) -> str:
    path = os.path.join(task_root, f"{label}.pem")
    try:
        with open(path, "rb") as handle:
            payload = handle.read(1001)
    except OSError as exc:
        raise RuntimeError("public_key_read") from exc
    if not 500 <= len(payload) <= 1000:
        raise RuntimeError("public_key_size")
    if not payload.startswith(b"-----BEGIN PUBLIC KEY-----\n") or not payload.endswith(b"-----END PUBLIC KEY-----\n"):
        raise RuntimeError("public_key_pem")
    metadata = os.lstat(path)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_gid != 0
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink != 1
    ):
        raise RuntimeError("public_key_metadata")
    check = subprocess.run(
        ["openssl", "pkey", "-pubin", "-in", path, "-text", "-noout"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if b"Public-Key: (3072 bit)" not in check.stdout:
        raise RuntimeError("public_key_bits")
    der = subprocess.run(
        ["openssl", "pkey", "-pubin", "-in", path, "-outform", "DER"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout
    if hashlib.sha256(der).hexdigest() != expected_sha:
        raise RuntimeError("public_key_hash")
    return path


path = validate_public_key(
    expected_host_label.lower(),
    public_key_sha,
)
ciphertext = subprocess.run(
    [
        "openssl",
        "pkeyutl",
        "-encrypt",
        "-pubin",
        "-inkey",
        path,
        "-pkeyopt",
        "rsa_padding_mode:oaep",
        "-pkeyopt",
        "rsa_oaep_md:sha256",
        "-pkeyopt",
        "rsa_mgf1_md:sha256",
    ],
    input=registry_token.encode("utf-8"),
    check=True,
    stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
).stdout
if len(ciphertext) != 384:
    raise RuntimeError("ciphertext_size")
envelope = {
    "host": expected_host_label,
    "public_key_sha256": public_key_sha,
    "ciphertext_b64": base64.b64encode(ciphertext).decode("ascii"),
}

result = {
    "status": "PASS",
    "request_id": request_id,
    "expire_time_ms": expire_time,
    "registry_username": username,
    "envelope": envelope,
    "token_requests": 1,
    "automatic_retry_allowed": False,
}
sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")))
PY
} 2>/dev/null)"
token_received=1
envelope_count=1

phase='broker_cleanup'
cleanup
[ "$cleanup_complete" = '1' ]
phase='accepted'
printf 'NOTEAI_ITEM24_PAYMENT_TOKEN_BROKER=%s\n' "$broker_output"
trap - EXIT
