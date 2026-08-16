import base64
import copy
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import extract_item26_manual_cost_stop_raw_v1 as extractor  # noqa: E402


def encoded(value):
    return base64.b64encode(extractor.canonical_bytes(value)).decode("ascii")


def envelope():
    records = []
    for sequence, slot in enumerate(extractor.REQUIRED_SLOTS, start=1):
        records.append({
            "sequence": sequence,
            "slot": slot,
            "operation": "ReadOnlyOrAlreadyConsumedProviderRecord",
            "started_at_utc": "2026-08-16T00:00:00.475Z",
            "completed_at_utc": "2026-08-16T00:00:01.475Z",
            "transport_outcome": "RESPONSE_RECEIVED",
            "request_json_base64": encoded({"page": sequence}),
            "response_json_base64": encoded({"ok": True}),
        })
    return {
        "schema": extractor.CAPTURE_SCHEMA,
        "task_id": extractor.TASK_ID,
        "operation_id": extractor.OPERATION_ID,
        "phase": "POST_ACTION_READBACK_ONLY",
        "ledger_context_revision": "1" * 40,
        "observed_at_utc": "2026-08-16T00:00:02.475Z",
        "records": records,
    }


class ManualCostStopRawExtractorTests(unittest.TestCase):
    def test_capture_envelope_accepts_fractional_provider_time(self):
        extractor.validate_capture_envelope(envelope())

    def test_capture_requires_every_exact_slot(self):
        value = envelope()
        value["records"].pop()
        with self.assertRaisesRegex(
            extractor.ExtractionError, "capture_slots"
        ):
            extractor.validate_capture_envelope(value)

    def test_noncanonical_embedded_json_rejected(self):
        value = copy.deepcopy(envelope())
        value["records"][0]["response_json_base64"] = base64.b64encode(
            b'{"ok": true}\n'
        ).decode("ascii")
        with self.assertRaisesRegex(
            extractor.ExtractionError, "response_canonical"
        ):
            extractor.validate_capture_envelope(value)

    def test_invalid_calendar_time_rejected(self):
        value = envelope()
        value["observed_at_utc"] = "2026-02-31T00:00:02Z"
        with self.assertRaisesRegex(
            extractor.ExtractionError, "capture_observed_at"
        ):
            extractor.validate_capture_envelope(value)

    def test_reverse_record_time_rejected(self):
        value = envelope()
        value["records"][0]["started_at_utc"] = "2026-08-16T00:00:02Z"
        with self.assertRaisesRegex(
            extractor.ExtractionError, "record_time_order"
        ):
            extractor.validate_capture_envelope(value)

    def test_non_page_slot_cannot_repeat(self):
        value = envelope()
        duplicate = copy.deepcopy(value["records"][0])
        duplicate["sequence"] = len(value["records"]) + 1
        value["records"].append(duplicate)
        with self.assertRaisesRegex(
            extractor.ExtractionError, "capture_slot_count"
        ):
            extractor.validate_capture_envelope(value)

    def test_projection_is_source_only_fail_closed(self):
        with self.assertRaisesRegex(
            extractor.ExtractionError, "provider_extractor_not_finalized"
        ):
            extractor.extract_projection(envelope())


if __name__ == "__main__":
    unittest.main()
