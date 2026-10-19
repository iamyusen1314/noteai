"""Pure contracts for an explicitly configured, separately quoted cover task.

No provider, storage, billing or database code is invoked here. An absent policy
is disabled; prices and product choices have no active defaults. Public price
estimates never become supplier bills merely because a calculation succeeded.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


OPERATION = "cover_generate"
PRO_PIXEL_THRESHOLD = 2_610_000


class CoverPolicyError(ValueError):
    pass


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise CoverPolicyError(name + " must be a nonempty fixed string")
    return value


def _integer(value, name, *, minimum=1):
    if type(value) is not int or value < minimum:
        raise CoverPolicyError(name + " must be an integer >= " + str(minimum))
    return value


def _amount(value, name, *, positive=False):
    if isinstance(value, bool) or value is None:
        raise CoverPolicyError(name + " must be a decimal amount")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise CoverPolicyError(name + " must be a decimal amount") from None
    if not amount.is_finite() or amount < 0 or (positive and amount == 0):
        raise CoverPolicyError(name + " must be finite and " + ("positive" if positive else "nonnegative"))
    return amount


@dataclass(frozen=True)
class CoverPolicy:
    provider: str
    model_id: str
    width: int
    height: int
    credits: Decimal
    retention_seconds: int
    max_physical_calls: int
    provider_budget: Decimal
    currency: str
    price_version: str
    pricing_mode: str
    output_price: Decimal | None
    output_small_price: Decimal | None
    output_large_price: Decimal | None
    extra_input_price: Decimal

    def snapshot(self):
        return {"enabled": True, "operation": OPERATION, **{
            key: str(value) if isinstance(value, Decimal) else value
            for key, value in self.__dict__.items()}}


def validate_policy(config: Mapping | None, *, supported_models: Mapping[str, Collection[str]]) -> CoverPolicy:
    """Validate a caller's explicit provider/model allowlist without fallbacks.

    The allowlist must come from separately verified route/account conditions;
    this helper does not claim that an account can actually use a model.
    """
    if not isinstance(config, Mapping) or config.get("enabled", False) is not True:
        raise CoverPolicyError("COVER_DISABLED")
    if config.get("operation") != OPERATION:
        raise CoverPolicyError("unsupported cover operation")
    provider = _text(config.get("provider"), "provider")
    model_id = _text(config.get("model_id"), "model_id")
    models = supported_models.get(provider, ())
    if isinstance(models, str) or model_id not in models:
        raise CoverPolicyError("unsupported explicit provider/model pair")
    if "latest" in model_id.lower() or "*" in model_id:
        raise CoverPolicyError("dynamic model aliases are not fixed versions")
    pricing = config.get("image_pricing")
    if not isinstance(pricing, Mapping):
        raise CoverPolicyError("explicit image_pricing is required")
    mode = pricing.get("mode")
    if mode not in {"seedream_pro_pixel_tier", "per_image"}:
        raise CoverPolicyError("unsupported image pricing mode")
    currency = _text(pricing.get("currency"), "price currency")
    if currency != config.get("budget_currency"):
        raise CoverPolicyError("budget and image prices must use the same currency")
    return CoverPolicy(
        provider=provider, model_id=model_id,
        width=_integer(config.get("width"), "width"),
        height=_integer(config.get("height"), "height"),
        credits=_amount(config.get("credits"), "credits", positive=True),
        retention_seconds=_integer(config.get("retention_seconds"), "retention_seconds"),
        max_physical_calls=_integer(config.get("max_physical_calls"), "max_physical_calls"),
        provider_budget=_amount(config.get("provider_budget"), "provider_budget", positive=True),
        currency=currency, price_version=_text(pricing.get("version"), "price version"),
        pricing_mode=mode,
        output_price=_amount(pricing.get("output"), "output price") if mode == "per_image" else None,
        output_small_price=_amount(pricing.get("output_le_2610000"), "small output price") if mode == "seedream_pro_pixel_tier" else None,
        output_large_price=_amount(pricing.get("output_gt_2610000"), "large output price") if mode == "seedream_pro_pixel_tier" else None,
        extra_input_price=_amount(pricing.get("extra_input"), "extra input price"),
    )


def resolve_cover_route(operation: str, policy: CoverPolicy):
    if operation != OPERATION:
        raise CoverPolicyError("unsupported cover operation")
    return {"provider": policy.provider, "model_id": policy.model_id}


def estimate_image_call(policy: CoverPolicy, *, input_images: int) -> Decimal:
    """Estimate one output image using supplied prices, including references.

    For the explicit Pro tier contract the 2,610,000-pixel boundary is inclusive.
    The first reference image is free; only subsequent inputs are priced.
    """
    _integer(input_images, "input_images")
    if input_images > 9:
        raise CoverPolicyError("at most nine source images are supported")
    if policy.pricing_mode == "seedream_pro_pixel_tier":
        output = policy.output_small_price if policy.width * policy.height <= PRO_PIXEL_THRESHOLD else policy.output_large_price
    else:
        output = policy.output_price
    if output is None:
        raise CoverPolicyError("explicit output price is required")
    return output + (input_images - 1) * policy.extra_input_price


def build_quote(policy: CoverPolicy, *, input_images: int, planned_image_calls: int = 1,
                other_planned_calls: int = 0, other_estimated_cost="0"):
    """Quote credits separately from estimates, without recording consumption.

    Design/QC calls must be counted explicitly. Their estimated cost is supplied
    by the caller, because image tariffs do not price text/vision calls.
    """
    image_calls = _integer(planned_image_calls, "planned_image_calls", minimum=0)
    other_calls = _integer(other_planned_calls, "other_planned_calls", minimum=0)
    other_cost = _amount(other_estimated_cost, "other_estimated_cost")
    if other_cost and not other_calls:
        raise CoverPolicyError("other model cost requires explicitly counted calls")
    if image_calls + other_calls > policy.max_physical_calls:
        raise CoverPolicyError("physical call limit exceeded")
    image_cost = estimate_image_call(policy, input_images=input_images) * image_calls
    estimated_total = image_cost + other_cost
    if estimated_total > policy.provider_budget:
        raise CoverPolicyError("estimated provider cost exceeds budget")
    values = {"policy": policy.snapshot(), "input_images": input_images,
              "planned_image_calls": image_calls, "other_planned_calls": other_calls,
              "estimated_image_cost": str(image_cost), "other_estimated_cost": str(other_cost)}
    version = hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:24]
    return {"operation": OPERATION, "quote_version": version,
            "credits": str(policy.credits), "charge_timing": "after_saved_cover",
            "charged_credits": "0", "planned_physical_calls": image_calls + other_calls,
            "estimated_image_cost": str(image_cost), "estimated_provider_cost": str(estimated_total),
            "provider_budget": str(policy.provider_budget), "currency": policy.currency,
            "price_version": policy.price_version, "cost_status": "public_estimate",
            "actual_provider_cost": None, "retention_seconds": policy.retention_seconds}


def summarize_costs(records: Sequence[Mapping]):
    """Deduplicate identical call observations; reject conflicting duplicates.

    A known supplier cost needs an explicit billed status and evidence reference.
    Public estimates and UNKNOWN observations cannot become exact amounts. An
    eventual reconciliation updates the original call record, rather than adding
    a second charge observation with the same physical identity.
    """
    unique = {}
    for raw in records:
        call_id = _text(raw.get("call_id"), "physical call id")
        status = raw.get("status")
        if status not in {"estimated", "unknown", "billed"}:
            raise CoverPolicyError("unsupported supplier cost status")
        estimate = _amount(raw.get("estimated_cost"), "estimated_cost")
        actual = None
        evidence = None
        if status == "billed":
            actual = _amount(raw.get("actual_cost"), "actual_cost")
            evidence = _text(raw.get("evidence_ref"), "billing evidence reference")
        elif raw.get("actual_cost") is not None:
            raise CoverPolicyError("unconfirmed cost cannot be labelled actual")
        currency = _text(raw.get("currency"), "cost currency")
        row = (status, estimate, actual, evidence, currency)
        if call_id in unique and unique[call_id] != row:
            raise CoverPolicyError("conflicting physical call observation; reconcile original record")
        unique[call_id] = row
    currencies = {row[4] for row in unique.values()}
    if len(currencies) > 1:
        raise CoverPolicyError("mixed supplier currencies need explicit conversion")
    unknown = sum(row[0] == "unknown" for row in unique.values())
    confirmed = sum((row[2] for row in unique.values() if row[2] is not None), Decimal(0))
    return {"physical_calls": len(unique), "estimated_cost": sum((r[1] for r in unique.values()), Decimal(0)),
            "known_billed_cost": confirmed, "unknown_calls": unknown,
            "currency": next(iter(currencies), None),
            "actual_cost": confirmed if unique and all(r[0] == "billed" for r in unique.values()) else None}


def recovery_action(*, dispatched: bool, outcome: str):
    """Return an action for the original task; never authorize a paid replay."""
    if type(dispatched) is not bool or outcome not in {"pending", "succeeded", "failed", "unknown"}:
        raise CoverPolicyError("invalid dispatch/outcome state")
    if not dispatched and outcome in {"succeeded", "unknown"}:
        raise CoverPolicyError("provider outcome requires original dispatch")
    if outcome == "succeeded":
        return "recover_original_result"
    if outcome == "failed":
        return "finish_original_failure"
    return "reconcile_original_request" if dispatched else "resume_original_unstarted_task"


def action_requires_new_quote(action: str):
    if action in {"query", "reopen", "download"}:
        return False
    if action in {"generate", "regenerate"}:
        return True
    raise CoverPolicyError("unsupported cover action")
