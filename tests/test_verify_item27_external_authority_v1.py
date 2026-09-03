import base64
import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]

from tools import verify_item27_external_authority_v1 as authority


def _projection(schema, status):
    return {
        "schema_version": 1,
        "schema": schema,
        "task_id": authority.TASK_ID,
        "status": status,
        "immutable_artifact_sha256": "a" * 64,
    }


def _envelope(kind, issuer, audience, payload):
    return {
        "authority": kind,
        "issuer": issuer,
        "audience": audience,
        "immutable_artifact_sha256": payload["immutable_artifact_sha256"],
        "payload": payload,
        "signature_base64": base64.b64encode(b"locally-invented").decode("ascii"),
    }


def _prior_manifest(*, schema_version=1, frozen_revision="0" * 40):
    provider_key = (
        b"-----BEGIN PUBLIC KEY-----\nprovider\n-----END PUBLIC KEY-----\n"
    )
    ci_key = b"-----BEGIN PUBLIC KEY-----\nci\n-----END PUBLIC KEY-----\n"
    def row(raw, issuer):
        return {
            "issuer": issuer,
            "audience": "noteai-item27",
            "public_key_pem_base64": base64.b64encode(raw).decode("ascii"),
            "public_key_pem_sha256": hashlib.sha256(raw).hexdigest(),
            "public_key_spki_sha256": "f" * 64,
        }
    return {
        "schema_version": schema_version,
        "schema": authority.PRIOR_ROOT_SCHEMA,
        "task_id": authority.TASK_ID,
        "status": "INDEPENDENTLY_INSTALLED_BEFORE_SOURCE",
        "repository": authority.REPOSITORY,
        "source_ref": authority.SOURCE_REF,
        "frozen_before_revision": frozen_revision,
        "provider": row(provider_key, "provider-issuer"),
        "ci": row(ci_key, "ci-issuer"),
    }


