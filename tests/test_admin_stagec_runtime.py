import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PATH = ROOT / "deploy" / "production" / "admin_stagec_runtime.py"


def load_runtime():
    spec = importlib.util.spec_from_file_location("noteai_admin_stagec_runtime", RUNTIME_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("stagec_runtime_import")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AdminStageCRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = load_runtime()

    def test_current_release_and_candidate_anchors_are_exact(self):
        runtime = self.runtime
        self.assertEqual(
            runtime.OLD_UNIT_SHA,
            "c299059d167eab0863639355a6485094e58e3dca6bcec7adbe9f78a3857a1ab2",
        )
        self.assertEqual(
            runtime.CANDIDATE_SHA,
            "101f8814d89736c2aa920f3107916b9b1ab53cabffdde0d69908285fd6d1fe8a",
        )
        self.assertEqual(
            runtime.OLD_CONFIG,
            "sha256:2283095764622e373e30b51ba749819751e6bfb0c37c6bb82e2d3bfe4937760f",
        )
        self.assertEqual(
            runtime.NEW_CONFIG,
            "sha256:fa0e658cba59a0adda16f64efb9bdfe543f459d90fe35997bd39046eb7743bd4",
        )
        self.assertEqual(
            runtime.REVISION,
            "5335bdaed933b1f999b5f819c047ec50c11821ae",
        )

    def test_v3_namespace_is_fresh_and_v2_identity_is_absent(self):
        runtime = self.runtime
        self.assertEqual(str(runtime.STAGE), "/root/.noteai-admin-stagec-5335-v3")
        self.assertEqual(str(runtime.RUN_ROOT), "/run/noteai-admin-stagec-5335-v3")
        self.assertEqual(runtime.CANARY, "noteai-admin-canary-stagec-5335-v3")
        source = RUNTIME_PATH.read_text(encoding="utf-8")
        for stale in (
            "noteai-admin-stagec-b55-v2",
            "noteai-admin-stagec-v2",
            "noteai-admin.candidate-v2.service",
            "noteai-admin-canary-stagec-v2",
            "b55f11882100e9ef919522540729e366a511f88f",
            "sha256:fac78f71d7b123621962738d2a93532ff98f2302232562dc75b6a8e0016b7626",
        ):
            self.assertNotIn(stale, source)

    def test_visible_settings_accept_only_nonsecret_allowlisted_subset(self):
        source = self.runtime.ACL_AUDIT_SOURCE
        self.assertNotIn("len(settings) == 2", source)
        self.assertIn(
            'visible_setting_keys <= {"model_registry", "crawler_config"}', source
        )
        self.assertIn("len(visible_setting_keys) == len(settings)", source)
        self.assertIn('all(int(row["is_secret"]) == 0 for row in settings)', source)

        def accepted(rows):
            keys = {row["key"] for row in rows}
            return (
                keys <= {"model_registry", "crawler_config"}
                and len(keys) == len(rows)
                and all(int(row["is_secret"]) == 0 for row in rows)
            )

        self.assertTrue(accepted([]))
        self.assertTrue(accepted([{"key": "crawler_config", "is_secret": 0}]))
        self.assertTrue(
            accepted(
                [
                    {"key": "crawler_config", "is_secret": 0},
                    {"key": "model_registry", "is_secret": 0},
                ]
            )
        )
        self.assertFalse(accepted([{"key": "unexpected", "is_secret": 0}]))
        self.assertFalse(accepted([{"key": "crawler_config", "is_secret": 1}]))
        self.assertFalse(
            accepted(
                [
                    {"key": "crawler_config", "is_secret": 0},
                    {"key": "crawler_config", "is_secret": 0},
                ]
            )
        )

    def test_system_settings_policy_shape_is_exact_and_fail_closed(self):
        source = self.runtime.ACL_AUDIT_SOURCE
        expected_qual = (
            "((CURRENT_USER = 'noteai_admin_runtime'::name) AND (is_secret = 0) "
            "AND (key = ANY (ARRAY['model_registry'::text, "
            "'crawler_config'::text])))"
        )
        for required in (
            'settings_policy_rows[0]["tablename"] == "system_settings"',
            'list(settings_policy_rows[0]["roles"]) == ["public"]',
            'settings_policy_rows[0]["cmd"] == "SELECT"',
            'settings_policy_rows[0]["qual"] == expected_settings_qual',
            'settings_policy_rows[0]["with_check"] is None',
            'and settings_policy_exact',
            '"system_settings_rls_policy_exact": settings_policy_exact',
        ):
            self.assertIn(required, source)

        expected = {
            "schemaname": "public",
            "tablename": "system_settings",
            "policyname": "noteai_system_settings_admin_read_v1",
            "permissive": "PERMISSIVE",
            "roles": ["public"],
            "cmd": "SELECT",
            "qual": expected_qual,
            "with_check": None,
        }

        def accepted(row):
            return row == expected

        self.assertTrue(accepted(dict(expected)))
        for key, wrong in (
            ("tablename", "other_table"),
            ("cmd", "ALL"),
            ("roles", ["noteai_admin_runtime"]),
            ("qual", expected_qual + " OR true"),
            ("with_check", expected_qual),
        ):
            with self.subTest(key=key):
                mutated = dict(expected)
                mutated[key] = wrong
                self.assertFalse(accepted(mutated))

    def test_embedded_python_sources_compile(self):
        embedded = {
            name: value
            for name, value in vars(self.runtime).items()
            if name.endswith("_SOURCE") and isinstance(value, str)
        }
        self.assertGreaterEqual(len(embedded), 3)
        for name, source in embedded.items():
            with self.subTest(name=name):
                compile(source, f"<{name}>", "exec")

    def test_mode_surface_is_exact_and_bounded(self):
        self.assertEqual(
            list(self.runtime.MODES),
            [
                "canary-start",
                "canary-validate",
                "acl-audit",
                "session-open",
                "promote",
                "formal-validate",
                "explicit-restart",
                "session-close",
                "cleanup",
                "abort",
            ],
        )


if __name__ == "__main__":
    unittest.main()
