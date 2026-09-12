import contextlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from scripts import reset_production_admin_password as recovery


class AdminPasswordRecoveryTests(unittest.TestCase):
    def test_input_errors_are_clear_retry_locally_and_never_echo_values(self):
        old = b"DATABASE_URL=fixture\nADMIN_PASSWORD=old-fixture-password\n"
        short = "short-fixture"
        good = "Replacement-fixture-123"
        wrong = "different-fixture-123"
        out = io.StringIO()
        with patch.object(recovery.getpass, "getpass", side_effect=[short, good, wrong, good, good]), contextlib.redirect_stdout(out):
            self.assertEqual(recovery.read_password(old), good)
        self.assertIn("16–128", out.getvalue())
        self.assertIn("两次输入不一致", out.getvalue())
        for value in [short, good, wrong, "old-fixture-password"]:
            self.assertNotIn(value, out.getvalue())

    def test_unsupported_characters_and_unchanged_password_are_not_applied(self):
        old = b"DATABASE_URL=fixture\nADMIN_PASSWORD=old-fixture-password\n"
        out = io.StringIO()
        with patch.object(recovery.getpass, "getpass", side_effect=["x" * 16 + "中", "old-fixture-password", "x" * 15]), contextlib.redirect_stdout(out):
            with self.assertRaises(recovery.InputRejected):
                recovery.read_password(old)
        self.assertIn("英文输入法", out.getvalue())
        self.assertIn("新密码不能与原密码相同", out.getvalue())
        self.assertNotIn("old-fixture-password", out.getvalue())

    def test_hidden_input_fallback_fails_closed(self):
        import warnings
        def fallback(prompt):
            warnings.warn("fixture warning", recovery.getpass.GetPassWarning)
            return "never-accepted-fixture"
        with patch.object(recovery.getpass, "getpass", side_effect=fallback), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(recovery.getpass.GetPassWarning):
                recovery.read_password(b"ADMIN_PASSWORD=old-fixture-password\n")

    def test_literal_password_preserves_every_other_config_byte(self):
        original = b"# retained\r\nDATABASE_URL=postgresql://fixture@local/db\r\nADMIN_PASSWORD=old-fixture-value\r\nOTHER=a=b\r\n"
        password = "Fixture$`'\";=Strong123"
        changed = recovery.replacement(original, password)
        self.assertEqual(changed.replace(password.encode(), b"old-fixture-value"), original)

    def test_rejects_env_injection_duplicate_missing_and_same_password(self):
        original = b"DATABASE_URL=fixture\nADMIN_PASSWORD=old-fixture-password\n"
        for password in ("short", "x" * 16 + "\nADMIN_USERNAME=intruder", "x" * 16 + "\0", "x" * 16 + "\r", " " * 20, "old-fixture-password"):
            with self.subTest(password_length=len(password)), self.assertRaises(recovery.RecoveryError):
                recovery.replacement(original, password)
        for bad in (original + b"ADMIN_PASSWORD=duplicate\n", b"DATABASE_URL=fixture\n", original + b"DATABASE_URL=duplicate\n"):
            with self.assertRaises(recovery.RecoveryError):
                recovery.replacement(bad, "Replacement-fixture-123")

    @unittest.skipUnless(os.geteuid() == 0, "private file ownership test runs in isolated root container")
    def test_atomic_file_permissions_conflict_and_symlink_refusal(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "admin.env"
            recovery.write_private(path, b"before", exclusive=True)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            recovery.write_private(path, b"after", expected=b"before")
            self.assertEqual(recovery.private_read(path), b"after")
            with self.assertRaises(recovery.RecoveryError):
                recovery.write_private(path, b"overwrite", expected=b"before")
            self.assertEqual(path.read_bytes(), b"after")
            link = Path(folder) / "link"
            link.symlink_to(path)
            with self.assertRaises(OSError):
                recovery.private_read(link)
            with self.assertRaises(FileExistsError):
                recovery.write_private(path, b"overwrite", exclusive=True)
            self.assertEqual(sorted(p.name for p in Path(folder).iterdir()), ["admin.env", "link"])

    def test_real_readiness_shape_and_logout_of_new_session(self):
        seen = []
        def request(path, **kwargs):
            seen.append((path, kwargs))
            if path == "/health/ready":
                return 200, {"status": "ready", "service": "noteai-admin", "checks": {"database": {"ok": True}}}
            if path == "/admin/login":
                return (401, None) if kwargs["password"] == "old-fixture" else (200, {"username": "noteai_admin", "token": "admin_fixture"})
            if path == "/admin/logout":
                return 200, {"ok": True}
            if path == "/admin/me":
                logged_out = any(p == "/admin/logout" for p, _ in seen)
                return (200, {"username": "noteai_admin"}) if kwargs.get("token") and not logged_out else (403, None)
            return 200, {}
        with patch.object(recovery, "request", side_effect=request), patch.object(recovery, "inspect", return_value={"Image": recovery.IMAGE}):
            result = recovery.verify("new-fixture", "old-fixture")
        self.assertEqual(result["logged_out_token"], 403)
        self.assertEqual(sum(path == "/admin/login" for path, _ in seen), 2)
        self.assertEqual(seen[-2][0], "/admin/logout")


@unittest.skipUnless(os.environ.get("NOTEAI_RESET_TEST_DATABASE_URL"), "isolated PG16 URL not set")
class AdminPasswordRecoveryPostgresTests(unittest.TestCase):
    def test_scoped_revocation_commits_and_preserves_other_admin(self):
        import psycopg
        dsn = os.environ["NOTEAI_RESET_TEST_DATABASE_URL"]
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute("CREATE ROLE noteai_admin_runtime LOGIN")
            conn.execute("CREATE TABLE public.admin_sessions(token TEXT PRIMARY KEY,username TEXT,created_at DOUBLE PRECISION,expires_at DOUBLE PRECISION)")
            conn.execute("GRANT SELECT,INSERT,DELETE ON public.admin_sessions TO noteai_admin_runtime")
            conn.execute("INSERT INTO public.admin_sessions VALUES ('fixture1','noteai_admin',1,2),('fixture2','noteai_admin',1,2),('fixture3','other_admin',1,2)")
        runtime = dsn.replace("postgres@", "noteai_admin_runtime@")
        with patch.dict(os.environ, {"DATABASE_URL": runtime}):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exec(recovery.database_code(True), {})
            self.assertEqual(json.loads(output.getvalue()), {"role": "noteai_admin_runtime", "before": 2, "deleted": 2, "remaining": 0})
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exec(recovery.database_code(), {})
            self.assertEqual(json.loads(output.getvalue())["remaining"], 0)
        with psycopg.connect(dsn) as conn:
            self.assertEqual(conn.execute("SELECT username FROM public.admin_sessions").fetchall(), [("other_admin",)])


if __name__ == "__main__":
    unittest.main()
