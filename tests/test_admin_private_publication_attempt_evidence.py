from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_admin_private_publication_attempt_evidence as verifier  # noqa: E402


def iter_leaf_paths(value, path=()):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from iter_leaf_paths(child, path + (key,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_leaf_paths(child, path + (index,))
    else:
        yield path, value


def iter_mapping_paths(value, path=()):
    if isinstance(value, dict):
        yield path
        for key, child in value.items():
            yield from iter_mapping_paths(child, path + (key,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_mapping_paths(child, path + (index,))


def resolve_path(value, path):
    current = value
    for part in path:
        current = current[part]
    return current


def replace_leaf(value, path, replacement) -> None:
    parent = resolve_path(value, path[:-1])
    parent[path[-1]] = replacement


def mutate_scalar(value):
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    if value is None:
        return "tampered"
    if isinstance(value, str):
        return f"{value}__tampered"
    raise AssertionError(f"unsupported evidence scalar: {type(value)!r}")


class AdminPrivatePublicationAttemptEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(verifier.EVIDENCE_PATH.read_text(encoding="utf-8"))

    def test_exact_evidence_passes(self) -> None:
        self.assertEqual(verifier.validate_evidence(copy.deepcopy(self.payload)), [])

    def test_registry_push_fails_closed(self) -> None:
        broken = copy.deepcopy(self.payload)
        broken["publication"]["registry_push_count"] = 1
        self.assertIn(
            "publication activity drift: registry_push_count",
            verifier.validate_evidence(broken),
        )

    def test_false_readiness_credit_fails_closed(self) -> None:
        broken = copy.deepcopy(self.payload)
        broken["decision"]["readiness_credit_awarded"] = True
        self.assertIn(
            "decision falsely advanced: readiness_credit_awarded",
            verifier.validate_evidence(broken),
        )

    def test_builder_not_stopped_fails_closed(self) -> None:
        broken = copy.deepcopy(self.payload)
        broken["cleanup"]["builder_stopped"] = False
        self.assertIn("builder not stopped", verifier.validate_evidence(broken))

    def test_every_scalar_leaf_is_bound_by_canonical_hash(self) -> None:
        for path, value in iter_leaf_paths(self.payload):
            with self.subTest(path=path):
                broken = copy.deepcopy(self.payload)
                replace_leaf(broken, path, mutate_scalar(value))
                self.assertIn(
                    "canonical evidence hash mismatch",
                    verifier.validate_evidence(broken),
                )

    def test_unexpected_key_in_every_mapping_fails_closed(self) -> None:
        for path in iter_mapping_paths(self.payload):
            with self.subTest(path=path):
                broken = copy.deepcopy(self.payload)
                resolve_path(broken, path)["__unexpected_evidence_key__"] = True
                self.assertIn(
                    "canonical evidence hash mismatch",
                    verifier.validate_evidence(broken),
                )

    def test_authorization_window_mismatch_fails_semantically(self) -> None:
        broken = copy.deepcopy(self.payload)
        broken["authorization"]["authorization_deadline"] = (
            "2026-07-31T01:00:08+08:00"
        )
        self.assertIn(
            "authorization window does not match runtime cap",
            verifier.validate_evidence(broken),
        )

    def test_stop_after_deadline_fails_semantically(self) -> None:
        broken = copy.deepcopy(self.payload)
        broken["cleanup"]["builder_stop_observed_before"] = (
            "2026-07-31T01:00:00+08:00"
        )
        self.assertIn(
            "builder stop timestamp exceeded authorization deadline",
            verifier.validate_evidence(broken),
        )

    def test_sensitive_string_values_are_rejected_without_echo(self) -> None:
        forbidden_examples = (
            "https://builder.example.invalid/path",
            "203.0.113.10",
            "LTAI0000000000000000",
            "postgresql://user:password@example.invalid/database",
            "i-example123456",
        )
        for value in forbidden_examples:
            with self.subTest(value_type=value.split(":", 1)[0]):
                broken = copy.deepcopy(self.payload)
                broken["diagnostic_value"] = value
                self.assertIn(
                    "receipt contains a forbidden sensitive value",
                    verifier.validate_evidence(broken),
                )

    def test_duplicate_key_cannot_hide_sensitive_raw_value(self) -> None:
        raw = verifier.EVIDENCE_PATH.read_text(encoding="utf-8")
        exact_task = (
            '"task": "PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001",'
        )
        duplicate = (
            '"task": "postgresql://synthetic:negative@example.invalid/database",\n'
            f"  {exact_task}"
        )
        tampered = raw.replace(exact_task, duplicate, 1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate-key.json"
            path.write_text(tampered, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate JSON key: task"):
                verifier.load_evidence(path)


if __name__ == "__main__":
    unittest.main()
