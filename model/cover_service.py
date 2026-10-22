"""One bounded cover worker hosted by the existing API process.

HTTP submit/query lifetimes do not own this worker. Persisted jobs own recovery;
only an original unstarted job can resume automatically after a process loss.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timezone

from fastapi import HTTPException

import billing
import cover_jobs
import cover_runtime
import cover_settings
import db
import model_admission
import private_storage
import public_product


def _store_image(user_id, body, *, ttl_seconds=cover_settings.RETENTION_SECONDS):
    return private_storage.store_media_bytes(user_id, purpose="image", content_type="image/png",
        payload=body, item_count=1, ttl_seconds=ttl_seconds, lifecycle="cover_v1")


def _run_claim(claim, *, runtime=None):
    user_id, job_id = claim["user_id"], claim["request_id"]
    invocation = public_product.Invocation(user_id, job_id, route="/covers",
        budget_id=claim["policy_snapshot"].get("budget_id", cover_settings.BUDGET_ID))
    operation, owns = model_admission.current().register(user_id,
        hashlib.sha256(job_id.encode()).hexdigest(), route="/covers")
    invocation.admission_state = operation
    marker = public_product._invocation.set(invocation)
    usage_marker = billing._ACTIVE_USAGE_ID.set(claim["charge"]["usage_id"])
    heartbeat_stop = threading.Event()
    candidate_refs = {}

    def heartbeat():
        while not heartbeat_stop.wait(30):
            try:
                cover_jobs.heartbeat_job(claim)
            except Exception:
                # A lost fence must never authorize another supplier dispatch.
                invocation.failure = "COVER_WORKER_FENCE_UNCONFIRMED"
                return

    pulse = threading.Thread(target=heartbeat, name="noteai-cover-heartbeat", daemon=True)
    pulse.start()

    def on_stage(stage):
        public_product.assert_result_known()
        mapped = {"render": "image", "local_adjustment": "qc", "ready_to_save": "saving"}.get(stage, stage)
        cover_jobs.mark_stage(claim, mapped)

    def before(stage, call_id, estimate):
        public_product.assert_result_known()
        if stage == "image":
            cover_jobs.begin_image_call(claim, call_id=call_id, provider=estimate["provider"],
                model_id=estimate["model_id"], input_images=estimate["input_images"],
                width=estimate["width"], height=estimate["height"],
                pricing_snapshot=estimate["pricing_snapshot"], estimated_cost=estimate["estimated_cost"],
                currency=estimate["currency"], price_version=estimate["price_version"])
        else:
            cover_jobs.before_text_call(claim, stage, call_id)

    def after(record):
        if record.get("stage") == "image":
            cover_jobs.finish_image_call(claim, record["call_id"], status=record["status"],
                output_images=record.get("output_images", 0), billed_images=record.get("billed_images"),
                actual_cost=record.get("actual_cost"), evidence_ref=record.get("evidence_ref"),
                response_hash=record.get("response_hash"), http_status=record.get("http_status"),
                provider_request_id=record.get("provider_request_id"))

    def on_design(snapshot):
        public_product.assert_result_known()
        try:
            cover_jobs.record_design_snapshot(claim, snapshot)
        except Exception:
            raise cover_runtime.CoverRuntimeError("COVER_DESIGN_CHECKPOINT_FAILED") from None

    def on_candidate(snapshot, body):
        digest = hashlib.sha256(body).hexdigest()
        reference = candidate_refs.get(digest)
        if reference is None:
            reference = _store_image(user_id, body).id
            candidate_refs[digest] = reference
        cover_jobs.record_agent_candidate(claim, snapshot, reference)

    try:
        if claim["policy_snapshot"].get("design_version") == 3:
            import cover_agent_runtime
            cover_agent_runtime.prepare_original_workspace(claim)
        sources = []
        for item in claim["source_manifest"]:
            _, body = private_storage.load_media_bytes(item["media_ref"], user_id=user_id, purpose="image")
            if hashlib.sha256(body).hexdigest() != item["sha256"]:
                raise cover_runtime.CoverRuntimeError("COVER_SOURCE_HASH_CHANGED")
            sources.append({**item, "payload": body})
        result = (runtime or cover_runtime.run_cover)(job_id=job_id, user_id=user_id,
            report=claim["input_snapshot"], sources=sources,
            design_version=claim["policy_snapshot"].get("design_version", 1),
            hooks=cover_runtime.RuntimeHooks(before_call=before, on_call=after,
                on_stage=on_stage, on_design=on_design, on_candidate=on_candidate))
        # A usable artifact must pass the actual final-pixel contract before
        # storage, as well as before the delivery settlement transaction.
        cover_runtime._validate_qc(result.qc)
        on_stage("ready_to_save")
        base = _store_image(user_id, result.base_bytes)
        final = _store_image(user_id, result.final_bytes)
        if result.layout.get("schema_version") == 3:
            import cover_agent_artifacts
            result.layout["editable_ref"] = cover_agent_artifacts.store(user_id, job_id,
                result.artifact["editable_bundle"])
        qc = result.qc
        return cover_jobs.complete_job(claim, final_media_ref=final.id, base_media_ref=base.id,
            layout=result.layout, qc_passed=True, qc_snapshot=qc, design_snapshot=result.design)
    except Exception as exc:
        # First read back the original transaction after a possible lost ACK.
        # A committed cover is never released or charged again.
        existing = cover_jobs.get_job(user_id, job_id)
        if existing and existing["status"] == "completed":
            return existing
        unknown = bool(getattr(exc, "outcome_unknown", False))
        code = getattr(exc, "code", None)
        if not isinstance(code, str) or not code.startswith(("COVER_", "ARK_")):
            code = "COVER_ORIGINAL_RESULT_UNCONFIRMED" if unknown else "COVER_DELIVERY_FAILED"
        try:
            cover_jobs.fail_job(claim, failure_code=code, outcome_unknown=unknown)
        except Exception:
            # Persisted lease/dispatch intent is the recovery fence. It is not
            # permission to replay the request or assume a financial rollback.
            logging.warning("cover_terminal_requires_readback job_id=%s", job_id)
        return cover_jobs.get_job(user_id, job_id)
    finally:
        heartbeat_stop.set()
        pulse.join(timeout=1)
        billing._ACTIVE_USAGE_ID.reset(usage_marker)
        public_product._invocation.reset(marker)
        if owns:
            model_admission.current().finish(operation)
        if claim["policy_snapshot"].get("design_version") == 3:
            import cover_agent_runtime
            try:
                cover_agent_runtime.cleanup_workspace(job_id)
            except (OSError, ValueError):
                logging.warning("cover_workspace_cleanup_requires_reconcile job_id=%s", job_id)


def run_next(*, runtime=None):
    """One worker slot; blocked users do not monopolize the pending queue."""
    cover_jobs.recover_jobs()
    import cover_agent_runtime
    cover_agent_runtime.cleanup_stale_workspaces(limit=16)
    rows = db.fetchall("SELECT q.id,q.user_id FROM cover_jobs q WHERE q.status='queued' AND NOT EXISTS "
        "(SELECT 1 FROM cover_jobs p WHERE p.status='queued' AND p.user_id=q.user_id AND "
        "(p.created_at<q.created_at OR (p.created_at=q.created_at AND p.id<q.id))) "
        "ORDER BY q.created_at,q.id LIMIT 32")
    for row in rows:
        admission = model_admission.current()
        with admission.lock:
            if len(admission.operations) >= admission.limits.operations:
                return None
            if sum(uid == row["user_id"] for uid, _ in admission.operations) >= admission.limits.operations_per_user:
                continue
        claim = cover_jobs.claim_job(row["id"])
        if claim:
            try:
                return _run_claim(claim, runtime=runtime)
            except model_admission.AdmissionError:
                # A report won the race before any cover provider call. Its
                # original provider-free lease can be recovered after expiry.
                return None
    return None


class CoverWorker:
    def __init__(self):
        self.stopping = asyncio.Event()
        self.task = None

    def start(self):
        if self.task is None:
            self.task = asyncio.create_task(self.loop())
        return self

    async def loop(self):
        while not self.stopping.is_set():
            try:
                await asyncio.to_thread(run_next)
            except Exception:
                logging.warning("cover_worker_state_requires_verification")
            try:
                await asyncio.wait_for(self.stopping.wait(), timeout=1)
            except asyncio.TimeoutError:
                pass

    async def stop(self):
        self.stopping.set()
        if self.task is not None:
            # Never interpret API shutdown as a user cancellation. A forced
            # process loss is handled by the persisted original lease/intents.
            await asyncio.shield(self.task)


def adjust(user_id, job_id, *, text, position, expected_revision, layer_id=None):
    job = cover_jobs.get_job(user_id, job_id)
    if not job or not job["has_final"]:
        raise HTTPException(404, "可调整的封面不存在或已过期")
    if job["asset_revision"] != expected_revision:
        raise HTTPException(409, "封面已更新，请重新打开")
    row = db.fetchone("SELECT layout_json,expires_at FROM cover_jobs WHERE id=? AND user_id=?", (job_id, user_id))
    layout = json.loads(row["layout_json"])
    remaining = max(60, min(cover_settings.RETENTION_SECONDS,
        int((datetime.fromisoformat(row["expires_at"]) - datetime.now(timezone.utc)).total_seconds()) + 1))
    if layout.get("schema_version") == 3:
        import cover_agent_artifacts
        try:
            final, updated = cover_agent_artifacts.adjust(user_id, job_id, layout, text=text,
                position=position, layer_id=layer_id, revision=expected_revision + 1, ttl_seconds=remaining)
        except ValueError as exc:
            if str(exc) == "COVER_EDITABLE_RENDER_BUSY":
                raise HTTPException(429, "排字处理中，请稍后重试；原成品仍可下载") from None
            raise HTTPException(422, "文字超出安全区域或源文件不可读，请缩短文字或保留原位置") from None
        stored = _store_image(user_id, final, ttl_seconds=remaining)
        return cover_jobs.update_adjusted_asset(user_id, job_id, final_media_ref=stored.id,
            layout=updated, expected_revision=expected_revision)
    base_ref = cover_jobs.asset_reference(user_id, job_id, base=True)
    _, base = private_storage.load_media_bytes(base_ref, user_id=user_id, purpose="image")
    xy = None
    if position is not None:
        if position not in job["layout"]["position_options"]:
            raise HTTPException(422, "该位置会遮挡照片，请保留当前位置或选择可用位置")
        box = layout["text_bbox"]
        margin = .025 if layout.get("schema_version") == 2 else .035
        xy = [box[0], margin if position == "top" else 1 - margin - (box[3] - box[1])]
    final, updated = cover_runtime.free_adjust(base, layout, text=text, position=xy)
    # New revision bytes may live a few seconds beyond the deadline, but all
    # job reads are still fenced by the original exact expiry, never extended.
    remaining = max(60, min(cover_settings.RETENTION_SECONDS,
        int((datetime.fromisoformat(row["expires_at"]) - datetime.now(timezone.utc)).total_seconds()) + 1))
    stored = _store_image(user_id, final, ttl_seconds=remaining)
    return cover_jobs.update_adjusted_asset(user_id, job_id, final_media_ref=stored.id,
        layout=updated, expected_revision=expected_revision)
