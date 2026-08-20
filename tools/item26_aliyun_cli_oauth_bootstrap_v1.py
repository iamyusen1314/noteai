#!/usr/bin/env python3
"""Inert stock-Aliyun-CLI OAuth capability assessment for Item 26 M1.

This module binds public, Secret-free facts about the locally installed
official Aliyun CLI 3.4.11 target and its corresponding official release
source.  It records the stock capability observations separately from the
requirements accepted by NoteAI.  The resulting assessment is deliberately
and permanently ``NO_GO_STOCK_CLI_FD_ONLY_OAUTH``.

This is source implementation only.  It does not inspect the installed file,
run the CLI, read a profile or environment variable, launch a process, open a
file, use a descriptor, contact a network endpoint, or configure OAuth.  The
public bootstrap boundary fails before inspecting any caller argument, and the
default entry point emits nothing.
"""

from __future__ import annotations

import json
from types import MappingProxyType
from typing import Any, Mapping, NoReturn


SOURCE_SCHEMA = "noteai.item26.aliyun-cli-oauth-bootstrap-source.v1"
STOCK_CLI_PROJECTION_SCHEMA = (
    "noteai.item26.aliyun-cli-oauth-bootstrap-stock-projection.v1"
)
SOURCE_ONLY_STATUS = "SOURCE_ONLY_IMPLEMENTATION_COMPLETE_NOT_AUTHORIZED"
BOOTSTRAP_STATUS = "NOT_PROVISIONED"
STOCK_CLI_ASSESSMENT = "NO_GO_STOCK_CLI_FD_ONLY_OAUTH"

LOCAL_CLI_DISTRIBUTION = "OFFICIAL_HOMEBREW_ALIYUN_CLI"
LOCAL_CLI_VERSION = "3.4.11"
LOCAL_CLI_RESOLVED_PATH = "/opt/homebrew/Cellar/aliyun-cli/3.4.11/bin/aliyun"
LOCAL_CLI_MODE = "0555"
LOCAL_CLI_OWNER = "openclaw:admin"
LOCAL_CLI_BYTES = 87_064_450
LOCAL_CLI_SHA256 = (
    "7a418ea428dcbfeaab2af8760938aeda8d2f16bd77b586cbe4c75b07034df8fb"
)
OFFICIAL_RELEASE_TAG = "v3.4.11"
OFFICIAL_RELEASE_COMMIT = "f54f5fe9caa99723a6324b20eaa60f3de3b049cb"

MAX_CANONICAL_BYTES = 65_536
MAX_JSON_DEPTH = 32
MAX_JSON_ITEMS = 256
MAX_PUBLIC_TEXT_BYTES = 16_384

SOURCE_ROUND_OPERATION_COUNT_SCOPE = "MODULE_RUNTIME_ONLY"
LOCAL_IDENTITY_PROVENANCE = "ACCEPTED_TRACKED_LEDGER_STATIC_NOT_LIVE_INSPECTION"


def _deep_freeze(value: Any) -> Any:
    """Recursively freeze trusted public evidence literals."""

    if type(value) is dict:
        return MappingProxyType(
            {key: _deep_freeze(item) for key, item in value.items()}
        )
    if type(value) is list:
        return tuple(_deep_freeze(item) for item in value)
    if type(value) in (bool, int, str) or value is None:
        return value
    raise TypeError("public_evidence_type")


