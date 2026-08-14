#!/usr/bin/env python3
"""Validate the Secret-free Item26 wrapper-parent diagnostic receipt."""

import hashlib
import json
import re
import sys
from pathlib import Path


SCHEMA = "noteai.item26.cloudshell-wrapper-parent-diagnostic.v1"
WRAPPER_PATH = "/usr/shell/bin/aliyun"
LEXICAL_PARENTS = ("/usr", "/usr/shell", "/usr/shell/bin")
PREDECESSOR = {
    "source_sha256": "e1ce4f28a0159f7c92ae7f8b0a542a2e7fbf49a2b6244c93899239bc66e25cd8",
    "command_bytes": 8506,
    "command_sha256": "8fbed548cff9d47ca19492f6c7e9c7509f0060ad9c961318b710c53fe3de9de7",
    "commitment_sha256": "9c86a12e84786793a04789ced1cca12a39f9edf00436568c5c1edbd4e1f5bbb5",
    "reason_code": "WRITABLE_EXECUTABLE_PARENT",
}
HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")
SAFE_PATH = re.compile(r"\A/[A-Za-z0-9._+/-]+\Z")
CODE = re.compile(r"\A[A-Z0-9_]+\Z")
MAX_CANONICAL_PARENTS = 64
VISIBLE_IDENTITY_KEYS = (
    "entry_type", "is_symlink", "uid", "gid", "mode", "nlink",
    "target_sha256", "group_or_other_writable",
)
BOUNDARY_VALUES = {
    "historical_identity_continuity_proven": False,
    "wrapper_identity_verified": False,
    "receipt_origin_authenticated": False,
    "opaque_target_resolution_proven_by_validator": False,
    "commitment_is_authentication_signature": False,
    "target_sha256_is_opaque_evidence": True,
    "direct_single_execution_provenance_required": True,
    "security_predicate_relaxed": False,
    "next_stage_authorized": False,
    "same_invocation_replay_allowed": False,
    "automatic_retry_allowed": False,
    "wrapper_content_read_count": 0,
    "environment_value_read_count": 0,
    "directory_enumeration_count": 0,
    "cli_invocation_count": 0,
    "provider_call_count": 0,
    "database_connection_count": 0,
    "host_write_count": 0,
    "remote_file_write_count": 0,
    "secret_values_emitted": 0,
}
BLOCKED_REASONS = {
    "CANONICAL_PARENT_COUNT_OUT_OF_RANGE",
    "CANONICAL_PARENT_NOT_DIRECTORY",
    "CTIME_NS_UNAVAILABLE",
    "INTERNAL_VALIDATION_ERROR",
    "NON_DIRECTORY_RESOLUTION_COMPONENT",
    "O_PATH_OR_NOFOLLOW_UNAVAILABLE",
    "PATH_CHANGED_DURING_CAPTURE",
    "PATH_IDENTITY_CHANGED",
    "PATH_PIN_FAILED",
    "PATH_PIN_IDENTITY_MISMATCH",
    "PATH_TYPE_CHANGED",
    "PATH_TYPE_CHANGED_DURING_CAPTURE",
    "PINNED_IDENTITY_CHANGED",
    "RESOLUTION_STEP_LIMIT",
    "RESOLVED_PATH_CHANGED_DURING_CAPTURE",
    "RESOLVED_PATH_DEPTH_LIMIT",
    "RESOLVED_PATH_TOO_LONG",
    "ROOT_PREREQUISITE_MISMATCH",
    "SYMLINK_CHANGED_DURING_CAPTURE",
    "SYMLINK_CHANGED_DURING_RESOLUTION",
    "SYMLINK_HOP_LIMIT",
    "SYMLINK_RESOLUTION_LOOP",
    "SYMLINK_TARGET_CHANGED",
    "SYMLINK_TARGET_UNREADABLE",
    "UNSAFE_PATH",
    "UNSAFE_PATH_COMPONENT",
    "UNSAFE_SYMLINK_TARGET",
    "UNSAFE_SYMLINK_TARGET_SHAPE",
}


