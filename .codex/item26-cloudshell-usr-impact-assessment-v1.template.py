#!/usr/bin/python3
"""Read-only Item26 Cloud Shell /usr impact assessment.

The atom pins / and /usr, binds the fixed child name ``shell`` relative to the
pinned /usr descriptor, and selects /usr's effective mount by the pinned
descriptor's fdinfo mnt_id.  Raw mount paths, roots, sources and identifiers
remain process-local and are never emitted or hashed.  Every outcome remains
BLOCKED and performs no mutation or CLI invocation.
"""

from __future__ import print_function

import hashlib
import json
import os
import re
import stat
import sys


SCHEMA = "noteai.item26.cloudshell-usr-impact-assessment.v1"
ROOT_PATH = "/"
USR_PATH = "/usr"
FIXED_CHILD = "shell"
MOUNTINFO_PATH = "/proc/self/mountinfo"
SELF_MOUNT_NAMESPACE_PATH = "/proc/self/ns/mnt"
PID1_MOUNT_NAMESPACE_PATH = "/proc/1/ns/mnt"
PREDECESSOR_SCHEMA = "noteai.item26.cloudshell-wrapper-parent-diagnostic.v1"
PREDECESSOR_SOURCE_COMMIT = "9c3b055e2f24b4c82f894d87ff954ae49a4b553a"
PREDECESSOR_COMMAND_BYTES = 8732
PREDECESSOR_COMMAND_SHA256 = (
    "4081b80e10399a7119b3b2963f101ade1b702b8cdf48fd1853c92ecbdb71e7c4"
)
PREDECESSOR_RECEIPT_BYTES = 4191
PREDECESSOR_RECEIPT_SHA256 = (
    "260bb8abdcd0936625712042ee6c485ccc6c906308622318f2210889b8b2b9f0"
)
PREDECESSOR_COMMITMENT_SHA256 = (
    "a09720b831b1141ff16b6b35a2c4d5abeff3e380c78893a9c70fdc340045479e"
)
MAX_MOUNTINFO_BYTES = 1024 * 1024
MAX_MOUNTINFO_LINES = 4096
MAX_MOUNTINFO_LINE_BYTES = 64 * 1024
MAX_FDINFO_BYTES = 16 * 1024


class AssessmentBlocked(Exception):
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


def stat_signature(value):
    ctime_ns = getattr(value, "st_ctime_ns", None)
    if type(ctime_ns) is not int:
        raise AssessmentBlocked("CTIME_NS_UNAVAILABLE")
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


def open_flags(path_only=True, nofollow=True, directory=False):
    if path_only:
        if not hasattr(os, "O_PATH"):
            raise AssessmentBlocked("O_PATH_UNAVAILABLE")
        flags = os.O_PATH
    else:
        flags = os.O_RDONLY
    if nofollow:
        if not hasattr(os, "O_NOFOLLOW"):
            raise AssessmentBlocked("O_NOFOLLOW_UNAVAILABLE")
        flags |= os.O_NOFOLLOW
    if directory and hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    return flags


def capture_fixed_directory(path):
    if path != ROOT_PATH:
        raise AssessmentBlocked("NONFIXED_PATH_REQUESTED")
    try:
        before = os.lstat(path)
    except OSError:
        raise AssessmentBlocked("PATH_STAT_FAILED")
    if not stat.S_ISDIR(before.st_mode):
        raise AssessmentBlocked("FIXED_PATH_NOT_DIRECTORY")
    try:
        fd = os.open(path, open_flags(directory=True))
    except OSError:
        raise AssessmentBlocked("PATH_PIN_FAILED")
    try:
        pinned = os.fstat(fd)
        after = os.lstat(path)
        signature = stat_signature(before)
        if signature != stat_signature(pinned):
            raise AssessmentBlocked("PATH_PIN_IDENTITY_MISMATCH")
        if signature != stat_signature(after):
            raise AssessmentBlocked("PATH_CHANGED_DURING_CAPTURE")
        if not stat.S_ISDIR(pinned.st_mode) or not stat.S_ISDIR(after.st_mode):
            raise AssessmentBlocked("PATH_TYPE_CHANGED_DURING_CAPTURE")
        return {
            "fd": fd,
            "kind": "fixed_directory",
            "path": path,
            "signature": signature,
            "stat": before,
        }
    except Exception:
        os.close(fd)
        raise


