from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_admin_dependency_cache_transient_state_v4 as verifier  # noqa: E402


class AdminDependencyCacheTransientStateV4Tests(unittest.TestCase):
    BUILDER_NAME = "noteai-admin-cache-v4-producer-123"

    def _fixture(self, root: Path) -> tuple[Path, Path]:
        docker_config = root / "noteai-empty-docker-config-v4"
        buildx_config = root / "noteai-buildx-state-v4"
        docker_config.mkdir(mode=0o700)
        buildx_config.mkdir(mode=0o700)
        config = docker_config / "config.json"
        config.write_text(json.dumps({"auths": {}}), encoding="utf-8")
        config.chmod(0o600)
        instances = buildx_config / "instances"
        instances.mkdir(mode=0o700)
        instance = instances / self.BUILDER_NAME
        instance.write_text(
            json.dumps(
                {
                    "Name": self.BUILDER_NAME,
                    "Driver": "docker-container",
                    "Nodes": [
                        {
                            "Name": f"{self.BUILDER_NAME}0",
                            "Endpoint": "unix:///var/run/docker.sock",
                            "Platforms": None,
                            "DriverOpts": {
                                "image": verifier.BUILDKIT_IMAGE,
                            },
                            "Flags": verifier.EXPECTED_BUILDKITD_FLAGS,
                            "Files": None,
                        }
                    ],
                    "Dynamic": False,
                }
            ),
            encoding="utf-8",
        )
        instance.chmod(0o600)
        return docker_config, buildx_config

    def test_exact_separated_state_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            docker_config, buildx_config = self._fixture(root)
            summary = verifier.validate_active_state(
                root,
                docker_config,
                buildx_config,
            )
            self.assertEqual(summary["docker_auth_entries"], 0)
            self.assertEqual(summary["buildx_state_files"], 1)

    def test_buildkitd_flags_require_exact_source_proven_default(self) -> None:
        cases = (
            None,
            [],
            ["--allow-insecure-entitlement=security.insecure"],
            verifier.EXPECTED_BUILDKITD_FLAGS + ["--debug"],
            ["--debug"] + verifier.EXPECTED_BUILDKITD_FLAGS,
            [
                "--allow-insecure-entitlement",
                "network.host",
            ],
        )
        for flags in cases:
            with self.subTest(flags=flags), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                docker_config, buildx_config = self._fixture(root)
                instance = (
                    buildx_config / "instances" / self.BUILDER_NAME
                )
                payload = json.loads(instance.read_text(encoding="utf-8"))
                payload["Nodes"][0]["Flags"] = flags
                instance.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaisesRegex(verifier.StateError, "flags changed"):
                    verifier.validate_active_state(
                        root,
                        docker_config,
                        buildx_config,
                    )

    def test_official_store_and_local_state_shapes_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            docker_config, buildx_config = self._fixture(root)
            activity = buildx_config / "activity"
            defaults = buildx_config / "defaults"
            refs = buildx_config / "refs"
            for directory in (activity, defaults, refs):
                directory.mkdir(mode=0o700)
            (activity / self.BUILDER_NAME).write_text(
                "2026-07-31T00:00:00Z",
                encoding="ascii",
            )
            (defaults / ("a" * 20)).write_text(
                self.BUILDER_NAME,
                encoding="utf-8",
            )
            (refs / "version").write_text("2", encoding="ascii")
            builder_refs = refs / self.BUILDER_NAME
            node_refs = builder_refs / f"{self.BUILDER_NAME}0"
            builder_refs.mkdir(mode=0o700)
            node_refs.mkdir(mode=0o700)
            ref = node_refs / "ref-1"
            ref.write_text(
                json.dumps(
                    {
                        "Target": "runtime-common",
                        "LocalPath": "/home/runner/work/noteai/noteai",
                        "DockerfilePath": (
                            "/home/runner/work/noteai/noteai/Dockerfile"
                        ),
                    }
                ),
                encoding="utf-8",
            )
            for path in (
                activity / self.BUILDER_NAME,
                defaults / ("a" * 20),
                refs / "version",
            ):
                path.chmod(0o600)
            ref.chmod(0o644)
            summary = verifier.validate_active_state(
                root,
                docker_config,
                buildx_config,
            )
            self.assertEqual(summary["buildx_state_files"], 5)

    def test_docker_config_duplicate_nonfinite_or_oversize_fail_closed(
        self,
    ) -> None:
        cases = ("duplicate", "nonfinite", "oversize")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                docker_config, buildx_config = self._fixture(root)
                config = docker_config / "config.json"
                if case == "duplicate":
                    config.write_text(
                        (
                            '{"auths":{"registry.invalid":{"auth":"hidden"}},'
                            '"auths":{}}'
                        ),
                        encoding="utf-8",
                    )
                elif case == "nonfinite":
                    config.write_text(
                        '{"auths":{},"unexpected":1e999}',
                        encoding="utf-8",
                    )
                else:
                    config.write_text(
                        '{"auths":{}}' + (" " * 129),
                        encoding="utf-8",
                    )
                with self.assertRaises(verifier.StateError):
                    verifier.validate_active_state(
                        root,
                        docker_config,
                        buildx_config,
                    )

    def test_docker_config_rejects_buildx_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            docker_config, buildx_config = self._fixture(root)
            (docker_config / "buildx").mkdir(mode=0o700)
            with self.assertRaisesRegex(
                verifier.StateError,
                "unexpected state",
            ):
                verifier.validate_active_state(
                    root,
                    docker_config,
                    buildx_config,
                )

    def test_buildx_state_rejects_unsafe_topology_or_content(self) -> None:
        cases = ("symlink", "hardlink", "credential", "world_writable")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                docker_config, buildx_config = self._fixture(root)
                instance = (
                    buildx_config / "instances" / self.BUILDER_NAME
                )
                if case == "symlink":
                    link = buildx_config / "link"
                    link.symlink_to(instance)
                elif case == "hardlink":
                    os.link(instance, buildx_config / "duplicate")
                elif case == "credential":
                    instance.write_text(
                        '{"access_token":"forbidden"}',
                        encoding="utf-8",
                    )
                else:
                    instance.chmod(0o666)
                with self.assertRaises(verifier.StateError):
                    verifier.validate_active_state(
                        root,
                        docker_config,
                        buildx_config,
                    )

    def test_buildx_state_schema_rejects_opaque_or_embedded_material(self) -> None:
        cases = ("opaque", "driver_option", "embedded_file")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                docker_config, buildx_config = self._fixture(root)
                instance = (
                    buildx_config / "instances" / self.BUILDER_NAME
                )
                if case == "opaque":
                    opaque = buildx_config / "opaque-state"
                    opaque.write_text(
                        '{"value":"not-schema-bound"}',
                        encoding="utf-8",
                    )
                    opaque.chmod(0o600)
                else:
                    payload = json.loads(instance.read_text(encoding="utf-8"))
                    node = payload["Nodes"][0]
                    if case == "driver_option":
                        node["DriverOpts"]["auth"] = "opaque"
                    else:
                        node["Files"] = {
                            "buildkitd.toml": "embedded-material"
                        }
                    instance.write_text(
                        json.dumps(payload),
                        encoding="utf-8",
                    )
                with self.assertRaises(verifier.StateError):
                    verifier.validate_active_state(
                        root,
                        docker_config,
                        buildx_config,
                    )

    def test_roots_must_be_exact_distinct_children(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            docker_config, buildx_config = self._fixture(root)
            with self.assertRaisesRegex(verifier.StateError, "root changed"):
                verifier.validate_active_state(
                    root,
                    docker_config,
                    buildx_config.with_name("other"),
                )


if __name__ == "__main__":
    unittest.main()
