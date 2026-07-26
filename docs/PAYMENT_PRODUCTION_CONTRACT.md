# NoteAI Adapay Payment Production Contract

Status: repository/offline contract for
`PROD-FIRST-LAUNCH-PAYMENT-CONTRACT-001`, followed by the transport-injected
adapter and dedicated callback-runtime phase
`PROD-FIRST-LAUNCH-PAYMENT-ADAPTER-001`. Neither phase authorizes merchant
activation, credential use, provider request, real or mock transaction,
production migration, grant, service start or cash movement.

## Provider facts and trust boundary

- Adapay is the selected first-launch direction. The official API exposes
  payment creation/query/close, refund creation/query and daily bill download.
- An asynchronous callback is a form POST containing `data` and `sign`.
  `sign` authenticates the exact UTF-8 bytes of `data` with Adapay's public
  key and SHA1withRSA. The Event id is globally unique. NoteAI returns success
  only after signature verification and a durable idempotent transition.
- Relevant Event types are `payment.succeeded`, `payment.failed`,
  `payment.close.succeeded`, `payment.close.failed`, `refund.succeeded` and
  `refund.failed`. Unknown types are recorded as content-free manual evidence
  and never grant or reverse an entitlement.
- A synchronous payment/refund response is only transport acceptance. It
  cannot grant an entitlement or prove a refund. Non-terminal or missing
  callbacks must be resolved by signed query/reconciliation evidence.
- Refunds use the original channel. Adapay documents up to ten partial
  refunds, a total not exceeding the original amount, and a general 178-day
  window. NoteAI V1 is stricter: only one full, unused-entitlement refund may
  be initiated automatically. Any partial, consumed or ambiguous case is
  `needs_manual`; cash truth is never hidden or rewritten.