def capture_usr_directory(root_handle):
    try:
        before = os.stat("usr", dir_fd=root_handle["fd"], follow_symlinks=False)
    except OSError:
        raise AssessmentBlocked("USR_STAT_FAILED")
    if not stat.S_ISDIR(before.st_mode):
        raise AssessmentBlocked("USR_NOT_DIRECTORY")
    try:
        fd = os.open(
            "usr", open_flags(directory=True), dir_fd=root_handle["fd"]
        )
    except OSError:
        raise AssessmentBlocked("USR_PIN_FAILED")
    try:
        pinned = os.fstat(fd)
        after = os.stat(
            "usr", dir_fd=root_handle["fd"], follow_symlinks=False
        )
        signature = stat_signature(before)
        if signature != stat_signature(pinned):
            raise AssessmentBlocked("USR_PIN_IDENTITY_MISMATCH")
        if signature != stat_signature(after):
            raise AssessmentBlocked("USR_CHANGED_DURING_CAPTURE")
        if not stat.S_ISDIR(pinned.st_mode) or not stat.S_ISDIR(after.st_mode):
            raise AssessmentBlocked("USR_TYPE_CHANGED_DURING_CAPTURE")
        return {
            "fd": fd,
            "kind": "fixed_usr",
            "parent_fd": root_handle["fd"],
            "signature": signature,
            "stat": before,
        }
    except Exception:
        os.close(fd)
        raise


def capture_fixed_child(usr_handle):
    try:
        before = os.stat(
            FIXED_CHILD, dir_fd=usr_handle["fd"], follow_symlinks=False
        )
    except OSError:
        raise AssessmentBlocked("FIXED_CHILD_STAT_FAILED")
    try:
        fd = os.open(FIXED_CHILD, open_flags(), dir_fd=usr_handle["fd"])
    except OSError:
        raise AssessmentBlocked("FIXED_CHILD_PIN_FAILED")
    try:
        pinned = os.fstat(fd)
        after = os.stat(
            FIXED_CHILD, dir_fd=usr_handle["fd"], follow_symlinks=False
        )
        signature = stat_signature(before)
        if signature != stat_signature(pinned):
            raise AssessmentBlocked("FIXED_CHILD_PIN_IDENTITY_MISMATCH")
        if signature != stat_signature(after):
            raise AssessmentBlocked("FIXED_CHILD_CHANGED_DURING_CAPTURE")
        return {
            "fd": fd,
            "kind": "fixed_child",
            "parent_fd": usr_handle["fd"],
            "signature": signature,
            "stat": before,
        }
    except Exception:
        os.close(fd)
        raise


def capture_namespace(path):
    if path not in (SELF_MOUNT_NAMESPACE_PATH, PID1_MOUNT_NAMESPACE_PATH):
        raise AssessmentBlocked("NONFIXED_NAMESPACE_REQUESTED")
    try:
        fd = os.open(path, open_flags(path_only=False, nofollow=False))
        metadata = os.fstat(fd)
    except OSError:
        try:
            os.close(fd)
        except (OSError, UnboundLocalError):
            pass
        raise AssessmentBlocked("MOUNT_NAMESPACE_PIN_FAILED")
    return {
        "fd": fd,
        "kind": "namespace",
        "signature": stat_signature(metadata),
    }


