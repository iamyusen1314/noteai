#!/bin/bash
set -Eeuo pipefail
set +x
umask 077
export LC_ALL=C
export PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy NO_PROXY no_proxy
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONINSPECT PYTHONOPTIMIZE
unset DATABASE_URL NOTEAI_SQLITE_PATH PGHOST PGPORT PGDATABASE PGUSER PGPASSWORD PGSERVICE PGSERVICEFILE
unset ALIBABA_CLOUD_ACCESS_KEY_ID ALIBABA_CLOUD_ACCESS_KEY_SECRET ALIBABA_CLOUD_SECURITY_TOKEN
unset ALICLOUD_ACCESS_KEY ALICLOUD_SECRET_KEY ALICLOUD_SECURITY_TOKEN OSS_ACCESS_KEY_ID OSS_ACCESS_KEY_SECRET
unset DOCKER_HOST DOCKER_CONTEXT DOCKER_CONFIG DOCKER_TLS DOCKER_TLS_VERIFY DOCKER_CERT_PATH

if [ ! -x /usr/bin/python3 ]; then
  printf '%s\n' '{"NOTEAI_ITEM26_RESTORED_PARENT_PROBE":"FAIL","application_secret_value_read_count":0,"automatic_retry_allowed":false,"container_start_count":0,"database_connection_count":0,"database_write_count":0,"environment_value_read_count":0,"host_task_write_count":0,"phase":"python","private_key_value_read_count":0,"resource_id_values_emitted":0,"same_invocation_replay_allowed":false,"secret_values_emitted":0}' >&2
  exit 3
fi

exec /usr/bin/python3 -I -B - <<'PY'
import json
import os
import stat

TRUSTED_PARENT = "/var/lib"
PERSISTENT_NAME = "noteai"


class Failure(Exception):
    def __init__(self, phase, unknown=False):
        Exception.__init__(self, phase)
        self.phase = phase
        self.unknown = unknown


def canonical(value):
    return (json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ) + "\n").encode("ascii")


def common():
    return {
        "application_secret_value_read_count": 0,
        "automatic_retry_allowed": False,
        "container_start_count": 0,
        "database_connection_count": 0,
        "database_write_count": 0,
        "environment_value_read_count": 0,
        "host_task_write_count": 0,
        "private_key_value_read_count": 0,
        "resource_id_values_emitted": 0,
        "same_invocation_replay_allowed": False,
        "secret_values_emitted": 0,
    }


def emit(value, code):
    body = canonical(value)
    if len(body) > 4096:
        os._exit(4)
    descriptor = 1 if code == 0 else 2
    try:
        if os.write(descriptor, body) != len(body):
            os._exit(4)
    except BaseException:
        os._exit(4)
    os._exit(code)


def terminal(state, phase):
    value = common()
    value.update({
        "NOTEAI_ITEM26_RESTORED_PARENT_PROBE": state,
        "phase": phase,
    })
    if state == "UNKNOWN":
        value["readback_required"] = True
    return value


def stable_tuple(row):
    return (
        row.st_mode,
        row.st_uid,
        row.st_gid,
        row.st_nlink,
        row.st_dev,
        row.st_ino,
        getattr(row, "st_mtime_ns", int(row.st_mtime * 1000000000)),
        getattr(row, "st_ctime_ns", int(row.st_ctime * 1000000000)),
    )


def trusted_parent_safe(row):
    mode = stat.S_IMODE(row.st_mode)
    return (
        stat.S_ISDIR(row.st_mode)
        and not stat.S_ISLNK(row.st_mode)
        and row.st_uid == 0
        and (mode & 0o700) == 0o700
        and (mode & 0o7000) == 0
        and (mode & 0o022) == 0
    )


