#!/usr/bin/env python3
"""Secret-contained, single-request Alibaba Cloud RPC transport for Item 26.

This module is a source component, not an operator launcher.  Its command-line
entry point is deliberately inert.  A separately accepted bridge must first
freeze the exact logical request with the installed Item 26 collector, project
only its temporary STS fields into a minimized anonymous-socket envelope, and
then call ``dispatch_authorized_fds`` exactly once.  This module never sees
OAuth access/refresh tokens, never reads a credential path, and never retries a
provider request.
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import hmac
import http.client
import json
import math
import os
import re
import resource
import socket
import ssl
import stat
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional
from urllib.parse import quote


SOURCE_SCHEMA = "noteai.item26.aliyun-official-read-v2-source.v1"
CREDENTIAL_SCHEMA = "noteai.item26.aliyun-temporary-sts-envelope.v1"
PROFILE_NAME = "noteai-item26-m1"
REGION_ID = "cn-shenzhen"
MAX_REQUEST_BYTES = 32768
MAX_CREDENTIAL_BYTES = 131072
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
CONNECT_AND_READ_TIMEOUT_SECONDS = 30
MINIMUM_STS_VALIDITY_SECONDS = 16 * 60
MAXIMUM_STS_VALIDITY_SECONDS = 24 * 60 * 60
MAX_JSON_DEPTH = 64
MAX_JSON_INTEGER_DIGITS = 128
MAX_CREDENTIAL_VALUE_BYTES = 16384
COST_STOP_LOOKUP_START = "2026-08-16T14:38:00Z"
COST_STOP_LOOKUP_END = "2026-08-16T14:46:00Z"
CLONE_CREATE_LOOKUP_START = "2026-08-12T00:00:00Z"
CLONE_CREATE_LOOKUP_END = "2026-08-13T00:00:00Z"
EXPECTED_OLD_CLONE_SHA256 = (
    "820121638125fcebe3b7c03f3416ddae1fef1a0a9f1de731320fa75dd69a1525"
)
EXPECTED_SOURCE_SHA256 = (
    "d3712c09b28ee82257ab128fa1b5ba79b223f8b774e5fa20f761a2c4782eee8d"
)
SYSTEM_CA_PATH = "/etc/ssl/cert.pem"
SYSTEM_CA_BYTES = 333483
SYSTEM_CA_SHA256 = (
    "9dae8d76e55cb08991f2b672d58999ea15560d910759c16b544f843bdffbb994"
)

_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_ACCESS_KEY_ID = re.compile(r"^STS\.[A-Za-z0-9._-]{8,124}$")
_FIXED_TRANSPORTS = MappingProxyType(
    {
        ("LookupEvents", "2020-07-06"): (
            "actiontrail.cn-shenzhen.aliyuncs.com",
            True,
        ),
        ("DescribeDBInstances", "2014-08-15"): (
            "rds.aliyuncs.com",
            False,
        ),
        ("QueryInstanceBill", "2017-12-14"): (
            "business.aliyuncs.com",
            True,
        ),
    }
)
__all__ = ("dispatch_authorized_fds", "source_only_status", "main")


class TransportError(ValueError):
    """Fixed-code failure that never includes provider or credential values."""

    def __init__(self, code: str, *, cloud_dispatch_count: int = 0):
        super().__init__(code)
        self.code = code
        self.cloud_dispatch_count = cloud_dispatch_count


@dataclass(frozen=True)
class TemporaryCredential:
    access_key_id: str = field(repr=False)
    access_key_secret: str = field(repr=False)
    security_token: str = field(repr=False)
    expiration: int


@dataclass(frozen=True)
class DispatchResult:
    response: bytes = field(repr=False)
    cloud_call_count: int
    cloud_write_count: int
    automatic_retry_count: int


def canonical_json(value: Any) -> bytes:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise TransportError("json_canonical") from exc


def _bounded_int(raw: str, code: str) -> int:
    if len(raw.lstrip("-")) > MAX_JSON_INTEGER_DIGITS:
        raise TransportError(code)
    try:
        return int(raw)
    except ValueError as exc:
        raise TransportError(code) from exc


def _bounded_float(raw: str) -> float:
    if len(raw.lstrip("-")) > MAX_JSON_INTEGER_DIGITS:
        raise TransportError("json_number")
    try:
        value = float(raw)
    except ValueError as exc:
        raise TransportError("json_number") from exc
    if not math.isfinite(value):
        raise TransportError("json_number")
    return value


def _reject_constant(_raw: str) -> Any:
    raise TransportError("json_number")


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise TransportError("json_duplicate_key")
        value[key] = item
    return value


def _depth(value: Any, current: int = 0) -> None:
    if current > MAX_JSON_DEPTH:
        raise TransportError("json_depth")
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise TransportError("json_key")
            _depth(item, current + 1)
    elif type(value) is list:
        for item in value:
            _depth(item, current + 1)


def _strict_json(raw: bytes, maximum: int, code: str) -> dict[str, Any]:
    if type(raw) is not bytes or not 1 <= len(raw) <= maximum or b"\0" in raw:
        raise TransportError(code + "_shape")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicates,
            parse_int=lambda item: _bounded_int(item, code + "_number"),
            parse_float=_bounded_float,
            parse_constant=_reject_constant,
        )
    except TransportError:
        raise
    except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise TransportError(code + "_json") from exc
    if type(value) is not dict:
        raise TransportError(code + "_object")
    _depth(value)
    return value


def _credential_text(value: Any, code: str, maximum: int) -> str:
    if type(value) is not str or not value:
        raise TransportError(code)
    try:
        raw = value.encode("ascii")
    except UnicodeError:
        raise TransportError(code) from None
    if len(raw) > maximum or any(byte < 0x21 or byte > 0x7E for byte in raw):
        raise TransportError(code)
    return value


def _load_temporary_credential_envelope(
    credential_raw: bytes,
    *,
    now_unix: int,
) -> TemporaryCredential:
    """Load a bridge-minimized temporary STS envelope, never CLI config."""

    value = _strict_json(credential_raw, MAX_CREDENTIAL_BYTES, "credential")
    if canonical_json(value) != credential_raw:
        raise TransportError("credential_canonical")
    if set(value) != {
        "schema",
        "source",
        "profile_name",
        "region_id",
        "access_key_id",
        "access_key_secret",
        "security_token",
        "expiration_unix",
    }:
        raise TransportError("credential_contract")
    if (
        value["schema"] != CREDENTIAL_SCHEMA
        or value["source"] != "BRIDGE_PROJECTED_CLI_OAUTH_TEMPORARY_STS"
        or value["profile_name"] != PROFILE_NAME
        or value["region_id"] != REGION_ID
    ):
        raise TransportError("credential_identity")
    access_key_id = _credential_text(
        value["access_key_id"], "credential_access_key_id", 128
    )
    if _ACCESS_KEY_ID.fullmatch(access_key_id) is None:
        raise TransportError("credential_access_key_id")
    access_key_secret = _credential_text(
        value["access_key_secret"],
        "credential_access_key_secret",
        256,
    )
    security_token = _credential_text(
        value["security_token"],
        "credential_security_token",
        MAX_CREDENTIAL_VALUE_BYTES,
    )
    expiration = value["expiration_unix"]
    if (
        type(expiration) is not int
        or type(now_unix) is not int
        or not MINIMUM_STS_VALIDITY_SECONDS
        <= expiration - now_unix
        <= MAXIMUM_STS_VALIDITY_SECONDS
    ):
        raise TransportError("credential_expired")
    return TemporaryCredential(
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        security_token=security_token,
        expiration=expiration,
    )


def _text(value: Any, code: str, maximum: int = 4096) -> str:
    if type(value) is not str or not value:
        raise TransportError(code)
    try:
        raw = value.encode("ascii")
    except UnicodeError:
        raise TransportError(code) from None
    if len(raw) > maximum or any(byte < 0x20 or byte > 0x7E for byte in raw):
        raise TransportError(code)
    return value


def _positive_int(value: Any, code: str, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise TransportError(code)
    return value


def _lookup_attributes(value: Any) -> list[dict[str, str]]:
    if type(value) is not list or len(value) != 2:
        raise TransportError("request_lookup_attributes")
    result: list[dict[str, str]] = []
    for row in value:
        if type(row) is not dict or set(row) != {"Key", "Value"}:
            raise TransportError("request_lookup_attributes")
        result.append(
            {
                "Key": _text(row["Key"], "request_lookup_key", 64),
                "Value": _text(row["Value"], "request_lookup_value", 512),
            }
        )
    allowed = (
        result
        == [
            {"Key": "ServiceName", "Value": "Rds"},
            {"Key": "EventRW", "Value": "Write"},
        ]
        or (
            result[0] == {"Key": "EventName", "Value": "CloneDBInstance"}
            and result[1]["Key"] == "ResourceName"
        )
    )
    if not allowed:
        raise TransportError("request_lookup_attributes")
    return result


def _value_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _validate_logical_request(request_raw: bytes) -> dict[str, Any]:
    value = _strict_json(request_raw, MAX_REQUEST_BYTES, "request")
    if canonical_json(value) != request_raw:
        raise TransportError("request_canonical")
    operation = value.get("Action")
    version = value.get("Version")
    if (operation, version) not in _FIXED_TRANSPORTS:
        raise TransportError("request_operation")
    if operation == "LookupEvents":
        allowed_keys = {
            "Action",
            "Version",
            "Direction",
            "StartTime",
            "EndTime",
            "LookupAttribute",
            "MaxResults",
        }
        if "NextToken" in value:
            allowed_keys.add("NextToken")
        if (
            set(value) != allowed_keys
            or value["Direction"] != "FORWARD"
            or value["MaxResults"] != "50"
        ):
            raise TransportError("request_lookup_contract")
        start = _text(value["StartTime"], "request_lookup_start", 64)
        end = _text(value["EndTime"], "request_lookup_end", 64)
        attributes = _lookup_attributes(value["LookupAttribute"])
        if attributes == [
            {"Key": "ServiceName", "Value": "Rds"},
            {"Key": "EventRW", "Value": "Write"},
        ]:
            if (start, end) != (
                COST_STOP_LOOKUP_START,
                COST_STOP_LOOKUP_END,
            ):
                raise TransportError("request_lookup_window")
        elif (
            (start, end)
            != (CLONE_CREATE_LOOKUP_START, CLONE_CREATE_LOOKUP_END)
            or _value_sha256(attributes[1]["Value"])
            != EXPECTED_OLD_CLONE_SHA256
        ):
            raise TransportError("request_lookup_identity")
        if "NextToken" in value:
            _text(value["NextToken"], "request_next_token", 4096)
    elif operation == "DescribeDBInstances":
        if (
            set(value)
            != {
                "Action",
                "Version",
                "RegionId",
                "DBInstanceId",
                "PageNumber",
                "PageSize",
            }
            or value["RegionId"] != REGION_ID
            or value["PageNumber"] != 1
            or value["PageSize"] != 100
        ):
            raise TransportError("request_describe_contract")
        instance_id = _text(
            value["DBInstanceId"],
            "request_instance_id",
            256,
        )
        if _value_sha256(instance_id) not in {
            EXPECTED_OLD_CLONE_SHA256,
            EXPECTED_SOURCE_SHA256,
        }:
            raise TransportError("request_instance_identity")
    else:
        expected = {
            "Action": "QueryInstanceBill",
            "Version": "2017-12-14",
            "BillingCycle": "2026-08",
            "ProductCode": "rds",
            "SubscriptionType": "PayAsYouGo",
            "IsBillingItem": False,
            "IsHideZeroCharge": False,
            "Granularity": "MONTHLY",
            "PageNum": 1,
            "PageSize": 300,
        }
        if value != expected:
            raise TransportError("request_billing_contract")
    return value


def _rpc_value(value: Any) -> str:
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        return str(value)
    if type(value) in {dict, list}:
        return canonical_json(value)[:-1].decode("ascii")
    if type(value) is str:
        return value
    raise TransportError("request_parameter_type")


def _percent(value: str) -> str:
    return quote(value, safe="-_.~")


def _signed_rpc_parameters(
    logical_request: Mapping[str, Any],
    credential: TemporaryCredential,
    *,
    timestamp: str,
    nonce: str,
) -> tuple[str, dict[str, str]]:
    operation = logical_request.get("Action")
    version = logical_request.get("Version")
    transport = _FIXED_TRANSPORTS.get((operation, version))
    if transport is None:
        raise TransportError("request_operation")
    if type(timestamp) is not str or not timestamp.endswith("Z") or len(timestamp) != 20:
        raise TransportError("timestamp")
    if type(nonce) is not str or _HEX32.fullmatch(nonce) is None:
        raise TransportError("nonce")
    host, adds_region = transport
    parameters = {key: _rpc_value(value) for key, value in logical_request.items()}
    if adds_region:
        parameters["RegionId"] = REGION_ID
    parameters.update(
        {
            "AccessKeyId": credential.access_key_id,
            "Format": "JSON",
            "SecurityToken": credential.security_token,
            "SignatureMethod": "HMAC-SHA1",
            "SignatureNonce": nonce,
            "SignatureType": "",
            "SignatureVersion": "1.0",
            "Timestamp": timestamp,
        }
    )
    canonical_query = "&".join(
        _percent(key) + "=" + _percent(parameters[key])
        for key in sorted(parameters)
    )
    string_to_sign = "POST&%2F&" + _percent(canonical_query)
    signature = base64.b64encode(
        hmac.new(
            (credential.access_key_secret + "&").encode("utf-8"),
            string_to_sign.encode("ascii"),
            hashlib.sha1,
        ).digest()
    ).decode("ascii")
    parameters["Signature"] = signature
    return host, parameters


def _default_now() -> tuple[int, str]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    return int(now.timestamp()), now.strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_nonce() -> str:
    # The nonce is public anti-replay material.  ``secrets`` is imported only
    # here so tests can prove deterministic signing without patching globals.
    import secrets

    return secrets.token_hex(16)


def _system_ca_payload() -> bytes:
    try:
        before = os.lstat(SYSTEM_CA_PATH)
    except OSError:
        raise TransportError("system_ca_identity") from None
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or stat.S_IMODE(before.st_mode) != 0o644
        or before.st_uid != 0
        or before.st_gid != 0
        or before.st_nlink != 1
        or before.st_size != SYSTEM_CA_BYTES
    ):
        raise TransportError("system_ca_identity")
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(SYSTEM_CA_PATH, flags)
        try:
            opened = os.fstat(descriptor)
            identity = (
                opened.st_dev,
                opened.st_ino,
                opened.st_mode,
                opened.st_uid,
                opened.st_gid,
                opened.st_nlink,
                opened.st_size,
                opened.st_mtime_ns,
                opened.st_ctime_ns,
            )
            expected = (
                before.st_dev,
                before.st_ino,
                before.st_mode,
                before.st_uid,
                before.st_gid,
                before.st_nlink,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
            if identity != expected:
                raise TransportError("system_ca_identity")
            chunks: list[bytes] = []
            size = 0
            while size <= SYSTEM_CA_BYTES:
                chunk = os.read(
                    descriptor,
                    min(65536, SYSTEM_CA_BYTES + 1 - size),
                )
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            closed = os.fstat(descriptor)
            if (
                closed.st_dev,
                closed.st_ino,
                closed.st_mode,
                closed.st_size,
                closed.st_mtime_ns,
                closed.st_ctime_ns,
            ) != (
                opened.st_dev,
                opened.st_ino,
                opened.st_mode,
                opened.st_size,
                opened.st_mtime_ns,
                opened.st_ctime_ns,
            ):
                raise TransportError("system_ca_identity")
        finally:
            os.close(descriptor)
        after = os.lstat(SYSTEM_CA_PATH)
    except TransportError:
        raise
    except OSError:
        raise TransportError("system_ca_read") from None
    if (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_uid,
        after.st_gid,
        after.st_nlink,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ) != expected:
        raise TransportError("system_ca_identity")
    raw = b"".join(chunks)
    if (
        len(raw) != SYSTEM_CA_BYTES
        or hashlib.sha256(raw).hexdigest() != SYSTEM_CA_SHA256
    ):
        raise TransportError("system_ca_hash")
    return raw


def _default_connection(
    host: str,
    *,
    timeout: int,
) -> http.client.HTTPSConnection:
    if host not in {row[0] for row in _FIXED_TRANSPORTS.values()}:
        raise TransportError("transport_host")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    try:
        context.load_verify_locations(
            cadata=_system_ca_payload().decode("ascii")
        )
    except TransportError:
        raise
    except (UnicodeError, ssl.SSLError):
        raise TransportError("system_ca_load") from None
    if context.keylog_filename is not None:
        raise TransportError("tls_keylog")
    return http.client.HTTPSConnection(host, timeout=timeout, context=context)


def _read_response(response: Any) -> bytes:
    content_type = response.getheader("Content-Type", "")
    if type(content_type) is not str or not content_type.lower().split(";", 1)[0].strip() in {
        "application/json",
        "text/json",
    }:
        raise TransportError("response_content_type", cloud_dispatch_count=1)
    content_encoding = response.getheader("Content-Encoding", "")
    if content_encoding not in {None, "", "identity"}:
        raise TransportError("response_content_encoding", cloud_dispatch_count=1)
    content_length = response.getheader("Content-Length")
    declared: Optional[int] = None
    if content_length not in {None, ""}:
        try:
            declared = int(content_length)
        except (TypeError, ValueError) as exc:
            raise TransportError(
                "response_content_length",
                cloud_dispatch_count=1,
            ) from exc
        if not 1 <= declared <= MAX_RESPONSE_BYTES:
            raise TransportError(
                "response_content_length",
                cloud_dispatch_count=1,
            )
    try:
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    except Exception:
        raise TransportError("response_read", cloud_dispatch_count=1) from None
    if not 1 <= len(raw) <= MAX_RESPONSE_BYTES:
        raise TransportError("response_shape", cloud_dispatch_count=1)
    if declared is not None and len(raw) != declared:
        raise TransportError(
            "response_content_length",
            cloud_dispatch_count=1,
        )
    try:
        value = _strict_json(raw, MAX_RESPONSE_BYTES, "response")
    except TransportError as exc:
        raise TransportError(
            exc.code,
            cloud_dispatch_count=1,
        ) from None
    # Parsing proves a bounded JSON object with no duplicate keys, while the
    # exact provider bytes remain the collector's custody and hash authority.
    del value
    return raw


def _dispatch_authorized_bytes(
    request_raw: bytes,
    credential_raw: bytes,
    *,
    now: Optional[tuple[int, str]] = None,
    nonce: Optional[str] = None,
    connection_factory: Callable[..., Any] = _default_connection,
) -> DispatchResult:
    """Perform one allowlisted read-only RPC request with no retry path."""

    logical_request = _validate_logical_request(request_raw)
    now_unix, timestamp = _default_now() if now is None else now
    credential = _load_temporary_credential_envelope(
        credential_raw,
        now_unix=now_unix,
    )
    nonce_value = _default_nonce() if nonce is None else nonce
    host, parameters = _signed_rpc_parameters(
        logical_request,
        credential,
        timestamp=timestamp,
        nonce=nonce_value,
    )
    query = "&".join(
        _percent(key) + "=" + _percent(parameters[key])
        for key in sorted(parameters)
    )
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "identity",
        "Content-Length": "0",
        "Content-Type": "application/x-www-form-urlencoded",
        "Host": host,
        "User-Agent": "noteai-item26-official-read-v2",
        "x-acs-action": str(logical_request["Action"]),
        "x-acs-version": str(logical_request["Version"]),
    }
    connection = None
    request_started = False
    try:
        connection = connection_factory(
            host,
            timeout=CONNECT_AND_READ_TIMEOUT_SECONDS,
        )
        request_started = True
        connection.request("POST", "/?" + query, body=b"", headers=headers)
        response = connection.getresponse()
        if type(response.status) is not int or response.status != 200:
            raise TransportError(
                "response_http_status",
                cloud_dispatch_count=1,
            )
        response_raw = _read_response(response)
    except TransportError:
        raise
    except Exception:
        raise TransportError(
            "transport_failure",
            cloud_dispatch_count=1 if request_started else 0,
        ) from None
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
    return DispatchResult(
        response=response_raw,
        cloud_call_count=1,
        cloud_write_count=0,
        automatic_retry_count=0,
    )


def _anonymous_socket_fd(fd: int, code: str) -> tuple[int, int, int]:
    if type(fd) is not int or fd < 3:
        raise TransportError(code)
    duplicate = -1
    try:
        row = os.fstat(fd)
        is_tty = os.isatty(fd)
        descriptor_flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        duplicate = os.dup(fd)
        channel = socket.socket(fileno=duplicate)
        duplicate = -1
        try:
            family = channel.family
            kind = channel.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE)
            local_name = channel.getsockname()
            peer_name = channel.getpeername()
        finally:
            channel.close()
    except OSError:
        if duplicate >= 0:
            os.close(duplicate)
        raise TransportError(code) from None
    if (
        is_tty
        or not stat.S_ISSOCK(row.st_mode)
        or family != socket.AF_UNIX
        or kind != socket.SOCK_STREAM
        or local_name not in {"", b""}
        or peer_name not in {"", b""}
        or descriptor_flags & os.O_ACCMODE != os.O_RDWR
        or descriptor_flags & os.O_NONBLOCK
        or descriptor_flags & getattr(os, "O_ASYNC", 0)
    ):
        raise TransportError(code)
    return (row.st_dev, row.st_ino, stat.S_IFMT(row.st_mode))


def _read_fd(fd: int, maximum: int, code: str) -> bytes:
    _anonymous_socket_fd(fd, code + "_identity")
    chunks: list[bytes] = []
    size = 0
    try:
        while size <= maximum:
            chunk = os.read(fd, min(65536, maximum + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
    except OSError:
        raise TransportError(code + "_read") from None
    raw = b"".join(chunks)
    if not 1 <= len(raw) <= maximum:
        raise TransportError(code + "_shape")
    return raw


def _preflight_response_writable(fd: int) -> None:
    """Prove the local response socket write-half is open without emitting data."""

    duplicate = -1
    try:
        duplicate = os.dup(fd)
        channel = socket.socket(fileno=duplicate)
        duplicate = -1
        try:
            if channel.send(b"") != 0:
                raise TransportError("response_fd_write_preflight")
        finally:
            channel.close()
    except TransportError:
        raise
    except OSError:
        if duplicate >= 0:
            os.close(duplicate)
        raise TransportError("response_fd_write_preflight") from None


def _write_fd(fd: int, raw: bytes) -> None:
    _anonymous_socket_fd(fd, "response_fd_identity")
    written = 0
    try:
        while written < len(raw):
            count = os.write(fd, raw[written:])
            if count <= 0:
                raise OSError("short write")
            written += count
    except OSError:
        raise TransportError(
            "response_fd_write",
            cloud_dispatch_count=1,
        ) from None


def _dispatch_authorized_fds(
    request_fd: int,
    credential_fd: int,
    response_fd: int,
    *,
    now: Optional[tuple[int, str]] = None,
    nonce: Optional[str] = None,
    connection_factory: Callable[..., Any] = _default_connection,
) -> dict[str, int]:
    """Consume and emit only through three anonymous AF_UNIX socketpairs.

    The separately accepted bridge owns all three descriptors, half-closes the
    two input peers, and drains the response peer concurrently from an isolated
    child.  No path, argv value, or environment variable can supply the logical
    request, minimized temporary credential envelope, or provider response
    through this operational interface.
    """

    if (
        type(request_fd) is not int
        or type(credential_fd) is not int
        or type(response_fd) is not int
        or len({request_fd, credential_fd, response_fd}) != 3
    ):
        raise TransportError("fd_contract")
    # Validate every endpoint before consuming input or starting a request.
    identities = (
        _anonymous_socket_fd(request_fd, "request_fd_identity"),
        _anonymous_socket_fd(credential_fd, "credential_fd_identity"),
        _anonymous_socket_fd(response_fd, "response_fd_identity"),
    )
    if len(set(identities)) != 3:
        raise TransportError("fd_identity_alias")
    _preflight_response_writable(response_fd)
    request_raw = _read_fd(request_fd, MAX_REQUEST_BYTES, "request_fd")
    credential_raw = _read_fd(
        credential_fd,
        MAX_CREDENTIAL_BYTES,
        "credential_fd",
    )
    result = _dispatch_authorized_bytes(
        request_raw,
        credential_raw,
        now=now,
        nonce=nonce,
        connection_factory=connection_factory,
    )
    _write_fd(response_fd, result.response)
    return {
        "request_fd_read_count": 1,
        "credential_fd_read_count": 1,
        "response_fd_write_count": 1,
        "cloud_dispatch_count": result.cloud_call_count,
        "cloud_write_count": result.cloud_write_count,
        "automatic_retry_count": result.automatic_retry_count,
    }


def _isolated_runtime() -> bool:
    """Return whether Python was started with the required isolation flags."""

    return (
        sys.dont_write_bytecode
        and sys.flags.isolated == 1
        and sys.flags.ignore_environment == 1
        and sys.flags.no_user_site == 1
        and sys.flags.no_site == 1
    )


def dispatch_authorized_fds(
    request_fd: int,
    credential_fd: int,
    response_fd: int,
) -> dict[str, int]:
    """Production entry with a fixed, secret-free failure surface.

    The future bridge must launch an isolated ``-I -S -B`` child after setting
    both core-dump limits to zero.  These checks happen before the private
    dispatcher can read the temporary credential descriptor.
    """

    failure: Optional[tuple[str, int]] = None
    try:
        if os.geteuid() != 0:
            raise TransportError("root_required")
        try:
            core_limits = resource.getrlimit(resource.RLIMIT_CORE)
        except (OSError, ValueError):
            raise TransportError("core_limit_unknown") from None
        if core_limits != (0, 0):
            raise TransportError("core_dump_enabled")
        if not _isolated_runtime():
            raise TransportError("isolated_runtime_required")
        return _dispatch_authorized_fds(
            request_fd,
            credential_fd,
            response_fd,
        )
    except TransportError as exc:
        failure = (exc.code, exc.cloud_dispatch_count)
    except Exception:
        failure = ("transport_internal", 0)
    # Raise outside the handler so the public exception retains no hidden
    # ``__context__`` reference to private frames or credential-bearing locals.
    if failure is None:
        raise TransportError("transport_internal") from None
    raise TransportError(
        failure[0],
        cloud_dispatch_count=failure[1],
    ) from None


def source_only_status() -> dict[str, Any]:
    return {
        "schema": SOURCE_SCHEMA,
        "status": "SOURCE_ONLY_NOT_AUTHORIZED",
        "aliyun_cli_install_count": 0,
        "oauth_configure_count": 0,
        "credential_value_read_count": 0,
        "cloud_call_count": 0,
        "cloud_write_count": 0,
        "database_connection_count": 0,
        "automatic_retry_count": 0,
        "capture_count": 0,
        "materialization_count": 0,
        "authorizes_new_action": False,
    }


def main(argv: Optional[list[str]] = None) -> int:
    # The source checkpoint must never become an ad-hoc transport launcher.
    del argv
    sys.stdout.write(canonical_json(source_only_status()).decode("ascii"))
    sys.stdout.flush()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
