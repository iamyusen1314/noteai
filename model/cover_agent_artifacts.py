"""Editable-Design source bundles in the existing private object store.

The existing cover revision rows are the durable reference index. No HTML is
served to the browser: only the server-side, network-disabled renderer reads it.
"""
from __future__ import annotations

import base64
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import tempfile
import threading
import shutil
import uuid

import content_retention
import db
import durable_ai
import private_storage

ENGINE = "editable-design-c87b16f-opencode-2.1.2"
SCHEMA = "noteai-cover-editable/v1"
ROOT = Path(__file__).resolve().parent
MAX_BUNDLE = 120 * 1024 * 1024
_EDIT_SLOT = threading.BoundedSemaphore(1)


def digest(body):
    return hashlib.sha256(body).hexdigest()


def relative(value):
    if (not isinstance(value, str) or not value or "\\" in value
            or PurePosixPath(value).is_absolute() or any(p in {"", ".", ".."} for p in value.split("/"))):
        raise ValueError("COVER_EDITABLE_PATH_INVALID")
    return value


def cli(command, request, *, _has_slot=False):
    """One local rendering operation; no shell, model or external URL."""
    env = {key: value for key, value in os.environ.items() if key in {
        "PATH", "TMPDIR", "LANG", "LC_ALL", "EDITABLE_DESIGN_BROWSER",
        "PUPPETEER_EXECUTABLE_PATH", "EDITABLE_DESIGN_NO_SANDBOX"}}
    temporary = Path(request["output_root"]).parent / "tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    env["TMPDIR"] = str(temporary)
    if not _has_slot and not _EDIT_SLOT.acquire(timeout=30):
        raise ValueError("COVER_EDITABLE_RENDER_BUSY")
    try:
        result = subprocess.run([os.environ.get("NOTEAI_COVER_NODE", "node"),
            str(ROOT / "cover_editable/cli.mjs"), command],
            input=json.dumps(request, ensure_ascii=False).encode(), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=300, env=env, check=False)
    finally:
        if not _has_slot:
            _EDIT_SLOT.release()
    try:
        output = json.loads(result.stdout)
    except (ValueError, TypeError):
        raise ValueError("COVER_EDITABLE_RENDER_FAILED") from None
    if result.returncode or output.get("ok") is not True:
        raise ValueError("COVER_EDITABLE_" + str(output.get("code", "RENDER_FAILED")))
    return output


def capture(result, *, expected_sources):
    """Capture the actual checked revision, never an arbitrary host file path."""
    directory = Path(result["revision_dir"]).resolve()
    raw = (directory / "render-manifest.json").read_bytes()
    if digest(raw) != result["manifest_sha256"]:
        raise ValueError("COVER_EDITABLE_MANIFEST_CHANGED")
    manifest = json.loads(raw)
    if (manifest.get("schema_version") != SCHEMA or manifest.get("status") != "RENDERED"
            or manifest.get("model_calls") != 0):
        raise ValueError("COVER_EDITABLE_MANIFEST_INVALID")
    selected = {item["ref"]: item["sha256"] for item in manifest["constraints"]["sources"]}
    if not selected or any(expected_sources.get(ref) != sha for ref, sha in selected.items()):
        raise ValueError("COVER_EDITABLE_SOURCE_CHANGED")
    files = {}
    for item in manifest["files"]:
        name = relative(item["path"])
        file = directory / name
        if file.is_symlink() or not file.resolve().is_relative_to(directory) or not file.is_file():
            raise ValueError("COVER_EDITABLE_PATH_INVALID")
        body = file.read_bytes()
        if digest(body) != item["sha256"] or len(body) != item["bytes"]:
            raise ValueError("COVER_EDITABLE_FILE_CHANGED")
        files[name] = base64.b64encode(body).decode("ascii")
    # Parent verification on free edits also needs the exact manifest bytes.
    files["render-manifest.json"] = base64.b64encode(raw).decode("ascii")
    bundle = {"schema_version": SCHEMA, "files": files, "manifest_sha256": digest(raw)}
    encoded = json.dumps(bundle, separators=(",", ":"), sort_keys=True).encode()
    if len(encoded) > MAX_BUNDLE:
        raise ValueError("COVER_EDITABLE_BUNDLE_TOO_LARGE")
    final = base64.b64decode(files["out/poster.png"], validate=True)
    if digest(final) != result["png_sha256"]:
        raise ValueError("COVER_EDITABLE_FINAL_CHANGED")
    checks = manifest["checks"]
    if checks["width"] != 1776 or checks["height"] != 2368 or checks.get("external_requests") != 0:
        raise ValueError("COVER_EDITABLE_RENDER_CONTRACT_INVALID")
    text_layers = [{"id": box["id"], "text": box["text"], "rect": box["rect"], "ink": box.get("ink", [])}
        for box in checks["boxes"]]
    layout = {"schema_version": 3, "route": "photo", "renderer_version": ENGINE,
        "width": 1776, "height": 2368, "final_sha256": digest(final),
        "source_hashes": selected, "input_source_hashes": expected_sources,
        "manifest_sha256": digest(raw), "text_layers": text_layers,
        "text": "\n".join(layer["text"] for layer in text_layers),
        "rendered_lines": [line for layer in text_layers for line in layer["text"].splitlines()],
        "constraints": manifest["constraints"], "base_kind": "final_preview_not_clean_background",
        "edit_delta": manifest.get("edits", []), "initial_qc_ref": manifest.get("initial_qc_ref"),
        "qc_status": manifest["qc_status"]}
    validate_layout(layout, require_reference=False)
    return final, encoded, layout