def verify_handle(handle):
    try:
        pinned = os.fstat(handle["fd"])
    except OSError:
        raise AssessmentBlocked("PINNED_HANDLE_REVERIFY_FAILED")
    if stat_signature(pinned) != handle["signature"]:
        raise AssessmentBlocked("PINNED_IDENTITY_CHANGED")
    if handle["kind"] == "fixed_directory":
        try:
            current = os.lstat(handle["path"])
        except OSError:
            raise AssessmentBlocked("PATH_REVERIFY_FAILED")
        if stat_signature(current) != handle["signature"]:
            raise AssessmentBlocked("PATH_IDENTITY_CHANGED")
    elif handle["kind"] == "fixed_usr":
        try:
            current = os.stat(
                "usr", dir_fd=handle["parent_fd"], follow_symlinks=False
            )
        except OSError:
            raise AssessmentBlocked("USR_REVERIFY_FAILED")
        if stat_signature(current) != handle["signature"]:
            raise AssessmentBlocked("USR_IDENTITY_CHANGED")
    elif handle["kind"] == "fixed_child":
        try:
            current = os.stat(
                FIXED_CHILD,
                dir_fd=handle["parent_fd"],
                follow_symlinks=False,
            )
        except OSError:
            raise AssessmentBlocked("FIXED_CHILD_REVERIFY_FAILED")
        if stat_signature(current) != handle["signature"]:
            raise AssessmentBlocked("FIXED_CHILD_IDENTITY_CHANGED")


def close_handles(handles):
    for handle in reversed(handles):
        try:
            os.close(handle["fd"])
        except OSError:
            pass


def read_bounded(path, limit, open_code, read_code, size_code):
    try:
        fd = os.open(path, open_flags(path_only=False))
    except OSError:
        raise AssessmentBlocked(open_code)
    try:
        chunks = []
        total = 0
        while True:
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                raise AssessmentBlocked(read_code)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise AssessmentBlocked(size_code)
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def pinned_mount_id(fd):
    path = "/proc/self/fdinfo/%d" % fd
    raw = read_bounded(
        path,
        MAX_FDINFO_BYTES,
        "FDINFO_OPEN_FAILED",
        "FDINFO_READ_FAILED",
        "FDINFO_SIZE_LIMIT",
    )
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        raise AssessmentBlocked("FDINFO_ENCODING_INVALID")
    values = []
    for line in text.splitlines():
        if line.startswith("mnt_id:"):
            value = line[len("mnt_id:"):].strip()
            if not value or len(value) > 20 or not value.isdigit():
                raise AssessmentBlocked("FDINFO_MOUNT_ID_INVALID")
            parsed = int(value, 10)
            if parsed <= 0 or parsed > 9223372036854775807:
                raise AssessmentBlocked("FDINFO_MOUNT_ID_INVALID")
            values.append(parsed)
    if len(values) != 1:
        raise AssessmentBlocked("FDINFO_MOUNT_ID_NOT_UNIQUE")
    return values[0]


def parse_uint(raw, code, allow_zero=False):
    if not raw or len(raw) > 20 or not raw.isdigit():
        raise AssessmentBlocked(code)
    value = int(raw, 10)
    if value < (0 if allow_zero else 1) or value > 9223372036854775807:
        raise AssessmentBlocked(code)
    return value


def parse_device(raw):
    parts = raw.split(":")
    if len(parts) != 2:
        raise AssessmentBlocked("MOUNTINFO_DEVICE_INVALID")
    return (
        parse_uint(parts[0], "MOUNTINFO_DEVICE_INVALID", True),
        parse_uint(parts[1], "MOUNTINFO_DEVICE_INVALID", True),
    )


def decode_mount_path(raw):
    result = []
    index = 0
    while index < len(raw):
        if raw[index] != "\\":
            result.append(raw[index])
            index += 1
            continue
        if index + 3 >= len(raw):
            raise AssessmentBlocked("MOUNTINFO_ESCAPE_INVALID")
        escaped = raw[index + 1:index + 4]
        if escaped not in ("040", "011", "012", "134"):
            raise AssessmentBlocked("MOUNTINFO_ESCAPE_INVALID")
        result.append(chr(int(escaped, 8)))
        index += 4
    value = "".join(result)
    if not value.startswith("/") or "\x00" in value or "\n" in value or "\r" in value:
        raise AssessmentBlocked("MOUNTINFO_PATH_INVALID")
    return value


