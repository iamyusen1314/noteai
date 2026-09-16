#!/usr/bin/env python3
"""Private full-session staging and quiescent Trends env CAS; never runs XHS.

The owner supplies an existing Request Cookie in a real hidden terminal. This
tool does not implement login, read a browser, clear DB/session blocks or start
workers. Existing Item34 identities and xhs-tracking.env are never modified.
"""
import argparse
import fcntl
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import stat
import subprocess
import sys
import tempfile
import warnings

ROOT = Path("/var/lib/noteai/item32-session")
TARGET = Path("/etc/noteai/xhs-trends.env")
LOCK = Path("/var/lib/noteai/item32-readonly-successor/executor.lock")
UNIT = Path("/etc/systemd/system/noteai-xhs-trends.service")
LIMIT = 131072


def require(ok):
    if not ok:
        raise ValueError("item32_session_preparation_rejected")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def cookie_records(raw):
    """Existing hidden intake's full Request Cookie format, with fixed bounds."""
    require(isinstance(raw, str) and 0 < len(raw) <= 32768
            and all(32 <= ord(c) <= 126 for c in raw))
    if raw.lower().startswith("cookie:"):
        raw = raw.split(":", 1)[1].strip()
    result, names = [], set()
    for pair in raw.split(";"):
        name, separator, value = pair.strip().partition("=")
        require(separator and value and name not in names
                and re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name))
        names.add(name)
        result.append({"name": name, "value": value, "domain": ".xiaohongshu.com", "path": "/"})
    require(2 <= len(result) <= 128 and {"a1", "web_session"}.issubset(names))
    return result


def env_rows(raw):
    require(isinstance(raw, bytes) and 0 < len(raw) <= LIMIT and b"\0" not in raw)
    result = {}
    for line in raw.decode("utf-8").splitlines():
        if not line or line.lstrip().startswith("#"):
            continue
        name, separator, value = line.partition("=")
        require(separator and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) and name not in result)
        result[name] = value
    return result


def validate_candidate(raw):
    rows = env_rows(raw)
    require(set(rows) <= {"NOTEAI_XHS_COOKIES_JSON", "NOTEAI_XHS_WEB_SSK_JSON"}
            and "NOTEAI_XHS_COOKIES_JSON" in rows)
    records = json.loads(rows["NOTEAI_XHS_COOKIES_JSON"])
    require(isinstance(records, list) and 2 <= len(records) <= 128)
    names = set()
    for row in records:
        require(isinstance(row, dict) and set(row) == {"name", "value", "domain", "path"}
                and isinstance(row["name"], str) and isinstance(row["value"], str)
                and row["name"] not in names and row["value"]
                and re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", row["name"])
                and all(32 <= ord(c) <= 126 and c != ";" for c in row["value"])
                and row["domain"] == ".xiaohongshu.com" and row["path"] == "/")
        names.add(row["name"])
    require({"a1", "web_session"}.issubset(names))
    ssk = rows.get("NOTEAI_XHS_WEB_SSK_JSON", "")
    if ssk:
        import base64
        value = json.loads(ssk)
        require(isinstance(value, dict) and set(value) == {"xhs-pc-web"}
                and isinstance(value["xhs-pc-web"], str)
                and 32 <= len(base64.b64decode(value["xhs-pc-web"], validate=True)) <= 1024)
    return rows


def merge_trends_env(original, candidate):
    """Pure exact-key merge; no DB, secret output or activation."""
    current, session = env_rows(original), validate_candidate(candidate)
    require("DATABASE_URL" in current and "NOTEAI_XHS_COOKIES_JSON" in current)
    updates = {"NOTEAI_XHS_COOKIES_JSON": session["NOTEAI_XHS_COOKIES_JSON"],
               "NOTEAI_XHS_WEB_SSK_JSON": session.get("NOTEAI_XHS_WEB_SSK_JSON", "")}
    output = []
    for line in original.splitlines(keepends=True):
        name = line.partition(b"=")[0].decode()
        if name in updates:
            ending = b"\r\n" if line.endswith(b"\r\n") else b"\n" if line.endswith(b"\n") else b""
            output.append(name.encode() + b"=" + updates.pop(name).encode() + ending)
        else:
            output.append(line)
    body = b"".join(output)
    if body and not body.endswith(b"\n"):
        body += b"\n"
    body += b"".join(k.encode()+b"="+v.encode()+b"\n" for k, v in updates.items())
    require(len(body) <= LIMIT)
    return body


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def private_dir(path, create=False):
    if create:
        os.mkdir(path, 0o700)
        os.chmod(path, 0o700, follow_symlinks=False)
        sync_dir(path.parent)
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode)
            and info.st_uid == info.st_gid == 0 and stat.S_IMODE(info.st_mode) == 0o700)