class Item27ExternalAuthorityTests(unittest.TestCase):
    SOURCE_REVISION = "1" * 40

    def test_missing_prior_root_is_an_unconditional_block(self):
        errors, projection = authority.validate_authority_bundle(
            {}, self.SOURCE_REVISION
        )
        self.assertTrue(any(
            "independent prior authority unavailable" in error
            for error in errors
        ))
        self.assertIsNone(projection)

    def test_local_json_and_local_hashes_cannot_replace_detached_authority(self):
        provider = _projection(
            authority.PROVIDER_PAYLOAD_SCHEMA, "PROVIDER_EXPORT_VERIFIED"
        )
        ci = _projection(
            authority.CI_PAYLOAD_SCHEMA, "ALL_EXACT_REVISIONS_CI_VERIFIED"
        )
        bundle = {
            "schema_version": 1,
            "schema": authority.BUNDLE_SCHEMA,
            "task_id": authority.TASK_ID,
            "status": "EXTERNALLY_ATTESTED",
            "provider": _envelope(
                "ALIYUN_TRUSTED_CONNECTOR_SIGNED_EXPORT",
                "provider-issuer", "noteai-item27", provider,
            ),
            "ci": _envelope(
                "GITHUB_TRUSTED_API_SIGNED_EXPORT",
                "ci-issuer", "noteai-item27", ci,
            ),
        }
        with mock.patch.object(
            authority, "_load_prior_authority_roots", return_value={
                "provider_key": b"prior-provider-key",
                "provider_issuer": "provider-issuer",
                "provider_audience": "noteai-item27",
                "ci_key": b"prior-ci-key",
                "ci_issuer": "ci-issuer",
                "ci_audience": "noteai-item27",
            },
        ), mock.patch.object(
            authority, "_load_external_bundle", return_value=bundle
        ), mock.patch.object(
            authority, "_verify_signature", return_value=False
        ):
            errors, projection = authority.validate_authority_bundle(
                provider, self.SOURCE_REVISION
            )
        self.assertTrue(any("signature invalid" in error for error in errors))
        self.assertIsNone(projection)

    def test_user_owned_local_manifest_cannot_become_a_trust_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "locally-selected-root.json"
            manifest.write_text("{}\n", encoding="ascii")
            with mock.patch.object(
                authority, "PRIOR_AUTHORITY_ROOT_MANIFEST_PATH", manifest
            ), self.assertRaisesRegex(ValueError, "root-owned"):
                authority._load_prior_authority_roots(
                    self.SOURCE_REVISION, root=ROOT
                )

    def test_recursive_type_aliases_are_rejected(self):
        provider = _projection(
            authority.PROVIDER_PAYLOAD_SCHEMA, "PROVIDER_EXPORT_VERIFIED"
        )
        ci = _projection(
            authority.CI_PAYLOAD_SCHEMA, "ALL_EXACT_REVISIONS_CI_VERIFIED"
        )
        bundle = {
            "schema_version": True,
            "schema": authority.BUNDLE_SCHEMA,
            "task_id": authority.TASK_ID,
            "status": "EXTERNALLY_ATTESTED",
            "provider": _envelope(
                "ALIYUN_TRUSTED_CONNECTOR_SIGNED_EXPORT",
                "provider-issuer", "noteai-item27", provider,
            ),
            "ci": _envelope(
                "GITHUB_TRUSTED_API_SIGNED_EXPORT",
                "ci-issuer", "noteai-item27", ci,
            ),
        }
        with mock.patch.object(
            authority, "_load_prior_authority_roots", return_value={
                "provider_key": b"prior-provider-key",
                "provider_issuer": "provider-issuer",
                "provider_audience": "noteai-item27",
                "ci_key": b"prior-ci-key",
                "ci_issuer": "ci-issuer",
                "ci_audience": "noteai-item27",
            },
        ), mock.patch.object(
            authority, "_load_external_bundle", return_value=bundle
        ):
            errors, projection = authority.validate_authority_bundle(
                provider, self.SOURCE_REVISION
            )
        self.assertEqual(errors, ["Item27 external authority bundle fields mismatch"])
        self.assertIsNone(projection)

        prior = _prior_manifest(schema_version=True)
        with mock.patch.object(
            authority, "_read_stable_root_owned",
            return_value=authority._canonical(prior),
        ), mock.patch.object(
            authority, "_git_is_ancestor", return_value=True
        ), self.assertRaisesRegex(ValueError, "did not predate source"):
            authority._load_prior_authority_roots(
                self.SOURCE_REVISION, root=ROOT
            )

    def test_prior_root_must_be_frozen_before_source_revision(self):
        prior = _prior_manifest(frozen_revision=self.SOURCE_REVISION)
        with mock.patch.object(
            authority, "_read_stable_root_owned",
            return_value=authority._canonical(prior),
        ), mock.patch.object(
            authority, "_git_is_ancestor", return_value=True
        ), self.assertRaisesRegex(ValueError, "did not predate source"):
            authority._load_prior_authority_roots(
                self.SOURCE_REVISION, root=ROOT
            )

    def test_openssl_receives_stable_key_bytes_via_private_temp_file(self):
        observed = {}
        class Result:
            returncode = 0
        def run(command, **kwargs):
            self.assertEqual(command[0], "/usr/bin/openssl")
            self.assertEqual(kwargs["env"], authority.TRUSTED_TOOL_ENV)
            key_path = Path(command[command.index("-verify") + 1])
            signature_path = Path(command[command.index("-signature") + 1])
            payload_path = Path(command[-1])
            observed.update({
                "key": key_path.read_bytes(),
                "signature": signature_path.read_bytes(),
                "payload": payload_path.read_bytes(),
                "key_path": key_path,
            })
            return Result()
        with mock.patch.object(authority.subprocess, "run", side_effect=run):
            self.assertTrue(authority._verify_signature(
                b"payload", b"signature", b"stable-prior-key"
            ))
        self.assertEqual(observed["key"], b"stable-prior-key")
        self.assertEqual(observed["signature"], b"signature")
        self.assertEqual(observed["payload"], b"payload")
        self.assertFalse(observed["key_path"].exists())

    def test_same_mathematical_key_with_different_pem_bytes_is_not_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            private_key = base / "key.pem"
            public_key = base / "key.pub.pem"
            subprocess.run(
                [
                    "/usr/bin/openssl", "genpkey", "-algorithm", "RSA",
                    "-pkeyopt", "rsa_keygen_bits:2048", "-out", str(private_key),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"},
            )
            subprocess.run(
                [
                    "/usr/bin/openssl", "pkey", "-in", str(private_key),
                    "-pubout", "-out", str(public_key),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"},
            )
            pem = public_key.read_bytes()
        alternate_pem = pem.replace(b"\n", b"\r\n")
        spki_digest = hashlib.sha256(
            authority._spki_der(pem, "fixture")
        ).hexdigest()

        def row(raw, issuer):
            return {
                "issuer": issuer,
                "audience": "noteai-item27",
                "public_key_pem_base64": base64.b64encode(raw).decode("ascii"),
                "public_key_pem_sha256": hashlib.sha256(raw).hexdigest(),
                "public_key_spki_sha256": spki_digest,
            }

        manifest = {
            "schema_version": 1,
            "schema": authority.PRIOR_ROOT_SCHEMA,
            "task_id": authority.TASK_ID,
            "status": "INDEPENDENTLY_INSTALLED_BEFORE_SOURCE",
            "repository": authority.REPOSITORY,
            "source_ref": authority.SOURCE_REF,
            "frozen_before_revision": "0" * 40,
            "provider": row(pem, "provider-issuer"),
            "ci": row(alternate_pem, "ci-issuer"),
        }
        with mock.patch.object(
            authority, "_read_stable_root_owned",
            return_value=authority._canonical(manifest),
        ), mock.patch.object(
            authority, "_git_is_ancestor", return_value=True
        ), self.assertRaisesRegex(ValueError, "must be independent"):
            authority._load_prior_authority_roots(
                self.SOURCE_REVISION, root=ROOT
            )

    def test_git_uses_absolute_binary_minimal_environment_and_disables_replacements(self):
        class Result:
            returncode = 0

        with mock.patch.object(
            authority.subprocess, "run", return_value=Result()
        ) as run:
            self.assertTrue(authority._git_is_ancestor(
                "0" * 40, "1" * 40, root=ROOT
            ))
        command = run.call_args.args[0]
        self.assertEqual(command[0], "/usr/bin/git")
        self.assertIn("--no-replace-objects", command)
        self.assertEqual(run.call_args.kwargs["env"], authority.TRUSTED_TOOL_ENV)
        self.assertEqual(
            authority.TRUSTED_TOOL_ENV["GIT_NO_REPLACE_OBJECTS"], "1"
        )


if __name__ == "__main__":
    unittest.main()
