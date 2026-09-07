#!/usr/bin/env python3
"""Run explicitly named offline tests under the paused takeover constraints.

Invoke with env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin .venv/bin/python
scripts/run_paused_local_checks.py tests.test_example [tests.test_other ...].
Use --readiness to read the existing static manifest accounting. No discovery,
production credentials, workspace databases or historical executors are needed.
These process guards are not an operating-system sandbox or production proof.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROTECTED = {
    ROOT / relative for relative in (
        ".codex/item26-envelope-rotate-promote.sh",
        ".codex/item26-envelope-rotate-stage.template.sh",
        ".codex/item26-source-manifest-executor.sh",
        ".codex/item26-source-manifest-readback.sh",
        ".codex/item26-source-manifest-recovery-executor.sh",
        "tests/test_stage_item26_manual_cost_stop_helper_v2.py",
        "tools/stage_item26_manual_cost_stop_helper_v2.py",
    )
}


def main() -> int:
    names = sys.argv[1:]
    if names != ["--readiness"] and (
        not names or any(not name.startswith("tests.test_") for name in names)
    ):
        raise SystemExit("Pass explicit test module/case names or --readiness")
    # A test must not inherit a real token, DSN, proxy or provider setting.
    os.environ.clear()
    os.environ["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
    import dotenv
    import psycopg
    dotenv.load_dotenv = lambda *args, **kwargs: False
    dotenv.dotenv_values = lambda *args, **kwargs: {}

    def no_postgres(*args, **kwargs):
        raise RuntimeError("PAUSED: PostgreSQL disabled")

    psycopg.connect = no_postgres

    def audit(event, args):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
            raise RuntimeError("PAUSED: network disabled")
        if event == "open" and isinstance(args[0], (str, bytes)):
            path = Path(os.path.abspath(os.fsdecode(args[0])))
            if (
                path in PROTECTED
                or str(path).startswith(("/etc/noteai/", "/var/lib/noteai/"))
                or (path.is_relative_to(ROOT) and path.name == ".env")
            ):
                raise RuntimeError("PAUSED: protected or Secret path disabled")
        if event == "sqlite3.connect" and str(args[0]).startswith(str(ROOT)):
            raise RuntimeError("PAUSED: workspace database disabled")
        if event == "subprocess.Popen":
            command = args[1]
            if not isinstance(command, (list, tuple)) or Path(command[0]).name not in {"git", "bash"}:
                raise RuntimeError("PAUSED: subprocess disabled")
            if Path(command[0]).name == "bash" and "-n" not in command:
                raise RuntimeError("PAUSED: only shell syntax checks allowed")

    sys.addaudithook(audit)
    with tempfile.TemporaryDirectory(prefix="noteai-paused-") as directory:
        os.environ["NOTEAI_SQLITE_PATH"] = str(Path(directory) / "bootstrap.db")
        if names == ["--readiness"]:
            import internal_deployment_readiness_gate as gate
            report = gate.build_report(gate.DEFAULT_MANIFEST)
            print({key: report[key] for key in ("internal_deployment", "complete_public_launch")})
            return 0
        suite = unittest.defaultTestLoader.loadTestsFromNames(names)
        return int(not unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful())


if __name__ == "__main__":
    raise SystemExit(main())