EVIDENCE_INDEX = _deep_freeze(
    {
        "ACCEPTED_LOCAL_IDENTITY_LEDGER": {
            "kind": "ACCEPTED_TRACKED_LEDGER_STATIC_IDENTITY",
            "live_inspection_performed": False,
            "path": "deploy/production/internal-deployment-readiness.json",
            "record": (
                "manual_cost_stop_a3_g_terminal_acceptance_aliyun_fd_adapter_"
                "l_candidate_20260819"
            ),
        },
        "BROWSER_PROCESS_EXACT_SOURCE": {
            "commit": OFFICIAL_RELEASE_COMMIT,
            "kind": "COMMIT_PINNED_OFFICIAL_SOURCE",
            "path": "util/util.go",
            "symbols": ["OpenBrowser"],
            "url": (
                "https://github.com/aliyun/aliyun-cli/blob/"
                "f54f5fe9caa99723a6324b20eaa60f3de3b049cb/util/util.go"
            ),
        },
        "CONFIG_PATH_ENTRY_EXACT_SOURCE": {
            "commit": OFFICIAL_RELEASE_COMMIT,
            "kind": "COMMIT_PINNED_OFFICIAL_SOURCE",
            "path": "config/configure.go",
            "symbols": [
                "NewConfigureCommand",
                "doConfigure",
                "loadOrCreateConfiguration",
            ],
            "url": (
                "https://github.com/aliyun/aliyun-cli/blob/"
                "f54f5fe9caa99723a6324b20eaa60f3de3b049cb/config/configure.go"
            ),
        },
        "CONFIG_STORAGE_EXACT_SOURCE": {
            "commit": OFFICIAL_RELEASE_COMMIT,
            "kind": "COMMIT_PINNED_OFFICIAL_SOURCE",
            "path": "config/configuration.go",
            "symbols": [
                "getConfigurePath",
                "LoadProfileWithContext",
                "LoadOrCreateConfiguration",
                "SaveConfiguration",
                "SaveConfigurationWithContext",
                "atomicWriteFileWithRename",
                "GetConfigPath",
            ],
            "url": (
                "https://github.com/aliyun/aliyun-cli/blob/"
                "f54f5fe9caa99723a6324b20eaa60f3de3b049cb/"
                "config/configuration.go"
            ),
        },
        "CREDENTIALS_OFFICIAL_DOC": {
            "kind": "SECONDARY_MUTABLE_OFFICIAL_DOCUMENTATION",
            "mutable": True,
            "url": "https://help.aliyun.com/en/cli/configure-credentials/",
        },
        "EXTERNAL_INGRESS_EXACT_README": {
            "commit": OFFICIAL_RELEASE_COMMIT,
            "kind": "COMMIT_PINNED_OFFICIAL_SOURCE",
            "path": "README.md",
            "section": "Use an external program to get credentials",
            "url": (
                "https://github.com/aliyun/aliyun-cli/blob/"
                "f54f5fe9caa99723a6324b20eaa60f3de3b049cb/README.md"
            ),
        },
        "OAUTH_EXCHANGE_TTL_EXACT_SOURCE": {
            "commit": OFFICIAL_RELEASE_COMMIT,
            "kind": "COMMIT_PINNED_OFFICIAL_SOURCE",
            "path": "config/configure.go",
            "symbols": [
                "OAuth case",
                "exchangeFromOAuth",
                "tryRefreshOauthToken",
            ],
            "url": (
                "https://github.com/aliyun/aliyun-cli/blob/"
                "f54f5fe9caa99723a6324b20eaa60f3de3b049cb/config/configure.go"
            ),
        },
        "OAUTH_FLOW_EXACT_SOURCE": {
            "commit": OFFICIAL_RELEASE_COMMIT,
            "kind": "COMMIT_PINNED_OFFICIAL_SOURCE",
            "path": "config/configure.go",
            "symbols": [
                "oauthClientMap",
                "oauthBaseUrlMap",
                "signInMap",
                "configureOAuth",
                "startOauthFlow",
            ],
            "url": (
                "https://github.com/aliyun/aliyun-cli/blob/"
                "f54f5fe9caa99723a6324b20eaa60f3de3b049cb/config/configure.go"
            ),
        },
        "OAUTH_OFFICIAL_DOC": {
            "kind": "SECONDARY_MUTABLE_OFFICIAL_DOCUMENTATION",
            "mutable": True,
            "url": "https://help.aliyun.com/zh/cli/oauth-credentials",
        },
        "PROFILE_REFRESH_EXACT_SOURCE": {
            "commit": OFFICIAL_RELEASE_COMMIT,
            "kind": "COMMIT_PINNED_OFFICIAL_SOURCE",
            "path": "config/profile.go",
            "symbols": [
                "type Profile",
                "mergeProfileAfterCredentialRefresh",
                "(*Profile).GetCredential OAuth case",
                "(*Profile).GetRuntimeEnv",
            ],
            "url": (
                "https://github.com/aliyun/aliyun-cli/blob/"
                "f54f5fe9caa99723a6324b20eaa60f3de3b049cb/config/profile.go"
            ),
        },
        "PROFILE_STDOUT_EXACT_SOURCE": {
            "commit": OFFICIAL_RELEASE_COMMIT,
            "kind": "COMMIT_PINNED_OFFICIAL_SOURCE",
            "path": "config/configure_get.go",
            "symbols": ["doConfigureGet"],
            "url": (
                "https://github.com/aliyun/aliyun-cli/blob/"
                "f54f5fe9caa99723a6324b20eaa60f3de3b049cb/"
                "config/configure_get.go"
            ),
        },
        "UPSTREAM_RELEASE_V3_4_11": {
            "commit": OFFICIAL_RELEASE_COMMIT,
            "commit_url": (
                "https://github.com/aliyun/aliyun-cli/commit/"
                "f54f5fe9caa99723a6324b20eaa60f3de3b049cb"
            ),
            "kind": "OFFICIAL_RELEASE_AND_EXACT_COMMIT",
            "release_url": (
                "https://github.com/aliyun/aliyun-cli/releases/tag/v3.4.11"
            ),
            "tag": OFFICIAL_RELEASE_TAG,
        },
    }
)


