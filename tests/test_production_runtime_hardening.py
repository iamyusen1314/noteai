import json
import re
import subprocess
import sys
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
)
TMPFS_PATTERN = re.compile(
    r"/tmp:rw,noexec,nosuid,nodev,size=(?:64|512)m,"
    r"mode=1777,uid=999,gid=999"
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
                self.assertRegex(block, TMPFS_PATTERN)
        for token in FORBIDDEN_TOKENS:
            self.assertNotIn(token, compose)

    def test_local_compose_hardens_all_browser_free_roles(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assert_hardened_services(
            compose,
            (
                "noteai",
                "noteai-admin",
                "noteai-payment",
                "noteai-ai-worker",
                "noteai-trends-worker",
                "noteai-tracking-worker",
            ),
        )
        self.assertEqual(compose.count('user: "999:999"'), 6)
        self.assertEqual(compose.count("read_only: true"), 6)
        self.assertEqual(compose.count("no-new-privileges:true"), 6)

    def test_production_template_requires_immutable_role_images_and_hardening(self):
        compose = (ROOT / "deploy" / "production" / "docker-compose.yml").read_text(
            encoding="utf-8"
        )

        self.assert_hardened_services(
            compose,
            (
                "api",
                "admin",
                "payment",
                "ai-dispatcher",
                "ai-worker",
                "xhs-trends",
                "xhs-tracking",
            ),
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
        self.assertIn(
            "${NOTEAI_PAYMENT_IMAGE_REPOSITORY:"
            "?set NOTEAI_PAYMENT_IMAGE_REPOSITORY}"
            "@sha256:${NOTEAI_PAYMENT_IMAGE_DIGEST_HEX:"
            "?set NOTEAI_PAYMENT_IMAGE_DIGEST_HEX to 64 lowercase hex characters}",
            compose,
        )
        self.assertIn(
            "${NOTEAI_AI_WORKER_IMAGE_REPOSITORY:?set NOTEAI_AI_WORKER_IMAGE_REPOSITORY}"
            "@sha256:${NOTEAI_AI_WORKER_IMAGE_DIGEST_HEX:"
            "?set NOTEAI_AI_WORKER_IMAGE_DIGEST_HEX to 64 lowercase hex characters}",
            compose,
        )
        self.assertEqual(
            compose.count(
                "${NOTEAI_AI_WORKER_IMAGE_REPOSITORY:?set NOTEAI_AI_WORKER_IMAGE_REPOSITORY}"
                "@sha256:${NOTEAI_AI_WORKER_IMAGE_DIGEST_HEX:"
                "?set NOTEAI_AI_WORKER_IMAGE_DIGEST_HEX to 64 lowercase hex characters}"
            ),
            2,
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
        self.assertIn(
            "${NOTEAI_API_ENV_FILE:-/etc/noteai/api.env}",
            service_block(compose, "api"),
        )
        self.assertIn(
            "${NOTEAI_ADMIN_ENV_FILE:-/etc/noteai/admin.env}",
            service_block(compose, "admin"),
        )
        self.assertIn(
            "${NOTEAI_PAYMENT_ENV_FILE:-/etc/noteai/payment.env}",
            service_block(compose, "payment"),
        )
        self.assertIn(
            "${NOTEAI_AI_DISPATCHER_ENV_FILE:-/etc/noteai/ai-dispatcher.env}",
            service_block(compose, "ai-dispatcher"),
        )
        self.assertIn(
            "${NOTEAI_AI_WORKER_ENV_FILE:-/etc/noteai/ai-worker.env}",
            service_block(compose, "ai-worker"),
        )
        self.assertIn(
            "${NOTEAI_PRIVATE_STORAGE_ENV_FILE:-/etc/noteai/private-storage.env}",
            service_block(compose, "ai-worker"),
        )
        self.assertNotIn(
            "NOTEAI_PRIVATE_STORAGE_ENV_FILE",
            service_block(compose, "ai-dispatcher"),
        )
        self.assertIn(
            "${NOTEAI_XHS_TRENDS_ENV_FILE:-/etc/noteai/xhs-trends.env}",
            service_block(compose, "xhs-trends"),
        )
        self.assertIn(
            "${NOTEAI_XHS_TRACKING_ENV_FILE:-/etc/noteai/xhs-tracking.env}",
            service_block(compose, "xhs-tracking"),
        )
        self.assertNotIn("NOTEAI_PRODUCTION_ENV_FILE", compose)
        self.assertEqual(compose.count("target: /app/model/data"), 3)
        self.assertNotIn(
            "target: /app/model/data",
            service_block(compose, "xhs-trends"),
        )
        self.assertNotIn("target: /app/model/artifacts", compose)
        self.assertNotIn("NOTEAI_ENABLE_CLOUD_MODEL_MUTATION: \"1\"", compose)

    def test_all_final_compose_roles_have_exact_bounded_local_logs(self):
        compose = (
            ROOT / "deploy" / "production" / "docker-compose.yml"
        ).read_text(encoding="utf-8")
        services = (
            "api",
            "admin",
            "payment",
            "ai-dispatcher",
            "ai-worker",
            "xhs-trends",
            "xhs-tracking",
        )
        for service in services:
            with self.subTest(service=service):
                block = service_block(compose, service)
                self.assertEqual(block.count("logging:"), 1)
                self.assertEqual(block.count("driver: local"), 1)
                self.assertEqual(block.count('max-size: "10m"'), 1)
                self.assertEqual(block.count('max-file: "2"'), 1)

    def test_final_systemd_and_recovery_units_have_exact_bounded_local_logs(self):
        systemd = ROOT / "deploy" / "production" / "systemd"
        for name in (
            "noteai-ai-dispatcher.service.template",
            "noteai-ai-worker.service.template",
            "noteai-xhs-trends.service.template",
            "noteai-xhs-tracking.service.template",
            "noteai-payment.service.template",
        ):
            with self.subTest(name=name):
                unit = (systemd / name).read_text(encoding="utf-8")
                self.assertEqual(unit.count("--log-driver=local"), 1)
                self.assertEqual(unit.count("--log-opt=max-size=10m"), 1)
                self.assertEqual(unit.count("--log-opt=max-file=2"), 1)

        recovery = (
            ROOT / "deploy" / "production" / "recover_minimal_api_runtimes.sh"
        ).read_text(encoding="utf-8")
        self.assertEqual(recovery.count("--log-driver=local"), 2)
        self.assertEqual(recovery.count("--log-opt=max-size=10m"), 2)
        self.assertEqual(recovery.count("--log-opt=max-file=2"), 2)

    def test_dormant_formal_units_wait_for_visibility_and_remove_failed_residue(self):
        systemd = ROOT / "deploy" / "production" / "systemd"
        units = {
            "noteai-ai-dispatcher.service.template": "noteai-ai-dispatcher",
            "noteai-ai-worker.service.template": "noteai-ai-worker",
            "noteai-xhs-trends.service.template": "noteai-xhs-trends",
            "noteai-xhs-tracking.service.template": "noteai-xhs-tracking",
        }
        for name, container in units.items():
            with self.subTest(name=name):
                unit = (systemd / name).read_text(encoding="utf-8")
                wait = "ExecStartPost=/usr/bin/sleep 5"
                health = "ExecStartPost=/usr/bin/docker exec " + container
                cleanup = (
                    "ExecStopPost=-/usr/bin/docker container rm " + container
                )
                self.assertEqual(unit.count(wait), 1)
                self.assertEqual(unit.count(health), 1)
                self.assertEqual(unit.count(cleanup), 1)
                self.assertEqual(unit.count("SuccessExitStatus=137"), 1)
                self.assertLess(unit.index(wait), unit.index(health))
                self.assertLess(unit.index(health), unit.index(cleanup))
                self.assertNotIn("/bin/sh", unit)

    def test_journald_and_signal_catalog_are_bounded_and_secret_free(self):
        journald = (
            ROOT
            / "deploy"
            / "production"
            / "systemd"
            / "30-noteai-runtime-log-bounds.conf"
        ).read_text(encoding="utf-8")
        self.assertEqual(
            journald,
            "[Journal]\n"
            "Storage=persistent\n"
            "SystemMaxUse=256M\n"
            "RuntimeMaxUse=64M\n"
            "MaxRetentionSec=7day\n"
            "MaxFileSec=1day\n",
        )

        catalog = json.loads(
            (
                ROOT / "deploy" / "production" / "observability-signals.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(catalog["schema"], "noteai.production.observability/v1")
        roles = catalog["role_process_alerts"]
        self.assertEqual(len(roles), 9)
        self.assertEqual(
            {item["key"] for item in roles},
            {
                "api-c",
                "api-f",
                "admin",
                "dispatcher",
                "worker-c",
                "worker-f",
                "trends",
                "tracking",
                "payment",
            },
        )
        self.assertEqual(
            {item["key"] for item in roles if item["expected_state"] == "running"},
            {"api-c", "api-f", "admin"},
        )
        self.assertEqual(
            {item["key"] for item in roles if item["expected_state"] == "suspended"},
            {"dispatcher", "worker-c", "worker-f", "trends", "tracking", "payment"},
        )
        for item in roles:
            if item["expected_state"] == "running":
                self.assertEqual(item["operator"], "LessThanThreshold")
                self.assertEqual(item["threshold"], 1)
                self.assertEqual(item["evaluation_count"], 3)
            else:
                self.assertEqual(
                    item["operator"],
                    "GreaterThanOrEqualToThreshold",
                )
                self.assertEqual(item["threshold"], 1)
                self.assertEqual(item["evaluation_count"], 1)
        self.assertTrue(catalog["process_metric"]["notification_test_required"])
        self.assertFalse(catalog["process_metric"]["automatic_resource_action"])
        signal_fields = {
            field
            for signal in catalog["application_signals"]
            for field in signal["fields"]
        }
        for field in (
            "oldest_queued_at",
            "ConnectionUsage",
            "429",
            "5xx",
            "timeout",
            "rpm",
            "itpm",
            "otpm",
            "p50_ms",
            "p95_ms",
            "p99_ms",
        ):
            self.assertIn(field, signal_fields)
        self.assertFalse(catalog["redaction_contract"]["raw_payload_retention"])
        self.assertFalse(catalog["budget_contract"]["automatic_paid_scaling"])

    def test_item25_log_bounds_executor_has_offline_fail_closed_contract(self):
        script = (
            ROOT
            / "deploy"
            / "production"
            / "apply_observability_log_bounds.py"
        )
        result = subprocess.run(
            [sys.executable, str(script), "--offline-self-test"],
            cwd=ROOT,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(
            result.stdout,
            "NOTEAI_ITEM25_LOG_BOUNDS_OFFLINE_SELF_TEST=PASS\n",
        )
        self.assertEqual(result.stderr, "")

        source = script.read_text(encoding="utf-8")
        self.assertIn('mutation_started = True', source)
        self.assertIn('"automatic_retry_allowed": False', source)
        self.assertIn('"production_database_write_count": 0', source)
        self.assertIn('"provider_control_plane_mutation_count": 0', source)
        self.assertIn('"metadata_identity_read_count": 2', source)
        self.assertIn('"admin_restart_count": admin_restarts', source)
        self.assertIn('"api_restart_count": 0', source)
        self.assertIn('"suspended_unit_start_count": 0', source)
        self.assertIn('"acceptance_unit_residue": 0', source)
        self.assertIn('"acceptance_container_residue": 0', source)
        self.assertIn('"id": inspect_value(name, "{{.Id}}")', source)
        self.assertIn('"started_at": inspect_value(name, "{{.State.StartedAt}}")', source)
        self.assertIn('"restart_count": inspect_value(name, "{{.RestartCount}}")', source)
        self.assertIn('{"database", "model"}', source)
        self.assertIn('{"admin_credentials", "database"}', source)
        self.assertIn('"ActiveState": "inactive"', source)
        self.assertIn('"SubState": "dead"', source)
        self.assertIn('"LoadState": "loaded"', source)
        self.assertIn('"DropInPaths": ""', source)
        self.assertIn('"FragmentPath": SYSTEMD_ROOT + "/" + unit', source)
        self.assertIn('wait_for_admin_ready(before_fingerprints["noteai-admin-c"])', source)
        self.assertIn('def verify_resume_state(host, units):', source)
        self.assertIn('"resumed_unit_updates": len(resumed)', source)
        self.assertIn('os.chmod(JOURNALD_ROOT, 0o755)', source)
        self.assertIn('INSERTION_POINT = b"ExecStart=/usr/bin/docker run "', source)
        self.assertNotIn('INSERTION_POINT = b"/usr/bin/docker run --pull=never "', source)
        self.assertEqual(source.count('"restart", "noteai-admin.service"'), 1)
        self.assertNotIn('container", "run"', source)
        self.assertNotIn("/etc/noteai/", source)

    def test_hardening_helper_rejects_comment_spoof_and_unsafe_mutations(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        services = (
            "noteai",
            "noteai-admin",
            "noteai-payment",
            "noteai-ai-worker",
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

    def test_tracking_worker_fails_stopped_and_has_provider_free_healthcheck(self):
        compose = (
            ROOT / "deploy" / "production" / "docker-compose.yml"
        ).read_text(encoding="utf-8")
        tracking = compose.split("\n  xhs-tracking:\n", 1)[1]
        self.assertIn('restart: "no"', tracking)
        self.assertNotIn('restart: "on-failure', tracking)
        self.assertIn("--healthcheck", tracking)

    def test_trends_systemd_template_is_bounded_and_default_suspended(self):
        unit = (
            ROOT
            / "deploy"
            / "production"
            / "systemd"
            / "noteai-xhs-trends.service.template"
        ).read_text(encoding="utf-8")

        self.assertEqual(unit.count("@@NOTEAI_XHS_IMAGE@@"), 2)
        self.assertIn("--name=noteai-xhs-trends", unit)
        self.assertIn("--label=com.noteai.service=noteai-xhs-trends", unit)
        self.assertIn("--pull=never", unit)
        self.assertIn("--user=999:999", unit)
        self.assertIn("--read-only", unit)
        self.assertIn("--cap-drop=ALL", unit)
        self.assertIn("--security-opt=no-new-privileges:true", unit)
        self.assertIn("--memory=512m", unit)
        self.assertIn("--cpus=0.50", unit)
        self.assertIn("--pids-limit=64", unit)
        self.assertIn("--env-file=/etc/noteai/xhs-trends.env", unit)
        self.assertIn("--env=NOTEAI_RUNTIME_ROLE=xhs-http", unit)
        self.assertIn("--env=NOTEAI_XHS_SERVICE=trends", unit)
        self.assertIn("--env=NOTEAI_XHS_COLLECTION_SUSPENDED=1", unit)
        self.assertIn("python market_timing_worker.py --daemon --interval 360", unit)
        self.assertIn("Restart=no", unit)
        self.assertNotIn("Restart=always", unit)
        self.assertNotIn("Restart=on-failure", unit)
        self.assertNotIn("WantedBy=default.target", unit)
        self.assertNotIn("EnvironmentFile=", unit)

    def test_tracking_systemd_template_is_bounded_and_default_suspended(self):
        unit = (
            ROOT
            / "deploy"
            / "production"
            / "systemd"
            / "noteai-xhs-tracking.service.template"
        ).read_text(encoding="utf-8")

        self.assertEqual(unit.count("@@NOTEAI_XHS_IMAGE@@"), 2)
        self.assertIn("--name=noteai-xhs-tracking", unit)
        self.assertIn("--label=com.noteai.service=noteai-xhs-tracking", unit)
        self.assertIn("--pull=never", unit)
        self.assertIn("--user=999:999", unit)
        self.assertIn("--read-only", unit)
        self.assertIn("--cap-drop=ALL", unit)
        self.assertIn("--security-opt=no-new-privileges:true", unit)
        self.assertIn("--memory=256m", unit)
        self.assertIn("--cpus=0.25", unit)
        self.assertIn("--pids-limit=64", unit)
        self.assertIn(
            "--mount=type=bind,src=/var/lib/noteai/data,dst=/app/model/data",
            unit,
        )
        self.assertIn("--env-file=/etc/noteai/xhs-tracking.env", unit)
        self.assertIn("--env=NOTEAI_RUNTIME_ROLE=xhs-http", unit)
        self.assertIn("--env=NOTEAI_XHS_SERVICE=tracking", unit)
        self.assertIn("--env=NOTEAI_XHS_COLLECTION_SUSPENDED=1", unit)
        self.assertIn(
            "python crawler_worker.py --loop --interval-minutes 60 --limit 50",
            unit,
        )
        self.assertIn("Restart=no", unit)
        self.assertNotIn("Restart=always", unit)
        self.assertNotIn("Restart=on-failure", unit)
        self.assertNotIn("WantedBy=default.target", unit)
        self.assertNotIn("EnvironmentFile=", unit)

    def test_payment_systemd_template_is_bounded_and_default_disabled(self):
        unit = (
            ROOT
            / "deploy"
            / "production"
            / "systemd"
            / "noteai-payment.service.template"
        ).read_text(encoding="utf-8")

        self.assertEqual(unit.count("@@NOTEAI_PAYMENT_IMAGE@@"), 2)
        self.assertIn("--name=noteai-payment", unit)
        self.assertIn("--label=com.noteai.service=noteai-payment", unit)
        self.assertIn("--pull=never", unit)
        self.assertIn("--restart=no", unit)
        self.assertIn("--user=999:999", unit)
        self.assertIn("--read-only", unit)
        self.assertIn("--cap-drop=ALL", unit)
        self.assertIn("--security-opt=no-new-privileges:true", unit)
        self.assertIn("--memory=256m", unit)
        self.assertIn("--cpus=0.25", unit)
        self.assertIn("--pids-limit=64", unit)
        self.assertIn("--env-file=/etc/noteai/payment.env", unit)
        self.assertIn("--env=NOTEAI_RUNTIME_ROLE=payment", unit)
        self.assertIn("--env=NOTEAI_DEPLOYMENT_STAGE=production", unit)
        self.assertIn("--env=NOTEAI_PAYMENT_CALLBACK_ENABLED=0", unit)
        self.assertIn("--env=NOTEAI_TRUSTED_PROXY_IPS=127.0.0.1", unit)
        self.assertIn("--publish=127.0.0.1:8002:8002", unit)
        self.assertIn("Restart=no", unit)
        self.assertNotIn("Restart=always", unit)
        self.assertNotIn("Restart=on-failure", unit)
        self.assertNotIn("WantedBy=default.target", unit)
        self.assertNotIn("EnvironmentFile=", unit)


if __name__ == "__main__":
    unittest.main()
