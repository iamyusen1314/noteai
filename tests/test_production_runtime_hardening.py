import unittest
from pathlib import Path

from tools.production_readiness_gate import (
    _compose_services_have_runtime_hardening,
)


ROOT = Path(__file__).resolve().parents[1]

HARDENING_TOKENS = (
    'user: "999:999"',
    "read_only: true",
    "privileged: false",
    "cap_drop:\n      - ALL",
    "security_opt:\n      - no-new-privileges:true",
    "/tmp:rw,noexec,nosuid,nodev,size=512m,mode=1777,uid=999,gid=999",
)

FORBIDDEN_TOKENS = (
    "privileged: true",
    "cap_add:",
    "devices:",
    "device_cgroup_rules:",
    "network_mode: host",
    "pid: host",
    "ipc: host",
    "seccomp=unconfined",
    "SYS_ADMIN",
    "SYS_RAWIO",
    "MKNOD",
)


def service_block(compose: str, service_name: str) -> str:
    marker = f"  {service_name}:\n"
    if marker not in compose:
        return ""
    tail = compose.split(marker, 1)[1]
    next_service = [
        offset
        for offset, line in enumerate(tail.splitlines(keepends=True))
        if offset > 0 and line.startswith("  ") and not line.startswith("    ") and line.rstrip().endswith(":")
    ]
    if not next_service:
        return tail
    return "".join(tail.splitlines(keepends=True)[:next_service[0]])


class ProductionRuntimeHardeningTests(unittest.TestCase):
    def assert_hardened_services(self, compose: str, services: tuple[str, ...]) -> None:
        for service in services:
            with self.subTest(service=service):
                block = service_block(compose, service)
                self.assertTrue(block, f"missing service {service}")
                for token in HARDENING_TOKENS:
                    self.assertIn(token, block)
        for token in FORBIDDEN_TOKENS:
            self.assertNotIn(token, compose)

    def test_local_compose_hardens_all_browser_free_roles(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assert_hardened_services(
            compose,
            ("noteai", "noteai-admin", "noteai-trends-worker", "noteai-tracking-worker"),
        )
        self.assertEqual(compose.count('user: "999:999"'), 4)
        self.assertEqual(compose.count("read_only: true"), 4)
        self.assertEqual(compose.count("no-new-privileges:true"), 4)

    def test_production_template_requires_immutable_role_images_and_hardening(self):
        compose = (ROOT / "deploy" / "production" / "docker-compose.yml").read_text(
            encoding="utf-8"
        )

        self.assert_hardened_services(
            compose,
            ("api", "admin", "xhs-trends", "xhs-tracking"),
        )
        self.assertNotIn("build:", compose)
        self.assertIn(
            "${NOTEAI_API_IMAGE_REPOSITORY:?set NOTEAI_API_IMAGE_REPOSITORY}"
            "@sha256:${NOTEAI_API_IMAGE_DIGEST_HEX:"
            "?set NOTEAI_API_IMAGE_DIGEST_HEX to 64 lowercase hex characters}",
            compose,
        )
        self.assertIn(
            "${NOTEAI_ADMIN_IMAGE_REPOSITORY:?set NOTEAI_ADMIN_IMAGE_REPOSITORY}"
            "@sha256:${NOTEAI_ADMIN_IMAGE_DIGEST_HEX:"
            "?set NOTEAI_ADMIN_IMAGE_DIGEST_HEX to 64 lowercase hex characters}",
            compose,
        )
        self.assertEqual(
            compose.count(
                "${NOTEAI_XHS_IMAGE_REPOSITORY:?set NOTEAI_XHS_IMAGE_REPOSITORY}"
                "@sha256:${NOTEAI_XHS_IMAGE_DIGEST_HEX:"
                "?set NOTEAI_XHS_IMAGE_DIGEST_HEX to 64 lowercase hex characters}"
            ),
            2,
        )
        self.assertNotIn("@${NOTEAI_API_IMAGE_DIGEST", compose)
        self.assertNotIn("@${NOTEAI_ADMIN_IMAGE_DIGEST", compose)
        self.assertNotIn("@${NOTEAI_XHS_IMAGE_DIGEST", compose)
        self.assertEqual(
            compose.count("${NOTEAI_API_ENV_FILE:-/etc/noteai/api.env}"),
            1,
        )
        self.assertEqual(
            compose.count("${NOTEAI_ADMIN_ENV_FILE:-/etc/noteai/admin.env}"),
            1,
        )
        self.assertEqual(
            compose.count("${NOTEAI_XHS_ENV_FILE:-/etc/noteai/xhs.env}"),
            2,
        )
        self.assertIn(
            "${NOTEAI_API_ENV_FILE:-/etc/noteai/api.env}",
            service_block(compose, "api"),
        )
        self.assertIn(
            "${NOTEAI_ADMIN_ENV_FILE:-/etc/noteai/admin.env}",
            service_block(compose, "admin"),
        )
        self.assertIn(
            "${NOTEAI_XHS_ENV_FILE:-/etc/noteai/xhs.env}",
            service_block(compose, "xhs-trends"),
        )
        self.assertIn(
            "${NOTEAI_XHS_ENV_FILE:-/etc/noteai/xhs.env}",
            service_block(compose, "xhs-tracking"),
        )
        self.assertNotIn("NOTEAI_PRODUCTION_ENV_FILE", compose)
        self.assertEqual(compose.count("target: /app/model/data"), 4)
        self.assertNotIn("target: /app/model/artifacts", compose)
        self.assertNotIn("NOTEAI_ENABLE_CLOUD_MODEL_MUTATION: \"1\"", compose)

    def test_hardening_helper_rejects_comment_spoof_and_unsafe_mutations(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        services = (
            "noteai",
            "noteai-admin",
            "noteai-trends-worker",
            "noteai-tracking-worker",
        )

        self.assertTrue(_compose_services_have_runtime_hardening(compose, services))
        mutations = {
            "missing_user": compose.replace('    user: "999:999"\n', "", 1),
            "commented_user": compose.replace(
                '    user: "999:999"\n',
                '    # user: "999:999"\n',
                1,
            ),
            "inline_comment_user_spoof": compose.replace(
                '    user: "999:999"\n',
                '    user: "0:0" # user: "999:999"\n',
                1,
            ),
            "privileged": compose.replace(
                "    privileged: false\n",
                "    privileged: true\n",
                1,
            ),
            "cap_add": compose.replace(
                "    cap_drop:\n      - ALL\n",
                "    cap_add:\n      - SYS_ADMIN\n    cap_drop:\n      - ALL\n",
                1,
            ),
            "devices": compose.replace(
                "    cap_drop:\n      - ALL\n",
                "    devices:\n      - /dev/sda:/dev/sda\n    cap_drop:\n      - ALL\n",
                1,
            ),
            "host_network": compose.replace(
                "    privileged: false\n",
                "    privileged: false\n    network_mode: host\n",
                1,
            ),
            "quoted_host_network": compose.replace(
                "    privileged: false\n",
                '    privileged: false\n    network_mode: "host"\n',
                1,
            ),
        }
        for name, mutation in mutations.items():
            with self.subTest(name=name):
                self.assertFalse(
                    _compose_services_have_runtime_hardening(mutation, services)
                )


if __name__ == "__main__":
    unittest.main()
