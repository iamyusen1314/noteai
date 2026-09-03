#!/bin/bash
set -Eeuo pipefail
set +x
umask 077
export LC_ALL=C
export PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONINSPECT PYTHONOPTIMIZE
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy NO_PROXY no_proxy
unset DATABASE_URL NOTEAI_SQLITE_PATH PGHOST PGPORT PGDATABASE PGUSER PGPASSWORD PGSERVICE PGSERVICEFILE
unset ALIBABA_CLOUD_ACCESS_KEY_ID ALIBABA_CLOUD_ACCESS_KEY_SECRET ALIBABA_CLOUD_SECURITY_TOKEN
unset ALICLOUD_ACCESS_KEY ALICLOUD_SECRET_KEY ALICLOUD_SECURITY_TOKEN OSS_ACCESS_KEY_ID OSS_ACCESS_KEY_SECRET

exec python3 -I -B - <<'PY'
import base64
import gzip
import hashlib
import json
import os
import re


CONTROLLER_GZIP_BYTES = @@CONTROLLER_GZIP_BYTES@@
CONTROLLER_GZIP_SHA256 = "@@CONTROLLER_GZIP_SHA256@@"
CONTROLLER_BYTES = @@CONTROLLER_BYTES@@
CONTROLLER_SHA256 = "@@CONTROLLER_SHA256@@"
CONTROLLER_GZIP_B85 = b"@@CONTROLLER_GZIP_B85@@"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
B85 = re.compile(br"^[0-9A-Za-z!#$%&()*+\-;<=>?@^_`{|}~]+$")


def canonical(value):
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")


def fixed(started, phase):
    return {
        "NOTEAI_ITEM26_SOURCE_MANIFEST_EXECUTOR_LOADER": (
            "UNKNOWN" if started else "FAIL"
        ),
        "incident_class": "CONNECTED_UNKNOWN" if started else "PRE_CONNECT",
        "phase": phase,
        "controller_started": started,
        "database_attempted_state": "UNKNOWN" if started else "NO",
        "readback_required": started,
        "automatic_retry_allowed": False,
    }


started = False
try:
    if os.geteuid() != 0 or os.getegid() != 0:
        raise ValueError("identity")
    if (
        type(CONTROLLER_GZIP_BYTES) is not int
        or type(CONTROLLER_BYTES) is not int
        or not 1 <= CONTROLLER_GZIP_BYTES <= 131072
        or not 1 <= CONTROLLER_BYTES <= 131072
        or HEX64.fullmatch(CONTROLLER_GZIP_SHA256) is None
        or HEX64.fullmatch(CONTROLLER_SHA256) is None
        or B85.fullmatch(CONTROLLER_GZIP_B85) is None
        or len(CONTROLLER_GZIP_B85) != (CONTROLLER_GZIP_BYTES * 5 + 3) // 4
    ):
        raise ValueError("binding")
    compressed = base64.b85decode(CONTROLLER_GZIP_B85)
    if (
        len(compressed) != CONTROLLER_GZIP_BYTES
        or hashlib.sha256(compressed).hexdigest() != CONTROLLER_GZIP_SHA256
    ):
        raise ValueError("gzip_hash")
    raw = gzip.decompress(compressed)
    if len(raw) != CONTROLLER_BYTES or hashlib.sha256(raw).hexdigest() != CONTROLLER_SHA256:
        raise ValueError("controller_hash")
    code = compile(raw.decode("ascii"), "<item26-v3-controller>", "exec", dont_inherit=True)
    started = True
    exec(code, {"__name__": "__main__"})
    raise RuntimeError("controller_returned")
except BaseException:
    body = canonical(fixed(started, "controller" if started else "loader"))
    if len(body) > 4096:
        os._exit(4)
    try:
        written = os.write(2, body)
        if written != len(body):
            os._exit(4)
    except BaseException:
        os._exit(4)
    os._exit(4 if started else 3)
PY
