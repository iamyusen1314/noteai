#!/usr/bin/env python3
"""Inert dedicated-root OAuth helper source contract for Item 26 M1.

This module is a source-only implementation checkpoint.  It describes and
implements only deterministic, in-memory validation primitives for a future
dedicated OAuth helper.  It does not register an OAuth client, install or run
a root helper, open a callback listener, launch a browser, contact an OAuth or
provider endpoint, read configuration, or hand credentials to C1/C2.

The current operational decision is therefore permanently fail closed:
``NO_GO_PENDING_DEDICATED_OAUTH_CLIENT_AND_ACTION_AUTHORIZATION``.  The public
request boundary raises ``NOT_PROVISIONED`` before inspecting caller input,
and the default entry point emits nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
from types import MappingProxyType
from typing import Any, Mapping, NoReturn


SOURCE_SCHEMA = "noteai.item26.aliyun-dedicated-root-oauth-helper-source.v1"
CONTRACT_SCHEMA = (
    "noteai.item26.aliyun-dedicated-root-oauth-helper-contract.v1"
)
PURE_CORE_SCHEMA = "noteai.item26.aliyun-dedicated-root-oauth-pure-core.v1"

SOURCE_ONLY_STATUS = "SOURCE_ONLY_IMPLEMENTATION_COMPLETE_NOT_AUTHORIZED"
BOOTSTRAP_STATUS = "NOT_PROVISIONED"
ASSESSMENT = (
    "NO_GO_PENDING_DEDICATED_OAUTH_CLIENT_AND_ACTION_AUTHORIZATION"
)

C1_INTERFACE_SCHEMA = (
    "noteai.item26.m1-root-custody-temporary-sts-interface.v1"
)
C1_READY_STATUS = "ROOT_CUSTODY_TEMPORARY_STS_READY"
C1_CURRENT_INNER_ENVELOPE_SOURCE = (
    "BRIDGE_PROJECTED_CLI_OAUTH_TEMPORARY_STS"
)
C1_ACCOUNT_BINDING_SCHEMA = "noteai.item26.aliyun-account-binding.v1"

C2_HANDSHAKE_SCHEMA = "noteai.item26.m1-c1-capture-handshake.v1"
C2_READY_BINDING_SCHEMA = "noteai.item26.m1-c1-ready-binding.v1"
C2_READY_STATUS = "ROOT_CUSTODY_TEMPORARY_STS_READY_FOR_CAPTURE_ACK"
C2_ACK_STATUS = "ROOT_CUSTODY_TEMPORARY_STS_CAPTURE_ACKNOWLEDGED"
C2_CURRENT_C1_SOURCE_REF = "tools/item26_aliyun_temporary_sts_capsule_v1.py"
C2_CURRENT_C1_SOURCE_REVISION = "86206f816fb092a7fca7a577b1391e251dfca5ca"
C2_CURRENT_C1_ACCEPTANCE_REVISION = (
    "314a6b885bc7bda9790074a201ac176e498326b5"
)
C2_CURRENT_C1_GIT_BLOB_OID = "99110863d055929fbc76950ec2bc9aa8fd0f7bc6"
C2_CURRENT_C1_FILE_SHA256 = (
    "7ed50fd5acdbb5733a174367e8bcb339b3a6bc07b49fed3a31243fddf763e4e3"
)
C2_CURRENT_C1_BYTES = 49_494

MAX_CANONICAL_BYTES = 65_536
MAX_JSON_DEPTH = 32
MAX_JSON_ITEMS = 512
MAX_PUBLIC_TEXT_BYTES = 16_384

MIN_PKCE_VERIFIER_BYTES = 43
MAX_PKCE_VERIFIER_BYTES = 128
PKCE_S256_CHALLENGE_BYTES = 43
MAX_CALLBACK_QUERY_BYTES = 8_192
MIN_AUTHORIZATION_CODE_BYTES = 16
MAX_AUTHORIZATION_CODE_BYTES = 4_096
MIN_STATE_BYTES = 16
MAX_STATE_BYTES = 512
MIN_TOKEN_BYTES = 16
MAX_TOKEN_BYTES = 16384
MIN_COMMITMENT_KEY_BYTES = 32
MAX_COMMITMENT_KEY_BYTES = 128
MAX_IDENTITY_BYTES = 4_096
MIN_TOKEN_VALIDITY_SECONDS = 60
MAX_TOKEN_VALIDITY_SECONDS = 86400
INITIAL_MINIMUM_STS_SECONDS = 31 * 60
PER_BEGIN_MINIMUM_STS_SECONDS = 16 * 60
MAXIMUM_STS_SECONDS = 24 * 60 * 60
MAX_SECURITY_TOKEN_BYTES = 16384

DEDICATED_RUNTIME_ROOT = (
    "/Library/Application Support/NoteAI/"
    "item26-dedicated-root-oauth-helper-v1"
)

SOURCE_ROUND_OPERATION_COUNT_SCOPE = "IMPORT_AND_INERT_REQUEST_MAIN_ONLY"

_STATE_DOMAIN = b"noteai.item26.dedicated-root-oauth-state.v1\x00"
_AUTHORIZATION_CODE_DOMAIN = (
    b"noteai.item26.dedicated-root-oauth-authorization-code.v1\x00"
)
_ACCESS_TOKEN_DOMAIN = (
    b"noteai.item26.dedicated-root-oauth-access-token.v1\x00"
)
_REFRESH_TOKEN_DOMAIN = (
    b"noteai.item26.dedicated-root-oauth-refresh-token.v1\x00"
)
_ACCOUNT_DOMAIN = b"noteai.item26.account-id-commitment.v1\x00"
_PRINCIPAL_DOMAIN = b"noteai.item26.principal-id-commitment.v1\x00"
_STS_ACCESS_KEY_ID_DOMAIN = (
    b"noteai.item26.dedicated-root-oauth-sts-access-key-id.v1\x00"
)
_STS_ACCESS_KEY_SECRET_DOMAIN = (
    b"noteai.item26.dedicated-root-oauth-sts-access-key-secret.v1\x00"
)
_STS_SECURITY_TOKEN_DOMAIN = (
    b"noteai.item26.dedicated-root-oauth-sts-security-token.v1\x00"
)
_STS_MATERIAL_BINDING_SCHEMA = (
    "noteai.item26.dedicated-root-oauth-temporary-sts-material-binding.v1"
)
_BASE64URL_ALPHABET = (
    b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)


def _deep_freeze(value: Any) -> Any:
    """Recursively freeze trusted public contract literals."""

    if type(value) is dict:
        return MappingProxyType(
            {key: _deep_freeze(item) for key, item in value.items()}
        )
    if type(value) is list:
        return tuple(_deep_freeze(item) for item in value)
    if type(value) in (bool, int, str) or value is None:
        return value
    raise TypeError("public_contract_type")


OPERATIONAL_BLOCKERS = _deep_freeze(
    {
        "c1_source_label_successor": {
            "blocking": True,
            "state": "PENDING",
            "required_artifact": "C1_SOURCE_LABEL_SUCCESSOR",
        },
        "c2_fixed_binding_successor": {
            "blocking": True,
            "state": "PENDING",
            "required_artifact": "C2_FIXED_BINDING_SUCCESSOR",
        },
        "dedicated_oauth_client_registration": {
            "blocking": True,
            "state": "ABSENT",
            "required_artifact": "DEDICATED_OAUTH_CLIENT_REGISTRATION_RECEIPT",
        },
        "unprivileged_broker": {
            "blocking": True,
            "state": "PENDING",
            "required_artifact": "UNPRIVILEGED_BROKER_SOURCE_AND_ACCEPTANCE",
        },
    }
)


ACTION_AUTHORIZATION = _deep_freeze(
    {
        "required_receipt": "SEPARATE_ACTION_AUTHORITY_RECEIPT",
        "required_before_any_action": True,
        "receipt_present": False,
        "state": "ABSENT",
    }
)


EXECUTION_GATES = MappingProxyType(
    {
        "action_authority_acceptance": False,
        "c1_capsule_handoff": False,
        "c2_capture_integration": False,
        "caller_identity_verification": False,
        "dedicated_oauth_client_registration": False,
        "loopback_callback_listener": False,
        "oauth_token_exchange": False,
        "root_custody_creation": False,
        "unprivileged_broker_execution": False,
    }
)


SOURCE_ROUND_OPERATION_COUNTS = MappingProxyType(
    {
        "argv_read_count": 0,
        "automatic_retry_count": 0,
        "browser_launch_count": 0,
        "c1_capsule_handoff_count": 0,
        "c2_handshake_count": 0,
        "caller_identity_verification_count": 0,
        "callback_accept_count": 0,
        "callback_listener_open_count": 0,
        "capture_count": 0,
        "cleanup_count": 0,
        "client_registration_count": 0,
        "config_read_count": 0,
        "config_write_count": 0,
        "credential_read_count": 0,
        "credential_write_count": 0,
        "database_connection_count": 0,
        "environment_read_count": 0,
        "filesystem_read_count": 0,
        "filesystem_write_count": 0,
        "helper_install_count": 0,
        "helper_process_count": 0,
        "materialization_count": 0,
        "network_call_count": 0,
        "oauth_authorization_count": 0,
        "oauth_token_exchange_count": 0,
        "provider_call_count": 0,
        "root_read_count": 0,
        "root_custody_creation_count": 0,
        "root_write_count": 0,
        "secret_input_count": 0,
        "secret_output_count": 0,
        "stderr_write_count": 0,
        "stdout_write_count": 0,
        "subprocess_count": 0,
        "sudo_dispatch_count": 0,
        "temporary_sts_projection_count": 0,
        "unprivileged_broker_dispatch_count": 0,
    }
)


# Historical observations are deliberately separate from the module-runtime
# zero counters.  Official evidence research occurred and was not exactly
# enumerated.  A prior read-intended Homebrew query caused one non-provider
# metadata-network event and may have written one Homebrew cache entry.
PRIOR_RESEARCH_AUDIT = MappingProxyType(
    {
        "aliyun_provider_cloud_call_count": 0,
        "generic_historical_filesystem_write_zero_claimed": False,
        "generic_historical_network_zero_claimed": False,
        "homebrew_nonprovider_metadata_network_event_count": 1,
        "homebrew_possible_cache_write_event_count": 1,
        "official_evidence_web_request_count": None,
        "official_evidence_web_request_count_status": "NOT_EXACTLY_ENUMERATED",
        "official_evidence_web_research_performed": True,
    }
)


__all__ = (
    "DedicatedRootOauthHelperError",
    "helper_contract",
    "main",
    "request_bootstrap",
    "scrub_bytearray",
    "source_status",
)


_ERROR_CODES = frozenset(
    {
        "NOT_PROVISIONED",
        "callback_contract",
        "callback_state_mismatch",
        "canonical_depth",
        "canonical_integer",
        "canonical_items",
        "canonical_key",
        "canonical_size",
        "canonical_text",
        "canonical_type",
        "helper_internal",
        "identity_commitment_mismatch",
        "identity_contract",
        "pkce_mismatch",
        "pkce_shape",
        "sts_contract",
        "sts_validity",
        "token_contract",
        "token_validity",
    }
)


class DedicatedRootOauthHelperError(ValueError):
    """Fixed-code error whose representation never includes caller data."""

    __slots__ = ("code",)

    def __init__(self, code: str):
        if type(code) is not str or code not in _ERROR_CODES:
            code = "helper_internal"
        self.code = code
        super().__init__(code)

    def __repr__(self) -> str:
        return "DedicatedRootOauthHelperError(<fixed-code>)"


def scrub_bytearray(value: Any) -> None:
    """Overwrite an exact mutable byte buffer without formatting it."""

    if type(value) is bytearray:
        value[:] = b"\x00" * len(value)


@dataclass(frozen=True, slots=True)
class _CallbackSummary:
    authorization_code_commitment_hmac_sha256: str
    authorization_code_present: bool
    parameter_count: int
    state_commitment_hmac_sha256: str


@dataclass(frozen=True, slots=True)
class _TokenSummary:
    access_token_commitment_hmac_sha256: str
    expiration_unix: int
    refresh_token_commitment_hmac_sha256: str
    remaining_seconds: int
    token_type: str


@dataclass(frozen=True, slots=True)
class _IdentityBindingSummary:
    account_binding_sha256: str
    account_commitment_hmac_sha256: str
    principal_commitment_hmac_sha256: str


@dataclass(frozen=True, slots=True)
class _TemporaryStsSummary:
    account_binding_sha256: str
    credential_material_binding_sha256: str
    expiration_unix: int
    remaining_seconds: int


def _is_exact_int(value: Any) -> bool:
    return type(value) is int


def _is_nonnegative_canonical_int(value: Any) -> bool:
    return type(value) is int and 0 <= value <= 2**63 - 1


def _is_lower_hex(value: Any, width: int) -> bool:
    return (
        type(value) is str
        and len(value) == width
        and all(character in "0123456789abcdef" for character in value)
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
        raise DedicatedRootOauthHelperError(code)
    if not allow_nul and 0 in value:
        raise DedicatedRootOauthHelperError(code)
    if visible_ascii and not all(0x21 <= byte <= 0x7E for byte in value):
        raise DedicatedRootOauthHelperError(code)
    return value


def _reject_private_aliases(code: str, *values: Any) -> None:
    exact_buffers = [value for value in values if type(value) is bytearray]
    for index, value in enumerate(exact_buffers):
        if any(value is other for other in exact_buffers[index + 1 :]):
            raise DedicatedRootOauthHelperError(code)


def _base64url_no_padding(value: bytearray) -> str:
    output = bytearray()
    index = 0
    try:
        while index + 3 <= len(value):
            block = (
                (value[index] << 16)
                | (value[index + 1] << 8)
                | value[index + 2]
            )
            output.extend(
                (
                    _BASE64URL_ALPHABET[(block >> 18) & 0x3F],
                    _BASE64URL_ALPHABET[(block >> 12) & 0x3F],
                    _BASE64URL_ALPHABET[(block >> 6) & 0x3F],
                    _BASE64URL_ALPHABET[block & 0x3F],
                )
            )
            index += 3
        remaining = len(value) - index
        if remaining == 1:
            block = value[index] << 16
            output.extend(
                (
                    _BASE64URL_ALPHABET[(block >> 18) & 0x3F],
                    _BASE64URL_ALPHABET[(block >> 12) & 0x3F],
                )
            )
        elif remaining == 2:
            block = (value[index] << 16) | (value[index + 1] << 8)
            output.extend(
                (
                    _BASE64URL_ALPHABET[(block >> 18) & 0x3F],
                    _BASE64URL_ALPHABET[(block >> 12) & 0x3F],
                    _BASE64URL_ALPHABET[(block >> 6) & 0x3F],
                )
            )
        return output.decode("ascii")
    finally:
        scrub_bytearray(output)


def _domain_commitment(
    key: bytearray,
    domain: bytes,
    value: bytearray,
) -> str:
    message = bytearray()
    try:
        message.extend(domain)
        message.extend(len(value).to_bytes(8, "big"))
        message.extend(value)
        return hmac.new(key, message, hashlib.sha256).hexdigest()
    finally:
        scrub_bytearray(message)


def _validate_pkce_pair(
    verifier: Any,
    expected_challenge: Any,
) -> str:
    """Validate one S256 pair while consuming the verifier buffer."""

    try:
        owned = _require_owned_buffer(
            verifier,
            "pkce_shape",
            MIN_PKCE_VERIFIER_BYTES,
            MAX_PKCE_VERIFIER_BYTES,
            visible_ascii=True,
        )
        if not all(
            byte in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
            b"0123456789-._~"
            for byte in owned
        ):
            raise DedicatedRootOauthHelperError("pkce_shape")
        if (
            type(expected_challenge) is not str
            or len(expected_challenge) != PKCE_S256_CHALLENGE_BYTES
            or not all(
                character.isascii()
                and (character.isalnum() or character in "-_")
                for character in expected_challenge
            )
        ):
            raise DedicatedRootOauthHelperError("pkce_shape")
        digest = bytearray(hashlib.sha256(owned).digest())
        try:
            computed = _base64url_no_padding(digest)
        finally:
            scrub_bytearray(digest)
        if not hmac.compare_digest(computed, expected_challenge):
            raise DedicatedRootOauthHelperError("pkce_mismatch")
        return computed
    finally:
        scrub_bytearray(verifier)


def _hex_nibble(byte: int) -> int:
    if 0x30 <= byte <= 0x39:
        return byte - 0x30
    if 0x41 <= byte <= 0x46:
        return byte - 0x41 + 10
    if 0x61 <= byte <= 0x66:
        return byte - 0x61 + 10
    raise DedicatedRootOauthHelperError("callback_contract")


def _percent_decode_callback_range(
    encoded: bytearray,
    start: int,
    end: int,
    output: bytearray,
) -> None:
    index = start
    completed = False
    try:
        while index < end:
            byte = encoded[index]
            if byte == 0x2B:
                raise DedicatedRootOauthHelperError("callback_contract")
            if byte != 0x25:
                output.append(byte)
                index += 1
                continue
            if index + 2 >= end:
                raise DedicatedRootOauthHelperError("callback_contract")
            high = _hex_nibble(encoded[index + 1])
            low = _hex_nibble(encoded[index + 2])
            output.append((high << 4) | low)
            index += 3
        completed = True
        return None
    except DedicatedRootOauthHelperError:
        raise DedicatedRootOauthHelperError("callback_contract") from None
    except Exception:
        raise DedicatedRootOauthHelperError("callback_contract") from None
    finally:
        if not completed:
            scrub_bytearray(output)


def _validate_callback_query(
    query: Any,
    *,
    state_commitment_key: Any,
    expected_state_commitment_hmac_sha256: Any,
) -> _CallbackSummary:
    """Validate an exact code/state query and return only public metadata."""

    code = None
    state = None
    try:
        code = bytearray()
        state = bytearray()
        _reject_private_aliases(
            "callback_contract",
            query,
            state_commitment_key,
        )
        owned_query = _require_owned_buffer(
            query,
            "callback_contract",
            1,
            MAX_CALLBACK_QUERY_BYTES,
            visible_ascii=True,
        )
        owned_key = _require_owned_buffer(
            state_commitment_key,
            "callback_contract",
            MIN_COMMITMENT_KEY_BYTES,
            MAX_COMMITMENT_KEY_BYTES,
            visible_ascii=False,
            allow_nul=True,
        )
        if not _is_lower_hex(expected_state_commitment_hmac_sha256, 64):
            raise DedicatedRootOauthHelperError("callback_contract")
        cursor = 0
        parameter_count = 0
        code_seen = False
        state_seen = False
        while cursor < len(owned_query):
            separator = owned_query.find(b"&", cursor)
            end = len(owned_query) if separator < 0 else separator
            delimiter = owned_query.find(b"=", cursor, end)
            if (
                end <= cursor
                or delimiter <= cursor
                or delimiter == end - 1
                or owned_query.find(b"=", delimiter + 1, end) >= 0
            ):
                raise DedicatedRootOauthHelperError("callback_contract")
            key_length = delimiter - cursor
            if (
                key_length == 4
                and owned_query[cursor] == 0x63
                and owned_query[cursor + 1] == 0x6F
                and owned_query[cursor + 2] == 0x64
                and owned_query[cursor + 3] == 0x65
            ):
                if code_seen:
                    raise DedicatedRootOauthHelperError("callback_contract")
                code_seen = True
                sink = code
            elif (
                key_length == 5
                and owned_query[cursor] == 0x73
                and owned_query[cursor + 1] == 0x74
                and owned_query[cursor + 2] == 0x61
                and owned_query[cursor + 3] == 0x74
                and owned_query[cursor + 4] == 0x65
            ):
                if state_seen:
                    raise DedicatedRootOauthHelperError("callback_contract")
                state_seen = True
                sink = state
            else:
                raise DedicatedRootOauthHelperError("callback_contract")
            _percent_decode_callback_range(
                owned_query,
                delimiter + 1,
                end,
                sink,
            )
            parameter_count += 1
            if separator < 0:
                cursor = len(owned_query)
            else:
                if separator == len(owned_query) - 1:
                    raise DedicatedRootOauthHelperError("callback_contract")
                cursor = separator + 1
        if parameter_count != 2 or not code_seen or not state_seen:
            raise DedicatedRootOauthHelperError("callback_contract")
        _require_owned_buffer(
            code,
            "callback_contract",
            MIN_AUTHORIZATION_CODE_BYTES,
            MAX_AUTHORIZATION_CODE_BYTES,
            visible_ascii=True,
        )
        _require_owned_buffer(
            state,
            "callback_contract",
            MIN_STATE_BYTES,
            MAX_STATE_BYTES,
            visible_ascii=True,
        )
        code_commitment = _domain_commitment(
            owned_key,
            _AUTHORIZATION_CODE_DOMAIN,
            code,
        )
        actual = _domain_commitment(owned_key, _STATE_DOMAIN, state)
        if not hmac.compare_digest(
            actual,
            expected_state_commitment_hmac_sha256,
        ):
            raise DedicatedRootOauthHelperError("callback_state_mismatch")
        return _CallbackSummary(
            authorization_code_commitment_hmac_sha256=code_commitment,
            authorization_code_present=bool(code),
            parameter_count=parameter_count,
            state_commitment_hmac_sha256=actual,
        )
    finally:
        scrub_bytearray(code)
        scrub_bytearray(state)
        scrub_bytearray(query)
        scrub_bytearray(state_commitment_key)


def _validate_token_material(
    *,
    access_token: Any,
    refresh_token: Any,
    token_type: Any,
    token_commitment_key: Any,
    issued_at_unix: Any,
    expires_in_seconds: Any,
    now_unix: Any,
) -> _TokenSummary:
    """Validate token metadata and return only domain-separated commitments."""

    try:
        _reject_private_aliases(
            "token_contract",
            access_token,
            refresh_token,
            token_type,
            token_commitment_key,
        )
        access = _require_owned_buffer(
            access_token,
            "token_contract",
            MIN_TOKEN_BYTES,
            MAX_TOKEN_BYTES,
            visible_ascii=True,
        )
        refresh = _require_owned_buffer(
            refresh_token,
            "token_contract",
            MIN_TOKEN_BYTES,
            MAX_TOKEN_BYTES,
            visible_ascii=True,
        )
        owned_token_type = _require_owned_buffer(
            token_type,
            "token_contract",
            6,
            6,
            visible_ascii=True,
        )
        key = _require_owned_buffer(
            token_commitment_key,
            "token_contract",
            MIN_COMMITMENT_KEY_BYTES,
            MAX_COMMITMENT_KEY_BYTES,
            visible_ascii=False,
            allow_nul=True,
        )
        if owned_token_type != b"Bearer":
            raise DedicatedRootOauthHelperError("token_contract")
        if (
            not _is_nonnegative_canonical_int(issued_at_unix)
            or not _is_exact_int(expires_in_seconds)
            or not _is_nonnegative_canonical_int(now_unix)
            or now_unix < issued_at_unix
            or not MIN_TOKEN_VALIDITY_SECONDS
            <= expires_in_seconds
            <= MAX_TOKEN_VALIDITY_SECONDS
        ):
            raise DedicatedRootOauthHelperError("token_validity")
        if issued_at_unix > 2**63 - 1 - expires_in_seconds:
            raise DedicatedRootOauthHelperError("token_validity")
        expiration = issued_at_unix + expires_in_seconds
        remaining = expiration - now_unix
        if not MIN_TOKEN_VALIDITY_SECONDS <= remaining <= MAX_TOKEN_VALIDITY_SECONDS:
            raise DedicatedRootOauthHelperError("token_validity")
        access_commitment = _domain_commitment(
            key,
            _ACCESS_TOKEN_DOMAIN,
            access,
        )
        refresh_commitment = _domain_commitment(
            key,
            _REFRESH_TOKEN_DOMAIN,
            refresh,
        )
        return _TokenSummary(
            access_token_commitment_hmac_sha256=access_commitment,
            expiration_unix=expiration,
            refresh_token_commitment_hmac_sha256=refresh_commitment,
            remaining_seconds=remaining,
            token_type="Bearer",
        )
    finally:
        scrub_bytearray(access_token)
        scrub_bytearray(refresh_token)
        scrub_bytearray(token_type)
        scrub_bytearray(token_commitment_key)


def _validate_temporary_sts_material(
    *,
    access_key_id: Any,
    access_key_secret: Any,
    security_token: Any,
    material_commitment_key: Any,
    claimed_account_binding_sha256: Any,
    expiration_unix: Any,
    now_after_caller_identity_unix: Any,
) -> _TemporaryStsSummary:
    """Validate initial STS material after the caller-identity clock point."""

    try:
        _reject_private_aliases(
            "sts_contract",
            access_key_id,
            access_key_secret,
            security_token,
            material_commitment_key,
        )
        key_id = _require_owned_buffer(
            access_key_id,
            "sts_contract",
            12,
            128,
            visible_ascii=True,
        )
        key_secret = _require_owned_buffer(
            access_key_secret,
            "sts_contract",
            1,
            256,
            visible_ascii=True,
        )
        token = _require_owned_buffer(
            security_token,
            "sts_contract",
            1,
            MAX_SECURITY_TOKEN_BYTES,
            visible_ascii=True,
        )
        key = _require_owned_buffer(
            material_commitment_key,
            "sts_contract",
            MIN_COMMITMENT_KEY_BYTES,
            MAX_COMMITMENT_KEY_BYTES,
            visible_ascii=False,
            allow_nul=True,
        )
        if (
            not key_id.startswith(b"STS.")
            or not all(
                key_id[index]
                in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
                b"0123456789._-"
                for index in range(4, len(key_id))
            )
            or not _is_lower_hex(claimed_account_binding_sha256, 64)
        ):
            raise DedicatedRootOauthHelperError("sts_contract")
        if (
            not _is_nonnegative_canonical_int(expiration_unix)
            or not _is_nonnegative_canonical_int(
                now_after_caller_identity_unix
            )
        ):
            raise DedicatedRootOauthHelperError("sts_validity")
        remaining = expiration_unix - now_after_caller_identity_unix
        if not INITIAL_MINIMUM_STS_SECONDS <= remaining <= MAXIMUM_STS_SECONDS:
            raise DedicatedRootOauthHelperError("sts_validity")
        key_id_commitment = _domain_commitment(
            key,
            _STS_ACCESS_KEY_ID_DOMAIN,
            key_id,
        )
        key_secret_commitment = _domain_commitment(
            key,
            _STS_ACCESS_KEY_SECRET_DOMAIN,
            key_secret,
        )
        token_commitment = _domain_commitment(
            key,
            _STS_SECURITY_TOKEN_DOMAIN,
            token,
        )
        binding = {
            "access_key_id_commitment_hmac_sha256": key_id_commitment,
            "access_key_secret_commitment_hmac_sha256": key_secret_commitment,
            "account_binding_sha256": claimed_account_binding_sha256,
            "expiration_unix": expiration_unix,
            "schema": _STS_MATERIAL_BINDING_SCHEMA,
            "security_token_commitment_hmac_sha256": token_commitment,
        }
        return _TemporaryStsSummary(
            account_binding_sha256=claimed_account_binding_sha256,
            credential_material_binding_sha256=hashlib.sha256(
                _canonical_bytes(binding)
            ).hexdigest(),
            expiration_unix=expiration_unix,
            remaining_seconds=remaining,
        )
    finally:
        scrub_bytearray(access_key_id)
        scrub_bytearray(access_key_secret)
        scrub_bytearray(security_token)
        scrub_bytearray(material_commitment_key)


def _account_binding(
    account_commitment: str,
    principal_commitment: str,
) -> str:
    aggregate = {
        "account_commitment_hmac_sha256": account_commitment,
        "principal_commitment_hmac_sha256": principal_commitment,
        "schema": C1_ACCOUNT_BINDING_SCHEMA,
    }
    return hashlib.sha256(_canonical_bytes(aggregate)).hexdigest()


def _validate_identity_binding(
    *,
    account_identity: Any,
    principal_identity: Any,
    identity_commitment_key: Any,
    expected_account_commitment_hmac_sha256: Any,
    expected_principal_commitment_hmac_sha256: Any,
) -> _IdentityBindingSummary:
    """Validate both expected identity commitments without a role oracle."""

    try:
        _reject_private_aliases(
            "identity_contract",
            account_identity,
            principal_identity,
            identity_commitment_key,
        )
        account = _require_owned_buffer(
            account_identity,
            "identity_contract",
            1,
            MAX_IDENTITY_BYTES,
            visible_ascii=True,
        )
        principal = _require_owned_buffer(
            principal_identity,
            "identity_contract",
            1,
            MAX_IDENTITY_BYTES,
            visible_ascii=True,
        )
        key = _require_owned_buffer(
            identity_commitment_key,
            "identity_contract",
            MIN_COMMITMENT_KEY_BYTES,
            MAX_COMMITMENT_KEY_BYTES,
            visible_ascii=False,
            allow_nul=True,
        )
        expected_shapes_valid = (
            _is_lower_hex(expected_account_commitment_hmac_sha256, 64)
            and _is_lower_hex(expected_principal_commitment_hmac_sha256, 64)
        )
        if not expected_shapes_valid:
            raise DedicatedRootOauthHelperError("identity_contract")
        account_commitment = _domain_commitment(key, _ACCOUNT_DOMAIN, account)
        principal_commitment = _domain_commitment(
            key,
            _PRINCIPAL_DOMAIN,
            principal,
        )
        account_matches = hmac.compare_digest(
            account_commitment,
            expected_account_commitment_hmac_sha256,
        )
        principal_matches = hmac.compare_digest(
            principal_commitment,
            expected_principal_commitment_hmac_sha256,
        )
        if not (account_matches & principal_matches):
            raise DedicatedRootOauthHelperError("identity_commitment_mismatch")
        return _IdentityBindingSummary(
            account_binding_sha256=_account_binding(
                account_commitment,
                principal_commitment,
            ),
            account_commitment_hmac_sha256=account_commitment,
            principal_commitment_hmac_sha256=principal_commitment,
        )
    finally:
        scrub_bytearray(account_identity)
        scrub_bytearray(principal_identity)
        scrub_bytearray(identity_commitment_key)


def _plain_public(value: Any) -> Any:
    """Thaw trusted immutable public values into fresh JSON containers."""

    if isinstance(value, Mapping):
        return {key: _plain_public(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_plain_public(item) for item in value]
    if type(value) in (bool, int, str) or value is None:
        return value
    raise TypeError("public_contract_type")


def _validate_json_value(value: Any, depth: int = 0) -> None:
    if depth > MAX_JSON_DEPTH:
        raise DedicatedRootOauthHelperError("canonical_depth")
    if value is None or type(value) is bool:
        return
    if type(value) is int:
        if value < -(2**63) or value > 2**63 - 1:
            raise DedicatedRootOauthHelperError("canonical_integer")
        return
    if type(value) is str:
        try:
            encoded = value.encode("utf-8", "strict")
        except UnicodeError:
            raise DedicatedRootOauthHelperError("canonical_text") from None
        if (
            not encoded
            or len(encoded) > MAX_PUBLIC_TEXT_BYTES
            or b"\x00" in encoded
        ):
            raise DedicatedRootOauthHelperError("canonical_text")
        return
    if type(value) is list:
        if len(value) > MAX_JSON_ITEMS:
            raise DedicatedRootOauthHelperError("canonical_items")
        for item in value:
            _validate_json_value(item, depth + 1)
        return
    if type(value) is dict:
        if len(value) > MAX_JSON_ITEMS:
            raise DedicatedRootOauthHelperError("canonical_items")
        for key, item in value.items():
            if type(key) is not str:
                raise DedicatedRootOauthHelperError("canonical_key")
            _validate_json_value(key, depth + 1)
            _validate_json_value(item, depth + 1)
        return
    raise DedicatedRootOauthHelperError("canonical_type")


def _canonical_bytes(value: dict[str, Any]) -> bytes:
    _validate_json_value(value)
    try:
        raw = (
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("ascii")
            + b"\n"
        )
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise DedicatedRootOauthHelperError("canonical_type") from None
    if len(raw) > MAX_CANONICAL_BYTES:
        raise DedicatedRootOauthHelperError("canonical_size")
    return raw


def _helper_contract_object() -> dict[str, Any]:
    return {
        "action_authorization": _plain_public(ACTION_AUTHORIZATION),
        "assessment": ASSESSMENT,
        "bootstrap_status": BOOTSTRAP_STATUS,
        "c1_interface_reference": {
            "current_inner_envelope_source": C1_CURRENT_INNER_ENVELOPE_SOURCE,
            "dedicated_helper_source_label_accepted": False,
            "exact_keys": [
                "account_binding_sha256",
                "credential_payload_exposed",
                "minimum_remaining_validity_seconds",
                "oauth_configure_count",
                "oauth_refresh_count",
                "schema",
                "status",
            ],
            "interface_schema": C1_INTERFACE_SCHEMA,
            "ready_status": C1_READY_STATUS,
            "reference_only": True,
            "runnable": False,
            "successor_required": True,
        },
        "c2_ready_ack_reference": {
            "ack_count": 1,
            "ack_status": C2_ACK_STATUS,
            "current_fixed_c1_binding": {
                "acceptance_revision": C2_CURRENT_C1_ACCEPTANCE_REVISION,
                "bytes": C2_CURRENT_C1_BYTES,
                "file_sha256": C2_CURRENT_C1_FILE_SHA256,
                "git_blob_oid": C2_CURRENT_C1_GIT_BLOB_OID,
                "source_ref": C2_CURRENT_C1_SOURCE_REF,
                "source_revision": C2_CURRENT_C1_SOURCE_REVISION,
            },
            "dedicated_helper_fixed_binding_present": False,
            "exact_keys": [
                "ack_count",
                "capsule_acceptance_revision",
                "capsule_source_revision",
                "projection",
                "ready_sha256",
                "schema",
                "status",
            ],
            "handshake_schema": C2_HANDSHAKE_SCHEMA,
            "ready_binding_schema": C2_READY_BINDING_SCHEMA,
            "ready_count": 0,
            "ready_status": C2_READY_STATUS,
            "reference_only": True,
            "runnable": False,
            "successor_required": True,
        },
        "default_action_leaves_present": False,
        "future_action_requirements": {
            "browser_managed_provider_request_count": None,
            "browser_managed_provider_request_count_status": "NOT_OBSERVABLE",
            "browser_url_transport": "ONE_SHOT_ANONYMOUS_BLOCKING_FD",
            "browser_url_in_argv": False,
            "browser_url_in_environment": False,
            "darwin_anonymous_unix_socket_device_normalization": (
                "FUTURE_ACTION_ADAPTER_REQUIRED"
            ),
            "dedicated_runtime_inventory_relationship": (
                "INDEPENDENT_SIBLING_NOT_C1_INVENTORY"
            ),
            "dedicated_runtime_root": DEDICATED_RUNTIME_ROOT,
            "replay_protection": "FUTURE_ROOT_TRANSACTION_STATE_REQUIRED",
        },
        "operational_blockers": _plain_public(OPERATIONAL_BLOCKERS),
        "pure_core": {
            "action_authority_created": False,
            "callback_contract": {
                "authorization_code_binding": "DOMAIN_SEPARATED_HMAC_SHA256",
                "duplicate_or_extra_parameters_rejected": True,
                "exact_parameters": ["code", "state"],
                "raw_authorization_code_exposed": False,
                "state_binding": "DOMAIN_SEPARATED_HMAC_SHA256",
            },
            "caller_owned_secret_buffer_type": (
                "DISPOSABLE_BYTEARRAY_COPY_CONSUMED_AND_SCRUBBED"
            ),
            "identity_contract": {
                "account_binding_schema": C1_ACCOUNT_BINDING_SCHEMA,
                "aggregate_binding": "SHA256_CANONICAL_ACCOUNT_BINDING",
                "commitment_algorithm": "DOMAIN_SEPARATED_HMAC_SHA256",
                "raw_identity_exposed": False,
            },
            "pkce_contract": {
                "algorithm": "S256",
                "challenge_base64url_padding": False,
                "verifier_maximum_bytes": MAX_PKCE_VERIFIER_BYTES,
                "verifier_minimum_bytes": MIN_PKCE_VERIFIER_BYTES,
                "verifier_octets": "RFC7636_UNRESERVED_ASCII",
            },
            "schema": PURE_CORE_SCHEMA,
            "secret_buffers_scrubbed_on_all_validation_paths": True,
            "temporary_sts_contract": {
                "account_binding_input_validation": "LOWER_HEX_64_SHAPE_ONLY",
                "caller_identity_completion_requirement": (
                    "FUTURE_ACTION_ORCHESTRATOR_REQUIRED"
                ),
                "credential_envelope_sha256_stability_requirement": (
                    "REQUIRED_NOT_VERIFIED_BY_C4_S"
                ),
                "exact_owned_secret_fields": [
                    "access_key_id",
                    "access_key_secret",
                    "security_token",
                ],
                "expiration_field": "expiration_unix",
                "final_clock_recheck_after_caller_identity": True,
                "initial_minimum_remaining_seconds": (
                    INITIAL_MINIMUM_STS_SECONDS
                ),
                "maximum_remaining_seconds": MAXIMUM_STS_SECONDS,
                "per_begin_minimum_remaining_seconds": (
                    PER_BEGIN_MINIMUM_STS_SECONDS
                ),
                "per_begin_validation": {
                    "implemented_by_c4_s": False,
                    "required_component": (
                        "C1_SOURCE_LABEL_AND_C2_FIXED_BINDING_SUCCESSORS"
                    ),
                    "status": "FUTURE_C1_CAPSULE_REQUIRED",
                },
                "raw_temporary_sts_exposed": False,
                "successor_envelope_source_required": True,
            },
            "token_contract": {
                "maximum_validity_seconds": MAX_TOKEN_VALIDITY_SECONDS,
                "minimum_validity_seconds": MIN_TOKEN_VALIDITY_SECONDS,
                "raw_token_exposed": False,
                "token_commitment_algorithm": "DOMAIN_SEPARATED_HMAC_SHA256",
                "token_type_input": "CALLER_OWNED_BYTEARRAY_EXACT_BEARER",
            },
        },
        "schema": CONTRACT_SCHEMA,
    }


_HELPER_CONTRACT_BYTES = _canonical_bytes(_helper_contract_object())


def _source_status_object() -> dict[str, Any]:
    return {
        "action_authorization": _plain_public(ACTION_AUTHORIZATION),
        "assessment": ASSESSMENT,
        "authorizes_execution": False,
        "authorized_cny": "0.00",
        "bootstrap_status": BOOTSTRAP_STATUS,
        "execution_gates": _plain_public(EXECUTION_GATES),
        "helper_contract": _helper_contract_object(),
        "implementation_complete": True,
        "implementation_completion_scope": (
            "C4_S_PURE_VALIDATION_AND_INERT_CONTRACT_ONLY"
        ),
        "incurred_cny": "0.00",
        "operational_blockers": _plain_public(OPERATIONAL_BLOCKERS),
        "operational_ready": False,
        "prior_research_audit": _plain_public(PRIOR_RESEARCH_AUDIT),
        "schema": SOURCE_SCHEMA,
        "source_round_operation_count_scope": SOURCE_ROUND_OPERATION_COUNT_SCOPE,
        "source_round_operation_count_scope_detail": (
            "PURE_VALIDATOR_INVOCATIONS_EXCLUDED_AND_NOT_RECORDED"
        ),
        "source_round_operation_counts": _plain_public(
            SOURCE_ROUND_OPERATION_COUNTS
        ),
        "pure_validation_invocation_accounting": "STATELESS_NOT_RECORDED",
        "status": SOURCE_ONLY_STATUS,
    }


_SOURCE_STATUS_BYTES = _canonical_bytes(_source_status_object())


def helper_contract() -> bytes:
    """Return the cached canonical, Secret-free helper contract."""

    return _HELPER_CONTRACT_BYTES


def source_status() -> bytes:
    """Return the cached canonical, Secret-free source status."""

    return _SOURCE_STATUS_BYTES


def request_bootstrap(*_args: Any, **_kwargs: Any) -> NoReturn:
    """Refuse before inspecting arguments or touching an action surface."""

    raise DedicatedRootOauthHelperError("NOT_PROVISIONED") from None


def main(_argv: Any = None) -> int:
    """Inert entry point; never reads ``_argv`` and never emits output."""

    try:
        request_bootstrap()
    except DedicatedRootOauthHelperError:
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
