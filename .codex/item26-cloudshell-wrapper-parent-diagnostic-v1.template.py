#!/usr/bin/python3
"""Content-free Item26 Cloud Shell wrapper-parent diagnostic.

This atom is a terminal, no-replay diagnostic for the predecessor result
WRITABLE_EXECUTABLE_PARENT.  It never reads the wrapper contents and never
invokes the wrapper, its interpreter, or the final CLI.
"""

from __future__ import print_function

import hashlib
import json
import os
import re
import stat
import sys


SCHEMA = "noteai.item26.cloudshell-wrapper-parent-diagnostic.v1"
WRAPPER_PATH = "/usr/shell/bin/aliyun"
LEXICAL_PARENTS = ("/usr", "/usr/shell", "/usr/shell/bin")
PREDECESSOR_SOURCE_SHA256 = (
    "e1ce4f28a0159f7c92ae7f8b0a542a2e7fbf49a2b6244c93899239bc66e25cd8"
)
PREDECESSOR_COMMAND_BYTES = 8506
PREDECESSOR_COMMAND_SHA256 = (
    "8fbed548cff9d47ca19492f6c7e9c7509f0060ad9c961318b710c53fe3de9de7"
)
PREDECESSOR_COMMITMENT_SHA256 = (
    "9c86a12e84786793a04789ced1cca12a39f9edf00436568c5c1edbd4e1f5bbb5"
)
PREDECESSOR_REASON = "WRITABLE_EXECUTABLE_PARENT"
MAX_CANONICAL_PARENTS = 64
MAX_PATH_BYTES = 4096
MAX_SYMLINK_HOPS = 8
MAX_RESOLUTION_STEPS = 256
SAFE_PATH = re.compile(r"\A/[A-Za-z0-9._+/-]+\Z")
SAFE_COMPONENT = re.compile(r"\A[A-Za-z0-9._+-]+\Z")
HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")


class ObservationBlocked(Exception):
    def __init__(self, code):
        Exception.__init__(self, code)
        self.code = code


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def committed(value):
    result = dict(value)
    result["commitment_sha256"] = hashlib.sha256(
        canonical(value).encode("utf-8")
    ).hexdigest()
    return result


def path_sha256(path):
    return hashlib.sha256(path.encode("ascii")).hexdigest()


def safe_absolute(path):
    if path == "/":
        return path
    if not isinstance(path, str) or not SAFE_PATH.match(path):
        raise ObservationBlocked("UNSAFE_PATH")
    if (
        len(path.encode("ascii")) > MAX_PATH_BYTES
        or "//" in path
        or "/./" in path
        or "/../" in path
        or path.endswith("/")
    ):
        raise ObservationBlocked("UNSAFE_PATH")
    return path


def path_depth(path):
    return len(path.split("/")) - 1


def prefixes(path):
    parts = path.split("/")[1:]
    current = ""
    for part in parts:
        current += "/" + part
        yield current


def stat_signature(value):
    ctime_ns = getattr(value, "st_ctime_ns", None)
    if type(ctime_ns) is not int:
        raise ObservationBlocked("CTIME_NS_UNAVAILABLE")
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_mode),
        int(value.st_uid),
        int(value.st_gid),
        int(value.st_nlink),
        int(value.st_size),
        ctime_ns,
    )


def entry_type(value):
    if stat.S_ISDIR(value.st_mode):
        return "directory"
    if stat.S_ISLNK(value.st_mode):
        return "symlink"
    return "other"


def readlink_hash(path):
    return hashlib.sha256(readlink_value(path).encode("ascii")).hexdigest()


def readlink_value(path):
    try:
        target = os.readlink(path)
        raw = target.encode("ascii")
    except (OSError, UnicodeEncodeError):
        raise ObservationBlocked("SYMLINK_TARGET_UNREADABLE")
    if not raw or b"\x00" in raw or b"\n" in raw or b"\r" in raw:
        raise ObservationBlocked("UNSAFE_SYMLINK_TARGET")
    return target


def identity_sha256(chain, ordinal, path, value, target_hash):
    payload = {
        "domain": "noteai.item26.wrapper-parent-identity.v1",
        "chain": chain,
        "ordinal": ordinal,
        "path_sha256": path_sha256(path),
        "stat": list(stat_signature(value)),
        "target_sha256": target_hash,
    }
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()