def propagation_class(optional_fields):
    shared = False
    master = False
    propagate_from = False
    unbindable = False
    for field in optional_fields:
        if field.startswith("shared:"):
            parse_uint(field[len("shared:"):], "MOUNTINFO_PROPAGATION_ID_INVALID")
            if shared:
                raise AssessmentBlocked("MOUNTINFO_PROPAGATION_DUPLICATE")
            shared = True
        elif field.startswith("master:"):
            parse_uint(field[len("master:"):], "MOUNTINFO_PROPAGATION_ID_INVALID")
            if master:
                raise AssessmentBlocked("MOUNTINFO_PROPAGATION_DUPLICATE")
            master = True
        elif field.startswith("propagate_from:"):
            parse_uint(
                field[len("propagate_from:"):],
                "MOUNTINFO_PROPAGATION_ID_INVALID",
            )
            if propagate_from:
                raise AssessmentBlocked("MOUNTINFO_PROPAGATION_DUPLICATE")
            propagate_from = True
        elif field == "unbindable":
            if unbindable:
                raise AssessmentBlocked("MOUNTINFO_PROPAGATION_DUPLICATE")
            unbindable = True
        else:
            raise AssessmentBlocked("MOUNTINFO_OPTIONAL_FIELD_UNSUPPORTED")
    if unbindable:
        if shared or master or propagate_from:
            raise AssessmentBlocked("MOUNTINFO_PROPAGATION_CONFLICT")
        return "UNBINDABLE"
    if shared and (master or propagate_from):
        return "SHARED_SLAVE"
    if shared:
        return "SHARED"
    if master or propagate_from:
        return "SLAVE"
    return "PRIVATE"


def filesystem_class(raw):
    if raw == "overlay":
        return "OVERLAY"
    if raw == "tmpfs":
        return "TMPFS"
    return "OTHER"


