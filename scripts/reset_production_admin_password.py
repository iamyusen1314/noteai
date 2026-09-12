#!/usr/bin/env python3
"""Owner-authorized, interactive API-C Admin credential recovery; no secret output.

Run as root from a genuine Workbench terminal. An existing result means reconcile,
not rerun. Failure after stopping Admin leaves it stopped with a private backup.
"""
import argparse
import datetime
import getpass
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import warnings

ADMIN = "noteai_admin"
IMAGE = "sha256:76018cdf498243b8d3a9716df3baebaa67564c64ce576233c97d518aa4d5b11c"
ENV = Path("/etc/noteai/admin.env")
STAGE = Path("/var/lib/noteai/admin-public-20260912")
RESULT = STAGE / "password-reset-result.json"
BACKUP = STAGE / "admin.env.before-password-reset"
SERVICE = "noteai-admin.service"


class RecoveryError(Exception):
    pass


def require(value):
    if not value:
        raise RecoveryError()


def terminate(signum, frame):
    raise RecoveryError()


def replacement(data, password):
    # Docker env-file values are literal; never shell-evaluate the password.
    require(16 <= len(password) <= 128)
    require(all(33 <= ord(char) <= 126 for char in password))
    lines = data.splitlines(keepends=True)
    matches = [i for i, line in enumerate(lines) if line.startswith(b"ADMIN_PASSWORD=")]
    require(len(matches) == 1)
    require(sum(line.startswith(b"DATABASE_URL=") for line in lines) == 1)
    i = matches[0]
    old = lines[i].removeprefix(b"ADMIN_PASSWORD=").rstrip(b"\r\n")
    require(old and not secrets.compare_digest(old, password.encode()))
    ending = b"\r\n" if lines[i].endswith(b"\r\n") else b"\n" if lines[i].endswith(b"\n") else b""
    lines[i] = b"ADMIN_PASSWORD=" + password.encode() + ending
    return b"".join(lines)


def private_read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_gid == 0)
        require(stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1)
        with os.fdopen(fd, "rb", closefd=False) as handle:
            return handle.read()
    finally:
        os.close(fd)


def write_private(path, data, *, expected=None, exclusive=False):
    if exclusive:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        temporary = None
    else:
        fd, name = tempfile.mkstemp(prefix=".admin-reset-", dir=path.parent)
        temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if temporary is not None:
            if expected is not None:
                require(private_read(path) == expected)
            os.replace(temporary, path)
        parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def command(args, *, body=None, timeout=40):
    result = subprocess.run(args, input=body, capture_output=True, timeout=timeout)
    require(result.returncode == 0)
    return result.stdout


def inspect(name):
    return json.loads(command(["docker", "inspect", name]))[0]


def database_code(revoke=False):
    # No app startup, migrations, general transaction collector or business DML.
    return '''import json,os,psycopg
with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=8) as conn:
 with conn.cursor() as cur:
  cur.execute("SET LOCAL statement_timeout='10000ms'")
  cur.execute("SET LOCAL lock_timeout='5000ms'")
  cur.execute("SELECT current_user,has_table_privilege(current_user,'public.admin_sessions','SELECT'),has_table_privilege(current_user,'public.admin_sessions','DELETE')")
  assert cur.fetchone()==('noteai_admin_runtime',True,True)
  cur.execute("SELECT count(*) FROM public.admin_sessions WHERE username=%s",('noteai_admin',))
  before=cur.fetchone()[0]
''' + ('''  cur.execute("DELETE FROM public.admin_sessions WHERE username=%s",('noteai_admin',))
  deleted=cur.rowcount
  cur.execute("SELECT count(*) FROM public.admin_sessions WHERE username=%s",('noteai_admin',))
  remaining=cur.fetchone()[0]
  assert remaining==0 and deleted==before
''' if revoke else '''  deleted=0
  remaining=before
''') + '''print(json.dumps({'role':'noteai_admin_runtime','before':before,'deleted':deleted,'remaining':remaining}),flush=True)
'''


