import json
import tempfile
import unittest
from pathlib import Path

from tools import production_readonly_preflight_gate as gate


def valid_evidence() -> dict:
    migration_hashes = gate._current_migration_hashes()
    unit_sha = "a" * 64

    def container(role: str, host: str) -> dict:
        digest_role = "xhs-http" if role.startswith("xhs") else role
        return {
            "role": role,
            "running": True,
            "managed": True,
            "image_digest_hex": gate.EXPECTED_DIGESTS[digest_role],
            "oci_revision": gate.HISTORICAL_REVISION,
            "unit_sha256": unit_sha,
            "loopback_listener": gate.EXPECTED_PORTS[host][role],
            "public_listener_count": 0,
        }

    def env_file(role: str) -> dict:
        return {
            "role": role,
            "file_label": f"{role}.env",
            "regular": True,
            "owner": "root",
            "mode": "0600",
            "key_count": 1,
            "duplicate_key_count": 0,
            "rejected_key_count": 0,
        }

    def host(label: str) -> dict:
        roles = gate.EXPECTED_HOST_ROLES[label]
        return {
            "label": label,
            "instance_state": "Running",
            "system_status": "OK",
            "private_only": True,
            "architecture": "x86_64",
            "docker_version": "28.3.3",
            "compose_version": "5.3.1",
            "docker_free_gib": 27.0,
            "memory_available_mib": 4096,
            "private_acr_dns": True,
            "private_acr_route": True,
            "containers": [container(role, label) for role in roles],
            "env_files": [env_file(role) for role in roles],
            "unexpected_container_count": 0,
            "unexpected_listener_count": 0,
            "mutable_image_ref_count": 0,
            "temporary_auth_entry_count": 0,
            "temporary_process_count": 0,
        }

    return {
        "schema_version": 1,
        "task_id": gate.TASK_ID,
        "status": "verified",
        "observed_at_utc": "2026-07-27T00:00:00Z",
        "application_revision": gate.APPLICATION_REVISION,
        "zero_mutation": {
            "cloud_changes": 0,
            "database_writes": 0,
            "business_row_values_read": 0,
            "registry_requests": 0,
            "service_changes": 0,
            "provider_calls": 0,
            "public_traffic_requests": 0,
            "secret_values_read": 0,
        },
        "cloud": {
            "acr": {
                "historical_digests": gate.EXPECTED_DIGESTS,
                "historical_images_normal": True,
                "historical_tags_immutable": True,
                "current_release_published": False,
                "registry_requests": 0,
            },
            "rds": {
                "state": "Running",
                "engine": "PostgreSQL",
                "major_version": 16,
                "high_availability": True,
                "encrypted": True,
                "ssl_enabled": True,
                "public_endpoint": False,
                "backup_enabled": True,
                "pitr_enabled": True,
                "backup_retention_days": 14,
                "max_connections": 1600,
            },
            "edge": {
                "alb_target_count": 0,
                "tls_listener_count": 0,
                "business_dns_record_count": 0,
                "traffic_request_count": 0,
            },
        },
        "hosts": [host("API-C"), host("API-F")],
        "database": {
            "metadata_session_read_only": True,
            "business_row_values_read": 0,
            "aggregate_query_count": (
                len(gate.SOURCE_ZERO_AGGREGATES)
                + len(gate.SOURCE_INFORMATIONAL_AGGREGATES)
            ),
            "applied_migration_hashes": {
                version: migration_hashes[version]
                for version in tuple(migration_hashes)[:8]
            },
            "pending_versions": list(tuple(migration_hashes)[8:]),
            "stored_migration_drift_count": 0,
            "source_preflight_complete": True,
            "source_preflight_blocker_count": 0,
            "effective_role_audit_complete": True,
            "unexpected_grant_count": 0,
            "runtime_owner_count": 0,
            "runtime_superuser_count": 0,
            "runtime_bypassrls_count": 0,
            "role_state": dict(gate.EXPECTED_ROLE_STATE),
            "source_aggregates": {
                **{name: 0 for name in gate.SOURCE_ZERO_AGGREGATES},
                **{
                    name: 0
                    for name in gate.SOURCE_INFORMATIONAL_AGGREGATES
                },
            },
        },
        "cleanup": {
            "temporary_file_count": 0,
            "temporary_credential_count": 0,
            "temporary_process_count": 0,
            "session_manager_enabled": False,
            "host_services_unchanged": True,
            "database_unchanged": True,
        },
    }