def selected_mount(raw, expected_mount_id, usr_stat):
    if type(raw) is not bytes or not raw or b"\x00" in raw:
        raise AssessmentBlocked("MOUNTINFO_PAYLOAD_INVALID")
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        raise AssessmentBlocked("MOUNTINFO_ENCODING_INVALID")
    lines = text.splitlines()
    if not lines or len(lines) > MAX_MOUNTINFO_LINES:
        raise AssessmentBlocked("MOUNTINFO_LINE_LIMIT")
    selected = []
    for line in lines:
        if not line or len(line.encode("ascii")) > MAX_MOUNTINFO_LINE_BYTES:
            raise AssessmentBlocked("MOUNTINFO_LINE_INVALID")
        fields = line.split(" ")
        if "" in fields or fields.count("-") != 1:
            raise AssessmentBlocked("MOUNTINFO_LINE_INVALID")
        separator = fields.index("-")
        if separator < 6 or len(fields) != separator + 4:
            raise AssessmentBlocked("MOUNTINFO_LINE_INVALID")
        mount_id = parse_uint(fields[0], "MOUNTINFO_MOUNT_ID_INVALID")
        if mount_id != expected_mount_id:
            continue
        parent_id = parse_uint(fields[1], "MOUNTINFO_PARENT_ID_INVALID")
        major, minor = parse_device(fields[2])
        mount_root = decode_mount_path(fields[3])
        mount_point = decode_mount_path(fields[4])
        if mount_point == ROOT_PATH:
            mountpoint_class = "ROOT"
        elif mount_point == USR_PATH:
            mountpoint_class = "EXACT_USR"
        else:
            raise AssessmentBlocked("SELECTED_MOUNTPOINT_OUT_OF_SCOPE")
        options = fields[5].split(",")
        if options.count("ro") + options.count("rw") != 1:
            raise AssessmentBlocked("MOUNTINFO_ACCESS_MODE_INVALID")
        propagation = propagation_class(fields[6:separator])
        fs_type = fields[separator + 1]
        super_options = fields[separator + 3].split(",")
        if super_options.count("ro") + super_options.count("rw") != 1:
            raise AssessmentBlocked("MOUNTINFO_SUPER_ACCESS_MODE_INVALID")
        fs_class = filesystem_class(fs_type)
        mode_options = [
            option[len("mode="):]
            for option in super_options
            if option.startswith("mode=")
        ]
        if len(mode_options) > 1:
            raise AssessmentBlocked("MOUNTINFO_MODE_OPTION_DUPLICATE")
        if mountpoint_class != "EXACT_USR":
            usr_mount_mode_class = "NOT_APPLICABLE"
        elif not mode_options:
            usr_mount_mode_class = "ABSENT"
        elif (
            re.match(r"\A[0-7]{3,5}\Z", mode_options[0])
            and int(mode_options[0], 8) == 0o1777
        ):
            usr_mount_mode_class = "EXPLICIT_1777"
        else:
            usr_mount_mode_class = "OTHER_OR_AMBIGUOUS"
        upperdir_present = fs_class == "OVERLAY" and any(
            option.startswith("upperdir=") and len(option) > len("upperdir=")
            for option in super_options
        )
        try:
            stat_major = os.major(usr_stat.st_dev)
            stat_minor = os.minor(usr_stat.st_dev)
        except (AttributeError, TypeError, ValueError, OverflowError):
            raise AssessmentBlocked("DEVICE_ID_UNAVAILABLE")
        if major != stat_major or minor != stat_minor:
            raise AssessmentBlocked("SELECTED_MOUNT_DEVICE_MISMATCH")
        normalized = {
            "filesystem_class": fs_class,
            "mountpoint_class": mountpoint_class,
            "access_mode": (
                "READ_ONLY"
                if "ro" in options or "ro" in super_options
                else "READ_WRITE"
            ),
            "propagation": propagation,
            "filesystem_root_class": (
                "FS_ROOT" if mount_root == ROOT_PATH else "SUBTREE"
            ),
            "noexec": "noexec" in options,
            "nosuid": "nosuid" in options,
            "nodev": "nodev" in options,
            "upperdir_present": upperdir_present,
            "usr_mount_mode_class": usr_mount_mode_class,
        }
        selected.append((normalized, line))
    if len(selected) != 1:
        raise AssessmentBlocked("SELECTED_MOUNT_NOT_UNIQUE")
    return selected[0]


def empty_observation():
    return {
        "root_prerequisite_satisfied": False,
        "usr_exact_predecessor_mode": False,
        "usr_current_class": "UNKNOWN",
        "fixed_shell_component_trusted": False,
        "mount": None,
        "pid1_mount_namespace_relation": "UNKNOWN",
    }


def classify_usr_stat(value):
    mode = stat.S_IMODE(value.st_mode)
    if (
        value.st_uid == 0
        and value.st_gid == 0
        and mode == 0o1777
        and value.st_nlink == 1
    ):
        return "ROOT_OWNED_STICKY_EXACT_1777"
    if (
        value.st_uid == 0
        and value.st_gid == 0
        and value.st_nlink == 1
        and not bool(mode & 0o022)
    ):
        return "ROOT_OWNED_NON_GROUP_OTHER_WRITABLE"
    return "UNSAFE_OR_UNKNOWN"


def fixed_shell_component_trusted(value):
    mode = stat.S_IMODE(value.st_mode)
    return (
        stat.S_ISDIR(value.st_mode)
        and not stat.S_ISLNK(value.st_mode)
        and value.st_uid == 0
        and value.st_gid == 0
        and value.st_nlink > 0
        and not bool(mode & 0o022)
    )


