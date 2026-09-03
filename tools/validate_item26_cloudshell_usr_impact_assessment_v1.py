#!/usr/bin/env python3
"""Validate a Secret-free Item26 Cloud Shell /usr impact receipt."""

import hashlib
import json
import re
import sys
from pathlib import Path


SCHEMA = "noteai.item26.cloudshell-usr-impact-assessment.v1"
PREDECESSOR = {
    "schema": "noteai.item26.cloudshell-wrapper-parent-diagnostic.v1",
    "source_commit": "9c3b055e2f24b4c82f894d87ff954ae49a4b553a",
    "command_bytes": 8732,
    "command_sha256": "4081b80e10399a7119b3b2963f101ade1b702b8cdf48fd1853c92ecbdb71e7c4",
    "receipt_bytes": 4191,
    "receipt_sha256": "260bb8abdcd0936625712042ee6c485ccc6c906308622318f2210889b8b2b9f0",
    "commitment_sha256": "a09720b831b1141ff16b6b35a2c4d5abeff3e380c78893a9c70fdc340045479e",
    "diagnostic_state": "CURRENT_STABLE_MATCH",
    "reason_code": "WRITABLE_EXECUTABLE_PARENT",
    "culprit_scope": "LEXICAL",
    "culprit_path": "/usr",
    "uid": 0,
    "gid": 0,
    "mode": "1777",
    "nlink": 1,
    "group_or_other_writable": True,
}
SCOPE = {
    "root": "/",
    "subject": "/usr",
    "fixed_child_relative_name": "shell",
    "mount_metadata": "linux-proc-mountinfo",
}
BOUNDARY_VALUES = {
    "historical_identity_continuity_proven": False,
    "receipt_origin_authenticated": False,
    "commitment_is_authentication_signature": False,
    "direct_single_execution_provenance_required": True,
    "mount_namespace_identity_authenticated": False,
    "cross_namespace_metadata_visibility_proven": False,
    "platform_operator_intent_proven": False,
    "effective_write_access_proven": False,
    "write_probe_performed": False,
    "metadata_only_impact_assessment": True,
    "allowlist_proven_safe": False,
    "deeper_execution_chain_verified": False,
    "caller_privilege_constraints_verified": False,
    "process_privilege_assessed": False,
    "user_namespace_assessed": False,
    "idmapped_mount_semantics_assessed": False,
    "filesystem_permission_semantics_assessed": False,
    "mount_observation_aba_excluded": False,
    "same_fd_chain_execution_required": True,
    "execveat_equivalent_required": True,
    "mutation_authorized": False,
    "security_predicate_relaxed": False,
    "next_stage_authorized": False,
    "same_invocation_replay_allowed": False,
    "automatic_retry_allowed": False,
    "proc_mountinfo_read_limit": 2,
    "mount_source_value_emitted": 0,
    "mount_root_value_emitted": 0,
    "mount_identifier_emitted": 0,
    "namespace_identifier_emitted": 0,
    "overlay_path_value_emitted": 0,
    "nonfixed_mount_path_emitted": 0,
    "mountinfo_raw_line_emitted": 0,
    "wrapper_content_read_count": 0,
    "environment_value_read_count": 0,
    "directory_enumeration_count": 0,
    "cli_invocation_count": 0,
    "process_spawn_count": 0,
    "provider_call_count": 0,
    "database_connection_count": 0,
    "chmod_count": 0,
    "chown_count": 0,
    "remount_count": 0,
    "host_write_count": 0,
    "remote_file_write_count": 0,
    "secret_values_emitted": 0,
}
BLOCKED_REASONS = {
    "CTIME_NS_UNAVAILABLE",
    "DEVICE_ID_UNAVAILABLE",
    "FDINFO_ENCODING_INVALID",
    "FDINFO_MOUNT_ID_INVALID",
    "FDINFO_MOUNT_ID_NOT_UNIQUE",
    "FDINFO_OPEN_FAILED",
    "FDINFO_READ_FAILED",
    "FDINFO_SIZE_LIMIT",
    "FIXED_CHILD_CHANGED_DURING_CAPTURE",
    "FIXED_CHILD_IDENTITY_CHANGED",
    "FIXED_CHILD_PIN_FAILED",
    "FIXED_CHILD_PIN_IDENTITY_MISMATCH",
    "FIXED_CHILD_REVERIFY_FAILED",
    "FIXED_CHILD_STAT_FAILED",
    "FIXED_PATH_NOT_DIRECTORY",
    "INTERNAL_VALIDATION_ERROR",
    "MOUNTINFO_ACCESS_MODE_INVALID",
    "MOUNTINFO_DEVICE_INVALID",
    "MOUNTINFO_ENCODING_INVALID",
    "MOUNTINFO_ESCAPE_INVALID",
    "MOUNTINFO_LINE_INVALID",
    "MOUNTINFO_LINE_LIMIT",
    "MOUNTINFO_MOUNT_ID_INVALID",
    "MOUNTINFO_MODE_OPTION_DUPLICATE",
    "MOUNTINFO_OPEN_FAILED",
    "MOUNTINFO_OPTIONAL_FIELD_UNSUPPORTED",
    "MOUNTINFO_PARENT_ID_INVALID",
    "MOUNTINFO_PATH_INVALID",
    "MOUNTINFO_PAYLOAD_INVALID",
    "MOUNTINFO_PROPAGATION_CONFLICT",
    "MOUNTINFO_PROPAGATION_DUPLICATE",
    "MOUNTINFO_PROPAGATION_ID_INVALID",
    "MOUNTINFO_READ_FAILED",
    "MOUNTINFO_SIZE_LIMIT",
    "MOUNTINFO_SUPER_ACCESS_MODE_INVALID",
    "MOUNT_NAMESPACE_PIN_FAILED",
    "NONFIXED_NAMESPACE_REQUESTED",
    "NONFIXED_PATH_REQUESTED",
    "O_NOFOLLOW_UNAVAILABLE",
    "O_PATH_UNAVAILABLE",
    "PATH_CHANGED_DURING_CAPTURE",
    "PATH_IDENTITY_CHANGED",
    "PATH_PIN_FAILED",
    "PATH_PIN_IDENTITY_MISMATCH",
    "PATH_REVERIFY_FAILED",
    "PATH_STAT_FAILED",
    "PATH_TYPE_CHANGED_DURING_CAPTURE",
    "PINNED_HANDLE_REVERIFY_FAILED",
    "PINNED_IDENTITY_CHANGED",
    "PINNED_USR_FD_NOT_DISTINCT",
    "ROOT_PREREQUISITE_MISMATCH",
    "SELECTED_MOUNTPOINT_OUT_OF_SCOPE",
    "SELECTED_MOUNT_DEVICE_MISMATCH",
    "SELECTED_MOUNT_NOT_UNIQUE",
    "USR_CHANGED_DURING_CAPTURE",
    "USR_IDENTITY_CHANGED",
    "USR_NOT_DIRECTORY",
    "USR_PIN_FAILED",
    "USR_PIN_IDENTITY_MISMATCH",
    "USR_REVERIFY_FAILED",
    "USR_STAT_FAILED",
    "USR_TYPE_CHANGED_DURING_CAPTURE",
}
HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")
CODE = re.compile(r"\A[A-Z0-9_]+\Z")