CAPABILITY_EVIDENCE_IDS = _deep_freeze(
    {
        "browser_loopback_pkce": [
            "OAUTH_FLOW_EXACT_SOURCE",
            "BROWSER_PROCESS_EXACT_SOURCE",
            "OAUTH_OFFICIAL_DOC",
        ],
        "config_path_full_lifecycle_safe": [
            "CONFIG_PATH_ENTRY_EXACT_SOURCE",
            "PROFILE_REFRESH_EXACT_SOURCE",
            "CONFIG_STORAGE_EXACT_SOURCE",
        ],
        "custom_config_flag": ["CONFIG_PATH_ENTRY_EXACT_SOURCE"],
        "device_code": ["OAUTH_FLOW_EXACT_SOURCE", "OAUTH_OFFICIAL_DOC"],
        "fd_secret_export": [
            "PROFILE_STDOUT_EXACT_SOURCE",
            "EXTERNAL_INGRESS_EXACT_README",
            "CREDENTIALS_OFFICIAL_DOC",
        ],
        "headless": [
            "OAUTH_FLOW_EXACT_SOURCE",
            "BROWSER_PROCESS_EXACT_SOURCE",
            "OAUTH_OFFICIAL_DOC",
        ],
        "oauth_configure_plugin_required": ["OAUTH_FLOW_EXACT_SOURCE"],
        "profile_contains_secrets": [
            "PROFILE_REFRESH_EXACT_SOURCE",
            "CREDENTIALS_OFFICIAL_DOC",
        ],
        "refresh_can_touch_default_config": [
            "CONFIG_PATH_ENTRY_EXACT_SOURCE",
            "PROFILE_REFRESH_EXACT_SOURCE",
            "CONFIG_STORAGE_EXACT_SOURCE",
            "OAUTH_OFFICIAL_DOC",
        ],
        "requested_sts_ttl_control": ["OAUTH_EXCHANGE_TTL_EXACT_SOURCE"],
        "stdout_profile_secret_export": [
            "PROFILE_STDOUT_EXACT_SOURCE",
            "CREDENTIALS_OFFICIAL_DOC",
        ],
    }
)


CAPABILITY_EVIDENCE_CLASSIFICATIONS = MappingProxyType(
    {
        "browser_loopback_pkce": "DIRECT_EXACT_SOURCE_AND_OFFICIAL_DOC",
        "config_path_full_lifecycle_safe": "DIRECT_EXACT_SOURCE",
        "custom_config_flag": "DIRECT_EXACT_SOURCE",
        "device_code": "ABSENCE_FROM_EXACT_SOURCE_CROSSED_WITH_OFFICIAL_DOC",
        "fd_secret_export": "EXACT_SURFACE_AND_DIRECTION_INFERENCE",
        "headless": "ABSENCE_FROM_EXACT_SOURCE_CROSSED_WITH_OFFICIAL_DOC",
        "oauth_configure_plugin_required": "INFERENCE_FROM_EXACT_SOURCE",
        "profile_contains_secrets": "DIRECT_EXACT_SOURCE_AND_OFFICIAL_DOC",
        "refresh_can_touch_default_config": "DIRECT_EXACT_SOURCE_AND_DOC",
        "requested_sts_ttl_control": "DIRECT_EXACT_SOURCE",
        "stdout_profile_secret_export": "DIRECT_EXACT_SOURCE_AND_OFFICIAL_DOC",
    }
)