def lexical_match_index(path):
    try:
        return LEXICAL_PARENTS.index(path)
    except ValueError:
        return -1


def capture(path, chain, ordinal, reveal_path, require_directory=False):
    safe_absolute(path)
    before = os.lstat(path)
    kind = entry_type(before)
    target_hash = readlink_hash(path) if kind == "symlink" else None
    if not hasattr(os, "O_PATH") or not hasattr(os, "O_NOFOLLOW"):
        raise ObservationBlocked("O_PATH_OR_NOFOLLOW_UNAVAILABLE")
    flags = os.O_PATH | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if require_directory:
        flags |= os.O_DIRECTORY
    try:
        fd = os.open(path, flags)
    except OSError:
        raise ObservationBlocked("PATH_PIN_FAILED")
    try:
        pinned = os.fstat(fd)
        after = os.lstat(path)
        if stat_signature(before) != stat_signature(pinned):
            raise ObservationBlocked("PATH_PIN_IDENTITY_MISMATCH")
        if stat_signature(before) != stat_signature(after):
            raise ObservationBlocked("PATH_CHANGED_DURING_CAPTURE")
        if entry_type(pinned) != kind:
            raise ObservationBlocked("PATH_TYPE_CHANGED_DURING_CAPTURE")
        if require_directory and kind != "directory":
            raise ObservationBlocked("CANONICAL_PARENT_NOT_DIRECTORY")
        if kind == "symlink" and readlink_hash(path) != target_hash:
            raise ObservationBlocked("SYMLINK_CHANGED_DURING_CAPTURE")
        mode = stat.S_IMODE(before.st_mode)
        record = {
            "chain": chain,
            "ordinal": ordinal,
            "path": path if reveal_path else None,
            "path_sha256": path_sha256(path),
            "path_depth": path_depth(path),
            "entry_type": kind,
            "is_symlink": kind == "symlink",
            "uid": int(before.st_uid),
            "gid": int(before.st_gid),
            "mode": "%04o" % mode,
            "nlink": int(before.st_nlink),
            "identity_sha256": identity_sha256(
                chain, ordinal, path, before, target_hash
            ),
            "target_sha256": target_hash,
            "group_or_other_writable": (
                kind == "directory" and bool(mode & 0o022)
            ),
            "matches_lexical_index": lexical_match_index(path),
        }
        return record, {"fd": fd, "path": path, "signature": stat_signature(before),
                        "kind": kind, "target_sha256": target_hash}
    except Exception:
        os.close(fd)
        raise


def verify_handle(handle):
    pinned = os.fstat(handle["fd"])
    current = os.lstat(handle["path"])
    if stat_signature(pinned) != handle["signature"]:
        raise ObservationBlocked("PINNED_IDENTITY_CHANGED")
    if stat_signature(current) != handle["signature"]:
        raise ObservationBlocked("PATH_IDENTITY_CHANGED")
    if entry_type(current) != handle["kind"]:
        raise ObservationBlocked("PATH_TYPE_CHANGED")
    if handle["kind"] == "symlink":
        if readlink_hash(handle["path"]) != handle["target_sha256"]:
            raise ObservationBlocked("SYMLINK_TARGET_CHANGED")


def close_handles(handles):
    for handle in handles:
        try:
            os.close(handle["fd"])
        except OSError:
            pass


