import contextlib
import io
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import validate_production_env_files as validator


ROOT = Path(__file__).resolve().parents[1]
SAFE_TEST_SECRET_VALUE = "test-key"
SAFE_DISABLED_VALUE = "0"


class ProductionEnvFileTests(unittest.TestCase):
    def _env_file(self, directory: Path, name: str, body: str) -> Path:
        path = directory / name
        path.write_text(body, encoding="utf-8")
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        return path

    def test_production_compose_uses_seven_role_specific_env_inputs(self):
        compose = (
            ROOT / "deploy" / "production" / "docker-compose.yml"
        ).read_text(encoding="utf-8")

        self.assertEqual(
            compose.count(
                "${NOTEAI_API_ENV_FILE:-/etc/noteai/api.env}"
            ),
            1,
        )
        self.assertEqual(
            compose.count(
                "${NOTEAI_ADMIN_ENV_FILE:-/etc/noteai/admin.env}"
            ),
            1,
        )
        self.assertEqual(
            compose.count(
                "${NOTEAI_PAYMENT_ENV_FILE:-/etc/noteai/payment.env}"
            ),
            1,
        )
        self.assertEqual(
            compose.count(
                "${NOTEAI_AI_DISPATCHER_ENV_FILE:-/etc/noteai/ai-dispatcher.env}"
            ),
            1,
        )
        self.assertEqual(
            compose.count(
                "${NOTEAI_AI_WORKER_ENV_FILE:-/etc/noteai/ai-worker.env}"
            ),
            1,
        )
        self.assertEqual(
            compose.count(
                "${NOTEAI_XHS_TRENDS_ENV_FILE:-/etc/noteai/xhs-trends.env}"
            ),
            1,
        )
        self.assertEqual(
            compose.count(
                "${NOTEAI_XHS_TRACKING_ENV_FILE:-/etc/noteai/xhs-tracking.env}"
            ),
            1,
        )
        self.assertNotIn("NOTEAI_PRODUCTION_ENV_FILE", compose)
        self.assertNotIn("/etc/noteai/runtime.env", compose)

    def test_each_role_accepts_only_its_documented_secret_names(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            role_paths = (
                (
                    "api",
                    self._env_file(
                        directory,
                        "api.env",
                        f"DATABASE_URL={SAFE_TEST_SECRET_VALUE}\n"
                        f"ANTHROPIC_API_KEY={SAFE_TEST_SECRET_VALUE}\n"
                        "NOTEAI_FACT_SEARCH=0\n",
                    ),
                ),
                (
                    "admin",
                    self._env_file(
                        directory,
                        "admin.env",
                        f"DATABASE_URL={SAFE_TEST_SECRET_VALUE}\n"
                        f"ADMIN_PASSWORD={SAFE_TEST_SECRET_VALUE}\n"
                        "ADMIN_USERNAME=synthetic\n",
                    ),
                ),
                (
                    "payment",
                    self._env_file(
                        directory,
                        "payment.env",
                        f"DATABASE_URL={SAFE_TEST_SECRET_VALUE}\n"
                        f"NOTEAI_ADAPAY_API_KEY={SAFE_TEST_SECRET_VALUE}\n"
                        f"NOTEAI_ADAPAY_MERCHANT_PRIVATE_KEY={SAFE_TEST_SECRET_VALUE}\n"
                        f"NOTEAI_ADAPAY_PUBLIC_KEY={SAFE_TEST_SECRET_VALUE}\n"
                        "NOTEAI_PAYMENT_CALLBACK_ENABLED=0\n",
                    ),
                ),
                (
                    "ai_dispatcher",
                    self._env_file(
                        directory,
                        "ai-dispatcher.env",
                        f"DATABASE_URL={SAFE_TEST_SECRET_VALUE}\n",
                    ),
                ),
                (
                    "ai_worker",
                    self._env_file(
                        directory,
                        "ai-worker.env",
                        f"DATABASE_URL={SAFE_TEST_SECRET_VALUE}\n"
                        f"ANTHROPIC_API_KEY={SAFE_TEST_SECRET_VALUE}\n"
                        f"NOTEAI_AI_WORKER_STORE_SECRET_ACCESS_KEY={SAFE_TEST_SECRET_VALUE}\n"
                        "NOTEAI_DURABLE_AI_SUSPENDED=1\n",
                    ),
                ),
                (
                    "xhs_trends",
                    self._env_file(
                        directory,
                        "xhs-trends.env",
                        f"DATABASE_URL={SAFE_TEST_SECRET_VALUE}\n"
                        f"NOTEAI_XHS_COOKIES_JSON={SAFE_TEST_SECRET_VALUE}\n"
                        f"NOTEAI_XHS_TOKEN_DISCOVERY={SAFE_DISABLED_VALUE}\n"
                        "NOTEAI_XHS_COLLECTION_SUSPENDED=1\n",
                    ),
                ),
                (
                    "xhs_tracking",
                    self._env_file(
                        directory,
                        "xhs-tracking.env",
                        f"DATABASE_URL={SAFE_TEST_SECRET_VALUE}\n"
                        f"NOTEAI_XHS_COOKIES_JSON={SAFE_TEST_SECRET_VALUE}\n"
                        "NOTEAI_XHS_COLLECTION_SUSPENDED=1\n",
                    ),
                ),
            )

            results = validator.validate_all_role_env_files(role_paths)

        self.assertEqual(
            [result["role"] for result in results],
            [
                "api",
                "admin",
                "payment",
                "ai_dispatcher",
                "ai_worker",
                "xhs_trends",
                "xhs_tracking",
            ],
        )
        self.assertEqual(
            [result["secret_key_count"] for result in results],
            [2, 2, 4, 1, 3, 2, 2],
        )

    def test_cross_role_and_unknown_secret_names_fail_closed(self):
        cases = (
            ("api", "ADMIN_PASSWORD"),
            ("admin", "ANTHROPIC_API_KEY"),
            ("payment", "ANTHROPIC_API_KEY"),
            ("ai_dispatcher", "ANTHROPIC_API_KEY"),
            ("ai_dispatcher", "NOTEAI_AI_WORKER_STORE_SECRET_ACCESS_KEY"),
            ("admin", "NOTEAI_ADAPAY_MERCHANT_PRIVATE_KEY"),
            ("admin", "NOTEAI_ADAPAY_PUBLIC_KEY"),
            ("ai_worker", "NOTEAI_ADAPAY_PUBLIC_KEY"),
            ("ai_worker", "NOTEAI_XHS_COOKIES_JSON"),
            ("xhs_trends", "MOONSHOT_API_KEY"),
            ("xhs_tracking", "NOTEAI_AUTHORIZED_TREND_TOKEN"),
            ("api", "UNREVIEWED_VENDOR_TOKEN"),
            ("xhs_tracking", "XHS_SESSION_COOKIE"),
            ("api", "NOTEAI_XHS_COOKIES_JSON"),
            ("admin", "NOTEAI_XHS_COOKIES_JSON"),
        )
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            for index, (role, key) in enumerate(cases):
                with self.subTest(role=role, key=key):
                    path = self._env_file(
                        directory,
                        f"{index}.env",
                        f"{key}=synthetic\n",
                    )
                    with self.assertRaisesRegex(
                        validator.EnvFileValidationError,
                        key,
                    ):
                        validator.validate_role_env_file(role, path)

    def test_roles_cannot_reuse_the_same_env_file(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            shared = self._env_file(
                directory,
                "shared.env",
                f"DATABASE_URL={SAFE_TEST_SECRET_VALUE}\n",
            )

            with self.assertRaisesRegex(
                validator.EnvFileValidationError,
                "must use distinct env files",
            ):
                validator.validate_all_role_env_files(
                    (
                        ("api", shared),
                        ("admin", shared),
                        ("payment", shared),
                        ("ai_dispatcher", shared),
                        ("ai_worker", shared),
                        ("xhs_trends", shared),
                        ("xhs_tracking", shared),
                    )
                )

    def test_duplicate_invalid_and_overexposed_files_fail(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            duplicate = self._env_file(
                directory,
                "duplicate.env",
                f"DATABASE_URL={SAFE_TEST_SECRET_VALUE}\n"
                f"DATABASE_URL={SAFE_TEST_SECRET_VALUE}\n",
            )
            invalid = self._env_file(
                directory,
                "invalid.env",
                "NOT A KEY=synthetic\n",
            )
            exposed = self._env_file(
                directory,
                "exposed.env",
                f"DATABASE_URL={SAFE_TEST_SECRET_VALUE}\n",
            )
            exposed.chmod(0o644)

            with self.assertRaisesRegex(
                validator.EnvFileValidationError,
                "duplicate key DATABASE_URL",
            ):
                validator.validate_role_env_file("api", duplicate)
            with self.assertRaisesRegex(
                validator.EnvFileValidationError,
                "invalid environment key name",
            ):
                validator.validate_role_env_file("api", invalid)
            with self.assertRaisesRegex(
                validator.EnvFileValidationError,
                "must not be group/world accessible",
            ):
                validator.validate_role_env_file("api", exposed)

    def test_symlink_env_file_fails(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            target = self._env_file(
                directory,
                "target.env",
                f"DATABASE_URL={SAFE_TEST_SECRET_VALUE}\n",
            )
            link = directory / "link.env"
            link.symlink_to(target)

            with self.assertRaisesRegex(
                validator.EnvFileValidationError,
                "missing or not regular",
            ):
                validator.validate_role_env_file("api", link)

    def test_cli_reports_counts_without_printing_values(self):
        synthetic_secret = "never-print-this-synthetic-value"
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            api = self._env_file(
                directory,
                "api.env",
                f"DATABASE_URL={synthetic_secret}\n",
            )
            admin = self._env_file(
                directory,
                "admin.env",
                f"ADMIN_PASSWORD={synthetic_secret}\n",
            )
            payment_env = self._env_file(
                directory,
                "payment.env",
                f"NOTEAI_ADAPAY_API_KEY={synthetic_secret}\n",
            )
            ai_worker = self._env_file(
                directory,
                "ai-worker.env",
                f"NOTEAI_AI_WORKER_STORE_SECRET_ACCESS_KEY={synthetic_secret}\n",
            )
            ai_dispatcher = self._env_file(
                directory,
                "ai-dispatcher.env",
                f"DATABASE_URL={synthetic_secret}\n",
            )
            xhs_trends = self._env_file(
                directory,
                "xhs-trends.env",
                f"NOTEAI_XHS_COOKIES_JSON={synthetic_secret}\n",
            )
            xhs_tracking = self._env_file(
                directory,
                "xhs-tracking.env",
                f"NOTEAI_XHS_COOKIES_JSON={synthetic_secret}\n",
            )
            output = io.StringIO()
            argv = [
                "validate_production_env_files.py",
                "--api",
                os.fspath(api),
                "--admin",
                os.fspath(admin),
                "--payment",
                os.fspath(payment_env),
                "--ai-dispatcher",
                os.fspath(ai_dispatcher),
                "--ai-worker",
                os.fspath(ai_worker),
                "--xhs-trends",
                os.fspath(xhs_trends),
                "--xhs-tracking",
                os.fspath(xhs_tracking),
            ]
            with mock.patch("sys.argv", argv), contextlib.redirect_stdout(output):
                exit_code = validator.main()

        self.assertEqual(exit_code, 0)
        self.assertNotIn(synthetic_secret, output.getvalue())
        self.assertEqual(output.getvalue().count("PASS role="), 7)

    def test_documented_allowlists_cover_every_implemented_secret_key(self):
        documentation = (ROOT / "docs" / "DEPLOYMENT_SECRETS.md").read_text(
            encoding="utf-8"
        )

        for role, names in validator.ROLE_ALLOWED_SECRET_KEYS.items():
            with self.subTest(role=role):
                for name in names:
                    self.assertIn(f"`{name}`", documentation)


if __name__ == "__main__":
    unittest.main()
