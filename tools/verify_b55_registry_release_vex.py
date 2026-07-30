#!/usr/bin/env python3
"""Build and verify the exact b55f118 private-ACR publication/VEX bundle.

The committed bundle is a Secret-free reduction of the accepted build10
evidence and the five serial private-registry publications.  It binds each
exact immutable tag to the local image config digest, the registry manifest
descriptor, the ACR control-plane digest, the retained push log and the
unsuppressed source-candidate SBOM/VEX evidence.

This verifier deliberately grants no deployment authorization.  API-C
loopback canary and reversible promotion remain a separate readiness gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any

import verify_b55_native_release_vex as source_bundle


ROOT = Path(__file__).resolve().parents[1]
RELEASE_COMMIT = source_bundle.RELEASE_COMMIT
RELEASE_SHORT = RELEASE_COMMIT[:7]
TASK_ID = "PROD-FIRST-LAUNCH-IMMUTABLE-RELEASE-B55F118-PUBLISH-001"
ROLES = source_bundle.ROLES
EVIDENCE_PATH = (
    ROOT / "security" / "vex" / f"{RELEASE_SHORT}-registry-release-evidence.json"
)
VEX_PATH = (
    ROOT / "security" / "vex" / f"{RELEASE_SHORT}-registry-release.vex.cdx.json"
)
REVIEW_PATH = (
    ROOT / "security" / "vex" / f"{RELEASE_SHORT}-registry-release-review.json"
)
SOURCE_EVIDENCE_PATH = source_bundle.EVIDENCE_PATH
SOURCE_VEX_PATH = source_bundle.VEX_PATH
SOURCE_REVIEW_PATH = source_bundle.REVIEW_PATH
ATTESTATION_PATH = (
    ROOT
    / "security"
    / "vex"
    / f"{RELEASE_SHORT}-registry-publication-attestation.json"
)

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
EXPECTED_FINDINGS = {
    "critical": 4,
    "high": 19,
    "secrets": 0,
    "browser_components": 0,
    "cryptography_48_0_1_components": 1,
    "forbidden_os_packages": 0,
}
EXPECTED_TAGS = {
    "api": "git-b55f118-amd64-api-r1",
    "admin": "git-b55f118-amd64-admin-r1",
    "payment": "git-b55f118-amd64-payment-r1",
    "ai-worker": "git-b55f118-amd64-ai-worker-r1",
    "xhs-http": "git-b55f118-amd64-xhs-http-r1",
}
EXPECTED_STAGE_A = {
    "raw_file_count": 43,
    "original_invocation_status": "TIMEOUT",
    "acceptance_version": 4,
    "summary_sha256": (
        "a8e1c7ca38e1d5886197f6f727a4fb51ce206817221cc404f4586d29588c41d0"
    ),
    "manifest_sha256": (
        "ec14390c4ccf9515f659ee29dfb20b60e6776d804dfe3005e2c2edb6d7bca865"
    ),
    "acceptance_sha256": (
        "e16a3c3d2308a6e4d1b9113d37059933efc4d7965a4f3c12f5cf0a43d9b10a75"
    ),
    "state_sha256": (
        "3bd7ed55948bf292ae969a4c159b03f10a17407788b950ca70b6a6b7d16403ef"
    ),
    "publication_authorized": True,
    "deployment_authorized": False,
    "database_authorized": False,
    "service_mutation_authorized": False,
    "public_traffic_authorized": False,
}
EXPECTED_SCANNER_CACHE = {
    "database_sha256": (
        "43c58b4f5d8c99a9480dd018596c2d907ac2df1f87e94f9da859b2563454bfa0"
    ),
    "metadata_sha256": (
        "c22e06141b5631651e7fda582ed629c876b0c500df2d78146053d157b6e4bb59"
    ),
    "offline_scan": True,
    "database_update_skipped": True,
    "java_database_update_skipped": True,
}
EXPECTED_RETAINED_EVIDENCE = {
    "category": "registry_publication_files",
    "retention_days": 14,
    "retain_until": "2026-08-13T05:42:21.099Z",
    "file_count": 19,
    "file_bytes": 66763,
    "tree_bytes": 83147,
    "sha256sums_sha256": (
        "151f676b27258e0ad02748bf2bb6f475b416ec2a2cd615e8a9df8c67cdd2b3ee"
    ),
    "root_owned_private_files": True,
    "symbolic_links": 0,
    "special_files": 0,
    "forbidden_credential_matches": 0,
}
EXPECTED_REPOSITORY = {
    "private": True,
    "status": "NORMAL",
    "tag_immutability": True,
    "tag_count_before": 10,
    "tag_count_after": 15,
    "baseline_tags_preserved": 10,
}
EXPECTED_PUBLICATION_CONTROLS = {
    "push_invocations": 5,
    "manual_retries": 0,
    "serial": True,
    "unique_digests": 5,
    "manifest_readbacks": 5,
    "control_plane_readbacks": 5,
    "registry_writes": 5,
    "database_connections": 0,
    "database_writes": 0,
    "service_mutations": 0,
    "public_endpoint_enabled": False,
    "public_traffic_enabled": False,
    "deployment_authorized": False,
}
EXPECTED_CLEANUP = {
    "builder_acr_vpc_links": 0,
    "production_acr_vpc_links": 1,
    "registry_public_endpoint_enabled": False,
    "publisher_policy_exists": False,
    "publisher_role_attached": False,
    "publisher_role_exists": False,
    "builder_ram_role_present": False,
    "builder_imds_ram_role_http_status": 404,
    "builder_acr_dns_records": 0,
    "docker_auth_entries": 0,
    "temporary_auth_directories": 0,
    "running_containers": 0,
    "push_processes": 0,
    "database_connections": 0,
    "source_images_retained": 5,
    "api_c_api_active": True,
    "api_c_admin_active": True,
    "api_c_ready_http_status": 200,
    "api_c_loopback_only": True,
    "api_c_private_acr_dns_records": 1,
    "api_f_api_active": True,
    "api_f_ready_http_status": 200,
    "api_f_loopback_only": True,
    "api_f_private_acr_dns_records": 1,
}
EXPECTED_SCOPE = {
    "registry_publication_complete": True,
    "registry_changed": True,
    "cloud_control_plane_changed": True,
    "temporary_identity_changed": True,
    "private_endpoint_changed": True,
    "application_deployed": False,
    "database_changed": False,
    "business_provider_called": False,
    "service_restarted": False,
    "public_traffic_changed": False,
    "deployment_authorized": False,
    "api_c_canary_completed": False,
}
EXPECTED_COMPONENT_REFS_JSONL_SHA256 = (
    "9cb5d680bce715c4c146e0cc5d7910f5c5a4cffb2094b8f2114afb381b2ca213"
)
EXPECTED_ATTESTATION_SEMANTIC_SHA256 = (
    "6065f797cd16fc5b6c19a32f70e67e624adfa5e799151cf7bcb8432e6d202ab4"
)
EXPECTED_ATTESTATION_FILE_SHA256 = (
    "c27205495011debc49d8f4b7bfa235d36b08de6c2c96c0dc38dbb9d552076325"
)
EXPECTED_REGISTRY_EVIDENCE_SEMANTIC_SHA256 = (
    "9104a2bcca8cfac071299aee7c79ca50882702f95523e67dbe3dbb66326efea0"
)

EXPECTED_ROLE_PRODUCTS: dict[str, dict[str, Any]] = {
    "api": {
        "target": "api-runtime",
        "local_image_id": (
            "sha256:dd955f9e736fc00df471f39de6e483ed0873f5855cc0ffffc074823845fefd53"
        ),
        "registry_digest": (
            "sha256:612a7e57b8a4226e4c23be6267ee60fb79677cae9eb46ea1843aed11fc517620"
        ),
        "manifest_json_sha256": (
            "1ed505f987188dd72531c0fb4e8392b9f769530d19f84c2414b29b15278986d8"
        ),
        "push_log_sha256": (
            "1828b5e46f6deb941a738fb9e9c5ca08c412584f0b796daf51cab2afc5aa7d31"
        ),
        "manifest_size": 4085,
        "layer_count": 18,
        "entrypoint": ["/app/scripts/docker_entrypoint.sh"],
        "cmd": ["/app/scripts/render_start_api.sh"],
        "sbom": {
            "sha256": (
                "2ebb2c874e3b2ebbde882e0f6950970fbf7d3598b3becbdc34b75f90d6c5cd98"
            ),
            "serial_number": "urn:uuid:8d28e096-f58c-4619-b886-e1de9a3be2b6",
            "version": 1,
            "component_count": 3076,
        },
        "raw_reports": {
            "build_metadata_sha256": (
                "e918a014a86f6f47e9992b87d079070451f0df88636fba9455d5e0f8cb3a25e0"
            ),
            "history_sha256": (
                "2aac126241963f0b52255ccab842d199dff74a93265e00f527322e23cf5509cc"
            ),
            "inspect_sha256": (
                "f273fdaafd9b1b94cf4c738db1e566652425ca0e6eeb5ebbaf404cfbe337f701"
            ),
            "os_packages_sha256": (
                "1cf41e20e68ddfd8ed52bf5c95f1c6c20dc146e506815c679731962010a85a54"
            ),
            "secret_sha256": (
                "384dbece595dbcc93d82fdae8da75d33b526935e19fe06f545c5fd583d815a44"
            ),
            "vulnerability_sha256": (
                "11641b35599da94e4c05264a2d6db88226decbf6a5aadfda6f28977f2264159d"
            ),
        },
    },
    "admin": {
        "target": "admin-runtime",
        "local_image_id": (
            "sha256:fac78f71d7b123621962738d2a93532ff98f2302232562dc75b6a8e0016b7626"
        ),
        "registry_digest": (
            "sha256:271a089e4e5ae7da3635b14d2ce8d5195955e7d74225723a4308d0c99cb79e56"
        ),
        "manifest_json_sha256": (
            "cbeb8d36f790158153f7639627b3ce73ace28fa402c3360c98feb2a95adf34c7"
        ),
        "push_log_sha256": (
            "9c8d18a11198eb17a303e07a98405aa4c6fccf0b32ff86b0b8fe987a70117fd2"
        ),
        "manifest_size": 4085,
        "layer_count": 18,
        "entrypoint": ["/app/scripts/docker_entrypoint.sh"],
        "cmd": ["/app/scripts/render_start_admin.sh"],
        "sbom": {
            "sha256": (
                "aa50f2c32f6f243afa635eaef2e0f7d17485fdfdac796022be5d17d936ec2f62"
            ),
            "serial_number": "urn:uuid:312aa052-443d-4ce1-9b78-5f019686af42",
            "version": 1,
            "component_count": 3076,
        },
        "raw_reports": {
            "build_metadata_sha256": (
                "0ea9c690fb9170f7275fae17d6e1ee124821e42060cd1960aebcbf674706e9a2"
            ),
            "history_sha256": (
                "393779257e550338114b3ba10c467bf48198ce151573d9c88b9f2d9494311af2"
            ),
            "inspect_sha256": (
                "4bb1e472d627106c5d4ec5fbde96b58bb9791eb8436ad77020c8a9220ea6b622"
            ),
            "os_packages_sha256": (
                "1cf41e20e68ddfd8ed52bf5c95f1c6c20dc146e506815c679731962010a85a54"
            ),
            "secret_sha256": (
                "2bb8be1874e18e474bfd862769fd8ff21b4e320876889d297dd1d089c97ebb16"
            ),
            "vulnerability_sha256": (
                "efe31379c3cc8fed582c7e17b8d449e1a17422d9aae40e7325f69c9603991863"
            ),
        },
    },
    "payment": {
        "target": "payment-runtime",
        "local_image_id": (
            "sha256:36b465dca36d5751318033cd494ed7544588f9ead18b781801542642ed2b1bc4"
        ),
        "registry_digest": (
            "sha256:ad5827450ad187bd3cfb47f00a903b78106b00a5ca8dbee5e9a77770f0c02e2b"
        ),
        "manifest_json_sha256": (
            "f5adebf6578856355a9e6a1013030ef5d4e748d5ebf539e44fb5a6ff264359ec"
        ),
        "push_log_sha256": (
            "5bdb454c6ec969d97037e967cf3a9224ba37f5b0dad6c1e5600bef44c63aecc6"
        ),
        "manifest_size": 4085,
        "layer_count": 18,
        "entrypoint": ["/app/scripts/docker_entrypoint.sh"],
        "cmd": ["/app/scripts/render_start_payment.sh"],
        "sbom": {
            "sha256": (
                "ca4e4c32252019d1de226f3cbd2c4a4b2f2c15e3eb218e957b442e29802591b5"
            ),
            "serial_number": "urn:uuid:a67c9a2a-56c8-42c7-b1b5-f69f87498468",
            "version": 1,
            "component_count": 3076,
        },
        "raw_reports": {
            "build_metadata_sha256": (
                "a08bfcd661c4b3b9c18c9e6c573276217128a7bfce9d35eca74f14763e6476c3"
            ),
            "history_sha256": (
                "2ac01cacbf87bd1afffc0a1ccfd0d1921196b018cb376cbfc9cbe02cff2ea1af"
            ),
            "inspect_sha256": (
                "7b6a88bbe097edce6bfea44a5b60613bbc8896877afdc8a54155f15cd1b4aad7"
            ),
            "os_packages_sha256": (
                "1cf41e20e68ddfd8ed52bf5c95f1c6c20dc146e506815c679731962010a85a54"
            ),
            "secret_sha256": (
                "24fc60063ef1afc428d255bba807bdbb8c9d3d307b146f89bf674812ba48bee4"
            ),
            "vulnerability_sha256": (
                "bdd0c685f07a8bcfa856f13b9655a18ab6b24f029a76fe1ad075895fbc9c59c8"
            ),
        },
    },
    "ai-worker": {
        "target": "ai-worker-runtime",
        "local_image_id": (
            "sha256:eb3850db2f76001a25cbdd93c6fdbca6df18a3c734aaf6bb5096e5707fd71b2d"
        ),
        "registry_digest": (
            "sha256:d4c5d0dde6927ee9f422db35967be98c1d1066aec31db4e1f65c82ec6aeff34b"
        ),
        "manifest_json_sha256": (
            "8fcb31c3f69fe606604fc0020cae100c69a34c4d636ba952612c526d13a8e217"
        ),
        "push_log_sha256": (
            "21faa2ecb992086f77508b6fb4488fad4b25154512cbb5d3e1e59325a7224e63"
        ),
        "manifest_size": 4085,
        "layer_count": 18,
        "entrypoint": ["/app/scripts/docker_entrypoint.sh"],
        "cmd": ["python", "durable_ai_worker.py", "--once"],
        "sbom": {
            "sha256": (
                "67137a20458aa12be6dd02c4eb1b1466bd0d0a35c58f4c0f36a6fcf35d613775"
            ),
            "serial_number": "urn:uuid:cf5434c3-cdff-4bd4-b436-d7bcb0252a01",
            "version": 1,
            "component_count": 3076,
        },
        "raw_reports": {
            "build_metadata_sha256": (
                "e297662242ad058e200b62faa997de8183f45cc261d21f547d2b2c39d11ffa17"
            ),
            "history_sha256": (
                "bdaba8b94556da3d56f8584e452ded5ee74c3eedb7d9fb3d8d661c1be79ab43c"
            ),
            "inspect_sha256": (
                "4bc86dbbc65b23ab9ba9cef2516c20840c884b1a193b45bc00cde77e93e0a76c"
            ),
            "os_packages_sha256": (
                "1cf41e20e68ddfd8ed52bf5c95f1c6c20dc146e506815c679731962010a85a54"
            ),
            "secret_sha256": (
                "58d14da26f85aa5567c92f046927b6a80952fac683fc31194f71d33145a97d2d"
            ),
            "vulnerability_sha256": (
                "70e3b95ca69da3b7f24b41c39d0142ed724ce280dcc8c56e2751373ff3af3ea5"
            ),
        },
    },
    "xhs-http": {
        "target": "xhs-http-runtime",
        "local_image_id": (
            "sha256:a78f4753591fd824ef3e4cfd8ed229c32542d1ac50d3c8c03b529e71fd01f8ec"
        ),
        "registry_digest": (
            "sha256:406445820107cda130698b157a20663b99697a0acdae65030784d3cb083c1e50"
        ),
        "manifest_json_sha256": (
            "bacd36994c26fc0ba981ad476fc597d162af48f701a2411bb9adf140c294296f"
        ),
        "push_log_sha256": (
            "57f57d4b263692d4f9193eb98726169d44e78866ad02ef49d6c3994a26f0fc7b"
        ),
        "manifest_size": 4294,
        "layer_count": 19,
        "entrypoint": ["/app/scripts/docker_entrypoint.sh"],
        "cmd": ["/bin/false"],
        "sbom": {
            "sha256": (
                "5172777e6cd275923113841de8701b0e065db3d1664511f9ca7375e5301b86ec"
            ),
            "serial_number": "urn:uuid:fb7a593f-dd23-4fad-ab64-5f9ef87aecd4",
            "version": 1,
            "component_count": 3078,
        },
        "raw_reports": {
            "build_metadata_sha256": (
                "4edd3e33044f04c2337791022eb9f58281ac0f3399dc5ef820a6ed3cfd88832f"
            ),
            "history_sha256": (
                "e45304ee9f26a0aeb496f60b9a735c013f0842775908d3a5d81e0eea2881ca40"
            ),
            "inspect_sha256": (
                "c9465453e0056c623b7986e94dc7d37fe55860c69e93c8abe68e648b569d7ae4"
            ),
            "os_packages_sha256": (
                "1cf41e20e68ddfd8ed52bf5c95f1c6c20dc146e506815c679731962010a85a54"
            ),
            "secret_sha256": (
                "2358ac05f1cf62822e09c095568df4415b4eea1c141892ece9477b4a9dc401c8"
            ),
            "vulnerability_sha256": (
                "17baddea95906e2467ecc99133079343c8670b6a4736b624cc9b2195779a6ff5"
            ),
        },
    },
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _canonical_jsonl_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value) + b"\n").hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def _source() -> dict[str, Any]:
    errors = source_bundle.validate_bundle()
    if errors:
        raise ValueError(f"b55 source-candidate bundle invalid: {errors[0]}")
    source = _load_json(SOURCE_EVIDENCE_PATH)
    if source.get("application_revision") != RELEASE_COMMIT:
        raise ValueError("b55 source-candidate revision mismatch")
    return source


def _source_binding() -> dict[str, str]:
    return {
        "evidence": str(SOURCE_EVIDENCE_PATH.relative_to(ROOT)),
        "evidence_semantic_sha256": _canonical_sha256(
            _load_json(SOURCE_EVIDENCE_PATH)
        ),
        "vex": str(SOURCE_VEX_PATH.relative_to(ROOT)),
        "vex_semantic_sha256": _canonical_sha256(_load_json(SOURCE_VEX_PATH)),
        "review": str(SOURCE_REVIEW_PATH.relative_to(ROOT)),
        "review_semantic_sha256": _canonical_sha256(
            _load_json(SOURCE_REVIEW_PATH)
        ),
    }


def validate_attestation(
    attestation: dict[str, Any],
    source: dict[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    try:
        if source is None:
            source = _source()
        semantic_payload = dict(attestation)
        recorded_semantic = semantic_payload.pop("semantic_sha256", None)
        if recorded_semantic != EXPECTED_ATTESTATION_SEMANTIC_SHA256:
            errors.append("b55 publication attestation recorded semantic hash mismatch")
        if _canonical_sha256(semantic_payload) != EXPECTED_ATTESTATION_SEMANTIC_SHA256:
            errors.append("b55 publication attestation content semantic hash mismatch")
        if attestation.get("manifest_version") != 1:
            errors.append("b55 publication attestation manifest version mismatch")
        if attestation.get("task") != TASK_ID:
            errors.append("b55 publication attestation task mismatch")
        if attestation.get("application_revision") != RELEASE_COMMIT:
            errors.append("b55 publication attestation revision mismatch")
        if attestation.get("platform") != "linux/amd64":
            errors.append("b55 publication attestation platform mismatch")
        if attestation.get("runner_architecture") != "x86_64":
            errors.append("b55 publication attestation architecture mismatch")
        if attestation.get("evidence_created") != "2026-07-29T08:44:37Z":
            errors.append("b55 publication attestation evidence timestamp mismatch")
        if attestation.get("generated_at") != "2026-07-30T05:42:21.099Z":
            errors.append("b55 publication attestation publication timestamp mismatch")
        if attestation.get("stage_a") != EXPECTED_STAGE_A:
            errors.append("b55 publication attestation Stage A binding mismatch")
        if attestation.get("scanner_cache") != EXPECTED_SCANNER_CACHE:
            errors.append("b55 publication attestation Trivy cache mismatch")
        if attestation.get("repository") != EXPECTED_REPOSITORY:
            errors.append("b55 publication attestation repository mismatch")
        if (
            attestation.get("publication_controls")
            != EXPECTED_PUBLICATION_CONTROLS
        ):
            errors.append("b55 publication attestation controls mismatch")
        if (
            attestation.get("retained_publication_evidence")
            != EXPECTED_RETAINED_EVIDENCE
        ):
            errors.append("b55 publication attestation retention mismatch")
        if attestation.get("cleanup") != EXPECTED_CLEANUP:
            errors.append("b55 publication attestation cleanup mismatch")
        if attestation.get("scope") != EXPECTED_SCOPE:
            errors.append("b55 publication attestation scope mismatch")

        roles = attestation.get("roles") or {}
        if set(roles) != set(ROLES):
            errors.append("b55 publication attestation role set mismatch")
            return errors
        registry_digests: set[str] = set()
        local_ids: set[str] = set()
        for role_name in ROLES:
            role = roles.get(role_name) or {}
            expected = EXPECTED_ROLE_PRODUCTS[role_name]
            source_role = source["roles"][role_name]
            if role.get("target") != expected["target"]:
                errors.append(f"{role_name}: attested target mismatch")
            if role.get("target") != source_role.get("target"):
                errors.append(f"{role_name}: target differs from source candidate")
            if role.get("tag") != EXPECTED_TAGS[role_name]:
                errors.append(f"{role_name}: attested exact immutable tag mismatch")

            local_id = str(role.get("observed_local_image_id", ""))
            config_digest = str(role.get("observed_config_digest", ""))
            push_digest = str(role.get("observed_push_digest", ""))
            manifest_digest = str(role.get("observed_manifest_digest", ""))
            control_plane_digest = str(
                role.get("observed_control_plane_digest", "")
            )
            for field_name, value in (
                ("local image ID", local_id),
                ("config digest", config_digest),
                ("push digest", push_digest),
                ("manifest digest", manifest_digest),
                ("control-plane digest", control_plane_digest),
            ):
                if not DIGEST_RE.fullmatch(value):
                    errors.append(f"{role_name}: invalid attested {field_name}")
            if local_id != expected["local_image_id"]:
                errors.append(f"{role_name}: attested local image ID mismatch")
            if config_digest != expected["local_image_id"]:
                errors.append(f"{role_name}: independent config digest mismatch")
            for field_name, value in (
                ("push", push_digest),
                ("manifest", manifest_digest),
                ("control-plane", control_plane_digest),
            ):
                if value != expected["registry_digest"]:
                    errors.append(
                        f"{role_name}: independent {field_name} digest mismatch"
                    )
            if not (
                push_digest == manifest_digest == control_plane_digest
                and local_id == config_digest
                and local_id != push_digest
            ):
                errors.append(f"{role_name}: independent digest observations diverge")
            registry_digests.add(control_plane_digest)
            local_ids.add(local_id)

            expected_manifest = {
                "schema_version": 2,
                "media_type": (
                    "application/vnd.docker.distribution.manifest.v2+json"
                ),
                "config_media_type": (
                    "application/vnd.docker.container.image.v1+json"
                ),
                "size": expected["manifest_size"],
                "layer_count": expected["layer_count"],
                "retained_json_sha256": expected["manifest_json_sha256"],
            }
            if role.get("manifest") != expected_manifest:
                errors.append(f"{role_name}: attested manifest evidence mismatch")
            expected_push = {
                "state": "PUSH_REPORTED_SUCCESS",
                "return_code": 0,
                "invocations": 1,
                "manual_retries": 0,
                "retained_log_sha256": expected["push_log_sha256"],
            }
            if role.get("push") != expected_push:
                errors.append(f"{role_name}: attested push evidence mismatch")
            if role.get("platform") != "linux/amd64":
                errors.append(f"{role_name}: attested platform mismatch")
            if role.get("registry_status") != "NORMAL":
                errors.append(f"{role_name}: attested registry status mismatch")
            if role.get("entrypoint") != expected["entrypoint"]:
                errors.append(f"{role_name}: attested entrypoint mismatch")
            if role.get("entrypoint") != source_role.get("entrypoint"):
                errors.append(f"{role_name}: entrypoint differs from source candidate")
            if role.get("cmd") != expected["cmd"]:
                errors.append(f"{role_name}: attested command mismatch")
            if role.get("cmd") != source_role.get("cmd"):
                errors.append(f"{role_name}: command differs from source candidate")
            expected_sbom = {
                **expected["sbom"],
                "component_refs_jsonl_sha256": (
                    EXPECTED_COMPONENT_REFS_JSONL_SHA256
                ),
            }
            if role.get("sbom") != expected_sbom:
                errors.append(f"{role_name}: attested SBOM identity mismatch")
            if role.get("raw_reports") != expected["raw_reports"]:
                errors.append(f"{role_name}: attested raw-report hashes mismatch")
            if role.get("findings") != EXPECTED_FINDINGS:
                errors.append(f"{role_name}: attested findings mismatch")
            if role.get("raw_gate_passed") is not False:
                errors.append(f"{role_name}: attested raw gate was rewritten")
        if len(registry_digests) != len(ROLES):
            errors.append("b55 attested registry digests are not unique")
        if len(local_ids) != len(ROLES) or registry_digests & local_ids:
            errors.append("b55 attested local and registry identities overlap")
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
        errors.append(f"malformed b55 publication attestation: {exc}")
    return errors


def _attestation() -> dict[str, Any]:
    if _sha256(ATTESTATION_PATH) != EXPECTED_ATTESTATION_FILE_SHA256:
        raise ValueError("b55 publication attestation file hash mismatch")
    attestation = _load_json(ATTESTATION_PATH)
    errors = validate_attestation(attestation)
    if errors:
        raise ValueError(errors[0])
    return attestation


def _attestation_binding() -> dict[str, str]:
    return {
        "path": str(ATTESTATION_PATH.relative_to(ROOT)),
        "file_sha256": EXPECTED_ATTESTATION_FILE_SHA256,
        "semantic_sha256": EXPECTED_ATTESTATION_SEMANTIC_SHA256,
    }


def build_evidence(
    attestation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = _source()
    if attestation is None:
        attestation = _attestation()
    else:
        errors = validate_attestation(attestation, source)
        if errors:
            raise ValueError(errors[0])
    components = source["roles"]["api"]["sbom"]["component_refs"]
    if _canonical_jsonl_sha256(components) != EXPECTED_COMPONENT_REFS_JSONL_SHA256:
        raise ValueError("vulnerable SBOM component refs changed")

    roles: dict[str, Any] = {}
    for role_name in ROLES:
        observed = attestation["roles"][role_name]
        roles[role_name] = {
            "target": observed["target"],
            "tag": observed["tag"],
            "local_image_id": observed["observed_local_image_id"],
            "config_digest": observed["observed_config_digest"],
            "push_digest": observed["observed_push_digest"],
            "manifest_digest": observed["observed_manifest_digest"],
            "control_plane_digest": observed["observed_control_plane_digest"],
            "registry_digest": observed["observed_control_plane_digest"],
            "platform": observed["platform"],
            "manifest": observed["manifest"],
            "push": observed["push"],
            "registry_status": observed["registry_status"],
            "entrypoint": observed["entrypoint"],
            "cmd": observed["cmd"],
            "sbom": observed["sbom"],
            "raw_reports": observed["raw_reports"],
            "findings": observed["findings"],
            "raw_gate_passed": observed["raw_gate_passed"],
        }

    scope = attestation["scope"]
    return {
        "manifest_version": 1,
        "task": TASK_ID,
        "application_revision": RELEASE_COMMIT,
        "platform": "linux/amd64",
        "builder": {
            "runner_architecture": attestation["runner_architecture"],
            "evidence_created": attestation["evidence_created"],
            "publication_recorded": attestation["generated_at"],
        },
        "publication_attestation_binding": _attestation_binding(),
        "source_candidate_binding": _source_binding(),
        "stage_a_binding": attestation["stage_a"],
        "base_images": source["base_images"],
        "scanner": {
            **source["scanner"],
            "cache": attestation["scanner_cache"],
        },
        "retained_publication_evidence": attestation[
            "retained_publication_evidence"
        ],
        "registry": {
            "repository": attestation["repository"],
            "controls": attestation["publication_controls"],
        },
        "cleanup": attestation["cleanup"],
        "components": components,
        "roles": roles,
        "vulnerability_rows_per_role": source["vulnerability_rows_per_role"],
        "decision": {
            "status": "not_affected_for_exact_registry_products",
            "raw_reports_rewritten": False,
            "registry_access_performed": scope["registry_publication_complete"],
            "acr_push_completed": scope["registry_publication_complete"],
            "control_plane_tag_digest_binding_verified": True,
            "temporary_publication_access_cleaned": True,
            "production_private_registry_path_restored": True,
            "cloud_control_plane_changes_performed": scope[
                "cloud_control_plane_changed"
            ],
            "temporary_identity_changes_performed": scope[
                "temporary_identity_changed"
            ],
            "private_endpoint_changes_performed": scope[
                "private_endpoint_changed"
            ],
            "production_exception": False,
            "deployment_authorization": scope["deployment_authorized"],
            "api_c_canary_completed": scope["api_c_canary_completed"],
            "business_provider_calls": int(scope["business_provider_called"]),
            "business_writes": 0,
            "services_restarted_or_redeployed": int(
                scope["service_restarted"]
            ),
            "public_traffic_changes": int(scope["public_traffic_changed"]),
        },
    }


def _bom_link(role: dict[str, Any], component_ref: str) -> str:
    serial = role["sbom"]["serial_number"]
    if not serial.startswith("urn:uuid:"):
        raise ValueError("invalid SBOM serial number")
    return (
        f"urn:cdx:{serial.removeprefix('urn:uuid:')}/"
        f"{role['sbom']['version']}#{component_ref}"
    )


def build_vex(
    evidence: dict[str, Any],
    source: dict[str, Any],
) -> dict[str, Any]:
    vulnerabilities: list[dict[str, Any]] = []
    for cve in sorted(source_bundle.native.EXPECTED_PACKAGES):
        disposition = source["dispositions"][cve]
        refs = sorted(
            _bom_link(
                evidence["roles"][role_name],
                evidence["components"][package],
            )
            for role_name in ROLES
            for package in source_bundle.native.EXPECTED_PACKAGES[cve]
        )
        vulnerabilities.append(
            {
                "bom-ref": f"urn:noteai:vulnerability-disposition:{cve}",
                "id": cve,
                "source": {
                    "name": "CVE",
                    "url": f"https://www.cve.org/CVERecord?id={cve}",
                },
                "advisories": [
                    {
                        "title": "Debian Security Tracker",
                        "url": f"https://security-tracker.debian.org/tracker/{cve}",
                    }
                ],
                "analysis": {
                    "state": "not_affected",
                    "justification": disposition["justification"],
                    "detail": disposition["detail"],
                    "firstIssued": evidence["builder"]["publication_recorded"],
                    "lastUpdated": evidence["builder"]["publication_recorded"],
                },
                "affects": [{"ref": ref} for ref in refs],
            }
        )

    components = []
    for role_name in ROLES:
        role = evidence["roles"][role_name]
        components.append(
            {
                "bom-ref": (
                    f"urn:noteai:container:{role_name}:"
                    f"{role['registry_digest'].replace(':', '-')}"
                ),
                "type": "container",
                "group": "NoteAI",
                "name": f"{role_name}-runtime",
                "version": RELEASE_COMMIT,
                "properties": [
                    {
                        "name": "noteai:local-image-id",
                        "value": role["local_image_id"],
                    },
                    {
                        "name": "noteai:registry-digest",
                        "value": role["registry_digest"],
                    },
                    {"name": "noteai:image-tag", "value": role["tag"]},
                    {
                        "name": "noteai:sbom-sha256",
                        "value": role["sbom"]["sha256"],
                    },
                    {
                        "name": "noteai:raw-vulnerability-report-sha256",
                        "value": role["raw_reports"]["vulnerability_sha256"],
                    },
                ],
            }
        )

    return {
        "$schema": "http://cyclonedx.org/schema/bom-1.6.schema.json",
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, TASK_ID)}",
        "version": 1,
        "metadata": {
            "timestamp": evidence["builder"]["publication_recorded"],
            "authors": [{"name": "NoteAI Production Release Management"}],
            "component": {
                "bom-ref": (
                    f"urn:noteai:release:{RELEASE_SHORT}-registry-five-role"
                ),
                "type": "application",
                "group": "NoteAI",
                "name": "registry-five-role-release-candidate",
                "version": RELEASE_COMMIT,
                "properties": [
                    {"name": "noteai:task", "value": TASK_ID},
                    {"name": "noteai:platform", "value": "linux/amd64"},
                    {
                        "name": "noteai:production-exception",
                        "value": "false",
                    },
                    {
                        "name": "noteai:deployment-authorization",
                        "value": "false",
                    },
                    {
                        "name": "noteai:api-c-canary-completed",
                        "value": "false",
                    },
                    {
                        "name": "noteai:registry-digest-binding",
                        "value": "five-exact-control-plane-readbacks",
                    },
                    {
                        "name": "noteai:raw-trivy-report",
                        "value": "canonical-and-unsuppressed",
                    },
                ],
            },
        },
        "components": components,
        "vulnerabilities": vulnerabilities,
    }


def build_review(
    evidence: dict[str, Any],
    vex: dict[str, Any],
    *,
    evidence_sha256: str,
    vex_sha256: str,
) -> dict[str, Any]:
    return {
        "review_version": 1,
        "task": TASK_ID,
        "reviewer": "production-release-manager:/root",
        "result": "PASS",
        "application_revision": RELEASE_COMMIT,
        "roles": list(ROLES),
        "reviewed_cves": sorted(source_bundle.native.EXPECTED_PACKAGES),
        "evidence_sha256": evidence_sha256,
        "vex_sha256": vex_sha256,
        "checks": {
            "exact_b55_tags": True,
            "five_unique_registry_manifest_digests": True,
            "push_manifest_control_plane_three_way_binding": True,
            "five_pushes_serial_and_no_retry": True,
            "native_amd64": True,
            "raw_reports_canonical_and_unsuppressed": True,
            "raw_critical_per_role": 4,
            "raw_high_per_role": 19,
            "secret_findings_per_role": 0,
            "browser_components_per_role": 0,
            "cryptography_48_0_1_per_role": 1,
            "cyclonedx_exact_bom_links": True,
            "retained_evidence_secret_free": True,
            "temporary_publication_access_cleanup": True,
            "production_private_registry_path_restored": True,
            "api_nodes_post_health_and_isolation": True,
            "production_exception": False,
            "deployment_authorization": False,
            "api_c_canary_completed": False,
        },
        "scope": {
            "registry_publication_complete": True,
            "registry_changed": True,
            "cloud_control_plane_changed": True,
            "temporary_identity_changed": True,
            "private_endpoint_changed": True,
            "application_deployed": False,
            "database_changed": False,
            "business_provider_called": False,
            "service_restarted": False,
            "public_traffic_changed": False,
            "local_image_ids_are_registry_digests": False,
        },
        "cyclonedx_schema_validation": {
            "specification_commit": "55343ba19dee1785acf1ce9191540d5fd7b590db",
            "schema": "schema/bom-1.6.schema.json",
            "schema_sha256": (
                "3e92dddbc30cf7f6a02b80f0942b1a4cfd4fb1c26f1dfc4310afa9d613cafb93"
            ),
            "validation_errors": 0,
        },
        "evidence_semantic_sha256": _canonical_sha256(evidence),
        "vex_semantic_sha256": _canonical_sha256(vex),
        "source_candidate_evidence_semantic_sha256": evidence[
            "source_candidate_binding"
        ]["evidence_semantic_sha256"],
        "re_review_required_on": [
            "application revision, exact tag or registry manifest digest changes",
            "local image ID, SBOM or package inventory changes",
            "base image or architecture changes",
            "entrypoint, command or subprocess graph changes",
            "runtime capabilities, devices, mounts or namespaces change",
            "official vulnerability scope changes",
        ],
    }


def validate_documents(
    evidence: dict[str, Any],
    vex: dict[str, Any],
    review: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    try:
        source = _source()
        _attestation()
        expected_evidence = build_evidence()
        if evidence != expected_evidence:
            errors.append("b55 registry evidence differs from exact observed facts")
        if evidence.get("manifest_version") != 1:
            errors.append("b55 registry evidence manifest version mismatch")
        if evidence.get("task") != TASK_ID:
            errors.append("b55 registry evidence task mismatch")
        if evidence.get("application_revision") != RELEASE_COMMIT:
            errors.append("b55 registry evidence revision mismatch")
        if evidence.get("platform") != "linux/amd64":
            errors.append("b55 registry evidence platform mismatch")
        if (
            _canonical_sha256(evidence)
            != EXPECTED_REGISTRY_EVIDENCE_SEMANTIC_SHA256
        ):
            errors.append("b55 registry evidence semantic hash mismatch")
        if evidence.get("stage_a_binding") != EXPECTED_STAGE_A:
            errors.append("b55 Stage A acceptance binding mismatch")
        if (
            evidence.get("publication_attestation_binding")
            != _attestation_binding()
        ):
            errors.append("b55 publication attestation binding mismatch")
        if evidence.get("source_candidate_binding") != _source_binding():
            errors.append("b55 source-candidate binding mismatch")
        if evidence.get("base_images") != source.get("base_images"):
            errors.append("b55 registry base images mismatch")
        if (
            evidence.get("retained_publication_evidence")
            != EXPECTED_RETAINED_EVIDENCE
        ):
            errors.append("b55 retained publication-evidence contract mismatch")
        if evidence.get("registry") != {
            "repository": EXPECTED_REPOSITORY,
            "controls": EXPECTED_PUBLICATION_CONTROLS,
        }:
            errors.append("b55 registry publication controls mismatch")
        if evidence.get("cleanup") != EXPECTED_CLEANUP:
            errors.append("b55 registry cleanup evidence mismatch")
        if (
            evidence.get("vulnerability_rows_per_role")
            != source.get("vulnerability_rows_per_role")
        ):
            errors.append("b55 registry vulnerability row set mismatch")
        if (
            _canonical_jsonl_sha256(evidence.get("components"))
            != EXPECTED_COMPONENT_REFS_JSONL_SHA256
        ):
            errors.append("b55 registry vulnerable component refs mismatch")

        roles = evidence.get("roles") or {}
        if set(roles) != set(ROLES):
            errors.append("b55 registry role set mismatch")
        digests: set[str] = set()
        local_ids: set[str] = set()
        for role_name in ROLES:
            role = roles.get(role_name) or {}
            expected = EXPECTED_ROLE_PRODUCTS[role_name]
            digest = str(role.get("registry_digest", ""))
            local_id = str(role.get("local_image_id", ""))
            if role.get("target") != expected["target"]:
                errors.append(f"{role_name}: exact runtime target mismatch")
            if role.get("tag") != EXPECTED_TAGS[role_name]:
                errors.append(f"{role_name}: exact immutable tag mismatch")
            if not DIGEST_RE.fullmatch(digest):
                errors.append(f"{role_name}: invalid registry digest")
            if not DIGEST_RE.fullmatch(local_id) or local_id == digest:
                errors.append(f"{role_name}: invalid local/registry identity boundary")
            digests.add(digest)
            local_ids.add(local_id)
            if {
                role.get("push_digest"),
                role.get("manifest_digest"),
                role.get("control_plane_digest"),
                digest,
            } != {expected["registry_digest"]}:
                errors.append(f"{role_name}: three-way registry digest mismatch")
            if local_id != expected["local_image_id"]:
                errors.append(f"{role_name}: exact local image identity mismatch")
            if role.get("config_digest") != expected["local_image_id"]:
                errors.append(f"{role_name}: config/local image identity mismatch")
            if role.get("platform") != "linux/amd64":
                errors.append(f"{role_name}: registry platform mismatch")
            if role.get("registry_status") != "NORMAL":
                errors.append(f"{role_name}: registry status mismatch")
            if role.get("entrypoint") != expected["entrypoint"]:
                errors.append(f"{role_name}: registry entrypoint mismatch")
            if role.get("cmd") != expected["cmd"]:
                errors.append(f"{role_name}: registry command mismatch")
            if role.get("findings") != EXPECTED_FINDINGS:
                errors.append(f"{role_name}: registry finding counts mismatch")
            if role.get("raw_gate_passed") is not False:
                errors.append(f"{role_name}: raw vulnerability result rewritten")
            if role.get("push") != {
                "state": "PUSH_REPORTED_SUCCESS",
                "return_code": 0,
                "invocations": 1,
                "manual_retries": 0,
                "retained_log_sha256": expected["push_log_sha256"],
            }:
                errors.append(f"{role_name}: push invocation evidence mismatch")
            if role.get("manifest") != {
                "schema_version": 2,
                "media_type": (
                    "application/vnd.docker.distribution.manifest.v2+json"
                ),
                "config_media_type": (
                    "application/vnd.docker.container.image.v1+json"
                ),
                "size": expected["manifest_size"],
                "layer_count": expected["layer_count"],
                "retained_json_sha256": expected["manifest_json_sha256"],
            }:
                errors.append(f"{role_name}: retained manifest evidence mismatch")
            if role.get("raw_reports") != expected["raw_reports"]:
                errors.append(f"{role_name}: raw-report hash inventory mismatch")
            expected_sbom = {
                **expected["sbom"],
                "component_refs_jsonl_sha256": (
                    EXPECTED_COMPONENT_REFS_JSONL_SHA256
                ),
            }
            if role.get("sbom") != expected_sbom:
                errors.append(f"{role_name}: SBOM identity mismatch")
        if len(digests) != len(ROLES):
            errors.append("b55 registry digests are not unique")
        if len(local_ids) != len(ROLES) or digests & local_ids:
            errors.append("b55 local and registry identities overlap")

        decision = evidence.get("decision") or {}
        for key in (
            "production_exception",
            "deployment_authorization",
            "api_c_canary_completed",
            "raw_reports_rewritten",
        ):
            if decision.get(key) is not False:
                errors.append(f"b55 registry decision.{key} must remain false")
        for key in (
            "registry_access_performed",
            "acr_push_completed",
            "control_plane_tag_digest_binding_verified",
            "temporary_publication_access_cleaned",
            "production_private_registry_path_restored",
            "cloud_control_plane_changes_performed",
            "temporary_identity_changes_performed",
            "private_endpoint_changes_performed",
        ):
            if decision.get(key) is not True:
                errors.append(f"b55 registry decision.{key} must remain true")
        if (
            decision.get("business_provider_calls") != 0
            or decision.get("business_writes") != 0
            or decision.get("services_restarted_or_redeployed") != 0
            or decision.get("public_traffic_changes") != 0
        ):
            errors.append("b55 registry publication scope boundary mismatch")

        expected_vex = build_vex(evidence, source)
        if vex != expected_vex:
            errors.append("b55 registry VEX differs from exact evidence")
        if len(vex.get("vulnerabilities") or []) != len(
            source_bundle.native.EXPECTED_PACKAGES
        ):
            errors.append("b55 registry VEX vulnerability count mismatch")
        if sum(
            len(item.get("affects") or [])
            for item in vex.get("vulnerabilities") or []
        ) != 115:
            errors.append("b55 registry VEX BOM-Link count mismatch")
        for item in vex.get("vulnerabilities") or []:
            analysis = item.get("analysis") or {}
            if analysis.get("state") != "not_affected" or "response" in analysis:
                errors.append(
                    f"{item.get('id')}: invalid b55 registry VEX disposition"
                )

        expected_review = build_review(
            evidence,
            vex,
            evidence_sha256=_sha256(EVIDENCE_PATH),
            vex_sha256=_sha256(VEX_PATH),
        )
        if review != expected_review:
            errors.append("b55 registry review differs from exact evidence/VEX")
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
        errors.append(f"malformed b55 registry release bundle: {exc}")
    return errors


def validate_bundle() -> list[str]:
    missing = [
        str(path.relative_to(ROOT))
        for path in (ATTESTATION_PATH, EVIDENCE_PATH, VEX_PATH, REVIEW_PATH)
        if not path.is_file()
    ]
    if missing:
        return [
            f"missing b55 registry release bundle file: {path}"
            for path in missing
        ]
    try:
        return validate_documents(
            _load_json(EVIDENCE_PATH),
            _load_json(VEX_PATH),
            _load_json(REVIEW_PATH),
        )
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot load b55 registry release bundle: {exc}"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the deterministic reduced evidence, VEX and review bundle.",
    )
    args = parser.parse_args()
    if args.write:
        evidence = build_evidence()
        vex = build_vex(evidence, _source())
        _write_json(EVIDENCE_PATH, evidence)
        _write_json(VEX_PATH, vex)
        review = build_review(
            evidence,
            vex,
            evidence_sha256=_sha256(EVIDENCE_PATH),
            vex_sha256=_sha256(VEX_PATH),
        )
        _write_json(REVIEW_PATH, review)
    errors = validate_bundle()
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print(
        "PASS: exact b55f118 five-role private-ACR manifests are bound to "
        "build10 and unsuppressed VEX evidence; API-C canary remains unauthorized"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