- Primary references:
  [callbacks](https://docs.adapay.tech/api/webhook.html),
  [payments and refunds](https://docs.adapay.tech/api/trade.html),
  [API paths](https://docs.adapay.tech/api/apipath.html),
  [authentication](https://docs.adapay.tech/api/introduce.html), and
  [bill download](https://docs.adapay.tech/api/assist.html).

## Implemented provider adapter boundary

- `model/adapay_adapter.py` implements the documented
  `https://api.adapay.tech` payment, query, refund, refund-query and daily-bill
  paths. A transport is injected explicitly; offline fixtures therefore have
  no implicit network path. The production HTTP transport has TLS
  verification enabled, ignores proxy environment variables, follows no
  redirect, retries nothing and bounds time, connections and response bytes.
- The adapter deliberately does not install or import the official Adapay
  Python packages. The inspected `adapay==1.3.4`/`adapay-core==1.2.0`
  implementation uses process-global credential state and can log request
  parameters or signatures. NoteAI reproduces its documented wire signature
  contract with instance-local credentials and pinned
  `cryptography==46.0.7`, the newest verified line compatible with the
  repository's existing training-tool environment.
- POST requests sign the exact full URL plus the default Python JSON encoding;
  GET requests sign the full URL plus ASCII-sorted plain `key=value` pairs.
  Every API result must be the signed `data`/`signature` envelope and is
  rejected before use if unsigned, malformed, duplicated, redirected,
  oversized or signature-invalid.
- First launch accepts only the explicit QR channels `alipay_qr` or
  `union_qr`. The caller's globally routable transaction-device IP is passed
  ephemerally because the provider requires it; it is validated before order
  creation and is never stored or logged. No username, phone, e-mail, content
  or NoteAI user id is sent.
- Checkout and bill URLs must be HTTPS on exact configured host allowlists.
  Bill ZIPs reject traversal, symlinks, encryption, duplicates, expansion
  abuse and unexpected schemas. The official 2026-07-27 templates used to
  freeze the exact headers had SHA-256
  `c1436920cd420300b408ee09b2c1a2dcb072366331f87211a3f5e5bae761c01a`
  for Charge and
  `e4f43554a39c80d7f43e342a03b2dbede1c6d9f7efe53a1ba81a69edc743ebba`
  for Refund. Template files are not retained in the repository.
- `model/payment_runtime.py` is the only callback processor. It exposes only
  liveness, readiness and the callback path, is disabled by default and, in
  production, fails closed unless PostgreSQL reports `current_user =
  noteai_payment`. The ordinary API keeps its callback path as a compatibility
  rejection and never processes provider events.
- `scripts/render_start_api.sh` and the payment start script trust only the
  exact configured proxy CIDRs, defaulting to loopback; wildcard forwarded
  headers are prohibited. The final deployment must set those CIDRs to the
  actual internal proxy addresses before payment ordering is enabled.

## Product and money contract

- All money is integer CNY fen. Floating-point values and inferred revenue
  are forbidden in the new cash ledger.
- The fixed catalogue is versioned. It contains four non-recurring 30-day
  subscription purchases (`pro` ¥99/260 credits, `growth` ¥199/560,
  `pro_plus` ¥299/900, `studio` ¥399/1250) and four credit packages
  (`starter` ¥12/30, `creator` ¥39/100, `growth` ¥109/300,
  `studio` ¥279/800). Studio remains one NoteAI account, not real seats.
- V1 has no auto-renewal, proration, overlapping paid subscription or saved
  payment method. A paid subscription receives one credit allocation for its
  exact 30-day term; it is not reset again at a calendar-month boundary.
- A catalogue snapshot is immutable on an order. The provider amount,
  currency, application, merchant order, provider mode and payment reference
  must all match before entitlement.
- User-facing purchase controls remain unavailable until the real adapter,
  merchant/channel acceptance, callback route and reconciliation runtime have
  been separately enabled and verified.

## Durable state and idempotency

1. The authenticated API creates one opaque order under the canonical user
   write fence. Only a digest of the caller idempotency key is stored.
2. Before any provider call, the database atomically reserves the order's
   sole submission attempt. A concurrent/replayed request cannot call the
   provider again. A crash or uncertain outcome after reservation becomes
   `needs_manual`; it is never automatically retried. Refund submission uses
   the same single-winner rule.
3. Callback verification happens before a database write. Invalid signatures,
   malformed/oversized form fields and duplicate JSON keys fail closed.
4. A verified Event is deduplicated by its provider Event-id digest. A second
   byte-identical delivery returns an idempotent success without a second
   ledger entry. Reuse of that Event id with different payload, signature,
   type, app, mode or clock is a collision and fails closed.
5. `payment.succeeded` records one immutable cash receipt and one entitlement
   transition in the same database transaction. Amount/app/mode/order
   mismatches record bounded manual evidence but grant no entitlement.
6. A later failed/close Event cannot downgrade success. Out-of-order or
   contradictory terminal evidence becomes `needs_manual`.
7. Credit-package grants create a source position. Wallet consumption is
   allocated to positions and an operation refund restores the same
   allocations. A cash refund is eligible only while the whole purchased
   position is unused.
8. A subscription refund is eligible only for the full order, while its exact
   subscription is active and no paid usage has occurred since activation.
9. Refund success records one negative cash entry before reversing an eligible
   entitlement. An unexpected partial/consumed refund remains cash truth plus
   `needs_manual`; it never fabricates a successful reversal.
10. Cash and entitlement ledgers are append-only. Corrections use compensating
    entries, never update/delete of ledger identity or amount.
11. Entitlement grant/reversal runs inside a database savepoint. If any
    intermediate credit, subscription, source-position or ledger write fails,
    all entitlement-side writes roll back while the verified cash entry,
    terminal provider fact and manual-review state remain durable.

## Data minimization and lifecycle

- Persist only opaque order/refund ids, provider references required for
  query, domain-separated subject hashes, fixed catalogue ids, integer
  amounts/counters, event/payload/signature digests, states and UTC clocks.
- Never persist callback bodies, signatures, checkout payloads, payer
  identities, bank/card data, QR codes, credentials, URLs, error text or raw
  bill/settlement files. Ordinary logs contain stable codes and opaque ids.
- Account deletion nulls the live user join while preserving pseudonymous
  statutory finance and reconciliation evidence. It does not delete or alter
  immutable cash history. The exact statutory retention period still requires
  professional legal approval.

## Reconciliation, settlement and Admin truth

- Daily reconciliation consumes a bounded, canonical provider adapter stream
  and the SHA-256 of the original bill. Only counts, integer totals, digests
  and hashed discrepancy references are stored.
- Every local succeeded receipt/refund must match one provider row by
  reference, kind, amount and terminal state. Missing, extra, duplicate,
  amount or status differences block finance readiness.
- A daily settlement summary must satisfy
  `gross_fen - refund_fen - fee_fen = net_fen` and retain its source digest.
  Adapay settlement is not falsely attributed to individual payments.
- Admin revenue is confirmed net cash from the immutable cash ledger.
  Active-plan-count multiplication and legacy credit estimates are labelled
  non-cash operational metrics and must not be reported as revenue/MRR.
- Signed-but-unmatched receipts/refunds are excluded from revenue and shown
  separately as a non-zero manual-review cash exposure in both Admin views.

## Runtime roles

- `noteai_app`: authenticated order intent, owner-bound status read and only
  the provider-submission/manual-unknown order columns plus account-deletion
  join removal; no callback, cash, entitlement, refund or reconciliation
  mutation.
- `noteai_payment`: isolated callback/order/refund/reconciliation writer with
  only exact table/column privileges and no user profile/content access.
- `noteai_admin`: read-only finance/reconciliation truth. Refund initiation
  must call the payment boundary; Admin never edits cash or entitlement rows.
- AI, dispatcher, Trends and Tracking roles have zero payment-table access.
- API and Payment receive distinct managed env files. The Adapay API key,
  merchant private key and provider public verification key may appear only
  in those two roles; the public key is treated as a role-bound trust root
  even though it is not confidential.
- Every runtime role lacks ownership, DDL, schema/database creation, TEMP,
  `TRUNCATE`, `REFERENCES`, `TRIGGER`, role membership, `BYPASSRLS`, grant
  option, unrestricted sequences and `schema_migrations`.
- Migration `0014` changes no ACL. The later exact privilege task must revoke
  `PUBLIC` direct execution on all eight payment trigger functions while
  retaining normal trigger invocation, and must prove the payment role has
  only the two canonical user-fence built-ins.

## Offline acceptance and later production gates

Offline acceptance requires exact catalogue snapshots; real RSA fixture
verification; tampered, replayed, duplicate and out-of-order callbacks;
amount/app/mode/reference mismatch rejection; exactly-once cash/entitlement;
credit consumption/restoration; unused full refund; unexpected partial refund
fail-closed behavior; content-free reconciliation/settlement; account
deletion pseudonymization; negative role matrix; disposable PostgreSQL
apply-twice/checksum/rollback; zero secret/log leakage and full regression.

The repository/offline adapter gate requires exact request-signature fixtures,
signed response/refund/bill fixtures, invalid-IP and data-minimization checks,
strict URL/archive/schema negatives, fail-closed bootstrap, dedicated-runtime
route isolation, exactly-once callback settlement, dependency verification
and the full regression suite.

Production remains blocked until separately controlled packages prove
merchant/channel admission, Secret injection and rotation, provider
mock-mode compatibility, callback reachability, production migration/ACL,
bounded reconciliation scheduling and alerts. A later minimal real-money test
must have an exact fen cap, named refund plan, pre/post ledger audit, explicit
evidence retention, no automatic retry and separate authorization.