class Invalid(Exception):
    pass


def require(condition, code):
    if not condition:
        raise Invalid(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def exact(value, expected):
    return type(value) is expected


def is_hash(value):
    return exact(value, str) and bool(HEX64.match(value))


def path_hash(path):
    return hashlib.sha256(path.encode("ascii")).hexdigest()


def literal_parents(path):
    if path == "/":
        return []
    parts = path.split("/")[1:]
    return ["/" + "/".join(parts[:index]) for index in range(1, len(parts))]


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


def safe_path(path):
    return bool(
        exact(path, str)
        and SAFE_PATH.match(path)
        and "//" not in path
        and "/./" not in path
        and "/../" not in path
        and not path.endswith("/")
    )


def validate_record(value, chain, ordinal):
    require(exact(value, dict), "record_type")
    require(set(value) == {
        "chain", "ordinal", "path", "path_sha256", "path_depth",
        "entry_type", "is_symlink", "uid", "gid", "mode", "nlink",
        "identity_sha256", "target_sha256", "group_or_other_writable",
        "matches_lexical_index",
    }, "record_keys")
    require(exact(value["chain"], str) and value["chain"] == chain, "record_chain")
    require(exact(value["ordinal"], int) and value["ordinal"] == ordinal, "record_ordinal")
    require(is_hash(value["path_sha256"]), "record_path_hash")
    require(exact(value["path_depth"], int) and value["path_depth"] > 0, "record_depth")
    require(
        exact(value["entry_type"], str)
        and value["entry_type"] in ("directory", "symlink", "other"),
        "record_entry_type",
    )
    require(exact(value["is_symlink"], bool), "record_symlink_type")
    require(value["is_symlink"] is (value["entry_type"] == "symlink"), "record_symlink")
    for key in ("uid", "gid", "nlink"):
        require(exact(value[key], int) and value[key] >= 0, "record_integer")
    require(value["nlink"] > 0, "record_nlink")
    require(exact(value["mode"], str) and re.match(r"\A[0-7]{4}\Z", value["mode"]), "record_mode")
    require(is_hash(value["identity_sha256"]), "record_identity")
    if value["entry_type"] == "symlink":
        require(is_hash(value["target_sha256"]), "record_target_hash")
    else:
        require(value["target_sha256"] is None, "record_target_absence")
    require(exact(value["group_or_other_writable"], bool), "record_writable_type")
    expected_writable = (
        value["entry_type"] == "directory" and bool(int(value["mode"], 8) & 0o022)
    )
    require(value["group_or_other_writable"] is expected_writable, "record_writable")
    require(
        exact(value["matches_lexical_index"], int)
        and -1 <= value["matches_lexical_index"] < len(LEXICAL_PARENTS),
        "record_lexical_index_type",
    )
    expected_alias = -1
    for index, fixed in enumerate(LEXICAL_PARENTS):
        if value["path_sha256"] == path_hash(fixed):
            expected_alias = index
            break
    require(value["matches_lexical_index"] == expected_alias, "record_lexical_index")
    if chain == "lexical":
        fixed = LEXICAL_PARENTS[ordinal]
        require(value["path"] == fixed and safe_path(value["path"]), "lexical_path")
        require(value["path_sha256"] == path_hash(fixed), "lexical_path_hash")
        require(value["path_depth"] == len(fixed.split("/")) - 1, "lexical_depth")
    elif chain == "endpoint":
        require(value["path"] is None, "hidden_path_must_be_null")
        require(value["path_sha256"] == path_hash(WRAPPER_PATH), "endpoint_path_hash")
        require(
            value["path_depth"] == len(WRAPPER_PATH.split("/")) - 1,
            "endpoint_depth",
        )
        require(value["matches_lexical_index"] == -1, "endpoint_lexical_index")
    else:
        require(value["path"] is None, "hidden_path_must_be_null")


def validate_observation(value, allow_empty=False):
    require(exact(value, dict), "observation_type")
    require(set(value) == {
        "lexical", "canonical", "endpoint", "canonical_path_sha256",
        "canonical_depth",
    }, "observation_keys")
    require(exact(value["lexical"], list), "lexical_type")
    if allow_empty and not value["lexical"]:
        require(value == {
            "lexical": [], "canonical": [], "endpoint": None,
            "canonical_path_sha256": None, "canonical_depth": 0,
        }, "empty_observation")
        return
    require(len(value["lexical"]) == len(LEXICAL_PARENTS), "lexical_count")
    for index, record in enumerate(value["lexical"]):
        validate_record(record, "lexical", index)
    require(exact(value["canonical"], list), "canonical_type")
    require(len(value["canonical"]) <= MAX_CANONICAL_PARENTS, "canonical_count")
    seen = set()
    for index, record in enumerate(value["canonical"]):
        validate_record(record, "canonical", index)
        require(record["entry_type"] == "directory", "canonical_not_directory")
        require(record["path_depth"] == index + 1, "canonical_depth_sequence")
        require(
            record["path_sha256"]
            not in (path_hash("/"), path_hash(WRAPPER_PATH)),
            "impossible_canonical_parent",
        )
        alias = record["matches_lexical_index"]
        if alias >= 0:
            require(alias == index, "canonical_alias_ordinal")
            require(
                [item["path_sha256"] for item in value["canonical"][:alias]]
                == [
                    path_hash(parent)
                    for parent in literal_parents(LEXICAL_PARENTS[alias])
                ],
                "canonical_alias_fixed_prefix",
            )
            lexical_record = value["lexical"][alias]
            require(
                record["path_depth"] == lexical_record["path_depth"],
                "canonical_alias_depth",
            )
            for key in VISIBLE_IDENTITY_KEYS:
                require(
                    strict_equal(record[key], lexical_record[key]),
                    "canonical_alias_metadata_" + key,
                )
        require(record["path_sha256"] not in seen, "canonical_path_duplicate")
        seen.add(record["path_sha256"])
    lexical_state, _ = prefix_state(value["lexical"])
    if value["canonical"]:
        require(lexical_state == "SAFE", "canonical_without_safe_lexical")
        validate_record(value["endpoint"], "endpoint", 0)
        require(endpoint_state(value["endpoint"]) == "SAFE", "canonical_with_untrusted_endpoint")
        require(is_hash(value["canonical_path_sha256"]), "canonical_path_hash")
        require(
            value["canonical_path_sha256"] not in seen,
            "canonical_final_equals_parent",
        )
        require(
            exact(value["canonical_depth"], int)
            and value["canonical_depth"] == len(value["canonical"]) + 1,
            "canonical_depth",
        )
        known_paths = ("/",) + LEXICAL_PARENTS + (WRAPPER_PATH,)
        for known_path in known_paths:
            if value["canonical_path_sha256"] == path_hash(known_path):
                expected_parent_hashes = [
                    path_hash(parent) for parent in literal_parents(known_path)
                ]
                require(
                    value["canonical_depth"]
                    == (0 if known_path == "/" else len(known_path.split("/")) - 1),
                    "known_canonical_final_depth",
                )
                require(
                    [record["path_sha256"] for record in value["canonical"]]
                    == expected_parent_hashes,
                    "known_canonical_final_parents",
                )
                if known_path in LEXICAL_PARENTS:
                    require(
                        not value["lexical"][LEXICAL_PARENTS.index(known_path)][
                            "is_symlink"
                        ],
                        "known_canonical_final_is_lexical_symlink",
                    )
                elif known_path == WRAPPER_PATH:
                    require(
                        not value["endpoint"]["is_symlink"],
                        "known_canonical_final_is_endpoint_symlink",
                    )
                break
        no_symlink_in_invoked_path = (
            not any(record["is_symlink"] for record in value["lexical"])
            and not value["endpoint"]["is_symlink"]
        )
        if no_symlink_in_invoked_path:
            require(
                value["canonical_path_sha256"] == path_hash(WRAPPER_PATH),
                "non_symlink_canonical_final",
            )
    else:
        if lexical_state == "SAFE":
            validate_record(value["endpoint"], "endpoint", 0)
            require(endpoint_state(value["endpoint"]) == "MISMATCH", "safe_lexical_without_canonical")
        else:
            require(value["endpoint"] is None, "unexpected_endpoint")
        require(value["canonical_path_sha256"] is None, "unexpected_canonical_hash")
        require(value["canonical_depth"] == 0 and exact(value["canonical_depth"], int), "empty_canonical_depth")


def prefix_state(records):
    for record in records:
        if record["entry_type"] == "symlink":
            if record["uid"] != 0 or record["gid"] != 0 or record["nlink"] != 1:
                return "MISMATCH", None
            continue
        if record["entry_type"] != "directory":
            return "MISMATCH", None
        if record["uid"] != 0 or record["gid"] != 0:
            return "MISMATCH", None
        if record["group_or_other_writable"]:
            return "WRITABLE", record["ordinal"]
    return "SAFE", None


def endpoint_state(record):
    if record["entry_type"] == "symlink" and (
        record["uid"] != 0 or record["gid"] != 0 or record["nlink"] != 1
    ):
        return "MISMATCH"
    return "SAFE"


def classify(observation):
    state, index = prefix_state(observation["lexical"])
    if state == "WRITABLE":
        return "LEXICAL", index
    if state != "SAFE":
        return "NONE", -1
    if endpoint_state(observation["endpoint"]) != "SAFE":
        return "NONE", -1
    state, index = prefix_state(observation["canonical"])
    if state == "WRITABLE":
        return "CANONICAL", index
    return "NONE", -1


def validate(value):
    require(exact(value, dict), "top_level_type")
    expected_keys = {
        "schema", "status", "predecessor", "scope", "diagnostic_complete",
        "diagnostic_state", "reason_code", "before", "after",
        "before_after_equal", "culprit_scope", "culprit_index",
        "culprit_path", "culprit_path_sha256", "commitment_sha256",
    } | set(BOUNDARY_VALUES)
    require(set(value) == expected_keys, "top_level_keys")
    require(value["schema"] == SCHEMA and exact(value["schema"], str), "schema")
    require(value["status"] == "BLOCKED" and exact(value["status"], str), "status")
    require(strict_equal(value["predecessor"], PREDECESSOR), "predecessor")
    require(
        strict_equal(value["scope"], {
            "role": "wrapper", "invoked_path": WRAPPER_PATH,
            "lexical_parents": list(LEXICAL_PARENTS),
        }),
        "scope",
    )
    for key, expected in BOUNDARY_VALUES.items():
        require(type(value[key]) is type(expected) and value[key] == expected, "boundary_" + key)
    require(exact(value["diagnostic_complete"], bool), "diagnostic_complete_type")
    require(
        exact(value["diagnostic_state"], str)
        and value["diagnostic_state"] in (
            "CURRENT_STABLE_MATCH", "CURRENT_STABLE_NO_MATCH", "UNSTABLE",
            "OBSERVATION_BLOCKED",
        ),
        "diagnostic_state",
    )
    require(exact(value["reason_code"], str) and CODE.match(value["reason_code"]), "reason_code")
    blocked_observation = value["diagnostic_state"] == "OBSERVATION_BLOCKED"
    validate_observation(value["before"], allow_empty=blocked_observation)
    validate_observation(value["after"], allow_empty=blocked_observation)
    require(exact(value["before_after_equal"], bool), "before_after_type")
    require(
        exact(value["culprit_scope"], str)
        and value["culprit_scope"] in ("LEXICAL", "CANONICAL", "NONE"),
        "culprit_scope",
    )
    require(exact(value["culprit_index"], int), "culprit_index_type")
    if blocked_observation:
        require(value["reason_code"] in BLOCKED_REASONS, "blocked_reason")
        require(value["diagnostic_complete"] is False, "blocked_complete")
        require(value["before_after_equal"] is False, "blocked_equal")
        require(value["culprit_scope"] == "NONE" and value["culprit_index"] == -1, "blocked_culprit")
        require(value["culprit_path"] is None and value["culprit_path_sha256"] is None, "blocked_culprit_path")
        require(strict_equal(value["before"], {
            "lexical": [], "canonical": [], "endpoint": None,
            "canonical_path_sha256": None, "canonical_depth": 0,
        }), "blocked_before_not_empty")
        require(strict_equal(value["after"], {
            "lexical": [], "canonical": [], "endpoint": None,
            "canonical_path_sha256": None, "canonical_depth": 0,
        }), "blocked_after_not_empty")
    elif value["diagnostic_state"] == "UNSTABLE":
        require(value["diagnostic_complete"] is True, "unstable_complete")
        require(value["before_after_equal"] is False, "unstable_equal")
        require(
            not strict_equal(value["before"], value["after"]),
            "unstable_observations_equal",
        )
        require(value["culprit_scope"] == "NONE" and value["culprit_index"] == -1, "unstable_culprit")
        require(value["culprit_path"] is None and value["culprit_path_sha256"] is None, "unstable_culprit_path")
        require(value["reason_code"] == "OBSERVATION_UNSTABLE", "unstable_reason")
    else:
        require(value["diagnostic_complete"] is True, "stable_complete")
        require(value["before_after_equal"] is True, "stable_equal")
        require(value["before"] == value["after"], "stable_observation_mismatch")
        expected_scope, expected_index = classify(value["before"])
        if value["diagnostic_state"] == "CURRENT_STABLE_MATCH":
            require(expected_scope != "NONE", "match_without_culprit")
            require(value["reason_code"] == "WRITABLE_EXECUTABLE_PARENT", "match_reason")
            require(value["culprit_scope"] == expected_scope, "match_scope")
            require(value["culprit_index"] == expected_index, "match_index")
            if expected_scope == "LEXICAL":
                expected_path = LEXICAL_PARENTS[expected_index]
                require(value["culprit_path"] == expected_path, "match_path")
                require(value["culprit_path_sha256"] == path_hash(expected_path), "match_path_hash")
            else:
                require(value["culprit_path"] is None, "canonical_path_leak")
                require(
                    value["culprit_path_sha256"]
                    == value["before"]["canonical"][expected_index]["path_sha256"],
                    "canonical_culprit_hash",
                )
        else:
            require(expected_scope == "NONE", "no_match_has_culprit")
            require(value["reason_code"] == "CURRENT_STATE_NOT_REPRODUCED", "no_match_reason")
            require(value["culprit_scope"] == "NONE" and value["culprit_index"] == -1, "no_match_culprit")
            require(value["culprit_path"] is None and value["culprit_path_sha256"] is None, "no_match_path")
    commitment = value["commitment_sha256"]
    require(is_hash(commitment), "commitment_shape")
    payload = dict(value)
    del payload["commitment_sha256"]
    expected = hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()
    require(commitment == expected, "commitment_mismatch")
    return value["diagnostic_state"], commitment


def reject_duplicate_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise Invalid("duplicate_key")
        value[key] = item
    return value


def main(argv):
    if len(argv) != 2:
        print("ITEM26_WRAPPER_PARENT_DIAGNOSTIC_INVALID")
        return 2
    try:
        value = json.loads(
            Path(argv[1]).read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_pairs,
        )
        state, commitment = validate(value)
    except Exception:
        print("ITEM26_WRAPPER_PARENT_DIAGNOSTIC_INVALID")
        return 1
    print(
        "ITEM26_WRAPPER_PARENT_DIAGNOSTIC_SCHEMA_VALID_UNAUTHENTICATED %s %s"
        % (state, commitment)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