def resolve_bounded(path):
    """Resolve one fixed path while pinning every traversed filesystem entry."""
    safe_absolute(path)
    pending = path[1:].split("/")
    resolved = []
    handles = []
    visited = set()
    hops = 0
    steps = 0
    try:
        while pending:
            steps += 1
            if steps > MAX_RESOLUTION_STEPS:
                raise ObservationBlocked("RESOLUTION_STEP_LIMIT")
            component = pending.pop(0)
            if component == ".":
                continue
            if component == "..":
                if resolved:
                    resolved.pop()
                continue
            if not SAFE_COMPONENT.match(component):
                raise ObservationBlocked("UNSAFE_PATH_COMPONENT")
            candidate = "/" + "/".join(resolved + [component])
            if len(candidate.encode("ascii")) > MAX_PATH_BYTES:
                raise ObservationBlocked("RESOLVED_PATH_TOO_LONG")
            record, handle = capture(candidate, "resolver", len(handles), False)
            handles.append(handle)
            if record["entry_type"] == "symlink":
                hops += 1
                if hops > MAX_SYMLINK_HOPS:
                    raise ObservationBlocked("SYMLINK_HOP_LIMIT")
                visit_key = (
                    handle["signature"][0],
                    handle["signature"][1],
                    tuple(pending),
                )
                if visit_key in visited:
                    raise ObservationBlocked("SYMLINK_RESOLUTION_LOOP")
                visited.add(visit_key)
                target = readlink_value(candidate)
                if (
                    hashlib.sha256(target.encode("ascii")).hexdigest()
                    != handle["target_sha256"]
                ):
                    raise ObservationBlocked("SYMLINK_CHANGED_DURING_RESOLUTION")
                if target != "/" and (target.endswith("/") or "//" in target):
                    raise ObservationBlocked("UNSAFE_SYMLINK_TARGET_SHAPE")
                absolute = target.startswith("/")
                target_body = target[1:] if absolute else target
                target_parts = [] if target_body == "" else target_body.split("/")
                if any(part == "" for part in target_parts):
                    raise ObservationBlocked("UNSAFE_SYMLINK_TARGET_SHAPE")
                if absolute:
                    resolved = []
                pending = target_parts + pending
                continue
            if pending and record["entry_type"] != "directory":
                raise ObservationBlocked("NON_DIRECTORY_RESOLUTION_COMPONENT")
            resolved.append(component)
            if len(resolved) > MAX_CANONICAL_PARENTS + 1:
                raise ObservationBlocked("RESOLVED_PATH_DEPTH_LIMIT")
        canonical_path = "/" + "/".join(resolved)
        safe_absolute(canonical_path)
        return canonical_path, handles
    except Exception:
        close_handles(handles)
        raise


def original_prefix_state(records):
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


def empty_observation():
    return {
        "lexical": [],
        "canonical": [],
        "endpoint": None,
        "canonical_path_sha256": None,
        "canonical_depth": 0,
    }


def observe_once():
    handles = []
    try:
        # Root was checked before either predecessor branch. Pin and validate it
        # without including raw inode/device metadata in the receipt.
        root_record, root_handle = capture("/", "root", 0, False, True)
        handles.append(root_handle)
        root_mode = int(root_record["mode"], 8)
        if (
            root_record["entry_type"] != "directory"
            or root_record["uid"] != 0
            or root_record["gid"] != 0
            or bool(root_mode & 0o022)
        ):
            raise ObservationBlocked("ROOT_PREREQUISITE_MISMATCH")

        lexical = []
        for ordinal, path in enumerate(LEXICAL_PARENTS):
            record, handle = capture(path, "lexical", ordinal, True)
            lexical.append(record)
            handles.append(handle)
        state, index = original_prefix_state(lexical)
        observation = {
            "lexical": lexical,
            "canonical": [],
            "endpoint": None,
            "canonical_path_sha256": None,
            "canonical_depth": 0,
        }
        if state != "SAFE":
            return observation, handles, state, index

        endpoint, endpoint_handle = capture(
            WRAPPER_PATH, "endpoint", 0, False
        )
        handles.append(endpoint_handle)
        observation["endpoint"] = endpoint
        if endpoint_state(endpoint) != "SAFE":
            return observation, handles, "ENDPOINT_MISMATCH", None
        canonical_path, resolver_handles = resolve_bounded(WRAPPER_PATH)
        handles.extend(resolver_handles)
        canonical_parents = list(prefixes(canonical_path))[:-1]
        if not canonical_parents or len(canonical_parents) > MAX_CANONICAL_PARENTS:
            raise ObservationBlocked("CANONICAL_PARENT_COUNT_OUT_OF_RANGE")
        canonical_records = []
        for ordinal, path in enumerate(canonical_parents):
            record, handle = capture(path, "canonical", ordinal, False, True)
            canonical_records.append(record)
            handles.append(handle)
        second_path, second_resolver_handles = resolve_bounded(WRAPPER_PATH)
        try:
            for handle in second_resolver_handles:
                verify_handle(handle)
            if second_path != canonical_path:
                raise ObservationBlocked("RESOLVED_PATH_CHANGED_DURING_CAPTURE")
        finally:
            close_handles(second_resolver_handles)
        observation.update({
            "canonical": canonical_records,
            "canonical_path_sha256": path_sha256(canonical_path),
            "canonical_depth": path_depth(canonical_path),
        })
        canonical_state, canonical_index = original_prefix_state(canonical_records)
        if canonical_state == "WRITABLE":
            return observation, handles, "CANONICAL_WRITABLE", canonical_index
        if canonical_state == "SAFE":
            return observation, handles, "SAFE", None
        return observation, handles, "CANONICAL_MISMATCH", None
    except Exception:
        close_handles(handles)
        raise