def validate_layout(layout, *, require_reference=True):
    allowed = {"schema_version", "route", "renderer_version", "width", "height", "final_sha256",
        "source_hashes", "input_source_hashes", "manifest_sha256", "text_layers", "text",
        "rendered_lines", "constraints", "base_kind", "edit_delta", "initial_qc_ref", "qc_status", "editable_ref"}
    if (not isinstance(layout, dict) or set(layout) - allowed or layout.get("schema_version") != 3
            or layout.get("renderer_version") != ENGINE or layout.get("route") != "photo"
            or (layout.get("width"), layout.get("height")) != (1776, 2368)
            or not layout.get("text_layers") or not layout.get("source_hashes")
            or not isinstance(layout.get("text"), str) or len(layout["text"]) > 2000):
        raise ValueError("COVER_EDITABLE_LAYOUT_INVALID")
    for key in ("final_sha256", "manifest_sha256"):
        if not isinstance(layout.get(key), str) or len(layout[key]) != 64:
            raise ValueError("COVER_EDITABLE_HASH_INVALID")
    if require_reference:
        reference(layout["editable_ref"])
    return layout


def position_options(layout, layer_id):
    layer = next((x for x in layout["text_layers"] if x["id"] == layer_id), None)
    constraint = next((x for x in layout["constraints"]["text_layers"] if x["id"] == layer_id), None)
    if not layer or not constraint:
        return {}
    rect, allowed = layer["rect"], constraint["allowed_rect"]
    shapes = [rect, *layer.get("ink", [])]
    top = min(shape["y"] for shape in shapes)
    bottom = max(shape["y"] + shape["height"] for shape in shapes)
    positions = {}
    for name, dy in (("top", allowed["y"] - top), ("bottom", allowed["y"] + allowed["height"] - bottom)):
        candidates = [{**shape, "y": shape["y"] + dy} for shape in shapes]
        intersects = lambda a, b: a["x"] < b["x"] + b["width"] and b["x"] < a["x"] + a["width"] and a["y"] < b["y"] + b["height"] and b["y"] < a["y"] + a["height"]
        if (min(shape["y"] for shape in candidates) >= allowed["y"]
                and max(shape["y"] + shape["height"] for shape in candidates) <= allowed["y"] + allowed["height"]
                and not any(intersects(candidate, protected) for candidate in candidates for protected in layout["constraints"]["protected_regions"])):
            positions[name] = dy
    return positions