def database(*, revoke=False, live=False):
    if live:
        return json.loads(command(["docker", "exec", "-i", "noteai-admin-c", "python", "-"],
                                  body=database_code().encode()))
    name = "noteai-admin-password-reset-db"
    label = "noteai.operation=admin-password-reset"
    args = ["docker", "run", "--rm", "--name=" + name, "--label=" + label,
            "--pull=never", "--network=bridge", "--user=999:999", "--read-only",
            "--cap-drop=ALL", "--security-opt=no-new-privileges:true", "--memory=256m",
            "--cpus=0.5", "--pids-limit=32", "--log-driver=none", "--env-file=" + str(ENV),
            "--env=PGOPTIONS=-c default_transaction_read_only=off",
            "--entrypoint=python", "-i", IMAGE, "-"]
    try:
        return json.loads(command(args, body=database_code(revoke).encode()))
    finally:
        # A timed-out docker CLI does not prove the helper stopped. Exact cleanup
        # is safe; its transaction outcome still requires independent readback.
        found = command(["docker", "ps", "-aq", "--filter=name=^/" + name + "$"]).strip()
        if found:
            actual = inspect(name)
            require(actual["Image"] == IMAGE and actual["Config"]["Labels"].get("noteai.operation") == "admin-password-reset")
            require(actual["Config"]["Entrypoint"] == ["python"] and actual["Config"]["Cmd"] == ["-"])
            command(["docker", "rm", "-f", actual["Id"]])


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def request(path, *, password=None, token=None, method="GET", port=8001):
    headers = {"Host": "admin.noteaipro.com" if port == 8001 else "noteaipro.com"}
    data = None
    if password is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps({"username": ADMIN, "password": password}).encode()
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request("http://127.0.0.1:" + str(port) + path,
                                 data=data, headers=headers, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(req, timeout=10) as response:
            return response.status, json.loads(response.read(2000000))
    except urllib.error.HTTPError as error:
        return error.code, None


def stopped():
    state = subprocess.run(["systemctl", "is-active", "--quiet", SERVICE], capture_output=True)
    require(state.returncode != 0)
    require(not command(["docker", "ps", "-aq", "--filter=name=^/noteai-admin-c$"]).strip())
    with socket.socket() as probe:
        probe.settimeout(2)
        require(probe.connect_ex(("127.0.0.1", 8001)) != 0)


def verify(password, old_password):
    for _ in range(30):
        try:
            status, health = request("/health/ready")
            if status == 200 and health.get("status") == "ready":
                break
        except (OSError, ValueError):
            pass
        time.sleep(1)
    else:
        raise RecoveryError()
    require(inspect("noteai-admin-c")["Image"] == IMAGE)
    require(request("/admin/me")[0] == 403)
    require(request("/admin/login", password=old_password, method="POST")[0] == 401)
    status, session = request("/admin/login", password=password, method="POST")
    require(status == 200 and session["username"] == ADMIN)
    token = session["token"]
    try:
        status, me = request("/admin/me", token=token)
        require(status == 200 and me["username"] == ADMIN)
        require(request("/admin/capabilities", token=token)[0] == 200)
        require(request("/admin/users?page=1&page_size=1", token=token)[0] == 200)
    finally:
        require(request("/admin/logout", token=token, method="POST")[0] == 200)
        require(request("/admin/me", token=token)[0] == 403)
    return {"new_login": 200, "old_password": 401, "anonymous": 403,
            "users": 200, "logout": 200, "logged_out_token": 403,
            "verification_session_inserts": 1, "verification_session_deletes": 1}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="requires genuine hidden terminal input")
    args = parser.parse_args()
    require(args.apply and os.geteuid() == 0 and socket.gethostname() == "noteai-api-c")
    require(sys.stdin.isatty() and sys.stderr.isatty())
    os.umask(0o077)
    require(STAGE.is_dir() and not STAGE.is_symlink() and not RESULT.exists() and not BACKUP.exists())
    for directory in (STAGE, ENV.parent):
        info = directory.stat()
        require(info.st_uid == 0 and not info.st_mode & 0o022)
    require(not ENV.parent.is_symlink())
    require(not command(["docker", "ps", "-aq", "--filter=name=^/noteai-admin-password-reset-db$"]).strip())
    original = private_read(ENV)
    old_password = next(line.split(b"=", 1)[1] for line in original.splitlines()
                        if line.startswith(b"ADMIN_PASSWORD=")).decode()
    admin = inspect("noteai-admin-c")
    require(admin["Image"] == IMAGE and admin["State"]["Running"])
    values = [value.split("=", 1) for value in admin["Config"]["Env"] if "=" in value]
    require([v for k, v in values if k == "ADMIN_PASSWORD"] == [old_password])
    require([v for k, v in values if k == "ADMIN_USERNAME"] in ([], [ADMIN]))
    api = inspect("noteai-api-c")
    require(request("/health/live", port=8000)[0] == 200)
    preflight = database(live=True)
    print("请输入新的 NoteAI 后台密码两次（16–128 位，不含空格；输入不显示）。", flush=True)
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        password = getpass.getpass("新后台密码: ")
        confirm = getpass.getpass("再次输入新后台密码: ")
    require(secrets.compare_digest(password.encode(), confirm.encode()))
    changed = replacement(original, password)
    # Once hidden input is complete, a Workbench disconnect must not interrupt
    # revocation halfway through. Durable result readback replaces terminal output.
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, terminate)
    result = {"state": "PREPARED", "username": ADMIN, "image": IMAGE,
              "preflight": preflight, "business_writes": 0, "provider_requests": 0}

    def record(state):
        result.update(state=state, at=datetime.datetime.now(datetime.timezone.utc).isoformat())
        write_private(RESULT, json.dumps(result).encode(), exclusive=not RESULT.exists())

    record("PREPARED")
    stop_started = False
    try:
        write_private(BACKUP, original, exclusive=True)
        require(private_read(ENV) == original)
        record("STOPPING_ADMIN")
        stop_started = True
        command(["systemctl", "stop", SERVICE], timeout=75)
        stopped()
        record("ADMIN_STOPPED")
        write_private(ENV, changed, expected=original)
        record("PASSWORD_CHANGED_REVOKE_PENDING")
        result["revocation"] = database(revoke=True)
        result["revocation_readback"] = database()
        require(result["revocation_readback"]["remaining"] == 0)
        record("OLD_SESSIONS_REVOKED")
        command(["systemctl", "start", SERVICE], timeout=75)
        record("VERIFYING_ADMIN")
        result["verification"] = verify(password, old_password)
        require(private_read(ENV) == changed)
        current_api = inspect("noteai-api-c")
        require(current_api["Id"] == api["Id"] and current_api["State"]["StartedAt"] == api["State"]["StartedAt"])
        require(request("/health/live", port=8000)[0] == 200)
        result["api_unchanged_healthy"] = True
        record("VERIFIED")
    except BaseException as error:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        result["failed_phase"] = result["state"]
        result["error_type"] = type(error).__name__
        if stop_started:
            try:
                command(["systemctl", "stop", SERVICE], timeout=75)
                stopped()
                result["admin_stopped"] = True
                # Restore only the exact configuration this process wrote. Never
                # overwrite a concurrent credential change or restore sessions.
                current = private_read(ENV)
                if current == changed:
                    write_private(ENV, original, expected=changed)
                else:
                    require(current == original)
                result["previous_config_restored_service_stopped"] = True
                result["reconcile"] = database()
            except BaseException as recovery:
                result["recovery_error_type"] = type(recovery).__name__
        record("FAILED_RECONCILE_REQUIRED")
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result["state"] == "VERIFIED" else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (Exception, KeyboardInterrupt) as error:
        # Error strings/tracebacks can include secret-bearing subprocess input.
        print(json.dumps({"state": "STOPPED", "error_type": type(error).__name__}), flush=True)
        sys.exit(1)