def observe_once():
    handles = []
    try:
        root_handle = capture_fixed_directory(ROOT_PATH)
        handles.append(root_handle)
        root_stat = root_handle["stat"]
        root_mode = stat.S_IMODE(root_stat.st_mode)
        root_safe = (
            root_stat.st_uid == 0
            and root_stat.st_gid == 0
            and not bool(root_mode & 0o022)
        )
        if not root_safe:
            raise AssessmentBlocked("ROOT_PREREQUISITE_MISMATCH")
        usr_handle = capture_usr_directory(root_handle)
        handles.append(usr_handle)
        shell_handle = capture_fixed_child(usr_handle)
        handles.append(shell_handle)
        self_ns = capture_namespace(SELF_MOUNT_NAMESPACE_PATH)
        handles.append(self_ns)
        pid1_ns = capture_namespace(PID1_MOUNT_NAMESPACE_PATH)
        handles.append(pid1_ns)

        usr_stat = usr_handle["stat"]
        usr_current_class = classify_usr_stat(usr_stat)
        usr_exact = usr_current_class == "ROOT_OWNED_STICKY_EXACT_1777"
        shell_stat = shell_handle["stat"]
        shell_trusted = fixed_shell_component_trusted(shell_stat)
        mount_id = pinned_mount_id(usr_handle["fd"])
        mount_raw = read_bounded(
            MOUNTINFO_PATH,
            MAX_MOUNTINFO_BYTES,
            "MOUNTINFO_OPEN_FAILED",
            "MOUNTINFO_READ_FAILED",
            "MOUNTINFO_SIZE_LIMIT",
        )
        mount, selected_mount_raw = selected_mount(
            mount_raw, mount_id, usr_stat
        )
        self_ns_identity = self_ns["signature"][:2]
        pid1_ns_identity = pid1_ns["signature"][:2]
        relation = (
            "SAME_AS_PID1"
            if self_ns_identity == pid1_ns_identity
            else "DIFFERENT_FROM_PID1"
        )
        public = {
            "root_prerequisite_satisfied": True,
            "usr_exact_predecessor_mode": usr_exact,
            "usr_current_class": usr_current_class,
            "fixed_shell_component_trusted": shell_trusted,
            "mount": mount,
            "pid1_mount_namespace_relation": relation,
        }
        private = {
            "usr_fd": usr_handle["fd"],
            "root_stat": root_handle["signature"],
            "usr_stat": usr_handle["signature"],
            "shell_stat": shell_handle["signature"],
            "self_ns_stat": self_ns["signature"],
            "pid1_ns_stat": pid1_ns["signature"],
            "mount_id": mount_id,
            "selected_mount_raw": selected_mount_raw,
        }
        return public, private, handles
    except Exception:
        close_handles(handles)
        raise


def predecessor():
    return {
        "schema": PREDECESSOR_SCHEMA,
        "source_commit": PREDECESSOR_SOURCE_COMMIT,
        "command_bytes": PREDECESSOR_COMMAND_BYTES,
        "command_sha256": PREDECESSOR_COMMAND_SHA256,
        "receipt_bytes": PREDECESSOR_RECEIPT_BYTES,
        "receipt_sha256": PREDECESSOR_RECEIPT_SHA256,
        "commitment_sha256": PREDECESSOR_COMMITMENT_SHA256,
        "diagnostic_state": "CURRENT_STABLE_MATCH",
        "reason_code": "WRITABLE_EXECUTABLE_PARENT",
        "culprit_scope": "LEXICAL",
        "culprit_path": USR_PATH,
        "uid": 0,
        "gid": 0,
        "mode": "1777",
        "nlink": 1,
        "group_or_other_writable": True,
    }


def scope():
    return {
        "root": ROOT_PATH,
        "subject": USR_PATH,
        "fixed_child_relative_name": FIXED_CHILD,
        "mount_metadata": "linux-proc-mountinfo",
    }