def adjust(user_id, job_id, layout, *, text, position, layer_id, revision, ttl_seconds):
    layer_id = layer_id or layout["text_layers"][0]["id"]
    if not any(layer["id"] == layer_id for layer in layout["text_layers"]):
        raise ValueError("COVER_EDITABLE_LAYER_INVALID")
    delta = {"layer_id": layer_id, "text": text}
    if position:
        options = position_options(layout, layer_id)
        if position not in options:
            raise ValueError("COVER_EDITABLE_POSITION_INVALID")
        delta["dy"] = options[position]
    if not _EDIT_SLOT.acquire(timeout=30):
        raise ValueError("COVER_EDITABLE_RENDER_BUSY")
    import cover_agent_runtime
    temporary = None
    try:
        bundle = validate_saved(user_id, layout)
        temporary = cover_agent_runtime.prepare_edit_workspace(user_id, job_id)
        source = restore(bundle, temporary / "source")
        result = cli("edit", {"schema_version": SCHEMA, "output_root": str(Path(temporary) / "revisions"),
            "parent_revision_dir": str(source), "expected_parent_manifest_sha256": layout["manifest_sha256"],
            "edits": [delta], "initial_qc_ref": layout["initial_qc_ref"]}, _has_slot=True)
        final, encoded, updated = capture(result, expected_sources=layout["input_source_hashes"])
    finally:
        if temporary is not None:
            shutil.rmtree(temporary)
        _EDIT_SLOT.release()
    updated["editable_ref"] = store(user_id, job_id, encoded, revision=revision, ttl_seconds=ttl_seconds)
    return final, updated


def reference(value):
    if not isinstance(value, dict) or set(value) != set(durable_ai.PayloadReference.__dataclass_fields__) - {"created"}:
        raise ValueError("COVER_EDITABLE_REFERENCE_INVALID")
    ref = durable_ai.PayloadReference(**value)
    if ref.purpose != "result" or ref.state not in {"ready", "deleted"} or ref.size_bytes > MAX_BUNDLE:
        raise ValueError("COVER_EDITABLE_REFERENCE_INVALID")
    return ref


def store(user_id, job_id, bundle, *, revision=1, ttl_seconds=90 * 86400):
    # A failed PNG save may leave an unindexed source candidate. A later free
    # edit is another candidate for the same CAS revision, not the same bytes.
    op_id = str(uuid.uuid5(uuid.UUID(job_id), "editable-source:" + str(revision) + ":" + digest(bundle)))
    with db.transaction(write=True) as tx:
        content_retention.assert_user_writable_with_storage(tx, user_id)
        lock = " FOR UPDATE" if tx.postgres else ""
        job = tx.fetchone("SELECT design_json FROM cover_jobs WHERE id=? AND user_id=?" + lock, (job_id, user_id))
        if not job:
            raise ValueError("COVER_EDITABLE_OWNER_JOB_REQUIRED")
        private_storage._assert_media_capacity(tx,
            __import__("idempotency").operation_subject_hash(user_id), len(bundle))
        ref = private_storage.PrivateObjectPayloadStore().put(operation_id=op_id,
            user_id=user_id, purpose="result", payload=bundle, item_count=1, ttl_seconds=ttl_seconds)
        descriptor = {key: value for key, value in asdict(ref).items() if key != "created"}
        design = json.loads(job["design_json"] or "{}")
        design.setdefault("editable_pending_refs", {})[ref.id] = descriptor
        tx.execute("UPDATE cover_jobs SET design_json=? WHERE id=?", (json.dumps(design), job_id))
    return descriptor


def load(user_id, layout):
    validate_layout(layout)
    return private_storage.PrivateObjectPayloadStore().get(reference(layout["editable_ref"]), user_id=user_id)


def restore(bundle, directory):
    value = json.loads(bundle)
    if value.get("schema_version") != SCHEMA or not isinstance(value.get("files"), dict):
        raise ValueError("COVER_EDITABLE_BUNDLE_INVALID")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    for name, encoded in value["files"].items():
        file = directory / relative(name)
        body = base64.b64decode(encoded, validate=True)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(body)
    if digest((directory / "render-manifest.json").read_bytes()) != value["manifest_sha256"]:
        raise ValueError("COVER_EDITABLE_MANIFEST_CHANGED")
    return directory