# These are observations of the fixed stock release, not NoteAI acceptance
# decisions.  In particular, browser-loopback PKCE and a custom-config flag do
# exist.  Their presence must never be rewritten as proof of a safe, headless,
# FD-only OAuth bootstrap.
OBSERVED_STOCK_CAPABILITIES = MappingProxyType(
    {
        "browser_loopback_pkce": True,
        "config_path_full_lifecycle_safe": False,
        "custom_config_flag": True,
        "device_code": False,
        "fd_secret_export": False,
        "headless": False,
        "oauth_configure_plugin_required": False,
        "profile_contains_secrets": True,
        "refresh_can_touch_default_config": True,
        "requested_sts_ttl_control": False,
        "stdout_profile_secret_export": True,
    }
)


# Each listed blocking NoteAI requirement is independently failed.  ``ABSENT``
# means the required stock capability is not present.  ``UNSAFE`` means a
# nearby stock feature exists, but its lifecycle or disclosure behavior
# violates the accepted boundary.  ``stock_support`` remains an exact bool and
# is false for every row.
_ACCEPTED_REQUIREMENT_CLASSIFICATIONS = MappingProxyType(
    {
        "browserless_headless_oauth": "ABSENT",
        "device_code_oauth": "ABSENT",
        "fd_only_secret_export": "ABSENT",
        "isolated_config_full_lifecycle": "UNSAFE",
        "refresh_default_config_neutral": "UNSAFE",
        "requested_sts_ttl_control": "ABSENT",
        "secret_free_profile": "UNSAFE",
        "secret_free_stdout": "UNSAFE",
    }
)


EXECUTION_GATES = MappingProxyType(
    {
        "browser_oauth": False,
        "capture_integration": False,
        "cli_oauth_configuration": False,
        "credential_bootstrap": False,
        "plugin_execution": False,
        "stock_cli_execution": False,
    }
)


SOURCE_ROUND_OPERATION_COUNTS = MappingProxyType(
    {
        "argv_read_count": 0,
        "automatic_retry_count": 0,
        "browser_launch_count": 0,
        "capture_count": 0,
        "cleanup_count": 0,
        "cli_configure_count": 0,
        "cli_execution_count": 0,
        "config_read_count": 0,
        "config_write_count": 0,
        "credential_read_count": 0,
        "credential_write_count": 0,
        "database_connection_count": 0,
        "environment_read_count": 0,
        "filesystem_read_count": 0,
        "filesystem_write_count": 0,
        "materialization_count": 0,
        "network_call_count": 0,
        "oauth_login_count": 0,
        "oauth_refresh_count": 0,
        "plugin_execution_count": 0,
        "provider_call_count": 0,
        "root_read_count": 0,
        "root_write_count": 0,
        "secret_input_count": 0,
        "secret_output_count": 0,
        "stderr_write_count": 0,
        "stdout_write_count": 0,
        "subprocess_count": 0,
        "sudo_dispatch_count": 0,
    }
)


# This historical research disclosure is intentionally outside the source-round
# zero counters.  The earlier read-intended Homebrew query caused one
# non-provider metadata-network event and may have written one Homebrew cache.
# Neither event was an Aliyun/provider/cloud call.
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
    "BootstrapError",
    "assess_stock_cli",
    "main",
    "request_bootstrap",
    "source_status",
    "stock_cli_projection",
)


class BootstrapError(RuntimeError):
    """Fixed public error surface carrying no caller-controlled value."""

    __slots__ = ("code",)

    def __init__(self, code: str):
        if code != "NOT_PROVISIONED":
            code = "NOT_PROVISIONED"
        self.code = code
        super().__init__(code)

    def __repr__(self) -> str:
        return "BootstrapError('NOT_PROVISIONED')"


