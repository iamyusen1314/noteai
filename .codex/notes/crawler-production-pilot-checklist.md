# Crawler Production Pilot Checklist

## Current Decision

- Cloud deployment is planned but deferred.
- Do not deploy crawler, XHS-Downloader, cron, worker, database, secrets, or production infrastructure until all core product flows and business value are validated.
- The current target is local and controlled gray-box validation with small samples.

## Pilot Goal

Validate that NoteAI can reliably track published Xiaohongshu notes and collect fresh industry evidence without relying on brittle browser selectors alone.

## Required Architecture For Pilot

- `noteai-api`: consumes tracking records, freshness status, Admin health, and user-facing note library state.
- `noteai-tracking-worker`: processes due `tracked_notes` records on a schedule.
- `noteai-trends-worker`: refreshes daily industry evidence and enforces XHS freshness gates.
- `xhs-downloader-sidecar`: independent XHS-Downloader API service used as the primary extraction path or hard fallback.
- Shared database: stores `tracked_notes`, `xhs_crawler_health`, and `xhs_freshness_ledger`.

## Entry Criteria Before Cloud Pilot

- Single-note tracking succeeds with a real Xiaohongshu URL through sidecar fallback.
- Worker moves a test note from `pending` to `checking_7d` with 24h metrics populated.
- Manual fill still works and writes growth records to the linked note version.
- Note library shows linked tracking state per note/version/root card.
- Admin crawler page shows sidecar status, freshness status, health rows, and ledger rows.
- `NOTEAI_XHS_DOWNLOADER_URL` is configured only in non-production or pilot env.
- No secrets, cookies, tokens, `.env` values, or raw API responses are logged.
- Full unit tests pass.
- `docker compose config --quiet` passes.

## Stability Evidence Required

- Run a small controlled sample for at least 3 consecutive days before broad release.
- Minimum sample: 1-3 notes per day and at least 2 domains for market evidence.
- Track success rate for:
  - sidecar HTTP success
  - normalized content/metrics present
  - `note_page_access_valid`
  - `selector_valid`
  - `risk_login_detected`
  - empty response rate
  - worker completion rate
- Any missing daily freshness should trigger Admin-visible action, not silent training ingestion.

## Do Not Treat As Production-Ready Until

- XHS-Downloader runs as a managed sidecar service, not a local cache install.
- Sidecar health check exists and is visible to Admin.
- Tracking worker and trends worker have bounded concurrency and request limits.
- All logs are redacted for cookies, auth headers, tokens, titles/body if sensitive, and raw provider responses.
- There is a rollback plan to disable crawler/sidecar without breaking core NoteAI generation and diagnosis.
- Billing and model usage accounting have been reviewed separately.
- Cloud cost and external AI cost budgets are defined.

## Guardrails

- No full-platform crawling.
- No unlimited retries.
- No concurrent load tests without explicit approval.
- No production database writes during validation.
- No payment, email, SMS, deploy, migration, seed, reset, or clean commands without explicit approval.
- Do not commit XHS-Downloader source, `.venv`, cookies, cache files, or raw JSON responses into NoteAI.

## Pilot Exit Criteria

- 3-7 days of small-sample runs show stable sidecar extraction.
- Daily freshness ledger stays green for the selected pilot domains.
- Tracking notes produce useful user-facing learning signals for Hermes agents.
- Failure modes are visible and actionable in Admin.
- Business value is validated by user testing before cloud migration.
