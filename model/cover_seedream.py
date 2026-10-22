"""One bounded Seedream Pro background call, with no retry or model fallback.

Official wire reference: https://docs.volcengine.com/docs/ark/image-generation-api
The shared public call guard owns dispatch and physical capacity; the cover
ledger owns image-based supplier estimates separately from text-token usage.
Supplier temporary URLs are never accepted as a saved NoteAI deliverable.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from typing import Callable

import httpx

import ark_media
import cover_renderer

MODEL = "doubao-seedream-5-0-pro-260628"
URL = ark_media.BASE_URL + "/images/generations"
PRICE_VERSION = "ark-public-seedream-pro-2026-10-19"
WIDTH, HEIGHT = cover_renderer.WIDTH, cover_renderer.HEIGHT
MAX_RESPONSE_BYTES = 24 * 1024 * 1024


class SeedreamError(RuntimeError):
    def __init__(self, code, *, outcome_unknown=False, call_id=None):
        self.code, self.outcome_unknown, self.call_id = code, bool(outcome_unknown), call_id
        super().__init__(code)


def estimate(input_images: int) -> dict:
    if type(input_images) is not int or not 1 <= input_images <= 9:
        raise SeedreamError("COVER_SEEDREAM_REFERENCE_COUNT_INVALID")
    from decimal import Decimal
    amount = Decimal("0.60") + Decimal("0.02") * (input_images - 1)
    return {"stage": "image", "provider": "seedream", "model_id": MODEL,
            "input_images": input_images, "output_images": 0, "width": WIDTH,
            "height": HEIGHT, "pixel_count": WIDTH * HEIGHT,
            "estimated_cost": str(amount), "actual_cost": None, "billed_images": None,
            "currency": "CNY", "price_version": PRICE_VERSION,
            "pricing_snapshot": {"mode": "seedream_pro_pixel_tier", "currency": "CNY",
                "output_le_2610000": "0.30", "output_gt_2610000": "0.60",
                "extra_input": "0.02", "version": PRICE_VERSION,
                "input_images_basis": "request_payload"},
            "cost_status": "public_estimate"}


def _request_id(response):
    value = response.headers.get("x-request-id") or response.headers.get("x-tt-logid")
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", value) else None


def generate_background(*, source_images: list[bytes], prompt: str, call_id: str,
                        before_call: Callable, on_call: Callable, transport=None) -> tuple[bytes, dict]:
    """Reserve, record intent, dispatch once, ledger the result, release the call.

    Hooks must persist through the existing cover job. In particular on_call
    records the image terminal *before* the public response terminal so the
    next QC call sees either image accounting or the original UNKNOWN fence.
    """
    import public_product
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 3000:
        raise SeedreamError("COVER_SEEDREAM_PROMPT_INVALID")
    if not isinstance(source_images, list):
        raise SeedreamError("COVER_SEEDREAM_REFERENCE_COUNT_INVALID")
    snapshot = estimate(len(source_images))
    if not callable(before_call) or not callable(on_call):
        raise SeedreamError("COVER_IMAGE_LEDGER_REQUIRED")
    images = [ark_media.image_part(payload)["image_url"]["url"] for payload in source_images]
    # No group/stream/search/layer-splitting parameters are sent to Pro.
    # Those capabilities have different model support and/or separate billing.
    payload = {"model": MODEL, "prompt": prompt, "image": images[0] if len(images) == 1 else images,
               "size": f"{WIDTH}x{HEIGHT}", "response_format": "b64_json",
               "output_format": "png", "watermark": True}
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > ark_media.MAX_REQUEST_BYTES:
        raise SeedreamError("COVER_SEEDREAM_INPUT_TOO_LARGE")
    headers = ark_media._headers()
    status, sent, ledger_terminal = None, False, False
    response_hash, provider_request_id = None, None
    with public_product.model_admission_sync(call_id, "seedream"):
        public_product.assert_result_known()
        public_product._reserve_payload({"model": MODEL, "provider": "seedream",
                "max_tokens": 0, "modality": "image_generation"},
                math.ceil(float(snapshot["estimated_cost"]) * 1000), call_id=call_id,
                require_metered=True, provenance={"task": "cover_generate", "step": "cover_background"})
        try:
            before_call("image", call_id, dict(snapshot))
            with httpx.Client(transport=transport, trust_env=False, follow_redirects=False,
                    timeout=httpx.Timeout(240, connect=10, write=90, pool=10)) as client:
                public_product.mark_model_dispatched(call_id)
                sent = True
                with client.stream("POST", URL, content=encoded,
                        headers={**headers, "Content-Type": "application/json"}) as response:
                    status = response.status_code
                    provider_request_id = _request_id(response)
                    chunks, length = [], 0
                    for chunk in response.iter_bytes():
                        length += len(chunk)
                        if length > MAX_RESPONSE_BYTES:
                            raise SeedreamError("COVER_SEEDREAM_RESPONSE_TOO_LARGE", outcome_unknown=True, call_id=call_id)
                        chunks.append(chunk)
                    body = b"".join(chunks)
                    response_hash = hashlib.sha256(body).hexdigest()
            if status != 200:
                record = {**snapshot, "call_id": call_id, "status": "failed", "http_status": status,
                          "provider_request_id": provider_request_id, "response_hash": response_hash}
                on_call(record)
                ledger_terminal = True
                public_product._record_response(call_id, status)
                raise SeedreamError("COVER_SEEDREAM_HTTP_" + str(status), call_id=call_id)
            try:
                data = json.loads(body)
                if not isinstance(data, dict) or data.get("model") != MODEL:
                    raise ValueError("model")
                images_out = data.get("data")
                usage = data.get("usage")
                if (not isinstance(images_out, list) or len(images_out) != 1
                        or not isinstance(images_out[0], dict) or images_out[0].get("error")
                        or not isinstance(usage, dict) or type(usage.get("generated_images")) is not int
                        or usage["generated_images"] != 1):
                    raise ValueError("output")
                # The official Ark SDK declares input_images Optional[int].
                # Request cardinality is already frozen before dispatch; an
                # omitted supplier counter is not an unknown image outcome.
                reported_inputs = usage.get("input_images")
                if reported_inputs is not None and (type(reported_inputs) is not int
                        or reported_inputs != len(source_images)):
                    raise ValueError("input count")
                item = images_out[0]
                if item.get("size") != f"{WIDTH}x{HEIGHT}" or not isinstance(item.get("b64_json"), str):
                    raise ValueError("format")
                image = base64.b64decode(item["b64_json"], validate=True)
                cover_renderer.read_image(image, exact_size=(WIDTH, HEIGHT)).close()
            except (ValueError, TypeError, cover_renderer.CoverRenderError):
                raise SeedreamError("COVER_SEEDREAM_OUTPUT_UNCONFIRMED", outcome_unknown=True, call_id=call_id) from None
            record = {**snapshot, "call_id": call_id, "status": "responded", "http_status": status,
                      "output_images": 1, "billed_images": usage["generated_images"],
                      "provider_reported_input_images": reported_inputs,
                      "input_images_basis": "request_payload" if reported_inputs is None else "supplier_usage",
                      "billing_count_basis": "usage.generated_images:official_success_only_tariff",
                      "provider_request_id": provider_request_id,
                      "response_hash": response_hash, "content_sha256": hashlib.sha256(image).hexdigest()}
            on_call(record)
            ledger_terminal = True
            public_product._record_response(call_id, status)
            return image, record
        except SeedreamError as exc:
            if ledger_terminal:
                raise
            unknown = sent
            record = {**snapshot, "call_id": call_id, "status": "unknown" if unknown else "failed",
                      "http_status": status, "provider_request_id": provider_request_id,
                      "response_hash": response_hash}
            ledger_failed = False
            try:
                on_call(record)
                ledger_terminal = True
            except Exception:
                ledger_failed = True
            try:
                public_product._record_response(call_id, status, unknown=unknown, not_dispatched=not sent)
            except Exception:
                ledger_failed = True
            if ledger_failed:
                raise SeedreamError("COVER_IMAGE_ACCOUNTING_UNKNOWN", outcome_unknown=True, call_id=call_id) from None
            raise SeedreamError(exc.code, outcome_unknown=unknown or exc.outcome_unknown, call_id=call_id) from None
        except BaseException as exc:
            # A failed local acknowledgement can follow a completed HTTP call.
            # Preserve UNKNOWN and stop, never infer that the supplier did no work.
            if not ledger_terminal:
                try:
                    on_call({**snapshot, "call_id": call_id, "status": "unknown" if sent else "failed",
                             "http_status": status, "provider_request_id": provider_request_id,
                             "response_hash": response_hash})
                except Exception:
                    pass
            # An image-ledger failure must not skip the original shared call
            # terminal. Its UNKNOWN fence prevents another paid attempt/QC.
            try:
                public_product._record_response(call_id, status, unknown=sent, not_dispatched=not sent)
            except Exception:
                pass
            if not isinstance(exc, Exception):
                raise
            raise SeedreamError("COVER_SEEDREAM_OUTCOME_UNKNOWN" if sent else "COVER_SEEDREAM_NOT_DISPATCHED",
                                outcome_unknown=sent, call_id=call_id) from None
