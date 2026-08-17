import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import build_item26_manual_cost_stop_activation_receipt_v3 as receipt_builder  # noqa: E402
import build_item26_manual_cost_stop_authority_root_v2 as root_builder  # noqa: E402
import install_item26_manual_cost_stop_runtime_v3 as installer  # noqa: E402
import verify_item26_manual_cost_stop_authority_v2 as authority  # noqa: E402
from tests.test_build_item26_manual_cost_stop_activation_receipt_v3 import (  # noqa: E402
    ci_row,
)
from tests.test_verify_item26_manual_cost_stop_authority_v2 import (  # noqa: E402
    SyntheticRsa3072Keys,
)


CONTROL_REVISION = "e" * 40


class Item26RuntimeInstallerV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.keys = SyntheticRsa3072Keys()
        cls.root_raw = root_builder.build_authority_root(cls.keys.public)
        cls.root_hash = authority._sha(cls.root_raw)
        cls.control_ci = {
            "push": {
                **ci_row(701, "push", "2026-08-17T05:20:00Z"),
                "head_sha": CONTROL_REVISION,
            },
            "pull_request": {
                **ci_row(
                    702,
                    "pull_request",
                    "2026-08-17T05:21:00Z",
                ),
                "head_sha": CONTROL_REVISION,
            },
        }
        cls.git_raw = {
            ref: ("synthetic " + ref + "\n").encode("ascii")
            for ref in authority.CONTROL_SOURCE_REFS
        }
        cls.git_raw[authority.PUBLIC_ROOT_REF] = cls.root_raw
        cls.git_raw[authority.CONTRACT_REF] = (
            ROOT / authority.CONTRACT_REF
        ).read_bytes()
        cls.git_raw[authority.VERIFIER_REF] = (
            ROOT / authority.VERIFIER_REF
        ).read_bytes()
        cls.git_raw[installer.INSTALLER_REF] = (
            ROOT / installer.INSTALLER_REF
        ).read_bytes()
        cls.source_bindings = {}
        for index, ref in enumerate(authority.CONTROL_SOURCE_REFS, 1):
            cls.source_bindings[ref] = {
                "git_blob_oid": f"{index:x}" * 40,
                "file_sha256": hashlib.sha256(cls.git_raw[ref]).hexdigest(),
            }
        with tempfile.TemporaryDirectory(
            prefix=".item26-installer-receipt-build-",
            dir=ROOT,
        ) as temporary:
            scratch = Path(temporary)
            scratch.chmod(0o700)

            def git_record(_revision, ref, *, root):
                del _revision, root
                raw = cls.git_raw[ref]
                binding = cls.source_bindings[ref]
                return {
                    "raw": raw,
                    "git_blob_oid": binding["git_blob_oid"],
                    "git_blob_sha256": binding["file_sha256"],
                    "file_sha256": binding["file_sha256"],
                }

            with mock.patch.object(
                authority,
                "AUTHORITY_V2_FINALIZED",
                True,
            ), mock.patch.object(
                authority,
                "EXPECTED_ROOT_SHA",
                cls.root_hash,
            ), mock.patch.object(
                authority,
                "EXPECTED_AUTHORITY_ROOT_FILE_SHA256",
                cls.root_hash,
            ), mock.patch.object(
                authority,
                "revision_is_strict_ancestor",
                return_value=True,
            ), mock.patch.object(
                authority,
                "_validate_ledger_git_bindings",
            ), mock.patch.object(
                authority,
                "_git_blob_record",
                side_effect=git_record,
            ), cls.keys.builder_patches(), cls.keys.verification_patcher():
                cls.receipt_raw = receipt_builder.build_activation_receipt(
                    root_raw=cls.root_raw,
                    local_ci_observation_private_key_pem=(
                        cls.keys.signing_handles["local_ci_observation"]
                    ),
                    control_revision=CONTROL_REVISION,
                    control_ci=cls.control_ci,
                    control_source_blobs=cls.source_bindings,
                    activated_at_utc="2026-08-17T05:22:00Z",
                    scratch_directory=scratch,
                )

    @classmethod
    def tearDownClass(cls):
        cls.keys.cleanup()

    def git_record(self, _revision, ref, *, root):
        del root
        raw = self.git_raw[ref]
        binding = self.source_bindings[ref]
        return {
            "raw": raw,
            "git_blob_oid": binding["git_blob_oid"],
            "git_blob_sha256": binding["file_sha256"],
            "file_sha256": binding["file_sha256"],
        }

    def patches(self, *, git_side_effect=None):
        return (
            mock.patch.object(authority, "AUTHORITY_V2_FINALIZED", True),
            mock.patch.object(authority, "EXPECTED_ROOT_SHA", self.root_hash),
            mock.patch.object(
                authority,
                "EXPECTED_AUTHORITY_ROOT_FILE_SHA256",
                self.root_hash,
            ),
            mock.patch.object(
                authority,
                "revision_is_strict_ancestor",
                return_value=True,
            ),
            mock.patch.object(
                authority,
                "_validate_ledger_git_bindings",
            ),
            mock.patch.object(
                authority,
                "_git_blob_record",
                side_effect=git_side_effect or self.git_record,
            ),
            self.keys.verification_patcher(),
            mock.patch.object(installer.os, "geteuid", return_value=0),
            mock.patch.object(
                installer,
                "_validate_execution_boundary",
                return_value={
                    installer.INSTALLER_REF: self.git_raw[
                        installer.INSTALLER_REF
                    ],
                    authority.VERIFIER_REF: self.git_raw[
                        authority.VERIFIER_REF
                    ],
                },
            ),
            mock.patch.object(
                installer,
                "_file_owner_uid",
                return_value=os.getuid(),
            ),
            mock.patch.object(installer, "_validate_parent_chain"),
        )

    def make_custody(self, base):
        custody_directory = base / "custody"
        custody_directory.mkdir(mode=0o700)
        material = {}
        for name in installer.CUSTODY_ROLE_FILES:
            raw = ("fixture-role-material:" + name + "\n").encode("ascii")
            path = custody_directory / name
            path.write_bytes(raw)
            path.chmod(0o600)
            material[name] = raw
        return custody_directory, material

    def invoke(
        self,
        base,
        *,
        receipt_raw=None,
        git_side_effect=None,
        create_custody=True,
    ):
        authority_directory = base / "authority"
        runtime_directory = base / "runtime"
        journal_directory = base / "journal"
        custody_directory = base / "custody"
        if create_custody and not custody_directory.exists():
            self.make_custody(base)
        patchers = self.patches(git_side_effect=git_side_effect)
        for patcher in patchers:
            patcher.start()
        try:
            result = installer.install_runtime(
                control_revision=CONTROL_REVISION,
                receipt_raw=(
                    self.receipt_raw if receipt_raw is None else receipt_raw
                ),
                authority_directory=authority_directory,
                runtime_directory=runtime_directory,
                journal_directory=journal_directory,
                custody_directory=custody_directory,
            )
        finally:
            for patcher in reversed(patchers):
                patcher.stop()
        return (
            result,
            authority_directory,
            runtime_directory,
            journal_directory,
            custody_directory,
        )

    def make_execution_staging(self, base):
        staging = base / "staging"
        staging.mkdir(mode=0o700)
        installer_path = staging / Path(installer.INSTALLER_REF).name
        authority_path = staging / Path(authority.VERIFIER_REF).name
        installer_path.write_bytes(self.git_raw[installer.INSTALLER_REF])
        authority_path.write_bytes(self.git_raw[authority.VERIFIER_REF])
        installer_path.chmod(0o600)
        authority_path.chmod(0o600)
        return staging, installer_path, authority_path

    def validate_synthetic_staging(
        self,
        staging,
        installer_path,
        authority_path,
        *,
        accept_current_owner=True,
    ):
        patchers = [
            mock.patch.object(installer, "EXECUTION_DIRECTORY", staging),
            mock.patch.object(installer, "__file__", str(installer_path)),
            mock.patch.object(authority, "__file__", str(authority_path)),
            mock.patch.object(installer, "_validate_execution_flags"),
            mock.patch.object(
                installer,
                "_validate_execution_parent_chain",
            ),
        ]
        if accept_current_owner:
            patchers.append(
                mock.patch.object(
                    installer,
                    "_execution_owner_uid",
                    return_value=os.getuid(),
                )
            )
        for patcher in patchers:
            patcher.start()
        try:
            return installer._validate_execution_boundary()
        finally:
            for patcher in reversed(patchers):
                patcher.stop()

    def test_installs_exact_new_root_runtime_and_empty_journal(self):
        with tempfile.TemporaryDirectory(
            prefix=".item26-installer-positive-",
            dir=ROOT,
        ) as temporary:
            base = Path(temporary)
            base.chmod(0o700)
            result, authority_dir, runtime_dir, journal_dir, custody_dir = (
                self.invoke(base)
            )
            self.assertEqual(result["status"], "ROOT_V2_RUNTIME_V3_INSTALLED")
            self.assertEqual(result["private_key_read_count"], 0)
            self.assertEqual(result["private_key_write_count"], 0)
            self.assertEqual(result["cloud_call_count"], 0)
            self.assertEqual(result["database_connection_count"], 0)
            self.assertEqual(
                set(path.name for path in custody_dir.iterdir()),
                set(installer.CUSTODY_ROLE_FILES),
            )
            self.assertEqual(stat.S_IMODE(custody_dir.stat().st_mode), 0o700)
            for path in custody_dir.iterdir():
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertEqual(path.stat().st_nlink, 1)
                self.assertEqual(
                    path.read_bytes(),
                    ("fixture-role-material:" + path.name + "\n").encode(
                        "ascii"
                    ),
                )
            self.assertEqual(
                set(path.name for path in authority_dir.iterdir()),
                {authority.ROOT_FILE},
            )
            self.assertEqual(
                set(path.name for path in runtime_dir.iterdir()),
                set(authority.RUNTIME_INVENTORY),
            )
            self.assertEqual(list(journal_dir.iterdir()), [])
            self.assertEqual(
                (authority_dir / authority.ROOT_FILE).read_bytes(),
                self.root_raw,
            )
            self.assertEqual(
                (runtime_dir / authority.ACTIVATION_RECEIPT_FILE).read_bytes(),
                self.receipt_raw,
            )
            for directory in (authority_dir, runtime_dir, journal_dir):
                self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
            for path in tuple(authority_dir.iterdir()) + tuple(runtime_dir.iterdir()):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertEqual(path.stat().st_nlink, 1)

    def test_module_has_no_v1_cloud_database_or_network_dependency(self):
        tree = ast.parse(
            (ROOT / installer.INSTALLER_REF).read_text(encoding="utf-8")
        )
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        forbidden = (
            "boto",
            "http",
            "psycopg",
            "requests",
            "sqlite",
            "subprocess",
        )
        self.assertFalse(any("_v1" in name for name in imported))
        self.assertFalse(
            any(name.startswith(forbidden) for name in imported)
        )

    def test_crash_residue_extra_symlink_hardlink_and_mode_reject_unchanged(self):
        for kind in ("partial", "extra", "symlink", "hardlink", "mode"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(
                prefix=".item26-installer-preexisting-",
                dir=ROOT,
            ) as temporary:
                base = Path(temporary)
                base.chmod(0o700)
                authority_target = base / "authority"
                if kind == "symlink":
                    outside = base / "outside"
                    outside.mkdir(mode=0o700)
                    authority_target.symlink_to(outside, target_is_directory=True)
                else:
                    authority_target.mkdir(mode=0o700)
                    if kind == "partial":
                        marker = authority_target / authority.ROOT_FILE
                        marker.write_bytes(b"crash residue\n")
                    elif kind == "extra":
                        marker = authority_target / "extra"
                        marker.write_bytes(b"existing extra\n")
                    elif kind == "hardlink":
                        outside = base / "outside-file"
                        outside.write_bytes(b"hardlinked residue\n")
                        marker = authority_target / authority.ROOT_FILE
                        os.link(outside, marker)
                    else:
                        marker = authority_target / authority.ROOT_FILE
                        marker.write_bytes(b"wrong mode residue\n")
                        marker.chmod(0o644)
                        authority_target.chmod(0o755)
                    original = marker.read_bytes()
                    original_mode = stat.S_IMODE(marker.stat().st_mode)
                    original_links = marker.stat().st_nlink
                with self.assertRaisesRegex(
                    installer.InstallError,
                    "target_not_new",
                ):
                    self.invoke(base)
                self.assertFalse((base / "runtime").exists())
                self.assertFalse((base / "journal").exists())
                self.assertTrue(authority_target.exists())
                if kind == "symlink":
                    self.assertTrue(authority_target.is_symlink())
                    self.assertEqual(os.readlink(authority_target), str(outside))
                else:
                    self.assertEqual(marker.read_bytes(), original)
                    self.assertEqual(
                        stat.S_IMODE(marker.stat().st_mode),
                        original_mode,
                    )
                    self.assertEqual(marker.stat().st_nlink, original_links)

    def test_partial_install_failure_rolls_back_only_new_inventory(self):
        with tempfile.TemporaryDirectory(
            prefix=".item26-installer-rollback-",
            dir=ROOT,
        ) as temporary:
            base = Path(temporary)
            base.chmod(0o700)
            original = installer._write_exclusive
            calls = 0

            def fail_second(directory_fd, name, raw):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise installer.InstallError("synthetic_write_failure")
                return original(directory_fd, name, raw)

            with mock.patch.object(
                installer,
                "_write_exclusive",
                side_effect=fail_second,
            ), self.assertRaisesRegex(
                installer.InstallError,
                "synthetic_write_failure",
            ):
                self.invoke(base)
            self.assertFalse((base / "authority").exists())
            self.assertFalse((base / "runtime").exists())
            self.assertFalse((base / "journal").exists())

    def test_source_drift_is_rejected_before_directory_preflight(self):
        drifted_raw = {**self.git_raw, authority.COLLECTOR_REF: b"drifted\n"}

        def drifted(_revision, ref, *, root):
            del root
            raw = drifted_raw[ref]
            digest = hashlib.sha256(raw).hexdigest()
            return {
                "raw": raw,
                "git_blob_oid": self.source_bindings[ref]["git_blob_oid"],
                "git_blob_sha256": digest,
                "file_sha256": digest,
            }

        with tempfile.TemporaryDirectory(
            prefix=".item26-installer-drift-",
            dir=ROOT,
        ) as temporary:
            base = Path(temporary)
            base.chmod(0o700)
            with mock.patch.object(
                installer,
                "_open_absent_target_parent",
                side_effect=AssertionError("directory preflight must not start"),
            ), self.assertRaises(ValueError):
                self.invoke(base, git_side_effect=drifted)
            self.assertEqual(
                set(path.name for path in base.iterdir()),
                {"custody"},
            )

    def test_old_or_tampered_receipt_is_rejected_before_mkdir(self):
        value = json.loads(self.receipt_raw.decode("ascii"))
        value["payload"]["schema"] = (
            "noteai.item26.manual-cost-stop-runtime-activation-receipt.v2"
        )
        old_receipt = authority.canonical_bytes(value)
        with tempfile.TemporaryDirectory(
            prefix=".item26-installer-old-receipt-",
            dir=ROOT,
        ) as temporary:
            base = Path(temporary)
            base.chmod(0o700)
            with mock.patch.object(
                installer,
                "_open_absent_target_parent",
                side_effect=AssertionError("target preflight must not start"),
            ), self.assertRaises(ValueError):
                self.invoke(base, receipt_raw=old_receipt)
            self.assertEqual(
                set(path.name for path in base.iterdir()),
                {"custody"},
            )

    def test_loaded_installer_and_authority_must_match_control_git_blobs(self):
        for ref in (installer.INSTALLER_REF, authority.VERIFIER_REF):
            with self.subTest(ref=ref), tempfile.TemporaryDirectory(
                prefix=".item26-installer-loaded-source-drift-",
                dir=ROOT,
            ) as temporary:
                base = Path(temporary)
                base.chmod(0o700)

                def drifted(_revision, observed_ref, *, root):
                    del root
                    row = self.git_record(_revision, observed_ref, root=ROOT)
                    if observed_ref == ref:
                        raw = row["raw"] + b"# drift\n"
                        digest = hashlib.sha256(raw).hexdigest()
                        return {
                            **row,
                            "raw": raw,
                            "git_blob_sha256": digest,
                            "file_sha256": digest,
                        }
                    return row

                with mock.patch.object(
                    installer,
                    "_open_absent_target_parent",
                    side_effect=AssertionError(
                        "target preflight must not start"
                    ),
                ), self.assertRaisesRegex(
                    installer.InstallError,
                    "loaded_source_binding",
                ):
                    self.invoke(base, git_side_effect=drifted)
                self.assertEqual(
                    set(path.name for path in base.iterdir()),
                    {"custody"},
                )

    def test_custody_metadata_is_required_before_target_preflight(self):
        for kind in (
            "absent",
            "missing",
            "extra",
            "symlink",
            "hardlink",
            "mode",
        ):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(
                prefix=".item26-installer-custody-negative-",
                dir=ROOT,
            ) as temporary:
                base = Path(temporary)
                base.chmod(0o700)
                custody, _ = self.make_custody(base)
                if kind == "absent":
                    for path in custody.iterdir():
                        path.unlink()
                    custody.rmdir()
                elif kind == "missing":
                    (custody / installer.CUSTODY_ROLE_FILES[0]).unlink()
                elif kind == "extra":
                    extra = custody / "unexpected-material"
                    extra.write_bytes(b"opaque\n")
                    extra.chmod(0o600)
                elif kind == "symlink":
                    target = custody / installer.CUSTODY_ROLE_FILES[0]
                    target.unlink()
                    target.symlink_to(custody / installer.CUSTODY_ROLE_FILES[1])
                elif kind == "hardlink":
                    target = custody / installer.CUSTODY_ROLE_FILES[0]
                    outside = base / "custody-hardlink"
                    os.link(target, outside)
                else:
                    (custody / installer.CUSTODY_ROLE_FILES[0]).chmod(0o644)
                with mock.patch.object(
                    installer,
                    "_open_absent_target_parent",
                    side_effect=AssertionError(
                        "target preflight must not start"
                    ),
                ), self.assertRaisesRegex(
                    installer.InstallError,
                    "custody_",
                ):
                    self.invoke(base, create_custody=False)
                self.assertFalse((base / "authority").exists())
                self.assertFalse((base / "runtime").exists())
                self.assertFalse((base / "journal").exists())

    def test_custody_validator_reads_only_metadata(self):
        with tempfile.TemporaryDirectory(
            prefix=".item26-installer-custody-metadata-",
            dir=ROOT,
        ) as temporary:
            base = Path(temporary)
            base.chmod(0o700)
            custody, _ = self.make_custody(base)
            with mock.patch.object(
                installer,
                "_file_owner_uid",
                return_value=os.getuid(),
            ), mock.patch.object(
                installer,
                "_validate_parent_chain",
            ), mock.patch.object(
                installer.os,
                "read",
                side_effect=AssertionError("key bytes must not be read"),
            ):
                installer._validate_custody_metadata(custody)

    def test_repo_execution_path_and_missing_esb_flags_are_rejected(self):
        with self.assertRaisesRegex(
            installer.InstallError,
            "execution_flags",
        ):
            installer._validate_execution_flags()
        with mock.patch.object(installer, "_validate_execution_flags"), \
                self.assertRaisesRegex(
                    installer.InstallError,
                    "execution_path",
                ):
            installer._validate_execution_boundary()

    def test_tmp_interpreter_is_rejected_before_source_or_git_io(self):
        with mock.patch.object(
            installer.sys,
            "executable",
            "/tmp/python",
        ), mock.patch.object(
            installer,
            "_validate_system_binary",
            side_effect=AssertionError("system binary read must not start"),
        ), mock.patch.object(
            installer,
            "_read_stable_source",
            side_effect=AssertionError("source read must not start"),
        ), mock.patch.object(
            authority,
            "_git_blob_record",
            side_effect=AssertionError("Git I/O must not start"),
        ), self.assertRaisesRegex(
            installer.InstallError,
            "interpreter_path",
        ):
            installer._validate_system_interpreter()

    def test_interpreter_binary_requires_stable_mode_owner_and_hash(self):
        with tempfile.TemporaryDirectory(
            prefix=".item26-installer-interpreter-",
            dir=ROOT,
        ) as temporary:
            path = Path(temporary) / "python3"
            raw = b"synthetic system interpreter\n"
            path.write_bytes(raw)
            path.chmod(0o755)
            digest = hashlib.sha256(raw).hexdigest()
            with mock.patch.object(
                installer,
                "ROOT_UID",
                os.getuid(),
            ), mock.patch.object(
                installer,
                "_validate_system_parent_chain",
            ):
                installer._validate_system_binary(path, digest)
                with self.assertRaisesRegex(
                    installer.InstallError,
                    "interpreter_binding",
                ):
                    installer._validate_system_binary(path, "0" * 64)
                path.chmod(0o777)
                with self.assertRaisesRegex(
                    installer.InstallError,
                    "interpreter_identity",
                ):
                    installer._validate_system_binary(path, digest)

    def test_staging_requires_root_owner_and_exact_authority_import_path(self):
        with tempfile.TemporaryDirectory(
            prefix=".item26-installer-staging-owner-",
            dir=ROOT,
        ) as temporary:
            base = Path(temporary)
            base.chmod(0o700)
            staging, installer_path, authority_path = (
                self.make_execution_staging(base)
            )
            if os.getuid() != 0:
                with self.assertRaisesRegex(
                    installer.InstallError,
                    "execution_identity",
                ):
                    self.validate_synthetic_staging(
                        staging,
                        installer_path,
                        authority_path,
                        accept_current_owner=False,
                    )
            outside = base / authority_path.name
            outside.write_bytes(authority_path.read_bytes())
            outside.chmod(0o600)
            with self.assertRaisesRegex(
                installer.InstallError,
                "execution_path",
            ):
                self.validate_synthetic_staging(
                    staging,
                    installer_path,
                    outside,
                )

    def test_staging_rejects_extra_pycache_mode_and_hardlink(self):
        for kind in ("extra", "pycache", "mode", "hardlink"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(
                prefix=".item26-installer-staging-negative-",
                dir=ROOT,
            ) as temporary:
                base = Path(temporary)
                base.chmod(0o700)
                staging, installer_path, authority_path = (
                    self.make_execution_staging(base)
                )
                expected_error = "execution_inventory"
                if kind == "extra":
                    (staging / "extra").write_bytes(b"extra\n")
                elif kind == "pycache":
                    (staging / "__pycache__").mkdir(mode=0o700)
                elif kind == "mode":
                    installer_path.chmod(0o644)
                    expected_error = "loaded_source_identity"
                else:
                    outside = base / "installer-hardlink"
                    os.link(installer_path, outside)
                    expected_error = "loaded_source_identity"
                with self.assertRaisesRegex(
                    installer.InstallError,
                    expected_error,
                ):
                    self.validate_synthetic_staging(
                        staging,
                        installer_path,
                        authority_path,
                    )

    def test_synthetic_staging_exact_inventory_returns_only_two_sources(self):
        with tempfile.TemporaryDirectory(
            prefix=".item26-installer-staging-positive-",
            dir=ROOT,
        ) as temporary:
            base = Path(temporary)
            base.chmod(0o700)
            staging, installer_path, authority_path = (
                self.make_execution_staging(base)
            )
            material = self.validate_synthetic_staging(
                staging,
                installer_path,
                authority_path,
            )
            self.assertEqual(
                material,
                {
                    installer.INSTALLER_REF: self.git_raw[
                        installer.INSTALLER_REF
                    ],
                    authority.VERIFIER_REF: self.git_raw[
                        authority.VERIFIER_REF
                    ],
                },
            )

    def test_complete_parent_chain_includes_anchor_and_rejects_unsafe_row(self):
        target = Path("/one/two/target")
        visited = []
        safe = SimpleNamespace(
            st_mode=stat.S_IFDIR | 0o755,
            st_uid=0,
        )

        def rows(path):
            visited.append(str(path))
            if str(path) == "/one":
                return SimpleNamespace(
                    st_mode=stat.S_IFDIR | 0o777,
                    st_uid=0,
                )
            return safe

        with mock.patch.object(Path, "lstat", autospec=True, side_effect=rows), \
                self.assertRaisesRegex(
                    installer.InstallError,
                    "parent_identity",
                ):
            installer._validate_parent_chain(target)
        self.assertEqual(visited, ["/", "/one"])

        visited.clear()
        with mock.patch.object(
            Path,
            "lstat",
            autospec=True,
            side_effect=lambda path: (visited.append(str(path)) or safe),
        ):
            installer._validate_parent_chain(target)
        self.assertEqual(visited, ["/", "/one", "/one/two"])

    def test_execution_staging_parent_chain_is_root_owned_and_not_writable(self):
        directory = Path("/one/two/staging")
        visited = []

        def safe_rows(path):
            visited.append(str(path))
            mode = 0o700 if path == directory else 0o755
            return SimpleNamespace(st_mode=stat.S_IFDIR | mode, st_uid=0)

        with mock.patch.object(
            Path,
            "lstat",
            autospec=True,
            side_effect=safe_rows,
        ):
            installer._validate_execution_parent_chain(directory)
        self.assertEqual(
            visited,
            ["/", "/one", "/one/two", "/one/two/staging"],
        )

        def unsafe_rows(path):
            mode = 0o777 if str(path) == "/one/two" else 0o755
            if path == directory:
                mode = 0o700
            return SimpleNamespace(st_mode=stat.S_IFDIR | mode, st_uid=0)

        with mock.patch.object(
            Path,
            "lstat",
            autospec=True,
            side_effect=unsafe_rows,
        ), self.assertRaisesRegex(
            installer.InstallError,
            "execution_parent_identity",
        ):
            installer._validate_execution_parent_chain(directory)

    def test_success_fsyncs_files_directories_and_target_parents(self):
        with tempfile.TemporaryDirectory(
            prefix=".item26-installer-fsync-",
            dir=ROOT,
        ) as temporary:
            base = Path(temporary)
            base.chmod(0o700)
            real_fsync = os.fsync
            synced_types = []

            def record_fsync(descriptor):
                synced_types.append(stat.S_IFMT(os.fstat(descriptor).st_mode))
                return real_fsync(descriptor)

            with mock.patch.object(
                installer.os,
                "fsync",
                side_effect=record_fsync,
            ):
                self.invoke(base)
            self.assertGreaterEqual(synced_types.count(stat.S_IFREG), 5)
            self.assertGreaterEqual(synced_types.count(stat.S_IFDIR), 9)

    def test_non_root_rejects_before_git_or_target_io(self):
        with mock.patch.object(authority, "AUTHORITY_V2_FINALIZED", True), \
                mock.patch.object(
                    authority,
                    "EXPECTED_ROOT_SHA",
                    self.root_hash,
                ), mock.patch.object(
                    authority,
                    "EXPECTED_AUTHORITY_ROOT_FILE_SHA256",
                    self.root_hash,
                ), mock.patch.object(
                    installer.os,
                    "geteuid",
                    return_value=501,
                ), mock.patch.object(
                    authority,
                    "_git_blob_record",
                    side_effect=AssertionError("Git I/O must not start"),
                ), self.assertRaisesRegex(
                    installer.InstallError,
                    "root_required",
                ):
            installer.install_runtime(
                control_revision=CONTROL_REVISION,
                receipt_raw=self.receipt_raw,
            )

    def test_world_writable_parent_shape_is_rejected(self):
        row = SimpleNamespace(st_mode=stat.S_IFDIR | 0o777, st_uid=0)
        with self.assertRaisesRegex(
            installer.InstallError,
            "parent_identity",
        ):
            installer._validate_parent_row(row)

    def test_directory_overlap_rejected_before_git_io(self):
        base = Path("/safe/root")
        with mock.patch.object(
            authority,
            "_git_blob_record",
            side_effect=AssertionError("Git I/O must not start"),
        ), self.assertRaisesRegex(
            installer.InstallError,
            "directory_partition",
        ):
            with mock.patch.object(authority, "AUTHORITY_V2_FINALIZED", True), \
                    mock.patch.object(authority, "EXPECTED_ROOT_SHA", self.root_hash), \
                    mock.patch.object(
                        authority,
                        "EXPECTED_AUTHORITY_ROOT_FILE_SHA256",
                        self.root_hash,
                    ), mock.patch.object(
                        installer.os,
                        "geteuid",
                        return_value=0,
                    ), mock.patch.object(
                        installer,
                        "_validate_execution_boundary",
                        return_value={
                            installer.INSTALLER_REF: self.git_raw[
                                installer.INSTALLER_REF
                            ],
                            authority.VERIFIER_REF: self.git_raw[
                                authority.VERIFIER_REF
                            ],
                        },
                    ):
                installer.install_runtime(
                    control_revision=CONTROL_REVISION,
                    receipt_raw=self.receipt_raw,
                    authority_directory=base,
                    runtime_directory=base / "nested",
                    journal_directory=Path("/safe/journal"),
                    custody_directory=Path("/safe/custody"),
                )

    def test_default_inert_main_rejects_before_mkdir_read_or_git(self):
        with mock.patch.object(
            installer.os,
            "mkdir",
            side_effect=AssertionError("mkdir must not start"),
        ), mock.patch.object(
            authority,
            "_git_blob_record",
            side_effect=AssertionError("Git I/O must not start"),
        ), mock.patch.object(
            Path,
            "read_bytes",
            side_effect=AssertionError("file read must not start"),
        ), mock.patch.object(
            installer.FixedArgumentParser,
            "parse_args",
            side_effect=AssertionError("argument parsing must not start"),
        ), self.assertRaisesRegex(ValueError, "not finalized"):
            installer.main(["--receipt-path", "/must/not/be-resolved"])


if __name__ == "__main__":
    unittest.main()