def predecessor():
    return {
        "source_sha256": PREDECESSOR_SOURCE_SHA256,
        "command_bytes": PREDECESSOR_COMMAND_BYTES,
        "command_sha256": PREDECESSOR_COMMAND_SHA256,
        "commitment_sha256": PREDECESSOR_COMMITMENT_SHA256,
        "reason_code": PREDECESSOR_REASON,
    }


def scope():
    return {
        "role": "wrapper",
        "invoked_path": WRAPPER_PATH,
        "lexical_parents": list(LEXICAL_PARENTS),
    }


def fixed_boundaries():
    return {
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


def result_base():
    result = {
        "schema": SCHEMA,
        "status": "BLOCKED",
        "predecessor": predecessor(),
        "scope": scope(),
    }
    result.update(fixed_boundaries())
    return result


def blocked(code):
    if not re.match(r"\A[A-Z0-9_]+\Z", code):
        code = "INTERNAL_VALIDATION_ERROR"
    result = result_base()
    result.update({
        "diagnostic_complete": False,
        "diagnostic_state": "OBSERVATION_BLOCKED",
        "reason_code": code,
        "before": empty_observation(),
        "after": empty_observation(),
        "before_after_equal": False,
        "culprit_scope": "NONE",
        "culprit_index": -1,
        "culprit_path": None,
        "culprit_path_sha256": None,
    })
    print(canonical(committed(result)))
    return 3


def diagnose():
    handles = []
    try:
        before, first_handles, before_state, before_index = observe_once()
        handles.extend(first_handles)
        after, second_handles, after_state, after_index = observe_once()
        handles.extend(second_handles)
        for handle in handles:
            verify_handle(handle)
        equal = before == after
        if not equal or before_state != after_state or before_index != after_index:
            diagnostic_state = "UNSTABLE"
            reason_code = "OBSERVATION_UNSTABLE"
            culprit_scope = "NONE"
            culprit_index = -1
            culprit_path = None
            culprit_hash = None
            exit_code = 4
        elif before_state == "WRITABLE":
            diagnostic_state = "CURRENT_STABLE_MATCH"
            reason_code = PREDECESSOR_REASON
            culprit_scope = "LEXICAL"
            culprit_index = before_index
            culprit_path = LEXICAL_PARENTS[before_index]
            culprit_hash = path_sha256(culprit_path)
            exit_code = 3
        elif before_state == "CANONICAL_WRITABLE":
            diagnostic_state = "CURRENT_STABLE_MATCH"
            reason_code = PREDECESSOR_REASON
            culprit_scope = "CANONICAL"
            culprit_index = before_index
            culprit_path = None
            culprit_hash = before["canonical"][before_index]["path_sha256"]
            exit_code = 3
        else:
            diagnostic_state = "CURRENT_STABLE_NO_MATCH"
            reason_code = "CURRENT_STATE_NOT_REPRODUCED"
            culprit_scope = "NONE"
            culprit_index = -1
            culprit_path = None
            culprit_hash = None
            exit_code = 3
        result = result_base()
        result.update({
            "diagnostic_complete": True,
            "diagnostic_state": diagnostic_state,
            "reason_code": reason_code,
            "before": before,
            "after": after,
            "before_after_equal": equal,
            "culprit_scope": culprit_scope,
            "culprit_index": culprit_index,
            "culprit_path": culprit_path,
            "culprit_path_sha256": culprit_hash,
        })
        print(canonical(committed(result)))
        return exit_code
    finally:
        close_handles(handles)


def main():
    try:
        return diagnose()
    except ObservationBlocked as exc:
        return blocked(exc.code)
    except Exception:
        return blocked("INTERNAL_VALIDATION_ERROR")


if __name__ == "__main__":
    sys.exit(main())