class Invalid(Exception):
    pass


def require(condition, code):
    if not condition:
        raise Invalid(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def exact(value, expected_type):
    return type(value) is expected_type


def is_hash(value):
    return exact(value, str) and bool(HEX64.match(value))


def strict_equal(value, expected):
    if type(value) is not type(expected):
        return False
    if type(expected) is dict:
        return set(value) == set(expected) and all(
            strict_equal(value[key], expected[key]) for key in expected
        )
    if type(expected) is list:
        return len(value) == len(expected) and all(
            strict_equal(left, right) for left, right in zip(value, expected)
        )
    return value == expected


def empty_observation():
    return {
        "root_prerequisite_satisfied": False,
        "usr_exact_predecessor_mode": False,
        "usr_current_class": "UNKNOWN",
        "fixed_shell_component_trusted": False,
        "mount": None,
        "pid1_mount_namespace_relation": "UNKNOWN",
    }


def validate_mount(value):
    require(exact(value, dict), "mount_type")
    require(set(value) == {
        "filesystem_class", "mountpoint_class", "access_mode", "propagation",
        "filesystem_root_class", "noexec", "nosuid", "nodev",
        "upperdir_present", "usr_mount_mode_class",
    }, "mount_keys")
    enums = {
        "filesystem_class": ("OVERLAY", "TMPFS", "OTHER"),
        "mountpoint_class": ("ROOT", "EXACT_USR"),
        "access_mode": ("READ_ONLY", "READ_WRITE"),
        "propagation": ("PRIVATE", "SHARED", "SLAVE", "SHARED_SLAVE", "UNBINDABLE"),
        "filesystem_root_class": ("FS_ROOT", "SUBTREE"),
        "usr_mount_mode_class": (
            "NOT_APPLICABLE", "ABSENT", "EXPLICIT_1777",
            "OTHER_OR_AMBIGUOUS",
        ),
    }
    for key, allowed in enums.items():
        require(exact(value[key], str) and value[key] in allowed, "mount_" + key)
    for key in ("noexec", "nosuid", "nodev", "upperdir_present"):
        require(exact(value[key], bool), "mount_bool_" + key)
    if value["filesystem_class"] != "OVERLAY":
        require(value["upperdir_present"] is False, "non_overlay_upperdir")
    if value["mountpoint_class"] != "EXACT_USR":
        require(
            value["usr_mount_mode_class"] == "NOT_APPLICABLE",
            "non_usr_mount_mode_class",
        )
    else:
        require(
            value["usr_mount_mode_class"] != "NOT_APPLICABLE",
            "usr_mount_mode_class",
        )


def validate_observation(value, allow_empty=False):
    require(exact(value, dict), "observation_type")
    require(set(value) == set(empty_observation()), "observation_keys")
    if allow_empty and strict_equal(value, empty_observation()):
        return
    require(value["root_prerequisite_satisfied"] is True, "root_prerequisite")
    require(exact(value["usr_exact_predecessor_mode"], bool), "usr_exact_type")
    require(
        exact(value["usr_current_class"], str)
        and value["usr_current_class"] in (
            "ROOT_OWNED_STICKY_EXACT_1777",
            "ROOT_OWNED_NON_GROUP_OTHER_WRITABLE",
            "UNSAFE_OR_UNKNOWN",
        ),
        "usr_current_class",
    )
    require(
        value["usr_exact_predecessor_mode"]
        is (value["usr_current_class"] == "ROOT_OWNED_STICKY_EXACT_1777"),
        "usr_exact_class_consistency",
    )
    require(exact(value["fixed_shell_component_trusted"], bool), "shell_trusted_type")
    validate_mount(value["mount"])
    require(
        exact(value["pid1_mount_namespace_relation"], str)
        and value["pid1_mount_namespace_relation"] in (
            "SAME_AS_PID1", "DIFFERENT_FROM_PID1"
        ),
        "namespace_relation",
    )


def validate(value):
    require(exact(value, dict), "top_level_type")
    expected_keys = {
        "schema", "status", "predecessor", "scope", "assessment_complete",
        "assessment_state", "reason_code", "before", "after",
        "before_after_equal", "pinned_private_state_equal",
        "offline_allowlist_candidate",
        "effective_mount_read_write_observed", "read_only_mount_observed",
        "commitment_sha256",
    } | set(BOUNDARY_VALUES)
    require(set(value) == expected_keys, "top_level_keys")
    require(exact(value["schema"], str) and value["schema"] == SCHEMA, "schema")
    require(exact(value["status"], str) and value["status"] == "BLOCKED", "status")
    require(strict_equal(value["predecessor"], PREDECESSOR), "predecessor")
    require(strict_equal(value["scope"], SCOPE), "scope")
    for key, expected in BOUNDARY_VALUES.items():
        require(type(value[key]) is type(expected) and value[key] == expected, "boundary_" + key)
    require(exact(value["assessment_complete"], bool), "assessment_complete_type")
    states = (
        "CURRENT_STABLE_MOUNT_READ_ONLY",
        "CURRENT_STABLE_MOUNT_READ_WRITE",
        "CURRENT_STABLE_SAFE_CURRENT_METADATA",
        "CURRENT_STABLE_UNSAFE_OR_UNKNOWN",
        "UNSTABLE",
        "OBSERVATION_BLOCKED",
    )
    require(exact(value["assessment_state"], str) and value["assessment_state"] in states, "assessment_state")
    require(exact(value["reason_code"], str) and bool(CODE.match(value["reason_code"])), "reason_code")
    blocked_observation = value["assessment_state"] == "OBSERVATION_BLOCKED"
    validate_observation(value["before"], allow_empty=blocked_observation)
    validate_observation(value["after"], allow_empty=blocked_observation)
    require(exact(value["before_after_equal"], bool), "before_after_type")
    require(exact(value["pinned_private_state_equal"], bool), "private_equal_type")
    require(
        exact(value["offline_allowlist_candidate"], str)
        and value["offline_allowlist_candidate"] in (
            "NONE", "READ_ONLY_MOUNT", "ROOT_OWNED_STICKY_EXACT_USR"
        ),
        "allowlist_candidate",
    )
    require(exact(value["effective_mount_read_write_observed"], bool), "mount_read_write_type")
    require(exact(value["read_only_mount_observed"], bool), "read_only_type")
    if blocked_observation:
        require(value["assessment_complete"] is False, "blocked_complete")
        require(value["reason_code"] in BLOCKED_REASONS, "blocked_reason")
        require(value["before_after_equal"] is False, "blocked_equal")
        require(value["pinned_private_state_equal"] is False, "blocked_private_equal")
        require(strict_equal(value["before"], empty_observation()), "blocked_before")
        require(strict_equal(value["after"], empty_observation()), "blocked_after")
        require(value["offline_allowlist_candidate"] == "NONE", "blocked_candidate")
        require(value["effective_mount_read_write_observed"] is False, "blocked_mount_read_write")
        require(value["read_only_mount_observed"] is False, "blocked_read_only")
    elif value["assessment_state"] == "UNSTABLE":
        require(value["assessment_complete"] is True, "unstable_complete")
        require(value["reason_code"] == "OBSERVATION_UNSTABLE", "unstable_reason")
        require(
            not value["before_after_equal"]
            or not value["pinned_private_state_equal"],
            "unstable_equal",
        )
        require(
            value["before_after_equal"]
            is strict_equal(value["before"], value["after"]),
            "unstable_public_equality",
        )
        require(value["offline_allowlist_candidate"] == "NONE", "unstable_candidate")
        require(value["effective_mount_read_write_observed"] is False, "unstable_mount_read_write")
        require(value["read_only_mount_observed"] is False, "unstable_read_only")
    else:
        require(value["assessment_complete"] is True, "stable_complete")
        require(value["before_after_equal"] is True, "stable_equal")
        require(value["pinned_private_state_equal"] is True, "stable_private_equal")
        require(strict_equal(value["before"], value["after"]), "stable_observation")
        before = value["before"]
        if value["assessment_state"] == "CURRENT_STABLE_SAFE_CURRENT_METADATA":
            require(
                before["usr_current_class"] == "ROOT_OWNED_NON_GROUP_OTHER_WRITABLE",
                "safe_current_class",
            )
            require(
                value["reason_code"]
                == "PREDECESSOR_NOT_REPRODUCED_SAFE_CURRENT_METADATA",
                "safe_current_reason",
            )
            require(value["offline_allowlist_candidate"] == "NONE", "safe_current_candidate")
            require(
                value["effective_mount_read_write_observed"]
                is (before["mount"]["access_mode"] == "READ_WRITE"),
                "safe_current_mount_read_write",
            )
            require(
                value["read_only_mount_observed"]
                is (before["mount"]["access_mode"] == "READ_ONLY"),
                "safe_current_read_only",
            )
        elif value["assessment_state"] == "CURRENT_STABLE_UNSAFE_OR_UNKNOWN":
            require(before["usr_current_class"] == "UNSAFE_OR_UNKNOWN", "unsafe_class")
            require(
                value["reason_code"] == "USR_CURRENT_METADATA_UNSAFE_OR_UNKNOWN",
                "unsafe_reason",
            )
            require(value["offline_allowlist_candidate"] == "NONE", "unsafe_candidate")
            require(
                value["effective_mount_read_write_observed"]
                is (before["mount"]["access_mode"] == "READ_WRITE"),
                "unsafe_mount_read_write",
            )
            require(
                value["read_only_mount_observed"]
                is (before["mount"]["access_mode"] == "READ_ONLY"),
                "unsafe_read_only",
            )
        elif value["assessment_state"] == "CURRENT_STABLE_MOUNT_READ_ONLY":
            require(before["usr_exact_predecessor_mode"] is True, "read_only_match")
            require(before["mount"]["access_mode"] == "READ_ONLY", "read_only_mount")
            require(value["reason_code"] == "USR_WRITABLE_BITS_MOUNT_READ_ONLY", "read_only_reason")
            require(value["offline_allowlist_candidate"] == "READ_ONLY_MOUNT", "read_only_candidate")
            require(value["effective_mount_read_write_observed"] is False, "read_only_mount_read_write")
            require(value["read_only_mount_observed"] is True, "read_only_flag")
        else:
            require(value["assessment_state"] == "CURRENT_STABLE_MOUNT_READ_WRITE", "read_write_state")
            require(before["usr_exact_predecessor_mode"] is True, "read_write_match")
            require(before["mount"]["access_mode"] == "READ_WRITE", "read_write_mount")
            require(value["reason_code"] == "USR_WRITABLE_BITS_MOUNT_READ_WRITE", "read_write_reason")
            expected_candidate = (
                "ROOT_OWNED_STICKY_EXACT_USR"
                if (
                    before["fixed_shell_component_trusted"]
                    and before["mount"]["filesystem_class"]
                    in ("OVERLAY", "TMPFS")
                )
                else "NONE"
            )
            require(value["offline_allowlist_candidate"] == expected_candidate, "read_write_candidate")
            require(value["effective_mount_read_write_observed"] is True, "read_write_mount_flag")
            require(value["read_only_mount_observed"] is False, "read_write_flag")
    require(is_hash(value["commitment_sha256"]), "commitment_shape")
    payload = dict(value)
    del payload["commitment_sha256"]
    expected_commitment = hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()
    require(value["commitment_sha256"] == expected_commitment, "commitment_mismatch")
    return value["assessment_state"], value["commitment_sha256"]


def reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Invalid("duplicate_key")
        result[key] = value
    return result


def main(argv):
    if len(argv) != 2:
        print("ITEM26_USR_IMPACT_ASSESSMENT_INVALID")
        return 2
    try:
        value = json.loads(
            Path(argv[1]).read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_pairs,
        )
        state, commitment = validate(value)
    except Exception:
        print("ITEM26_USR_IMPACT_ASSESSMENT_INVALID")
        return 1
    print(
        "ITEM26_USR_IMPACT_ASSESSMENT_SCHEMA_VALID_UNAUTHENTICATED %s %s"
        % (state, commitment)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
