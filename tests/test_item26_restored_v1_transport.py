import base64
import copy
import gzip
import hashlib
import json
from pathlib import Path
import re
import secrets
import unittest

from tools import render_item26_restored_v1_transport as restored


ROOT = Path(__file__).resolve().parents[1]


def envelope():
    value = {
        "algorithm": "RSA-OAEP-SHA256+AES-256-GCM",
        "ciphertext": base64.b64encode(b"x" * 16).decode("ascii"),
        "nonce": base64.b64encode(b"n" * 12).decode("ascii"),
        "schema_version": 1,
        "wrapped_key": base64.b64encode(b"w" * 384).decode("ascii"),
    }
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")


class Item26RestoredV1TransportTests(unittest.TestCase):
    def render(self):
        return restored._render_item26_restored_v1_transport_for_test(
            envelope(),
            "a" * 64,
            "b" * 64,
            100,
            "c" * 64,
            "d" * 64,
            "e" * 64,
            "f" * 64,
            gzip_compressor=lambda body: gzip.compress(body, 9, mtime=0),
        )

    def test_templates_are_exact_and_synthetic_render_is_bounded(self):
        rendered = self.render()
        self.assertLessEqual(
            rendered["sizing"]["capture_command_content"]["bytes"],
            restored.MAX_COMMAND_CONTENT_BYTES,
        )
        for name, identity in restored.TEMPLATE_IDENTITIES.items():
            body = restored.TEMPLATE_PATHS[name].read_bytes()
            self.assertEqual(len(body), identity["bytes"])
            self.assertEqual(hashlib.sha256(body).hexdigest(), identity["sha256"])

    def test_random_high_entropy_bindings_remain_bounded(self):
        for _ in range(8):
            value = {
                "algorithm": "RSA-OAEP-SHA256+AES-256-GCM",
                "ciphertext": base64.b64encode(secrets.token_bytes(1024)).decode(),
                "nonce": base64.b64encode(secrets.token_bytes(12)).decode(),
                "schema_version": 1,
                "wrapped_key": base64.b64encode(secrets.token_bytes(384)).decode(),
            }
            control = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
            hashes = [secrets.token_hex(32) for _ in range(6)]
            rendered = restored._render_item26_restored_v1_transport_for_test(
                control,
                hashes[0],
                hashes[1],
                secrets.randbelow(restored.MAX_SOURCE_MANIFEST_BYTES) + 1,
                hashes[2],
                hashes[3],
                hashes[4],
                hashes[5],
                gzip_compressor=lambda body: gzip.compress(body, 9, mtime=0),
            )
            self.assertLessEqual(
                rendered["sizing"]["capture_command_content"]["bytes"],
                restored.MAX_COMMAND_CONTENT_BYTES,
            )

    def test_persistent_write_once_and_read_only_guards_are_present(self):
        capture = (ROOT / ".codex/item26-restored-capture-v1.template.sh").read_text()
        executor = (ROOT / ".codex/item26-restored-capture-executor-v1.template.sh").read_text()
        self.assertIn("/var/lib/noteai/item26-restored-v1", capture)
        self.assertIn(restored.TRANSFER_PATH, executor)
        self.assertIn("SET LOCAL search_path=pg_catalog,public", capture)
        self.assertIn("current_setting('search_path')='pg_catalog, public'", capture)
        self.assertIn("os.O_EXCL|os.O_NOFOLLOW", capture)
        self.assertIn("ITEM26_RESTORED_SUCCESSOR_V1_ATTEMPT", capture)
        self.assertIn(
            "de7dd59a303a5333f60de5c07d5747904b61de41109ff539f6c50f537707c7cd",
            capture,
        )
        self.assertIn("reconciliation.json", capture)
        self.assertIn("os.fsync(dirfd)", capture)
        self.assertIn("--cap-drop ALL --cap-add DAC_READ_SEARCH", capture)
        self.assertIn("verify_restore(source,restored)", capture)
        self.assertEqual(capture.count("/usr/sbin/ss -Htan"), 2)
        self.assertNotRegex(capture, r"(?<![/A-Za-z0-9_])ss -Htan")
        self.assertNotIn("cleanup_task", capture)

    def test_retained_transfer_is_ssl_corrected_only_in_memory(self):
        rendered = self.render()
        raw = rendered["artifacts"]["capture"]
        executor = rendered["artifacts"]["executor"].decode("ascii")
        source = executor.split("def ssl_corrected(raw):\n", 1)[1].split(
            "\ndef no_duplicates", 1
        )[0]

        class PatchFailure(Exception):
            def __init__(self, phase, spawned=False, transfer="UNVERIFIED"):
                super().__init__(phase)
                self.phase = phase
                self.spawned = spawned
                self.transfer = transfer

        expected = restored._ssl_corrected_capture(raw)
        namespace = {
            "Failure": PatchFailure,
            "PATCHED_RAW_BYTES": len(expected),
            "PATCHED_RAW_SHA256": hashlib.sha256(expected).hexdigest(),
            "hashlib": hashlib,
        }
        exec("def ssl_corrected(raw):\n" + source, namespace)
        corrected = namespace["ssl_corrected"](raw)

        self.assertEqual(
            hashlib.sha256(raw).hexdigest(),
            rendered["sizing"]["capture"]["sha256"],
        )
        self.assertEqual(
            hashlib.sha256(rendered["artifacts"]["capture_gzip"]).hexdigest(),
            rendered["sizing"]["capture_gzip"]["sha256"],
        )
        self.assertNotEqual(corrected, raw)
        self.assertIn(b"capture-ssl-corrected-attempted-v1", corrected)
        self.assertIn(b"capture-ssl-corrected-task-v1", corrected)
        self.assertIn(b"restored-manifest-ssl-corrected-v1", corrected)
        self.assertNotIn(b"capture-successor-attempted-v1", corrected)
        self.assertIn(
            b'query.get("sslmode")!="require"',
            corrected,
        )
        self.assertIn(
            b'values.update({**query,"sslmode":"disable","channel_binding":"disable"})',
            corrected,
        )
        self.assertIn(b"ITEM26_RESTORED_CORRECTED_V1_ATTEMPT\\n", corrected)
        self.assertIn(
            b"8d4960991e090cf39ffe81fb91d8608117a5d1ee25c39915192d2662056581c6",
            corrected,
        )
        with self.assertRaises(PatchFailure):
            namespace["ssl_corrected"](corrected)

    def test_wrapper_rejects_extra_terminal_fields(self):
        template = restored.CAPTURE_WRAPPER_TEMPLATE.decode("ascii")
        source = "import json,re\n" + template.split("started=False\n", 1)[1].split(
            "try:\n    if os.geteuid", 1
        )[0]
        namespace = {"started": False}
        exec(source, namespace)
        value = namespace["fixed"]()
        self.assertTrue(namespace["valid"](value, 3))
        value["unexpected"] = "secret-boundary-bypass"
        self.assertFalse(namespace["valid"](value, 3))

    def test_executor_rejects_extra_terminal_fields(self):
        template = (
            ROOT / ".codex/item26-restored-capture-executor-v1.template.sh"
        ).read_text()
        source = "HEX64=" + template.split("HEX64=", 1)[1].split(
            "def run(raw):", 1
        )[0]
        namespace = {"json": json, "re": re}
        exec(source, namespace)
        value = {
            "NOTEAI_ITEM26_RESTORED_CAPTURE": "FAIL",
            "automatic_retry_allowed": False,
            "database_attempted_state": "NO",
            "incident_class": "PRE_CONNECT",
            "new_capture_allowed": False,
            "phase": "preflight",
            "same_invocation_replay_allowed": False,
        }
        self.assertTrue(namespace["exact_contract"](value, 3))
        value["unexpected"] = "secret-boundary-bypass"
        self.assertFalse(namespace["exact_contract"](value, 3))

    def test_capture_specific_driver_phase_is_accepted_by_both_outer_layers(self):
        capture = (
            ROOT / ".codex/item26-restored-capture-v1.template.sh"
        ).read_text()
        self.assertIn('print("driver_"+row["code"])', capture)
        self.assertIn('"OperationalError"', capture)
        executor = (
            ROOT / ".codex/item26-restored-capture-executor-v1.template.sh"
        ).read_text()
        source = "HEX64=" + executor.split("HEX64=", 1)[1].split(
            "def run(raw):", 1
        )[0]
        namespace = {"json": json, "re": re}
        exec(source, namespace)
        terminal = {
            "NOTEAI_ITEM26_RESTORED_CAPTURE": "FAIL",
            "automatic_retry_allowed": False,
            "database_attempted_state": "NO",
            "incident_class": "PRE_CONNECT",
            "new_capture_allowed": False,
            "phase": "driver_backend",
            "same_invocation_replay_allowed": False,
        }
        self.assertTrue(namespace["exact_contract"](terminal, 3))
        wrapper = restored.CAPTURE_WRAPPER_TEMPLATE.decode("ascii")
        wrapper_source = "import json,re\n" + wrapper.split(
            "started=False\n", 1
        )[1].split("try:\n    if os.geteuid", 1)[0]
        wrapper_namespace = {"started": False}
        exec(wrapper_source, wrapper_namespace)
        self.assertTrue(wrapper_namespace["valid"](terminal, 3))

    def test_summary_cross_links_control_envelope(self):
        rendered = self.render()
        summary = copy.deepcopy(rendered["sizing"])
        control = envelope()
        summary["production_provenance"] = restored._production_provenance()
        summary["public_bindings"] = {
            "builder_identity_sha256": "b" * 64,
            "control_envelope_bytes": len(control),
            "control_envelope_sha256": hashlib.sha256(control).hexdigest(),
            "recipient_public_key_sha256": "a" * 64,
            "restored_topology_sha256": "e" * 64,
            "source_manifest_bytes": 100,
            "source_manifest_file_sha256": "c" * 64,
            "source_manifest_sha256": "d" * 64,
            "storage_config_sha256": "f" * 64,
        }
        restored.canonical_summary(summary)
        summary["public_bindings"]["control_envelope_bytes"] += 1
        with self.assertRaisesRegex(restored.RenderError, "summary_contract"):
            restored.canonical_summary(summary)


if __name__ == "__main__":
    unittest.main()
