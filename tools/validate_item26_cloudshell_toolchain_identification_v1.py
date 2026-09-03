#!/usr/bin/env python3
"""Validate a Secret-free Item26 Cloud Shell toolchain commitment."""

import hashlib
import json
import re
import sys
from pathlib import Path


SCHEMA = "noteai.item26.cloudshell-toolchain-identification.v1"
PARSER = "strict-absolute-literal-exec-v1"
WRAPPER_PATH = "/usr/shell/bin/aliyun"
WRAPPER_BYTES = 1289
WRAPPER_SHA256 = (
    "af8fa54a2c4dbe063de90a7d47d2384b4c3fdd8c3484d42e56eb4fcd716eb7b9"
)
HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")
SAFE_PATH = re.compile(r"\A/[A-Za-z0-9._+/-]+\Z")


class Invalid(Exception):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def require(condition, code):
    if not condition:
        raise Invalid(code)


def exact_type(value, expected):
    return type(value) is expected


def safe_path(value):
    return bool(
        exact_type(value, str)
        and SAFE_PATH.match(value)
        and "//" not in value
        and "/./" not in value
        and "/../" not in value
        and not value.endswith("/")
    )


def validate_symlink(value):
    require(exact_type(value, dict), "symlink_type")
    require(set(value) == {
        "path", "uid", "gid", "mode", "nlink", "target_sha256",
    }, "symlink_keys")
    require(safe_path(value["path"]), "symlink_path")
    require(exact_type(value["uid"], int) and exact_type(value["gid"], int), "symlink_owner_type")
    require(value["uid"] == 0 and value["gid"] == 0, "symlink_owner")
    require(exact_type(value["nlink"], int) and value["nlink"] == 1, "symlink_nlink")
    require(exact_type(value["mode"], str) and re.match(r"\A[0-7]{4}\Z", value["mode"]), "symlink_mode")
    require(exact_type(value["target_sha256"], str) and HEX64.match(value["target_sha256"]), "symlink_hash")


def validate_record(value, role):
    require(exact_type(value, dict), "record_type")
    require(set(value) == {
        "role", "invoked_path", "canonical_path", "uid", "gid", "mode",
        "nlink", "size", "sha256", "symlinks",
    }, "record_keys")
    require(exact_type(value["role"], str) and value["role"] == role, "record_role")
    for key in ("invoked_path", "canonical_path"):
        require(safe_path(value[key]), "record_path")
    require(exact_type(value["uid"], int) and exact_type(value["gid"], int), "record_owner_type")
    require(value["uid"] == 0 and value["gid"] == 0, "record_owner")
    require(exact_type(value["mode"], str) and value["mode"] == "0755", "record_mode")
    require(exact_type(value["nlink"], int) and value["nlink"] == 1, "record_nlink")
    require(exact_type(value["size"], int) and 0 < value["size"] <= 512 * 1024 * 1024, "record_size")
    require(exact_type(value["sha256"], str) and HEX64.match(value["sha256"]), "record_hash")
    require(exact_type(value["symlinks"], list) and len(value["symlinks"]) <= 8, "record_symlinks")
    seen = set()
    for item in value["symlinks"]:
        validate_symlink(item)
        require(item["path"] not in seen, "symlink_duplicate")
        require(
            value["invoked_path"] == item["path"]
            or value["invoked_path"].startswith(item["path"] + "/"),
            "symlink_not_in_invoked_path",
        )
        seen.add(item["path"])


def validate(value):
    require(exact_type(value, dict), "top_level_type")
    require(set(value) == {
        "schema", "status", "parser", "wrapper_language", "wrapper_policy",
        "final_cli_format", "before", "after", "before_after_equal",
        "commitment_sha256",
    }, "top_level_keys")
    require(exact_type(value["schema"], str) and value["schema"] == SCHEMA, "schema")
    require(exact_type(value["status"], str) and value["status"] == "PASS", "status")
    require(exact_type(value["parser"], str) and value["parser"] == PARSER, "parser")
    require(
        exact_type(value["wrapper_language"], str)
        and value["wrapper_language"] in ("shell", "python"),
        "wrapper_language",
    )
    require(
        exact_type(value["final_cli_format"], str)
        and value["final_cli_format"] == "elf64-static-linux-amd64",
        "final_format",
    )
    require(exact_type(value["before_after_equal"], bool) and value["before_after_equal"] is True, "before_after_flag")
    require(exact_type(value["before"], list) and len(value["before"]) == 3, "before_chain_length")
    require(exact_type(value["after"], list) and len(value["after"]) == 3, "after_chain_length")
    roles = ("wrapper", "wrapper_interpreter", "final_cli")
    for record, role in zip(value["before"], roles):
        validate_record(record, role)
    for record, role in zip(value["after"], roles):
        validate_record(record, role)
    require(value["before"] == value["after"], "before_after_mismatch")
    require(value["before"][0]["invoked_path"] == WRAPPER_PATH, "wrapper_path")
    require(value["before"][0]["size"] == WRAPPER_BYTES, "wrapper_size")
    require(value["before"][0]["sha256"] == WRAPPER_SHA256, "wrapper_hash")
    require(len(set(record["canonical_path"] for record in value["before"])) == 3, "chain_alias")
    require(exact_type(value["wrapper_policy"], dict), "wrapper_policy_type")
    expected_policy = {
        "absolute_shebang": True,
        "literal_final_exec": True,
        "exact_argv_forwarding": True,
        "path_lookup": False,
        "variable_dispatch": False,
        "inherited_environment_dispatch": False,
        "dynamic_download": False,
        "cli_invocations": 0,
    }
    require(set(value["wrapper_policy"]) == set(expected_policy), "wrapper_policy_keys")
    for key in (
        "absolute_shebang", "literal_final_exec", "exact_argv_forwarding",
        "path_lookup", "variable_dispatch", "inherited_environment_dispatch",
        "dynamic_download",
    ):
        require(exact_type(value["wrapper_policy"][key], bool), "wrapper_policy_bool_type")
    require(exact_type(value["wrapper_policy"]["cli_invocations"], int), "wrapper_policy_count_type")
    require(value["wrapper_policy"] == expected_policy, "wrapper_policy")
    commitment = value["commitment_sha256"]
    require(exact_type(commitment, str) and HEX64.match(commitment), "commitment_shape")
    payload = dict(value)
    del payload["commitment_sha256"]
    expected = hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()
    require(commitment == expected, "commitment_mismatch")
    return commitment


def reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Invalid("duplicate_key")
        result[key] = value
    return result


def main(argv):
    if len(argv) != 2:
        print("ITEM26_TOOLCHAIN_IDENTIFICATION_INVALID")
        return 2
    try:
        value = json.loads(
            Path(argv[1]).read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_pairs,
        )
        commitment = validate(value)
    except Exception:
        print("ITEM26_TOOLCHAIN_IDENTIFICATION_INVALID")
        return 1
    print("ITEM26_TOOLCHAIN_IDENTIFICATION_VALID " + commitment)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