def fixed_boundaries():
    return {
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
        "assessment_complete": False,
        "assessment_state": "OBSERVATION_BLOCKED",
        "reason_code": code,
        "before": empty_observation(),
        "after": empty_observation(),
        "before_after_equal": False,
        "pinned_private_state_equal": False,
        "offline_allowlist_candidate": "NONE",
        "effective_mount_read_write_observed": False,
        "read_only_mount_observed": False,
    })
    print(canonical(committed(result)))
    return 3


def private_equal(before, after):
    keys = (
        "root_stat", "usr_stat", "shell_stat", "self_ns_stat",
        "pid1_ns_stat", "mount_id", "selected_mount_raw",
    )
    return all(before[key] == after[key] for key in keys)


def diagnose():
    handles = []
    try:
        before, before_private, before_handles = observe_once()
        handles.extend(before_handles)
        after, after_private, after_handles = observe_once()
        handles.extend(after_handles)
        if before_private["usr_fd"] == after_private["usr_fd"]:
            raise AssessmentBlocked("PINNED_USR_FD_NOT_DISTINCT")
        for handle in handles:
            verify_handle(handle)
        public_equal = before == after
        private_is_equal = private_equal(before_private, after_private)
        if not public_equal or not private_is_equal:
            state = "UNSTABLE"
            reason = "OBSERVATION_UNSTABLE"
            candidate = "NONE"
            mount_read_write = False
            read_only = False
            exit_code = 4
        elif before["usr_current_class"] == "ROOT_OWNED_NON_GROUP_OTHER_WRITABLE":
            state = "CURRENT_STABLE_SAFE_CURRENT_METADATA"
            reason = "PREDECESSOR_NOT_REPRODUCED_SAFE_CURRENT_METADATA"
            candidate = "NONE"
            read_only = before["mount"]["access_mode"] == "READ_ONLY"
            mount_read_write = not read_only
            exit_code = 3
        elif before["usr_current_class"] == "UNSAFE_OR_UNKNOWN":
            state = "CURRENT_STABLE_UNSAFE_OR_UNKNOWN"
            reason = "USR_CURRENT_METADATA_UNSAFE_OR_UNKNOWN"
            candidate = "NONE"
            read_only = before["mount"]["access_mode"] == "READ_ONLY"
            mount_read_write = not read_only
            exit_code = 3
        else:
            read_only = before["mount"]["access_mode"] == "READ_ONLY"
            mount_read_write = not read_only
            if read_only:
                state = "CURRENT_STABLE_MOUNT_READ_ONLY"
                reason = "USR_WRITABLE_BITS_MOUNT_READ_ONLY"
                candidate = "READ_ONLY_MOUNT"
            else:
                state = "CURRENT_STABLE_MOUNT_READ_WRITE"
                reason = "USR_WRITABLE_BITS_MOUNT_READ_WRITE"
                candidate = (
                    "ROOT_OWNED_STICKY_EXACT_USR"
                    if (
                        before["fixed_shell_component_trusted"]
                        and before["mount"]["filesystem_class"]
                        in ("OVERLAY", "TMPFS")
                    )
                    else "NONE"
                )
            exit_code = 3
        result = result_base()
        result.update({
            "assessment_complete": True,
            "assessment_state": state,
            "reason_code": reason,
            "before": before,
            "after": after,
            "before_after_equal": public_equal,
            "pinned_private_state_equal": private_is_equal,
            "offline_allowlist_candidate": candidate,
            "effective_mount_read_write_observed": mount_read_write,
            "read_only_mount_observed": read_only,
        })
        print(canonical(committed(result)))
        return exit_code
    finally:
        close_handles(handles)


def main():
    try:
        return diagnose()
    except AssessmentBlocked as exc:
        return blocked(exc.code)
    except Exception:
        return blocked("INTERNAL_VALIDATION_ERROR")


if __name__ == "__main__":
    sys.exit(main())