def validate_saved(user_id, layout, *, final_bytes=None):
    raw = load(user_id, layout)
    value = json.loads(raw)
    manifest_raw = base64.b64decode(value["files"]["render-manifest.json"], validate=True)
    manifest = json.loads(manifest_raw)
    if (digest(manifest_raw) != layout["manifest_sha256"]
            or manifest["constraints"] != layout["constraints"]
            or {item["ref"]: item["sha256"] for item in manifest["constraints"]["sources"]} != layout["source_hashes"]):
        raise ValueError("COVER_EDITABLE_SAVED_SOURCE_CHANGED")
    for file in manifest["files"]:
        body = base64.b64decode(value["files"][relative(file["path"])], validate=True)
        if digest(body) != file["sha256"] or len(body) != file["bytes"]:
            raise ValueError("COVER_EDITABLE_FILE_CHANGED")
    poster = base64.b64decode(value["files"]["out/poster.png"], validate=True)
    if (layout["final_sha256"] != digest(poster)
            or not any(file["path"] == "out/poster.png" and file["sha256"] == digest(poster) for file in manifest["files"])):
        raise ValueError("COVER_EDITABLE_FINAL_CHANGED")
    layers = [{"id": box["id"], "text": box["text"], "rect": box["rect"], "ink": box.get("ink", [])} for box in manifest["checks"]["boxes"]]
    if (layout["text_layers"] != layers or layout["text"] != "\n".join(layer["text"] for layer in layers)
            or layout["rendered_lines"] != [line for layer in layers for line in layer["text"].splitlines()]):
        raise ValueError("COVER_EDITABLE_TEXT_CHANGED")
    for source in manifest["constraints"]["sources"]:
        if digest(base64.b64decode(value["files"][relative(source["path"])], validate=True)) != source["sha256"]:
            raise ValueError("COVER_EDITABLE_SOURCE_CHANGED")
    if final_bytes is not None and digest(final_bytes) != layout["final_sha256"]:
        raise ValueError("COVER_EDITABLE_FINAL_CHANGED")
    return raw


def _indexed_layouts(*, user_id=None, reference_id=None, expires_before=None, limit=None):
    # Optional feature: don't query a nonexistent table in a shared transaction.
    exists = db.fetchone("SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='cover_asset_revisions'"
        if db.using_postgres() else "SELECT 1 FROM sqlite_master WHERE type='table' AND name='cover_asset_revisions'")
    if not exists:
        return []
    def field(name):
        return ("r.layout_json::jsonb->'editable_ref'->>'" + name + "'" if db.using_postgres()
            else "json_extract(r.layout_json,'$.editable_ref." + name + "')")
    clauses, args = [], []
    for clause, value in (("j.user_id=?", user_id), (field("id") + "=?", reference_id),
                          (field("expires_at") + "<=?", expires_before)):
        if value is not None:
            clauses.append(clause)
            args.append(value)
    if expires_before is not None:
        clauses.append(field("state") + "='ready'")
        deleted = ("j.design_json::jsonb->'editable_source_deletions'->>(" + field("id") + ")"
            if db.using_postgres() else "json_extract(j.design_json,'$.editable_source_deletions.' || " + field("id") + ")")
        clauses.append(deleted + " IS NULL")
    sql = "SELECT r.job_id,r.revision,r.layout_json FROM cover_asset_revisions r JOIN cover_jobs j ON j.id=r.job_id"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY r.job_id,r.revision"
    if limit is not None:
        sql += " LIMIT ?"
        args.append(limit)
    return db.fetchall(sql, tuple(args))


def active_bundle_totals(storage, subject_hash):
    postgres = getattr(storage, "postgres", db.using_postgres())
    exists = storage.fetchone("SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='cover_asset_revisions'"
        if postgres else "SELECT 1 FROM sqlite_master WHERE type='table' AND name='cover_asset_revisions'")
    if not exists:
        return 0, 0
    field = "layout_json::jsonb->'editable_ref'->>'subject_hash'" if postgres else "json_extract(layout_json,'$.editable_ref.subject_hash')"
    field = "r." + field if postgres else field.replace("layout_json", "r.layout_json")
    rows = storage.fetchall("SELECT r.layout_json,j.design_json FROM cover_asset_revisions r JOIN cover_jobs j ON j.id=r.job_id WHERE " + field + "=?", (subject_hash,))
    refs = {}
    for row in rows:
        value = json.loads(row["layout_json"])["editable_ref"]
        deleted = json.loads(row["design_json"] or "{}").get("editable_source_deletions", {})
        if value["state"] == "ready" and value["id"] not in deleted:
            refs[value["id"]] = int(value["size_bytes"])
    for row in _pending_references(storage, subject_hash=subject_hash):
        value = row["reference"]
        refs[value["id"]] = int(value["size_bytes"])
    return len(refs), sum(refs.values())