def pin_trusted_parent():
    try:
        before = os.lstat(TRUSTED_PARENT)
    except FileNotFoundError:
        raise Failure("trusted_parent")
    except OSError:
        raise Failure("trusted_parent_runtime", True)
    if not trusted_parent_safe(before):
        raise Failure("trusted_parent")
    if not all(hasattr(os, name) for name in ("O_DIRECTORY", "O_NOFOLLOW", "O_CLOEXEC")):
        raise Failure("tool")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = None
    try:
        descriptor = os.open(TRUSTED_PARENT, flags)
        opened = os.fstat(descriptor)
        after = os.lstat(TRUSTED_PARENT)
    except OSError:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise Failure("trusted_parent_race", True)
    if (
        stable_tuple(before) != stable_tuple(opened)
        or stable_tuple(before) != stable_tuple(after)
        or not trusted_parent_safe(opened)
    ):
        os.close(descriptor)
        raise Failure("trusted_parent_race", True)
    return descriptor, before


def stable_child_lstat(parent_descriptor):
    try:
        before = os.stat(
            PERSISTENT_NAME,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        try:
            os.stat(
                PERSISTENT_NAME,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return None
        except OSError:
            raise Failure("persistent_parent_race", True)
        raise Failure("persistent_parent_race", True)
    except OSError:
        raise Failure("persistent_parent_runtime", True)
    try:
        after = os.stat(
            PERSISTENT_NAME,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
    except OSError:
        raise Failure("persistent_parent_race", True)
    if stable_tuple(before) != stable_tuple(after):
        raise Failure("persistent_parent_race", True)
    return before


def verify_trusted_parent(parent_descriptor, snapshot):
    try:
        opened = os.fstat(parent_descriptor)
        current = os.lstat(TRUSTED_PARENT)
    except OSError:
        raise Failure("trusted_parent_race", True)
    if (
        stable_tuple(snapshot) != stable_tuple(opened)
        or stable_tuple(snapshot) != stable_tuple(current)
        or not trusted_parent_safe(opened)
    ):
        raise Failure("trusted_parent_race", True)


def file_type(row):
    if stat.S_ISLNK(row.st_mode):
        return "SYMLINK"
    if stat.S_ISDIR(row.st_mode):
        return "DIRECTORY"
    if stat.S_ISREG(row.st_mode):
        return "REGULAR_FILE"
    if stat.S_ISBLK(row.st_mode):
        return "BLOCK_DEVICE"
    if stat.S_ISCHR(row.st_mode):
        return "CHARACTER_DEVICE"
    if stat.S_ISFIFO(row.st_mode):
        return "FIFO"
    if stat.S_ISSOCK(row.st_mode):
        return "SOCKET"
    return "OTHER"


def observe():
    if os.geteuid() != 0:
        raise Failure("root")
    parent_descriptor, trusted = pin_trusted_parent()
    try:
        observed = stable_child_lstat(parent_descriptor)
        verify_trusted_parent(parent_descriptor, trusted)
    except BaseException:
        try:
            os.close(parent_descriptor)
        except OSError:
            pass
        raise
    try:
        os.close(parent_descriptor)
    except OSError:
        raise Failure("trusted_parent_race", True)
    value = common()
    value.update({
        "NOTEAI_ITEM26_RESTORED_PARENT_PROBE": "PASS",
        "persistent_parent_gid": None if observed is None else observed.st_gid,
        "persistent_parent_is_symlink": (
            False if observed is None else stat.S_ISLNK(observed.st_mode)
        ),
        "persistent_parent_mode": (
            None if observed is None else format(stat.S_IMODE(observed.st_mode), "04o")
        ),
        "persistent_parent_nlink": None if observed is None else observed.st_nlink,
        "persistent_parent_state": "ABSENT" if observed is None else "PRESENT",
        "persistent_parent_type": "ABSENT" if observed is None else file_type(observed),
        "persistent_parent_uid": None if observed is None else observed.st_uid,
        "schema_version": 1,
        "trusted_parent_gid": trusted.st_gid,
        "trusted_parent_mode": format(stat.S_IMODE(trusted.st_mode), "04o"),
        "trusted_parent_nlink": trusted.st_nlink,
        "trusted_parent_safe": True,
    })
    return value


try:
    emit(observe(), 0)
except Failure as exc:
    emit(terminal("UNKNOWN" if exc.unknown else "FAIL", exc.phase), 4 if exc.unknown else 3)
except BaseException:
    emit(terminal("UNKNOWN", "unexpected"), 4)
PY