class ProductionReadonlyPreflightGateTests(unittest.TestCase):
    def test_complete_sanitized_evidence_passes(self):
        evidence = valid_evidence()
        self.assertIs(gate.validate_evidence(evidence), evidence)

    def test_secret_network_and_instance_material_fail_closed(self):
        mutations = {
            "connection": ("observed_at_utc", "postgresql://user:pass@db/name"),
            "instance": ("observed_at_utc", "i-wz9abcdefghijk"),
            "network": ("observed_at_utc", "10.1.2.3"),
            "private_key": (
                "observed_at_utc",
                "-----BEGIN PRIVATE KEY-----",
            ),
        }
        for name, (key, value) in mutations.items():
            with self.subTest(name=name):
                evidence = valid_evidence()
                evidence[key] = value
                with self.assertRaises(gate.PreflightEvidenceError):
                    gate.validate_evidence(evidence)

    def test_any_mutation_exposure_or_residue_fails(self):
        evidence = valid_evidence()
        evidence["zero_mutation"]["database_writes"] = 1
        with self.assertRaisesRegex(gate.PreflightEvidenceError, "must be zero"):
            gate.validate_evidence(evidence)

        evidence = valid_evidence()
        evidence["hosts"][0]["unexpected_listener_count"] = 1
        with self.assertRaisesRegex(gate.PreflightEvidenceError, "must be zero"):
            gate.validate_evidence(evidence)

        evidence = valid_evidence()
        evidence["cleanup"]["session_manager_enabled"] = True
        with self.assertRaisesRegex(gate.PreflightEvidenceError, "Session Manager"):
            gate.validate_evidence(evidence)

    def test_host_capacity_identity_and_runtime_are_exact(self):
        mutations = {
            "missing_host": lambda item: item["hosts"].pop(),
            "architecture": lambda item: item["hosts"][0].__setitem__(
                "architecture", "arm64"
            ),
            "disk": lambda item: item["hosts"][0].__setitem__(
                "docker_free_gib", 11.99
            ),
            "mutable": lambda item: item["hosts"][0].__setitem__(
                "mutable_image_ref_count", 1
            ),
            "digest": lambda item: item["hosts"][0]["containers"][0].__setitem__(
                "image_digest_hex", "0" * 64
            ),
            "listener": lambda item: item["hosts"][0]["containers"][0].__setitem__(
                "loopback_listener", "0.0.0.0:8000"
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                evidence = valid_evidence()
                mutate(evidence)
                with self.assertRaises(gate.PreflightEvidenceError):
                    gate.validate_evidence(evidence)

    def test_rds_backup_and_database_drift_fail_closed(self):
        mutations = {
            "rds_state": lambda item: item["cloud"]["rds"].__setitem__(
                "state", "Unavailable"
            ),
            "public_endpoint": lambda item: item["cloud"]["rds"].__setitem__(
                "public_endpoint", True
            ),
            "pitr": lambda item: item["cloud"]["rds"].__setitem__(
                "pitr_enabled", False
            ),
            "retention": lambda item: item["cloud"]["rds"].__setitem__(
                "backup_retention_days", 13
            ),
            "migration_drift": lambda item: item["database"].__setitem__(
                "stored_migration_drift_count", 1
            ),
            "source_blocker": lambda item: item["database"].__setitem__(
                "source_preflight_blocker_count", 1
            ),
            "privilege": lambda item: item["database"].__setitem__(
                "unexpected_grant_count", 1
            ),
            "tracking_history": lambda item: item["database"][
                "source_aggregates"
            ].__setitem__("tracking_noncanonical_identity_count", 1),
            "role_state": lambda item: item["database"]["role_state"].__setitem__(
                "noteai_payment", "present"
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                evidence = valid_evidence()
                mutate(evidence)
                with self.assertRaises(gate.PreflightEvidenceError):
                    gate.validate_evidence(evidence)

    def test_schema_is_exact_and_malformed_files_fail(self):
        evidence = valid_evidence()
        evidence["unexpected"] = "field"
        with self.assertRaisesRegex(gate.PreflightEvidenceError, "keys mismatch"):
            gate.validate_evidence(evidence)

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "evidence.json"
            path.write_text("{", encoding="utf-8")
            with self.assertRaisesRegex(gate.PreflightEvidenceError, "cannot load"):
                gate.load_evidence(path)

            path.write_text(json.dumps(valid_evidence()), encoding="utf-8")
            self.assertEqual(gate.load_evidence(path)["status"], "verified")

    def test_repository_migrations_are_bound_exactly(self):
        evidence = valid_evidence()
        evidence["database"]["applied_migration_hashes"]["0008"] = "0" * 64
        with self.assertRaisesRegex(
            gate.PreflightEvidenceError, "migration hashes"
        ):
            gate.validate_evidence(evidence)

        evidence = valid_evidence()
        evidence["database"]["pending_versions"] = ["0009"]
        with self.assertRaisesRegex(
            gate.PreflightEvidenceError, "pending migration set"
        ):
            gate.validate_evidence(evidence)


if __name__ == "__main__":
    unittest.main()