def _pending_references(storage=db, *, user_id=None, subject_hash=None, reference_id=None, expires_before=None, limit=None):
    postgres = getattr(storage, "postgres", db.using_postgres())
    exists = storage.fetchone("SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='cover_jobs'"
        if postgres else "SELECT 1 FROM sqlite_master WHERE type='table' AND name='cover_jobs'")
    if not exists:
        return []
    each = ("jsonb_each(COALESCE(j.design_json::jsonb->'editable_pending_refs','{}'::jsonb)) p"
        if postgres else "json_each(COALESCE(json_extract(j.design_json,'$.editable_pending_refs'),'{}')) p")
    field = lambda key: "p.value->>'" + key + "'" if postgres else "json_extract(p.value,'$." + key + "')"
    deleted = ("j.design_json::jsonb->'editable_source_deletions'->>(" + field("id") + ")"
        if postgres else "json_extract(j.design_json,'$.editable_source_deletions.' || " + field("id") + ")")
    clauses, args = [field("state") + "='ready'", deleted + " IS NULL"], []
    for clause, value in (("j.user_id=?", user_id), (field("subject_hash") + "=?", subject_hash),
                          (field("id") + "=?", reference_id), (field("expires_at") + "<=?", expires_before)):
        if value is not None:
            clauses.append(clause)
            args.append(value)
    sql = "SELECT j.id AS job_id,p.value AS reference_json FROM cover_jobs j," + each + " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY j.id,p.key"
    if limit is not None:
        sql += " LIMIT ?"
        args.append(limit)
    rows = storage.fetchall(sql, tuple(args))
    return [{"job_id": row["job_id"], "reference": json.loads(row["reference_json"])
        if isinstance(row["reference_json"], str) else row["reference_json"]} for row in rows]


def has_reference(reference_id):
    return bool(_indexed_layouts(reference_id=reference_id, limit=1) or _pending_references(reference_id=reference_id, limit=1))


def delete_bundles(*, user_id=None, expired_only=False, backend=None, now=None, limit=None):
    clock = (now or datetime.now(timezone.utc)).isoformat()
    seen = set()
    store = private_storage.PrivateObjectPayloadStore(backend=backend)
    rows = []
    for row in _indexed_layouts(user_id=user_id, expires_before=clock if expired_only else None, limit=limit):
        layout = json.loads(row["layout_json"])
        if layout.get("schema_version") == 3:
            rows.append({"job_id": row["job_id"], "reference": layout["editable_ref"]})
    rows.extend(_pending_references(user_id=user_id, expires_before=clock if expired_only else None, limit=limit))
    for row in rows:
        ref = reference(row["reference"])
        if ref.state == "deleted" or ref.id in seen or (expired_only and ref.expires_at > clock):
            continue
        if limit is not None and len(seen) >= limit:
            break
        # For expiry the descriptor's owner is intentionally used only to form
        # its exact opaque key; no content is read or returned.
        key = private_storage._payload_key(ref.id, ref.subject_hash, ref.purpose)
        if digest(key.encode()) != ref.object_key_hash or not store._backend().delete(key):
            raise private_storage.ObjectStorageUnavailable("COVER_EDITABLE_DELETE_UNCONFIRMED")
        with db.transaction(write=True) as tx:
            # Revision rows stay immutable (the existing app role has no UPDATE
            # privilege on them). Use the already writable job for lifecycle
            # receipts; original design fields and supplier history stay intact.
            lock = " FOR UPDATE" if tx.postgres else ""
            current = tx.fetchone("SELECT design_json FROM cover_jobs WHERE id=?" + lock, (row["job_id"],))
            design = json.loads(current["design_json"] or "{}") if current else {}
            design.setdefault("editable_source_deletions", {})[ref.id] = clock
            tx.execute("UPDATE cover_jobs SET design_json=? WHERE id=?", (json.dumps(design), row["job_id"]))
        seen.add(ref.id)
    return len(seen)