def read_private(path, mode=0o600):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == before.st_gid == 0
                and stat.S_IMODE(before.st_mode) == mode and before.st_nlink == 1
                and 0 < before.st_size <= LIMIT)
        raw = os.read(fd, LIMIT + 1)
        after = os.fstat(fd)
        linked = path.lstat()
        require(len(raw) == before.st_size and (before.st_dev, before.st_ino) == (linked.st_dev, linked.st_ino)
                and (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                == (after.st_size, after.st_mtime_ns, after.st_ctime_ns))
        return raw
    finally:
        os.close(fd)


def save_new(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    sync_dir(path.parent)


def quiescent(expected_unit_sha):
    require(re.fullmatch(r"[0-9a-f]{64}", expected_unit_sha)
            and digest(read_private(UNIT, mode=0o644)) == expected_unit_sha)
    def run(args):
        value = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, timeout=15, check=False,
                               env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
        require(value.returncode == 0 and len(value.stdout) < 8192)
        return value.stdout.decode()
    state = dict(line.split("=", 1) for line in run([
        "/usr/bin/systemctl", "show", "noteai-xhs-trends.service",
        "--property=ActiveState,SubState,Job,MainPID,NeedDaemonReload"]).splitlines())
    require(state == {"ActiveState": "inactive", "SubState": "dead", "Job": "", "MainPID": "0", "NeedDaemonReload": "no"})
    require(not run(["/usr/bin/docker", "container", "ls", "-aq", "--no-trunc", "--filter", "name=^/noteai-xhs-trends$"]).strip())
    for task in ("item32-readonly", "item32-xhs-diagnostic", "item32-readonly-successor"):
        require(not run(["/usr/bin/docker", "container", "ls", "-aq", "--no-trunc", "--filter",
                         "label=com.noteai.task="+task]).strip())


def replace_exact(expected, replacement):
    require(read_private(TARGET) == expected)
    fd, temporary = tempfile.mkstemp(prefix=".item32-session-", dir=TARGET.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(replacement)
            stream.flush()
            os.fsync(stream.fileno())
        require(read_private(TARGET) == expected)
        os.replace(temporary, TARGET)
        sync_dir(TARGET.parent)
        require(read_private(TARGET) == replacement)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def apply_once(directory, *, expected_env_sha, expected_unit_sha):
    """Under original executor lock; changing credentials does not clear DB stops."""
    require(directory.parent == ROOT and re.fullmatch(r"[0-9a-f]{32}", directory.name))
    private_dir(ROOT)
    private_dir(directory)
    require(re.fullmatch(r"[0-9a-f]{64}", expected_env_sha))
    fd = os.open(LOCK, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        lock_info = os.fstat(fd)
        require(stat.S_ISREG(lock_info.st_mode) and lock_info.st_uid == lock_info.st_gid == 0
                and stat.S_IMODE(lock_info.st_mode) == 0o600 and lock_info.st_nlink == 1
                and lock_info.st_size == 0)
        def same_lock():
            linked = LOCK.lstat()
            require((linked.st_dev, linked.st_ino) == (lock_info.st_dev, lock_info.st_ino)
                    and linked.st_size == 0 and stat.S_IMODE(linked.st_mode) == 0o600
                    and linked.st_uid == linked.st_gid == 0 and linked.st_nlink == 1)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        same_lock()
        quiescent(expected_unit_sha)
        original = read_private(TARGET)
        require(digest(original) == expected_env_sha)
        candidate = read_private(directory / "session-candidate.env")
        updated = merge_trends_env(original, candidate)
        marker = {"state": "STARTED_UNKNOWN_READBACK_ONLY", "before_sha256": expected_env_sha,
                  "after_sha256": digest(updated), "candidate_sha256": digest(candidate)}
        save_new(directory / "apply-started.json", encoded(marker))
        save_new(directory / "original.env", original)
        save_new(directory / "merged.env", updated)
        quiescent(expected_unit_sha)
        same_lock()
        replace_exact(original, updated)
        quiescent(expected_unit_sha)
        result = dict(marker, state="APPLIED_SUSPENDED_NOT_PROVIDER_VALIDATED", xhs_requests=0,
                      database_operations=0, service_restarts=0, session_block_cleared=False)
        save_new(directory / "apply-result.json", encoded(result))
        return result
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("stage", "apply", "readback"))
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--expected-env-sha256")
    parser.add_argument("--expected-unit-sha256")
    args = parser.parse_args()
    require(os.geteuid() == os.getegid() == 0 and socket.gethostname() == "noteai-api-f")
    os.umask(0o077)
    if args.operation == "stage":
        require(sys.stdin.isatty() and sys.stderr.isatty() and args.directory is None)
        if not ROOT.exists():
            private_dir(ROOT, create=True)
        private_dir(ROOT)
        directory = ROOT / secrets.token_hex(16)
        private_dir(directory, create=True)
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            records = cookie_records(getpass.getpass("Existing full Request Cookie (hidden): "))
            ssk = getpass.getpass("Existing webSsk JSON (optional, hidden): ")
        values = {"NOTEAI_XHS_COOKIES_JSON": json.dumps(records, ensure_ascii=True, separators=(",", ":"))}
        if ssk:
            values["NOTEAI_XHS_WEB_SSK_JSON"] = ssk
        candidate = b"".join(k.encode()+b"="+v.encode()+b"\n" for k,v in values.items())
        validate_candidate(candidate)
        save_new(directory / "session-candidate.env", candidate)
        result = {"state": "STAGED_NOT_APPLIED", "directory": str(directory), "cookie_count": len(records),
                  "optional_signing_state_present": bool(ssk), "xhs_requests": 0, "database_operations": 0}
        save_new(directory / "stage-result.json", encoded(result))
    elif args.operation == "apply":
        result = apply_once(args.directory, expected_env_sha=args.expected_env_sha256,
                            expected_unit_sha=args.expected_unit_sha256)
    else:
        require(args.directory is not None and args.directory.parent == ROOT
                and re.fullmatch(r"[0-9a-f]{32}", args.directory.name))
        private_dir(ROOT)
        private_dir(args.directory)
        marker = json.loads(read_private(args.directory / "apply-started.json"))
        actual = digest(read_private(TARGET))
        result = {"state": "BEFORE" if actual == marker["before_sha256"] else
                           "AFTER" if actual == marker["after_sha256"] else "CHANGED_UNKNOWN",
                  "xhs_requests": 0, "database_operations": 0}
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        print('{"state":"SESSION_ACTION_UNCONFIRMED_READBACK_ONLY","secret_values_output":false}')
        sys.exit(2)
