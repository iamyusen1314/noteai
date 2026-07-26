# NoteAI first-launch data and security contract

Version: `first-launch-2026-07-25`

Status: product contract implemented in the repository; Chinese legal,
privacy, consumer-protection and provider review is still required before
public traffic. This document is not professional legal advice.

## Account and contact security

- Passwords are 10–128 characters, reject common values and require at least
  two of letters, digits and symbols. A full username or contact identifier
  cannot be embedded in the password.
- Five failed password attempts in 15 minutes block both the account identifier
  and the identifier/requester pair for 15 minutes.
- A phone must pass OTP verification before first binding, phone registration,
  OTP login or password reset. An email must be verified before it is stored
  during registration or profile binding and can then be the fallback recovery
  channel. Verification challenges expire after 10 minutes, allow five
  attempts and five requests per destination/purpose/hour.
- The repository contains only a test delivery adapter. It is disabled by
  default and refuses to run in a production stage. No real SMS or email
  vendor is connected by this task.
- Password change/reset revokes every session. Users may also revoke all
  sessions explicitly.
- New registrations record the exact contract version plus separate privacy
  and cross-border acknowledgements. Existing accounts can record the same
  immutable versioned acceptance through the authenticated contract endpoint;
  public rollout still requires an adoption/backfill decision.

## Archive, export and deletion

- Owner export covers saved notes, diagnosis reports, chat sessions and
  sanitized generation context, memories, learned preferences, growth history,
  Tracking records, contract acceptance, session metadata without tokens,
  commercial summaries and AI-operation status metadata. Temporary original
  media, raw supplier responses, ordinary service logs and detailed
  finance/security ledgers are excluded.
- Free-created archives stay online for 7×24 hours, followed by a 7-day
  recovery period. Their rolling-backup copies are cleared within 30 days
  after expiry according to the production backup runbook.
- Archives created under a paid plan have no product expiry while the account
  exists. Downgrading does not delete them, and export remains available.
  If the owner explicitly deletes a paid archive, it becomes inaccessible
  immediately and enters the same bounded 30-day purge window while retaining
  its paid-at-creation classification. The first accepted deletion fixes the
  tombstone and purge deadline; duplicate or retried deletion requests cannot
  extend that deadline.
- Retention deadlines must be real, explicitly zoned clocks and are compared
  by time rather than text, including paid-at-creation subscription windows.
  A supplied content-creation clock uses the same strict source-clock parser;
  outer whitespace is normalized, while malformed input fails closed instead
  of being replaced with the current time.
  A purge marker is valid only at or after its deadline, no later than the
  database clock, and after the matching Note or Diagnosis primary row is
  absent. Runtime insertion of a pre-purged record and later rewriting or
  clearing of a purge marker fail closed. Retention content identity, owner,
  paid/free classification, creation clock and contract version are immutable
  after insertion; SQLite also rejects `REPLACE`/`INSERT OR REPLACE` of an
  existing retention identity. The reviewed application helper preserves
  idempotent repeats only after matching the existing owner, contract version
  and, when supplied, the same real creation instant; a conflict fails closed
  without a write. Matching Note and Diagnosis primary `id` and `user_id`
  values are also immutable; the API role can update only
  `notes.parent_id` and has no Diagnosis UPDATE permission. Once a retention
  identity exists, its primary content ID cannot be reused, including after
  purge, by a different owner, or later in the same transaction. New
  retention metadata must reference matching primary content. PostgreSQL
  serializes primary insertion against the retention row; SQLite enforces the
  same identity and no-resurrection invariants with database triggers.
  SQLite legacy-contract replacement is guarded by an atomic savepoint and
  fails closed on invalid rows or stale upgrade residue.
- Account export removes provider-internal or model-reasoning fields. Account
  closure locks the user row, verifies the password, builds the final export
  and fences future content/session writes in one transaction. It returns the
  export in the same no-store response.
- An account deletion request revokes sessions and makes the account
  inaccessible immediately. The deletion ledger sets a primary deletion
  deadline within 24 hours and rolling-backup clearance within 30 days.
  The repository contains bounded idempotent primary-content/account purge
  processors. Detailed finance/security records retain only a pseudonymous
  subject reference. Backup deletion is never inferred: a separate confirmation
  boundary requires an external evidence reference. Scheduling, migration
  execution and backup-platform work remain separately approved operations.

## Secret, logging and reasoning boundaries

- Runtime secrets must be injected by a managed deployment secret. The
  database-backed runtime settings API refuses secret writes and does not read
  historical rows marked secret.
