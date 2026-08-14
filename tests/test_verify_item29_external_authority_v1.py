import base64
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import verify_item29_external_authority_v1 as authority


REVISION = "a" * 40
RECEIPT = "b" * 64
ACCEPTANCE = "c" * 64


def payloads():
    provider = {
        "schema": authority.PROVIDER_SCHEMA,
        "task_id": authority.TASK_ID,
        "status": "PROVIDER_TERMINAL_VERIFIED",
        "source_revision": REVISION,
        "receipt_sha256": RECEIPT,
        "terminal_acceptance_sha256": ACCEPTANCE,
        "history_key": "Name",
        "provider_client_token_readback_supported": False,
        "command_match_count": 1,
        "invocation_match_count": 1,
        "result_match_count": 1,
        "repeat_count": 1,
        "automatic_retry_count": 0,
    }
    ci = {
        "schema": authority.CI_SCHEMA,
        "task_id": authority.TASK_ID,
        "status": "EXACT_HEAD_CI_ACCEPTED",
        "repository": authority.REPOSITORY,
        "source_ref": authority.SOURCE_REF,
        "source_revision": REVISION,
        "push_conclusion": "success",
        "pull_request_conclusion": "success",
        "push_attempt": 1,
        "pull_request_attempt": 1,
    }
    return provider, ci


class Item29ExternalAuthorityTests(unittest.TestCase):
    @staticmethod
    def public_key():
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "private.pem"
            subprocess.run(
                [
                    str(authority.OPENSSL), "genpkey", "-algorithm", "RSA",
                    "-pkeyopt", "rsa_keygen_bits:2048", "-out", str(private),
                ],
                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"},
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=20,
                check=True,
            )
            return subprocess.run(
                [str(authority.OPENSSL), "pkey", "-in", str(private), "-pubout"],
                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"},
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=True,
            ).stdout

    @staticmethod
    def key_row(key, issuer):
        spki = subprocess.run(
            [
                str(authority.OPENSSL), "pkey", "-pubin", "-inform", "PEM",
                "-outform", "DER",
            ],
            input=key,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"},
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=True,
        ).stdout
        return {
            "issuer": issuer,
            "audience": "noteai-item29",
            "public_key_pem_base64": base64.b64encode(key).decode("ascii"),
            "public_key_sha256": hashlib.sha256(key).hexdigest(),
            "public_key_spki_sha256": hashlib.sha256(spki).hexdigest(),
        }

    def test_default_external_root_absence_blocks(self):
        errors, binding = authority.validate_authority_bundle(
            source_revision=REVISION,
            receipt_sha256=RECEIPT,
            terminal_acceptance_sha256=ACCEPTANCE,
        )
        self.assertTrue(errors)
        self.assertIsNone(binding)
        provider, ci = payloads()
        ci["push_attempt"] = 2
        errors, binding = authority.validate_payloads(
            provider,
            ci,
            source_revision=REVISION,
            receipt_sha256=RECEIPT,
            terminal_acceptance_sha256=ACCEPTANCE,
        )
        self.assertTrue(errors)
        self.assertIsNone(binding)

    def test_signed_numeric_bool_float_and_string_aliases_are_rejected(self):
        attacks = (
            ("bool", "provider", "repeat_count", True),
            ("float", "provider", "automatic_retry_count", 0.0),
            ("string", "ci", "push_attempt", "1"),
        )
        for label, target, field, alias in attacks:
            with self.subTest(alias=label):
                provider, ci = payloads()
                payload = provider if target == "provider" else ci
                payload[field] = alias
                errors, binding = authority.validate_payloads(
                    provider,
                    ci,
                    source_revision=REVISION,
                    receipt_sha256=RECEIPT,
                    terminal_acceptance_sha256=ACCEPTANCE,
                )
                self.assertTrue(errors)
                self.assertIsNone(binding)

    def test_exact_payload_projection_is_accepted(self):
        provider, ci = payloads()
        errors, binding = authority.validate_payloads(
            provider,
            ci,
            source_revision=REVISION,
            receipt_sha256=RECEIPT,
            terminal_acceptance_sha256=ACCEPTANCE,
        )
        self.assertEqual(errors, [])
        self.assertIsNotNone(binding)
        self.assertEqual(binding["source_revision"], REVISION)

    def test_client_token_readback_or_ci_rerun_claim_is_rejected(self):
        provider, ci = payloads()
        provider["provider_client_token_readback_supported"] = True
        errors, binding = authority.validate_payloads(
            provider,
            ci,
            source_revision=REVISION,
            receipt_sha256=RECEIPT,
            terminal_acceptance_sha256=ACCEPTANCE,
        )
        self.assertTrue(errors)
        self.assertIsNone(binding)

    def test_same_mathematical_key_with_different_pem_bytes_is_rejected(self):
        key = self.public_key()
        alternate_pem = b"\n" + key
        self.assertNotEqual(
            hashlib.sha256(key).digest(), hashlib.sha256(alternate_pem).digest()
        )
        provider = self.key_row(key, "provider-issuer")
        ci = self.key_row(alternate_pem, "ci-issuer")
        self.assertEqual(
            provider["public_key_spki_sha256"],
            ci["public_key_spki_sha256"],
        )
        with self.assertRaisesRegex(
            ValueError, "mathematical_keys_not_distinct"
        ):
            authority._decode_distinct_authority_keys(provider, ci)

    def test_distinct_spki_keys_are_accepted_by_key_decoder(self):
        provider = self.key_row(self.public_key(), "provider-issuer")
        ci = self.key_row(self.public_key(), "ci-issuer")
        decoded = authority._decode_distinct_authority_keys(provider, ci)
        self.assertNotEqual(decoded[2], decoded[3])

        changed = dict(provider)
        changed["public_key_spki_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "key_spki_identity"):
            authority._decode_key(changed, "provider")


if __name__ == "__main__":
    unittest.main()