def _plain_public(value: Any) -> Any:
    """Thaw trusted public evidence into JSON-only fresh containers."""

    if isinstance(value, Mapping):
        return {key: _plain_public(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_plain_public(item) for item in value]
    if type(value) in (bool, int, str) or value is None:
        return value
    raise TypeError("public_evidence_type")


def _accepted_requirement_object() -> dict[str, dict[str, Any]]:
    return {
        name: {
            "classification": classification,
            "stock_support": False,
        }
        for name, classification in _ACCEPTED_REQUIREMENT_CLASSIFICATIONS.items()
    }


def _stock_cli_projection_object() -> dict[str, Any]:
    return {
        "accepted_requirements": _accepted_requirement_object(),
        "assessment": STOCK_CLI_ASSESSMENT,
        "capability_evidence_classifications": _plain_public(
            CAPABILITY_EVIDENCE_CLASSIFICATIONS
        ),
        "capability_evidence_ids": _plain_public(CAPABILITY_EVIDENCE_IDS),
        "evidence_index": _plain_public(EVIDENCE_INDEX),
        "local_cli_identity": {
            "bytes": LOCAL_CLI_BYTES,
            "distribution": LOCAL_CLI_DISTRIBUTION,
            "evidence_id": "ACCEPTED_LOCAL_IDENTITY_LEDGER",
            "live_inspection_performed": False,
            "mode": LOCAL_CLI_MODE,
            "owner": LOCAL_CLI_OWNER,
            "provenance": LOCAL_IDENTITY_PROVENANCE,
            "resolved_path": LOCAL_CLI_RESOLVED_PATH,
            "root_owned": False,
            "sha256": LOCAL_CLI_SHA256,
            "version": LOCAL_CLI_VERSION,
        },
        "observed_stock_capabilities": _plain_public(
            OBSERVED_STOCK_CAPABILITIES
        ),
        "official_release_identity": {
            "commit": OFFICIAL_RELEASE_COMMIT,
            "evidence_id": "UPSTREAM_RELEASE_V3_4_11",
            "tag": OFFICIAL_RELEASE_TAG,
        },
        "schema": STOCK_CLI_PROJECTION_SCHEMA,
    }


def _validate_json_value(value: Any, depth: int = 0) -> None:
    if depth > MAX_JSON_DEPTH:
        raise ValueError("canonical_depth")
    if value is None:
        return
    if type(value) is bool:
        return
    if type(value) is int:
        if value < -(2**63) or value > 2**63 - 1:
            raise ValueError("canonical_integer")
        return
    if type(value) is str:
        encoded = value.encode("utf-8", "strict")
        if not encoded or len(encoded) > MAX_PUBLIC_TEXT_BYTES or b"\x00" in encoded:
            raise ValueError("canonical_text")
        return
    if type(value) is list:
        if len(value) > MAX_JSON_ITEMS:
            raise ValueError("canonical_items")
        for item in value:
            _validate_json_value(item, depth + 1)
        return
    if type(value) is dict:
        if len(value) > MAX_JSON_ITEMS:
            raise ValueError("canonical_items")
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("canonical_key")
            _validate_json_value(key, depth + 1)
            _validate_json_value(item, depth + 1)
        return
    raise ValueError("canonical_type")


def _canonical_bytes(value: dict[str, Any]) -> bytes:
    _validate_json_value(value)
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
    if len(raw) > MAX_CANONICAL_BYTES:
        raise ValueError("canonical_size")
    return raw


_STOCK_CLI_PROJECTION_BYTES = _canonical_bytes(_stock_cli_projection_object())


def _source_status_object() -> dict[str, Any]:
    return {
        "authorizes_execution": False,
        "authorized_cny": "0.00",
        "bootstrap_status": BOOTSTRAP_STATUS,
        "execution_gates": _plain_public(EXECUTION_GATES),
        "implementation_complete": True,
        "incurred_cny": "0.00",
        "operational_ready": False,
        "prior_research_audit": _plain_public(PRIOR_RESEARCH_AUDIT),
        "schema": SOURCE_SCHEMA,
        "source_round_operation_count_scope": SOURCE_ROUND_OPERATION_COUNT_SCOPE,
        "source_round_operation_counts": _plain_public(
            SOURCE_ROUND_OPERATION_COUNTS
        ),
        "status": SOURCE_ONLY_STATUS,
        "stock_cli_assessment": STOCK_CLI_ASSESSMENT,
        "stock_cli_projection": _stock_cli_projection_object(),
    }


_SOURCE_STATUS_BYTES = _canonical_bytes(_source_status_object())


def stock_cli_projection() -> bytes:
    """Return the immutable canonical public stock-CLI projection."""

    return _STOCK_CLI_PROJECTION_BYTES


def assess_stock_cli() -> str:
    """Return the only possible stock-CLI assessment."""

    return STOCK_CLI_ASSESSMENT


def source_status() -> bytes:
    """Return canonical, Secret-free source status bytes."""

    return _SOURCE_STATUS_BYTES


def request_bootstrap(*_args: Any, **_kwargs: Any) -> NoReturn:
    """Refuse before inspecting arguments or touching any action surface."""

    raise BootstrapError("NOT_PROVISIONED") from None


def main(_argv: Any = None) -> int:
    """Inert default entry point; it never reads ``_argv`` or emits output."""

    try:
        request_bootstrap()
    except BootstrapError:
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