- XHS cookies may be read only from the dedicated injected runtime variable;
  plaintext cookie-file fallback is disabled.
- Admin service logs expose event levels, stable event codes and line hashes,
  never raw lines or absolute paths. Crawler events use a scalar allowlist.
- Saved diagnosis payloads remove raw provider request/response, prompts,
  system prompts, reasoning and thinking fields before persistence. Historical
  payloads receive the same filter on read/export.

## Field-level data map

| Data | Purpose | Primary store | External route | Archive/export | Retention/control |
|---|---|---|---|---|---|
| Username, nickname, avatar, password hash/salt | Authentication/profile | PostgreSQL | None | Profile/avatar included; password never exported | Account lifecycle |
| Verified phone/email | Login/recovery | PostgreSQL | Future SMS/email vendor only after approval | Included for the account owner | Verification and deletion clocks |
| OTP destination hash, code hash, masked contact | Abuse-resistant verification | PostgreSQL | Test adapter only in this phase | Excluded | 10-minute challenge; cleanup job required |
| Notes and versions | Creation/history | PostgreSQL | Minimum necessary AI text where selected | Included | Free 7d + recovery 7d; paid-created indefinite |
| Diagnosis reports | Product result | PostgreSQL | AI providers where selected | Sanitized report included | Same archive contract as notes |
| Chat messages, preferences and generation context | Iterative rewriting and recovery | PostgreSQL | Minimum necessary AI text where selected | Sanitized owner export | Deleted with account; the whole version-chain conversation is deleted when any linked version is deleted |
| Creator memories, learned preferences and growth history | Personalization and progress | PostgreSQL | Minimum necessary prompt context where selected | Included | Deleted with account; source-linked context memory is deleted with the note version chain, including conservative cleanup of legacy unlinked context |
| Tracking URL, metrics and collection state | XHS outcome tracking | PostgreSQL | XHS only after explicit supplier approval | Included without raw internal errors | Deleted with account; source references cleared on source deletion |
| Session user-agent and requester fingerprint hashes | Session security and abuse control | PostgreSQL | None | Session metadata without tokens; fingerprints excluded | Session expiry/account deletion; challenge cleanup required |
| Idempotency and AI operation metadata | At-most-once billing and failure recovery | PostgreSQL | None | Safe status metadata only | Pseudonymous operational audit after account deletion |
| Contract version and consent timestamps | Legal/privacy evidence | PostgreSQL | None | Included | Versioned, account lifecycle |
| Temporary images/video | OCR/vision input | Current temporary storage; private OSS is a later gate | China vision processing by default | Excluded | Separate private-storage lifecycle gate |
| Claude prompt/context | AI processing | In-process/minimal audit metadata | Singapore Gateway may receive minimum necessary text | Raw prompt excluded | Cross-border notice and legal review required |
| Kimi/Amap/Meituan request | AI/fact enrichment | Minimal audit metadata | Named provider | Raw response excluded | Provider-specific production approval required |
| XHS session/cookies | Supplier authentication | Managed runtime secret only | Xiaohongshu | Excluded | Rotation/revocation runbook required |
| Subscription and credit balance | Commercial state | PostgreSQL | Payment provider only after approval | Summary included | Account lifecycle |
| Detailed usage/credit/security ledger | Commercial, fraud and incident audit | PostgreSQL | Payment provider only after approval | Excluded | Pseudonymized on primary deletion; statutory period requires legal approval |
| Service/crawler logs | Reliability/security | Managed logs | Log platform after approval | Excluded | Allowlisted structured fields and expiry policy |

## Cross-border and refund disclosures

- The intended Claude path may send minimum necessary text from Alibaba Cloud
  China to a Gateway in Singapore. Original images should be processed in
  China by default, and only required extracted text should cross the boundary.
- The exact processor list, legal basis, consent/notice, localization and
  transfer mechanism require Chinese professional review before public use.
- No real payment gateway is enabled by this repository phase, so no real
  payment may be collected. Pricing remains visible, but the UI states that
  plans and credits cannot currently be purchased and gives no off-platform
  payment direction. The future production contract must implement
  original-channel refund, signed callbacks and ledger reconciliation before
  charging users.

## Explicitly outside this repository phase

No production migration, GRANT, business-data write, real SMS/email, legal or
provider call, deployment/image/ACR action, service start, ALB/TLS/DNS change,
XHS/Tracking/real payment execution, or public traffic is authorized here.
