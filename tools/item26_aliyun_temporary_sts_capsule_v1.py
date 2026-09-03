#!/usr/bin/env python3
"""Fail-closed temporary-STS custody capsule for Item 26 M1.

This file is a complete *source* component, not action authority.  It can
construct and validate a minimized temporary-STS envelope from caller-owned
buffers, derive non-reversible account/principal commitments, and expose the
exact secret-free interface consumed by the accepted M1 stager.  The shipped
entry point is deliberately inert.  It does not discover a CLI profile, read a
user configuration directory, launch a process, use the network, or write a
file.

Every function that handles private bytes uses fixed error codes.  Callers own
the final destruction of an issued envelope after transferring it to the M1
adapter; ``IssuedTemporarySts.scrub`` and ``scrub_bytearray`` provide that
operation without ever formatting the bytes.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import math
import os
import socket
import stat
import threading
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional


SOURCE_SCHEMA = "noteai.item26.aliyun-temporary-sts-capsule-source.v1"
INNER_ENVELOPE_SCHEMA = "noteai.item26.aliyun-temporary-sts-envelope.v1"
INTERFACE_SCHEMA = "noteai.item26.m1-root-custody-temporary-sts-interface.v1"
ACCOUNT_BINDING_SCHEMA = "noteai.item26.aliyun-account-binding.v1"
INNER_ENVELOPE_SOURCE = "BRIDGE_PROJECTED_CLI_OAUTH_TEMPORARY_STS"
PROFILE_NAME = "noteai-item26-m1"
REGION_ID = "cn-shenzhen"

SOURCE_ONLY_STATUS = "SOURCE_ONLY_IMPLEMENTATION_COMPLETE_NOT_AUTHORIZED"
CREDENTIAL_CAPSULE_STATUS = "NOT_PROVISIONED"
READY_STATUS = "ROOT_CUSTODY_TEMPORARY_STS_READY"

INITIAL_MINIMUM_VALIDITY_SECONDS = 31 * 60
PER_BEGIN_MINIMUM_VALIDITY_SECONDS = 16 * 60
MAXIMUM_VALIDITY_SECONDS = 24 * 60 * 60
MAX_INNER_ENVELOPE_BYTES = 131072
MAX_JSON_DEPTH = 64
MAX_JSON_INTEGER_DIGITS = 32
MAX_IDENTITY_BYTES = 4096
MAX_SECURITY_TOKEN_BYTES = 16384
NANOSECONDS_PER_SECOND = 1_000_000_000
MAX_PROVIDER_DISPATCHES = 64

RUNTIME_ROOT = (
    "/Library/Application Support/NoteAI/"
    "item26-manual-cost-stop-v2-m1-credential-runtime"
)
CUSTODY_ROOT = (
    "/Library/Application Support/NoteAI/"
    "item26-manual-cost-stop-v2-m1-credential-custody"
)
RUNTIME_FILE_NAMES = (
    "item26_aliyun_temporary_sts_capsule_v1.py",
    "credential-runtime-manifest.json",
)
CUSTODY_FILE_NAMES = (
    "temporary-sts-envelope.json",
    "credential-capsule-state.json",
)
ROOT_UID = 0
WHEEL_GID = 0
DIRECTORY_MODE = 0o700
FILE_MODE = 0o600
FILE_CREATE_FLAGS = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | os.O_NOFOLLOW
    | getattr(os, "O_CLOEXEC", 0)
)
DIRECTORY_READ_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | os.O_NOFOLLOW
    | getattr(os, "O_CLOEXEC", 0)
)
ANCESTOR_DIRECTORY_MODES = MappingProxyType(
    {
        "/": 0o755,
        "/Library": 0o755,
        "/Library/Application Support": 0o755,
        "/Library/Application Support/NoteAI": 0o700,
        RUNTIME_ROOT: DIRECTORY_MODE,
        CUSTODY_ROOT: DIRECTORY_MODE,
    }
)

# These gates describe separate future action classes.  No supported mutation
# can enable them in this source checkpoint, and the public action boundary is
# an unconditional refusal.
EXECUTION_GATES = MappingProxyType(
    {
        "cli_oauth_configuration": False,
        "credential_projection": False,
        "root_custody_stage": False,
        "capture_integration": False,
    }
)

_ACCOUNT_DOMAIN = b"noteai.item26.account-id-commitment.v1\x00"
_PRINCIPAL_DOMAIN = b"noteai.item26.principal-id-commitment.v1\x00"

__all__ = (
    "CapsuleError",
    "IssuedTemporarySts",
    "build_root_custody_capsule",
    "canonical_json",
    "read_anonymous_frame",
    "root_custody_contract",
    "scrub_bytearray",
    "source_only_status",
    "validate_inner_envelope",
    "validate_root_custody_inventory",
    "validate_fd_roles",
    "write_anonymous_frame",
    "provision_root_custody",
    "main",
)


class CapsuleError(ValueError):
    """A fixed-code error with no private value in ``str`` or ``repr``."""

    __slots__ = ("code",)

    def __init__(self, code: str):
        if type(code) is not str or not code or len(code) > 80:
            code = "capsule_internal"
        self.code = code
        super().__init__(code)

    def __repr__(self) -> str:
        return "CapsuleError(<fixed-code>)"


def scrub_bytearray(value: Any) -> None:
    """Overwrite a mutable byte buffer without inspecting or formatting it."""

    if type(value) is bytearray:
        value[:] = b"\x00" * len(value)


def canonical_json(value: Any) -> bytes:
    try:
        return (
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise CapsuleError("json_canonical") from None


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise CapsuleError("json_duplicate_key")
        value[key] = item
    return value


def _parse_integer(raw: str) -> int:
    if len(raw.lstrip("-")) > MAX_JSON_INTEGER_DIGITS:
        raise CapsuleError("json_number")
    try:
        return int(raw)
    except ValueError:
        raise CapsuleError("json_number") from None


def _parse_float(raw: str) -> float:
    if len(raw) > MAX_JSON_INTEGER_DIGITS:
        raise CapsuleError("json_number")
    try:
        value = float(raw)
    except ValueError:
        raise CapsuleError("json_number") from None
    if not math.isfinite(value):
        raise CapsuleError("json_number")
    return value


def _reject_constant(_raw: str) -> Any:
    raise CapsuleError("json_number")


def _check_depth(value: Any, depth: int = 0) -> None:
    if depth > MAX_JSON_DEPTH:
        raise CapsuleError("json_depth")
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise CapsuleError("json_key")
            _check_depth(item, depth + 1)
    elif type(value) is list:
        for item in value:
            _check_depth(item, depth + 1)


def _strict_json_object(raw: Any, maximum: int, code: str) -> dict[str, Any]:
    if (
        type(raw) not in {bytes, bytearray}
        or type(maximum) is not int
        or maximum < 1
        or not 1 <= len(raw) <= maximum
        or 0 in raw
    ):
        raise CapsuleError(code + "_shape")
    try:
        decoded = bytes(raw).decode("utf-8")
        value = json.loads(
            decoded,
            object_pairs_hook=_reject_duplicates,
            parse_int=_parse_integer,
            parse_float=_parse_float,
            parse_constant=_reject_constant,
        )
    except CapsuleError:
        raise
    except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError):
        raise CapsuleError(code + "_json") from None
    if type(value) is not dict:
        raise CapsuleError(code + "_object")
    _check_depth(value)
    return value


def _is_exact_int(value: Any) -> bool:
    return type(value) is int


def _is_lower_hex(value: Any, width: int) -> bool:
    return (
        type(value) is str
        and len(value) == width
        and all(character in "0123456789abcdef" for character in value)
    )


def _visible_ascii_text(value: Any, minimum: int, maximum: int) -> bool:
    if type(value) is not str:
        return False
    try:
        raw = value.encode("ascii")
    except UnicodeError:
        return False
    return (
        minimum <= len(raw) <= maximum
        and all(0x21 <= byte <= 0x7E for byte in raw)
    )


def _access_key_id_shape(value: Any) -> bool:
    if not _visible_ascii_text(value, 12, 128) or not value.startswith("STS."):
        return False
    return all(
        character.isascii()
        and (character.isalnum() or character in "._-")
        for character in value[4:]
    )


@dataclass(frozen=True)
class EnvelopeSummary:
    expiration_unix: int
    remaining_seconds: int
    credential_envelope_sha256: str


def validate_inner_envelope(
    raw: Any,
    *,
    now_unix: int,
    minimum_remaining_seconds: int = PER_BEGIN_MINIMUM_VALIDITY_SECONDS,
) -> EnvelopeSummary:
    """Validate exact canonical envelope bytes and return no private fields."""

    if (
        not _is_exact_int(now_unix)
        or not _is_exact_int(minimum_remaining_seconds)
        or minimum_remaining_seconds
        not in {
            INITIAL_MINIMUM_VALIDITY_SECONDS,
            PER_BEGIN_MINIMUM_VALIDITY_SECONDS,
        }
    ):
        raise CapsuleError("credential_clock")
    value = _strict_json_object(raw, MAX_INNER_ENVELOPE_BYTES, "credential")
    if canonical_json(value) != bytes(raw):
        raise CapsuleError("credential_canonical")
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
        raise CapsuleError("credential_contract")
    if (
        value.get("schema") != INNER_ENVELOPE_SCHEMA
        or value.get("source") != INNER_ENVELOPE_SOURCE
        or value.get("profile_name") != PROFILE_NAME
        or value.get("region_id") != REGION_ID
        or not _access_key_id_shape(value.get("access_key_id"))
        or not _visible_ascii_text(value.get("access_key_secret"), 1, 256)
        or not _visible_ascii_text(
            value.get("security_token"), 1, MAX_SECURITY_TOKEN_BYTES
        )
        or not _is_exact_int(value.get("expiration_unix"))
    ):
        raise CapsuleError("credential_contract")
    expiration = value["expiration_unix"]
    remaining = expiration - now_unix
    if not minimum_remaining_seconds <= remaining <= MAXIMUM_VALIDITY_SECONDS:
        raise CapsuleError("credential_validity")
    return EnvelopeSummary(
        expiration_unix=expiration,
        remaining_seconds=remaining,
        credential_envelope_sha256=hashlib.sha256(bytes(raw)).hexdigest(),
    )


def _require_owned_buffer(
    value: Any,
    code: str,
    minimum: int,
    maximum: int,
    *,
    visible_ascii: bool,
    allow_nul: bool = False,
) -> bytearray:
    if type(value) is not bytearray or not minimum <= len(value) <= maximum:
        raise CapsuleError(code)
    if not allow_nul and 0 in value:
        raise CapsuleError(code)
    if visible_ascii and not all(0x21 <= byte <= 0x7E for byte in value):
        raise CapsuleError(code)
    return value


def _append_json_string(target: bytearray, value: bytearray) -> None:
    target.append(0x22)
    for byte in value:
        if byte == 0x22:
            target.extend(b'\\"')
        elif byte == 0x5C:
            target.extend(b"\\\\")
        else:
            target.append(byte)
    target.append(0x22)


def _append_public_json_string(target: bytearray, value: str) -> None:
    try:
        raw = value.encode("ascii")
    except UnicodeError:
        raise CapsuleError("credential_contract") from None
    _append_json_string(target, bytearray(raw))


def _build_inner_envelope(
    access_key_id: bytearray,
    access_key_secret: bytearray,
    security_token: bytearray,
    expiration_unix: int,
) -> bytearray:
    """Build sorted canonical JSON without materializing private text strings."""

    output = bytearray()
    output.extend(b'{"access_key_id":')
    _append_json_string(output, access_key_id)
    output.extend(b',"access_key_secret":')
    _append_json_string(output, access_key_secret)
    output.extend(b',"expiration_unix":')
    output.extend(str(expiration_unix).encode("ascii"))
    output.extend(b',"profile_name":')
    _append_public_json_string(output, PROFILE_NAME)
    output.extend(b',"region_id":')
    _append_public_json_string(output, REGION_ID)
    output.extend(b',"schema":')
    _append_public_json_string(output, INNER_ENVELOPE_SCHEMA)
    output.extend(b',"security_token":')
    _append_json_string(output, security_token)
    output.extend(b',"source":')
    _append_public_json_string(output, INNER_ENVELOPE_SOURCE)
    output.extend(b"}\n")
    return output


def _commitment(key: bytearray, domain: bytes, raw_identity: bytearray) -> str:
    message = bytearray(domain)
    message.extend(len(raw_identity).to_bytes(8, "big"))
    message.extend(raw_identity)
    try:
        return hmac.new(key, message, hashlib.sha256).hexdigest()
    finally:
        scrub_bytearray(message)


def _account_binding(
    account_commitment: str,
    principal_commitment: str,
) -> str:
    aggregate = {
        "account_commitment_hmac_sha256": account_commitment,
        "principal_commitment_hmac_sha256": principal_commitment,
        "schema": ACCOUNT_BINDING_SCHEMA,
    }
    return hashlib.sha256(canonical_json(aggregate)).hexdigest()


class IssuedTemporarySts:
    """One caller-owned envelope copy; representation is always redacted."""

    __slots__ = (
        "__envelope",
        "__remaining_seconds",
        "__account_binding_sha256",
        "__credential_envelope_sha256",
        "__transferred",
    )

    def __init__(
        self,
        *_args: Any,
        **_kwargs: Any,
    ) -> None:
        raise CapsuleError("issued_construction_denied") from None

    def __repr__(self) -> str:
        return "IssuedTemporarySts(<redacted>)"

    __str__ = __repr__

    @property
    def remaining_seconds(self) -> int:
        return self.__remaining_seconds

    @property
    def account_binding_sha256(self) -> str:
        return self.__account_binding_sha256

    @property
    def credential_envelope_sha256(self) -> str:
        return self.__credential_envelope_sha256

    @property
    def refresh_count(self) -> int:
        return 0

    @property
    def configure_count(self) -> int:
        return 0

    def take_m1_supplier_mapping(self) -> dict[str, Any]:
        """Transfer one mutable copy in the exact accepted capture-core shape.

        The returned mapping is a narrow compatibility boundary: the accepted
        M1 capture core requires ``type(envelope) is bytearray`` and scrubs it
        in its own ``finally`` block.  Callers that do not transfer it to that
        core must call ``scrub_bytearray(mapping["envelope"])`` themselves.
        """

        if self.__transferred or not self.__envelope:
            raise CapsuleError("issued_credential_unavailable")
        if not hmac.compare_digest(
            hashlib.sha256(self.__envelope).hexdigest(),
            self.__credential_envelope_sha256,
        ):
            raise CapsuleError("credential_binding_drift")
        transferred = self.__envelope
        self.__envelope = bytearray()
        self.__transferred = True
        return {
            "envelope": transferred,
            "remaining_seconds": self.__remaining_seconds,
            "account_binding_sha256": self.__account_binding_sha256,
            "credential_envelope_sha256": self.__credential_envelope_sha256,
            "refresh_count": 0,
            "configure_count": 0,
        }

    def __reduce_ex__(self, _protocol: Any) -> Any:
        raise CapsuleError("issued_serialization_denied") from None

    def __reduce__(self) -> Any:
        raise CapsuleError("issued_serialization_denied") from None

    def __getstate__(self) -> Any:
        raise CapsuleError("issued_serialization_denied") from None

    def __setstate__(self, _state: Any) -> None:
        raise CapsuleError("issued_serialization_denied") from None

    def __copy__(self) -> Any:
        raise CapsuleError("issued_copy_denied") from None

    def __deepcopy__(self, _memo: Any) -> Any:
        raise CapsuleError("issued_copy_denied") from None

    def scrub(self) -> None:
        scrub_bytearray(self.__envelope)
        self.__envelope = bytearray()
        self.__transferred = True

    def __enter__(self) -> "IssuedTemporarySts":
        return self

    def __exit__(self, _kind: Any, _value: Any, _traceback: Any) -> None:
        self.scrub()

    def __del__(self) -> None:
        try:
            self.scrub()
        except Exception:
            pass


class _RootCustodyTemporaryStsCapsule:
    """Serial, single-envelope custody state with monotonic TTL accounting."""

    __slots__ = (
        "__envelope",
        "__expiration_unix",
        "__initial_wall_unix",
        "__initial_monotonic_ns",
        "__initial_remaining_seconds",
        "__last_remaining_seconds",
        "__account_commitment",
        "__principal_commitment",
        "__account_binding",
        "__envelope_sha256",
        "__scrubbed",
        "__round_count",
        "__lock",
    )

    def __init__(
        self,
        *_args: Any,
        **_kwargs: Any,
    ) -> None:
        raise CapsuleError("capsule_construction_denied") from None

    def __repr__(self) -> str:
        return (
            "RootCustodyTemporaryStsCapsule(status="
            + ("SCRUBBED" if self.__scrubbed else READY_STATUS)
            + ", envelope=<redacted>, identities=<committed>)"
        )

    def __reduce_ex__(self, _protocol: Any) -> Any:
        raise CapsuleError("capsule_serialization_denied") from None

    def __reduce__(self) -> Any:
        raise CapsuleError("capsule_serialization_denied") from None

    def __getstate__(self) -> Any:
        raise CapsuleError("capsule_serialization_denied") from None

    def __setstate__(self, _state: Any) -> None:
        raise CapsuleError("capsule_serialization_denied") from None

    def __copy__(self) -> Any:
        raise CapsuleError("capsule_copy_denied") from None

    def __deepcopy__(self, _memo: Any) -> Any:
        raise CapsuleError("capsule_copy_denied") from None

    @property
    def account_binding_sha256(self) -> str:
        with self.__lock:
            self._assert_binding_integrity()
            return self.__account_binding

    @property
    def credential_envelope_sha256(self) -> str:
        with self.__lock:
            self._assert_binding_integrity()
            return self.__envelope_sha256

    @property
    def round_count(self) -> int:
        with self.__lock:
            return self.__round_count

    def _remaining(
        self,
        *,
        wall_now_unix: int,
        monotonic_now_ns: int,
        minimum: int,
    ) -> int:
        if self.__scrubbed:
            raise CapsuleError("credential_scrubbed")
        if (
            not _is_exact_int(wall_now_unix)
            or not _is_exact_int(monotonic_now_ns)
            or monotonic_now_ns < self.__initial_monotonic_ns
        ):
            raise CapsuleError("credential_clock")
        elapsed_ns = monotonic_now_ns - self.__initial_monotonic_ns
        elapsed_seconds_ceiling = (
            elapsed_ns + NANOSECONDS_PER_SECOND - 1
        ) // NANOSECONDS_PER_SECOND
        by_wall = self.__expiration_unix - wall_now_unix
        by_monotonic = (
            self.__initial_remaining_seconds - elapsed_seconds_ceiling
        )
        remaining = min(
            self.__last_remaining_seconds,
            by_wall,
            by_monotonic,
            MAXIMUM_VALIDITY_SECONDS,
        )
        if not _is_exact_int(remaining) or remaining < minimum:
            raise CapsuleError("credential_validity")
        self._assert_binding_integrity()
        self.__last_remaining_seconds = remaining
        return remaining

    def _assert_binding_integrity(self) -> None:
        if self.__scrubbed:
            raise CapsuleError("credential_scrubbed")
        try:
            envelope_matches = hmac.compare_digest(
                hashlib.sha256(self.__envelope).hexdigest(),
                self.__envelope_sha256,
            )
            aggregate_matches = hmac.compare_digest(
                _account_binding(
                    self.__account_commitment,
                    self.__principal_commitment,
                ),
                self.__account_binding,
            )
        except Exception:
            raise CapsuleError("credential_binding_drift") from None
        if (
            not _is_lower_hex(self.__account_binding, 64)
            or not _is_lower_hex(self.__account_commitment, 64)
            or not _is_lower_hex(self.__principal_commitment, 64)
            or not envelope_matches
            or not aggregate_matches
        ):
            raise CapsuleError("credential_binding_drift")

    def project_m1_interface(
        self,
        *,
        wall_now_unix: int,
        monotonic_now_ns: int,
    ) -> dict[str, Any]:
        with self.__lock:
            remaining = self._remaining(
                wall_now_unix=wall_now_unix,
                monotonic_now_ns=monotonic_now_ns,
                minimum=INITIAL_MINIMUM_VALIDITY_SECONDS,
            )
            return {
                "schema": INTERFACE_SCHEMA,
                "status": READY_STATUS,
                "account_binding_sha256": self.__account_binding,
                "minimum_remaining_validity_seconds": remaining,
                "credential_payload_exposed": False,
                "oauth_refresh_count": 0,
                "oauth_configure_count": 0,
            }

    def initial_probe(
        self,
        *,
        wall_now_unix: int,
        monotonic_now_ns: int,
    ) -> dict[str, Any]:
        with self.__lock:
            remaining = self._remaining(
                wall_now_unix=wall_now_unix,
                monotonic_now_ns=monotonic_now_ns,
                minimum=INITIAL_MINIMUM_VALIDITY_SECONDS,
            )
            return {
                "remaining_seconds": remaining,
                "account_binding_sha256": self.__account_binding,
                "credential_envelope_sha256": self.__envelope_sha256,
                "refresh_count": 0,
                "configure_count": 0,
            }

    def issue_for_begin(
        self,
        *,
        wall_now_unix: int,
        monotonic_now_ns: int,
    ) -> IssuedTemporarySts:
        with self.__lock:
            if self.__round_count >= MAX_PROVIDER_DISPATCHES:
                raise CapsuleError("credential_round_limit")
            remaining = self._remaining(
                wall_now_unix=wall_now_unix,
                monotonic_now_ns=monotonic_now_ns,
                minimum=PER_BEGIN_MINIMUM_VALIDITY_SECONDS,
            )
            self.__round_count += 1
            issued = object.__new__(IssuedTemporarySts)
            object.__setattr__(
                issued,
                "_IssuedTemporarySts__envelope",
                bytearray(self.__envelope),
            )
            object.__setattr__(
                issued,
                "_IssuedTemporarySts__remaining_seconds",
                remaining,
            )
            object.__setattr__(
                issued,
                "_IssuedTemporarySts__account_binding_sha256",
                self.__account_binding,
            )
            object.__setattr__(
                issued,
                "_IssuedTemporarySts__credential_envelope_sha256",
                self.__envelope_sha256,
            )
            object.__setattr__(issued, "_IssuedTemporarySts__transferred", False)
            return issued

    def scrub(self) -> None:
        with self.__lock:
            scrub_bytearray(self.__envelope)
            self.__envelope = bytearray()
            self.__scrubbed = True

    def __enter__(self) -> "_RootCustodyTemporaryStsCapsule":
        return self

    def __exit__(self, _kind: Any, _value: Any, _traceback: Any) -> None:
        self.scrub()

    def __del__(self) -> None:
        try:
            envelope = getattr(self, "_RootCustodyTemporaryStsCapsule__envelope", None)
            scrub_bytearray(envelope)
        except Exception:
            pass


def build_root_custody_capsule(
    *,
    access_key_id: bytearray,
    access_key_secret: bytearray,
    security_token: bytearray,
    expiration_unix: int,
    account_identity: bytearray,
    principal_identity: bytearray,
    commitment_key: bytearray,
    expected_account_commitment_hmac_sha256: str,
    expected_principal_commitment_hmac_sha256: str,
    wall_now_unix: int,
    monotonic_now_ns: int,
) -> _RootCustodyTemporaryStsCapsule:
    """Consume caller-owned private buffers and return a redacted capsule.

    All six caller-owned private buffers are overwritten on every return path.  A
    successful capsule retains only the minimized STS envelope, commitments,
    and their hashes; raw account/principal identity and the commitment key are
    never retained.
    """

    supplied = (
        access_key_id,
        access_key_secret,
        security_token,
        account_identity,
        principal_identity,
        commitment_key,
    )
    envelope: Optional[bytearray] = None
    result: Optional[_RootCustodyTemporaryStsCapsule] = None
    failure: Optional[str] = None
    try:
        ak_id = _require_owned_buffer(
            access_key_id, "credential_access_key_id", 12, 128,
            visible_ascii=True,
        )
        ak_secret = _require_owned_buffer(
            access_key_secret, "credential_access_key_secret", 1, 256,
            visible_ascii=True,
        )
        token = _require_owned_buffer(
            security_token, "credential_security_token", 1,
            MAX_SECURITY_TOKEN_BYTES, visible_ascii=True,
        )
        account = _require_owned_buffer(
            account_identity, "account_identity", 1, MAX_IDENTITY_BYTES,
            visible_ascii=True,
        )
        principal = _require_owned_buffer(
            principal_identity, "principal_identity", 1, MAX_IDENTITY_BYTES,
            visible_ascii=True,
        )
        key = _require_owned_buffer(
            commitment_key, "commitment_key", 32, 64,
            visible_ascii=False, allow_nul=True,
        )
        if (
            not _is_lower_hex(expected_account_commitment_hmac_sha256, 64)
            or not _is_lower_hex(expected_principal_commitment_hmac_sha256, 64)
        ):
            raise CapsuleError("expected_commitment")
        if (
            not _is_exact_int(expiration_unix)
            or not _is_exact_int(wall_now_unix)
            or not _is_exact_int(monotonic_now_ns)
            or monotonic_now_ns < 0
            or len(ak_id) < 4
            or tuple(ak_id[:4]) != (0x53, 0x54, 0x53, 0x2E)
            or any(
                not (
                    0x30 <= byte <= 0x39
                    or 0x41 <= byte <= 0x5A
                    or 0x61 <= byte <= 0x7A
                    or byte in b"._-"
                )
                for byte in ak_id[4:]
            )
        ):
            raise CapsuleError("credential_contract")
        initial_remaining = expiration_unix - wall_now_unix
        if not (
            INITIAL_MINIMUM_VALIDITY_SECONDS
            <= initial_remaining
            <= MAXIMUM_VALIDITY_SECONDS
        ):
            raise CapsuleError("credential_validity")
        account_commitment = _commitment(key, _ACCOUNT_DOMAIN, account)
        principal_commitment = _commitment(key, _PRINCIPAL_DOMAIN, principal)
        account_matches = hmac.compare_digest(
            account_commitment,
            expected_account_commitment_hmac_sha256,
        )
        principal_matches = hmac.compare_digest(
            principal_commitment,
            expected_principal_commitment_hmac_sha256,
        )
        if not (account_matches and principal_matches):
            raise CapsuleError("commitment_mismatch")
        account_binding = _account_binding(
            expected_account_commitment_hmac_sha256,
            expected_principal_commitment_hmac_sha256,
        )
        envelope = _build_inner_envelope(
            ak_id,
            ak_secret,
            token,
            expiration_unix,
        )
        summary = validate_inner_envelope(
            envelope,
            now_unix=wall_now_unix,
            minimum_remaining_seconds=INITIAL_MINIMUM_VALIDITY_SECONDS,
        )
        result = object.__new__(_RootCustodyTemporaryStsCapsule)
        object.__setattr__(
            result,
            "_RootCustodyTemporaryStsCapsule__envelope",
            envelope,
        )
        object.__setattr__(
            result,
            "_RootCustodyTemporaryStsCapsule__expiration_unix",
            expiration_unix,
        )
        object.__setattr__(
            result,
            "_RootCustodyTemporaryStsCapsule__initial_wall_unix",
            wall_now_unix,
        )
        object.__setattr__(
            result,
            "_RootCustodyTemporaryStsCapsule__initial_monotonic_ns",
            monotonic_now_ns,
        )
        object.__setattr__(
            result,
            "_RootCustodyTemporaryStsCapsule__initial_remaining_seconds",
            initial_remaining,
        )
        object.__setattr__(
            result,
            "_RootCustodyTemporaryStsCapsule__last_remaining_seconds",
            initial_remaining,
        )
        object.__setattr__(
            result,
            "_RootCustodyTemporaryStsCapsule__account_commitment",
            account_commitment,
        )
        object.__setattr__(
            result,
            "_RootCustodyTemporaryStsCapsule__principal_commitment",
            principal_commitment,
        )
        object.__setattr__(
            result,
            "_RootCustodyTemporaryStsCapsule__account_binding",
            account_binding,
        )
        object.__setattr__(
            result,
            "_RootCustodyTemporaryStsCapsule__envelope_sha256",
            summary.credential_envelope_sha256,
        )
        object.__setattr__(
            result,
            "_RootCustodyTemporaryStsCapsule__scrubbed",
            False,
        )
        object.__setattr__(
            result,
            "_RootCustodyTemporaryStsCapsule__round_count",
            0,
        )
        object.__setattr__(
            result,
            "_RootCustodyTemporaryStsCapsule__lock",
            threading.Lock(),
        )
        envelope = None
    except CapsuleError as exc:
        failure = exc.code
    except Exception:
        failure = "capsule_internal"
    finally:
        if envelope is not None:
            scrub_bytearray(envelope)
        for value in supplied:
            scrub_bytearray(value)
    if failure is not None or result is None:
        raise CapsuleError(failure or "capsule_internal") from None
    return result


@dataclass(frozen=True)
class FdIdentity:
    device: int
    inode: int
    file_type: int
    direction: str


def _default_socket_probe(fd: int, direction: str) -> Mapping[str, Any]:
    duplicate = -1
    try:
        duplicate = os.dup(fd)
        channel = socket.socket(fileno=duplicate)
        duplicate = -1
        try:
            return {
                "family": channel.family,
                "kind": channel.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE),
                "local_name": channel.getsockname(),
                "peer_name": channel.getpeername(),
                "direction": direction,
            }
        finally:
            channel.close()
    except OSError:
        if duplicate >= 0:
            os.close(duplicate)
        raise CapsuleError("fd_socket_identity") from None


def _validate_anonymous_fd(
    fd: Any,
    direction: str,
    *,
    fstat_fn: Callable[[int], Any] = os.fstat,
    getfl_fn: Callable[[int, int], int] = fcntl.fcntl,
    isatty_fn: Callable[[int], bool] = os.isatty,
    socket_probe: Callable[[int, str], Mapping[str, Any]] = _default_socket_probe,
) -> FdIdentity:
    if type(fd) is not int or fd < 3 or direction not in {"read", "write"}:
        raise CapsuleError("fd_contract")
    dependency_failure = False
    try:
        row = fstat_fn(fd)
        flags = getfl_fn(fd, fcntl.F_GETFL)
        tty = isatty_fn(fd)
        probe = socket_probe(fd, direction)
        row_mode = row.st_mode
        row_device = row.st_dev
        row_inode = row.st_ino
    except CapsuleError:
        raise
    except Exception:
        dependency_failure = True
    if dependency_failure:
        raise CapsuleError("fd_identity") from None
    validation_failure = False
    try:
        invalid = (
            type(flags) is not int
            or type(row_mode) is not int
            or type(row_device) is not int
            or type(row_inode) is not int
            or row_device < 0
            or row_inode <= 0
            or type(tty) is not bool
            or type(probe) is not dict
            or set(probe) != {
                "family",
                "kind",
                "local_name",
                "peer_name",
                "direction",
            }
            or tty
            or not stat.S_ISSOCK(row_mode)
            or probe["family"] != socket.AF_UNIX
            or probe["kind"] != socket.SOCK_STREAM
            or probe["local_name"] not in {"", b""}
            or probe["peer_name"] not in {"", b""}
            or probe["direction"] != direction
            or flags & os.O_ACCMODE != os.O_RDWR
            or flags & os.O_NONBLOCK
            or flags & getattr(os, "O_ASYNC", 0)
        )
    except Exception:
        validation_failure = True
        invalid = True
    if validation_failure:
        raise CapsuleError("fd_identity") from None
    if invalid:
        raise CapsuleError("fd_identity")
    return FdIdentity(
        device=row_device,
        inode=row_inode,
        file_type=stat.S_IFMT(row_mode),
        direction=direction,
    )


def validate_fd_roles(
    read_fd: int,
    write_fd: int,
    **dependencies: Any,
) -> tuple[FdIdentity, FdIdentity]:
    if type(read_fd) is not int or type(write_fd) is not int or read_fd == write_fd:
        raise CapsuleError("fd_alias")
    reader = _validate_anonymous_fd(
        read_fd,
        "read",
        **dependencies,
    )
    writer = _validate_anonymous_fd(
        write_fd,
        "write",
        **dependencies,
    )
    if (reader.device, reader.inode, reader.file_type) == (
        writer.device,
        writer.inode,
        writer.file_type,
    ):
        raise CapsuleError("fd_alias")
    return reader, writer


def read_anonymous_frame(
    fd: int,
    maximum: int,
    *,
    reader: Callable[[int, int], bytes] = os.read,
    eof_probe: Callable[[int], bool] = lambda _fd: True,
    **dependencies: Any,
) -> bytearray:
    """Read one bounded frame and require a separately probed terminal EOF."""

    _validate_anonymous_fd(fd, "read", **dependencies)
    if type(maximum) is not int or maximum < 1:
        raise CapsuleError("fd_size")
    output = bytearray()
    saw_eof = False
    failure: Optional[str] = None
    try:
        while len(output) <= maximum:
            chunk = reader(fd, min(65536, maximum + 1 - len(output)))
            if type(chunk) is not bytes:
                failure = "fd_read"
                break
            if not chunk:
                saw_eof = True
                break
            output.extend(chunk)
        if failure is None and not 1 <= len(output) <= maximum:
            failure = "fd_size"
        if failure is None and (not saw_eof or eof_probe(fd) is not True):
            failure = "fd_eof"
    except Exception:
        failure = "fd_read"
    if failure is not None:
        scrub_bytearray(output)
        raise CapsuleError(failure) from None
    return output


def _default_shutdown_write(fd: int, how: int) -> None:
    duplicate = -1
    try:
        duplicate = os.dup(fd)
        channel = socket.socket(fileno=duplicate)
        duplicate = -1
        try:
            channel.shutdown(how)
        finally:
            channel.close()
    except OSError:
        if duplicate >= 0:
            os.close(duplicate)
        raise CapsuleError("fd_shutdown") from None


def write_anonymous_frame(
    fd: int,
    raw: bytearray,
    maximum: int,
    *,
    writer: Callable[[int, Any], int] = os.write,
    shutdown_fn: Callable[[int, int], Any] = _default_shutdown_write,
    **dependencies: Any,
) -> int:
    """Write one bounded frame, then exactly once half-close it for EOF."""

    _validate_anonymous_fd(fd, "write", **dependencies)
    if (
        type(raw) is not bytearray
        or type(maximum) is not int
        or maximum < 1
        or not 1 <= len(raw) <= maximum
    ):
        raise CapsuleError("fd_size")
    try:
        if writer(fd, b"") != 0:
            raise CapsuleError("fd_write_preflight")
    except CapsuleError:
        raise
    except Exception:
        raise CapsuleError("fd_write_preflight") from None
    written = 0
    try:
        while written < len(raw):
            count = writer(fd, memoryview(raw)[written:])
            remaining = len(raw) - written
            if type(count) is not int or count <= 0 or count > remaining:
                raise CapsuleError("fd_write")
            written += count
    except CapsuleError:
        raise
    except Exception:
        raise CapsuleError("fd_write") from None
    try:
        if shutdown_fn(fd, socket.SHUT_WR) is not None:
            raise CapsuleError("fd_shutdown")
    except Exception:
        raise CapsuleError("fd_shutdown") from None
    return written


def root_custody_contract() -> dict[str, Any]:
    files = tuple(
        [RUNTIME_ROOT + "/" + name for name in RUNTIME_FILE_NAMES]
        + [CUSTODY_ROOT + "/" + name for name in CUSTODY_FILE_NAMES]
    )
    return {
        "runtime_root": RUNTIME_ROOT,
        "custody_root": CUSTODY_ROOT,
        "directory_paths": (RUNTIME_ROOT, CUSTODY_ROOT),
        "ancestor_directory_modes": dict(ANCESTOR_DIRECTORY_MODES),
        "file_paths": files,
        "root_uid": ROOT_UID,
        "wheel_gid": WHEEL_GID,
        "directory_mode": DIRECTORY_MODE,
        "file_mode": FILE_MODE,
        "file_create_flags": FILE_CREATE_FLAGS,
        "directory_read_flags": DIRECTORY_READ_FLAGS,
        "root_exact_entry_names": {
            RUNTIME_ROOT: RUNTIME_FILE_NAMES,
            CUSTODY_ROOT: CUSTODY_FILE_NAMES,
        },
        "regular_file_required": True,
        "file_nlink": 1,
        "exact_inventory_required": True,
        "ancestor_observation": "lstat-no-follow",
        "leaf_observation": "exclusive-create-fd-pre-post-and-path-lstat",
    }


_LEAF_STAT_FIELDS = frozenset(
    {"st_mode", "uid", "gid", "nlink", "dev", "ino", "size"}
)
_ANCESTOR_STAT_FIELDS = frozenset(
    {"st_mode", "uid", "gid", "nlink", "dev", "ino"}
)
_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def _validated_leaf_stat(value: Any, code: str) -> dict[str, int]:
    if type(value) is not dict or set(value) != _LEAF_STAT_FIELDS:
        raise CapsuleError(code)
    for name in _LEAF_STAT_FIELDS:
        if type(value.get(name)) is not int:
            raise CapsuleError(code)
    if (
        not stat.S_ISREG(value["st_mode"])
        or stat.S_ISLNK(value["st_mode"])
        or stat.S_IMODE(value["st_mode"]) != FILE_MODE
        or value["uid"] != ROOT_UID
        or value["gid"] != WHEEL_GID
        or value["nlink"] != 1
        or value["dev"] < 0
        or value["ino"] <= 0
        or value["size"] < 0
    ):
        raise CapsuleError(code)
    return dict(value)


def _validated_ancestor_stat(
    value: Any,
    required_mode: int,
    code: str,
) -> dict[str, int]:
    if (
        type(value) is not dict
        or set(value) != _ANCESTOR_STAT_FIELDS
        or any(type(value.get(name)) is not int for name in _ANCESTOR_STAT_FIELDS)
        or not stat.S_ISDIR(value["st_mode"])
        or stat.S_ISLNK(value["st_mode"])
        or stat.S_IMODE(value["st_mode"]) != required_mode
        or value["uid"] != ROOT_UID
        or value["gid"] != WHEEL_GID
        or value["nlink"] < 1
        or value["dev"] < 0
        or value["ino"] <= 0
    ):
        raise CapsuleError(code)
    return dict(value)


class _DirectoryListingReceipt:
    """Immutable inode-bound result from a fixed no-follow directory open."""

    __slots__ = ("__path", "__fd_stat", "__entry_names")

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise CapsuleError("custody_listing_construction_denied") from None

    def __setattr__(self, _name: str, _value: Any) -> None:
        raise AttributeError("directory listing receipt is immutable")

    def __repr__(self) -> str:
        return "_DirectoryListingReceipt(<verified>)"

    def __copy__(self) -> "_DirectoryListingReceipt":
        return self

    def __deepcopy__(self, _memo: Any) -> "_DirectoryListingReceipt":
        return self


def _capture_root_directory_listing(
    path: str,
    *,
    lister: Callable[[str, int], Any],
) -> _DirectoryListingReceipt:
    """Seal an injected inode-bound listing opened with source-fixed flags."""

    expected_by_root = root_custody_contract()["root_exact_entry_names"]
    if type(path) is not str or path not in expected_by_root:
        raise CapsuleError("custody_listing_path")
    try:
        evidence = lister(path, DIRECTORY_READ_FLAGS)
    except Exception:
        raise CapsuleError("custody_listing_leaf") from None
    if type(evidence) is not dict or set(evidence) != {"fd_stat", "entry_names"}:
        raise CapsuleError("custody_directory_entries")
    fd_stat = _validated_ancestor_stat(
        evidence["fd_stat"],
        DIRECTORY_MODE,
        "custody_directory_entries",
    )
    names = evidence["entry_names"]
    expected_names = expected_by_root[path]
    if (
        type(names) is not tuple
        or any(
            type(name) is not str
            or not name
            or name in {".", ".."}
            or "/" in name
            or "\x00" in name
            for name in names
        )
        or names != expected_names
        or len(set(names)) != len(names)
    ):
        raise CapsuleError("custody_directory_entries")
    receipt = object.__new__(_DirectoryListingReceipt)
    object.__setattr__(receipt, "_DirectoryListingReceipt__path", path)
    object.__setattr__(
        receipt,
        "_DirectoryListingReceipt__fd_stat",
        MappingProxyType(fd_stat),
    )
    object.__setattr__(receipt, "_DirectoryListingReceipt__entry_names", names)
    return receipt


class _ExclusiveCreationReceipt:
    """Internally minted proof that fixed exclusive flags reached a creator."""

    __slots__ = ("__path", "__pre", "__post", "__pre_hash", "__post_hash")

    def __init__(
        self,
        *_args: Any,
        **_kwargs: Any,
    ) -> None:
        raise CapsuleError("custody_receipt_construction_denied") from None

    def __setattr__(self, _name: str, _value: Any) -> None:
        raise AttributeError("creation receipt is immutable")

    def __repr__(self) -> str:
        return "_ExclusiveCreationReceipt(<verified>)"


def _capture_exclusive_creation_receipt(
    path: str,
    *,
    creator: Callable[[str, int, int], Any],
) -> _ExclusiveCreationReceipt:
    """Invoke an injected creator with source-fixed flags and seal its FD proof.

    There is deliberately no default creator: this source checkpoint cannot
    reach a filesystem through this leaf.  A future separately authorized
    integration must inject the creator; tests inject a fake.
    """

    expected_paths = set(root_custody_contract()["file_paths"])
    if type(path) is not str or path not in expected_paths or not path.startswith("/"):
        raise CapsuleError("custody_receipt_path")
    try:
        evidence = creator(path, FILE_CREATE_FLAGS, FILE_MODE)
    except Exception:
        raise CapsuleError("custody_create_leaf") from None
    if type(evidence) is not dict or set(evidence) != {
        "pre_fd_stat",
        "post_fd_stat",
        "pre_content_sha256",
        "post_content_sha256",
    }:
        raise CapsuleError("custody_creation_receipt")
    pre = _validated_leaf_stat(evidence["pre_fd_stat"], "custody_creation_receipt")
    post = _validated_leaf_stat(evidence["post_fd_stat"], "custody_creation_receipt")
    pre_hash = evidence["pre_content_sha256"]
    post_hash = evidence["post_content_sha256"]
    if (
        pre["size"] != 0
        or post["size"] < 1
        or (pre["dev"], pre["ino"]) != (post["dev"], post["ino"])
        or any(pre[name] != post[name] for name in ("st_mode", "uid", "gid", "nlink"))
        or pre_hash != _EMPTY_SHA256
        or not _is_lower_hex(post_hash, 64)
    ):
        raise CapsuleError("custody_creation_receipt")
    receipt = object.__new__(_ExclusiveCreationReceipt)
    object.__setattr__(receipt, "_ExclusiveCreationReceipt__path", path)
    object.__setattr__(
        receipt,
        "_ExclusiveCreationReceipt__pre",
        MappingProxyType(dict(pre)),
    )
    object.__setattr__(
        receipt,
        "_ExclusiveCreationReceipt__post",
        MappingProxyType(dict(post)),
    )
    object.__setattr__(receipt, "_ExclusiveCreationReceipt__pre_hash", pre_hash)
    object.__setattr__(receipt, "_ExclusiveCreationReceipt__post_hash", post_hash)
    return receipt


def validate_root_custody_inventory(
    live_snapshot: Any,
    *,
    creation_receipts: Any,
) -> dict[str, Any]:
    """Validate separate creation proof and no-follow live metadata snapshots."""

    contract = root_custody_contract()
    expected_files = set(contract["file_paths"])
    expected_ancestors = set(ANCESTOR_DIRECTORY_MODES)
    if (
        type(live_snapshot) is not dict
        or set(live_snapshot)
        != {"ancestor_lstat", "file_lstat", "root_directory_entries"}
        or type(live_snapshot.get("ancestor_lstat")) is not dict
        or set(live_snapshot["ancestor_lstat"]) != expected_ancestors
        or type(live_snapshot.get("file_lstat")) is not dict
        or set(live_snapshot["file_lstat"]) != expected_files
        or type(live_snapshot.get("root_directory_entries")) is not dict
        or set(live_snapshot["root_directory_entries"])
        != {RUNTIME_ROOT, CUSTODY_ROOT}
        or type(creation_receipts) is not dict
        or set(creation_receipts) != expected_files
    ):
        raise CapsuleError("custody_inventory")
    for path, required_mode in ANCESTOR_DIRECTORY_MODES.items():
        row = live_snapshot["ancestor_lstat"].get(path)
        _validated_ancestor_stat(row, required_mode, "custody_ancestor")
    expected_by_root = contract["root_exact_entry_names"]
    for path in (RUNTIME_ROOT, CUSTODY_ROOT):
        listing = live_snapshot["root_directory_entries"].get(path)
        if type(listing) is not _DirectoryListingReceipt:
            raise CapsuleError("custody_directory_entries")
        ancestor = live_snapshot["ancestor_lstat"][path]
        if (
            listing._DirectoryListingReceipt__path != path
            or dict(listing._DirectoryListingReceipt__fd_stat) != ancestor
            or listing._DirectoryListingReceipt__entry_names
            != expected_by_root[path]
        ):
            raise CapsuleError("custody_directory_entries")
    for path in contract["file_paths"]:
        row = live_snapshot["file_lstat"].get(path)
        receipt = creation_receipts.get(path)
        if (
            type(row) is not dict
            or set(row) != (_LEAF_STAT_FIELDS | {"sha256"})
            or type(receipt) is not _ExclusiveCreationReceipt
        ):
            raise CapsuleError("custody_file")
        live_stat = _validated_leaf_stat(
            {name: row[name] for name in _LEAF_STAT_FIELDS},
            "custody_file",
        )
        if (
            receipt._ExclusiveCreationReceipt__path != path
            or live_stat != dict(receipt._ExclusiveCreationReceipt__post)
            or not _is_lower_hex(row.get("sha256"), 64)
            or not hmac.compare_digest(
                row["sha256"],
                receipt._ExclusiveCreationReceipt__post_hash,
            )
        ):
            raise CapsuleError("custody_file")
    return contract


def provision_root_custody(*_args: Any, **_kwargs: Any) -> None:
    """Public action boundary: fixed refusal before inspecting any argument."""

    raise CapsuleError("source_only_execution_denied") from None


def source_only_status() -> dict[str, Any]:
    return {
        "schema": SOURCE_SCHEMA,
        "status": SOURCE_ONLY_STATUS,
        "implementation_complete": True,
        "authorizes_execution": False,
        "operational_ready": False,
        "credential_capsule_status": CREDENTIAL_CAPSULE_STATUS,
        "execution_gates": dict(EXECUTION_GATES),
        "cli_install_count": 0,
        "cli_configure_count": 0,
        "oauth_configure_count": 0,
        "oauth_refresh_count": 0,
        "credential_read_count": 0,
        "root_read_count": 0,
        "root_write_count": 0,
        "filesystem_mutation_count": 0,
        "subprocess_count": 0,
        "network_call_count": 0,
        "provider_call_count": 0,
        "database_connection_count": 0,
        "capture_count": 0,
        "materialization_count": 0,
        "automatic_retry_count": 0,
        "cleanup_count": 0,
        "authorized_cny": "0.00",
        "incurred_cny": "0.00",
    }


def main(_argv: Any = None) -> int:
    # This must remain the first and only operation: do not inspect argv, read a
    # descriptor, import an execution dependency, consult input/environment, or
    # emit to stdout/stderr from the source checkpoint.
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
