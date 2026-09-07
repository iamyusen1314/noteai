# NoteAI Payment Production Contract

## Item31 direct-provider preparation — 2026-09-04

The owner-designated first-launch providers are WeChat Pay direct and Alipay
direct. Item31 is `BLOCKED_EXTERNAL_DEPENDENCY` until ICP filing, both merchant
and product approvals, and secure production credential injection are complete.
No direct-provider payment, callback, refund or reconciliation acceptance has
run, and the earlier Ping++ TEST preparation gives Item31 no readiness credit.

The existing `PaymentProvider` boundary, internal order state machine,
authenticated callback ledger, provider-event idempotency, exactly-once
entitlement, unused full-refund flow and reconciliation model remain the shared
implementation base. Provider-specific transports and signature verification
must terminate at that boundary; they must not create a second billing system.
Migration `0018_direct_payment_providers.sql` only reserves the two direct
provider identities while preserving accepted Adapay rows. It contains no
Secret, role, grant, payment, refund, entitlement or balance action.

`model/direct_payment_gateways.py` now provides the minimum implementations
`WeChatPayGateway` and `AlipayGateway` on the existing `PaymentProvider`
boundary. They map Native/precreate payment, query, full refund, refund query
and authenticated reconciliation rows into the existing integer-fen contract.
The WeChat gateway verifies the exact API v3 notification bytes with the
configured platform-certificate or public-key verification identity, binds the
declared signature algorithm, and decrypts `AEAD_AES_256_GCM` resources before
it can create a canonical callback event. The Alipay gateway verifies the
sorted form fields with RSA2, then binds the application, seller, notification
type, order and exact amount before it can create the same canonical payment
event. Authenticated payment callbacks and WeChat refund callbacks enter the
existing callback/idempotency/ledger boundary; neither gateway can grant an
entitlement from a redirect page or synchronous create response. Alipay QR
checkout is restricted to the official `qr.alipay.com` host.

Alipay's synchronous refund response remains a non-terminal submission receipt
even when it reports a fund change. An authenticated
`alipay.trade.fastpay.refund.query` response is bound to its exact signed JSON
bytes, merchant order, payment, refund identity and amount, then enters the
existing `refund.succeeded`/`refund.failed` event boundary under a deterministic
receipt identity. Repeating the same query receipt therefore cannot duplicate
the cash or entitlement reversal ledger entries. WeChat's payment query state
`REFUND` is recognized as a refund-reconciliation condition and cannot be
treated as a malformed payment response or a new entitlement grant.

The one-attempt WeChat API v3 and Alipay RSA2 HTTP transports now sign exact
payment/refund/query requests and verify the exact provider response before
returning its signed JSON node. TLS verification is enabled; environment
proxies, redirects and automatic retries are disabled; response bytes and
clocks are bounded. WeChat trade-bill location and download are signed, the
download URL and provider-signed locator's SHA-1 digest are verified, and the
official trade-bill CSV shape is parsed and bound to the requested merchant,
app and bill date. Alipay's signed bill locator, exact TLS download URL and
bounded trade-bill ZIP/CSV parser are implemented. Merchant-authorized official
sample compatibility remains unverified, so Alipay bill reconciliation stays
on external provider-compatibility hold until that sample is read back. An injected
transport must return a provider-bound,
already authenticated response or bill; the gateway rejects an unsigned,
cross-provider, malformed or oversized result.
Item31 counts five semantic provider operations per direct-provider canary:
payment creation, payment query, refund submission, refund query and daily
reconciliation. This count is not described as a raw HTTP-request count because
a provider's reconciliation operation can require a signed locator request and
a separate bounded download. Callback delivery and its duplicate replay are
authenticated inbound events and do not increase that operation count. Each
byte-identical duplicate increments the original event's bounded durable
delivery counter, so the canary can prove one replay without granting or
reversing entitlement twice.
When the temporary Item31 canary flag is enabled, the existing order API binds
creation to the selected direct provider, the synthetic user and subject,
`credit_package/starter` at exactly 1200 fen, one fixed Idempotency-Key digest,
and an activation window of at most one hour before any order write or provider
call. A successful create emits only domain-separated request, response,
checkout, order, user and activation digests; it does not change the API
response or log raw provider/order/checkout values. Alipay refund evidence uses
the authenticated `out_request_no` as its provider-bound refund identity when
the provider does not issue a separate refund id; only its domain-separated
digest is exposed.
The current transports use live provider origins only, so both direct gateways
reject mock mode in every deployment stage. Their provider notifications are
bound to the exact public NoteAI endpoints
`https://api.noteaipro.cn/payments/wechat/callback` and
`https://api.noteaipro.cn/payments/alipay/callback`; another host, port, path,
query or fragment is rejected before a provider request can be made.
App IDs, merchant IDs and seller IDs are non-secret environment configuration
and must not be scattered through application code. Private keys, API v3 keys
and other API keys must use the existing managed Secret path and must never
appear in source, logs, Evidence or handoff files. Provider public verification
keys and certificate identities are role-bound trust configuration and must be
rotated through the same controlled runtime configuration path.
All four direct-provider PEM inputs use strict canonical standard Base64 on one
unquoted env-file line. The process decodes them only in memory before strict
RSA parsing; quoted values, escaped-newline text, whitespace, noncanonical
Base64 and oversized material fail closed. This keeps Compose `env_file` and
Docker `--env-file` semantics identical without exposing resolved key bytes.
The API ordering role receives merchant request-signing keys and provider
response trust roots, but no WeChat API v3 callback-decryption key. The isolated
Payment callback role receives that API v3 key and provider trust roots, but no
merchant request-signing private key while it exposes callback routes only.

The public ALB keeps its exact two API backends on port 8000. The two direct
callback paths are relayed by the API ingress, without parsing or DB access, to
the co-located Payment container on `127.0.0.1:8002`. The Payment container
shares the API container network namespace and publishes no second host or ALB
port. The relay is disabled by default, accepts only those two fixed paths,
preserves only the exact body, content type and WeChat signature headers, and
uses one bounded no-retry loopback request. Callback authentication and all
payment-state writes remain exclusively in the Payment role. Activation must
enable the API relay and Payment callback together. The Payment systemd unit is
bound to the API unit so an API restart stops the old namespace-bound Payment
container before both are started and verified again.

Status: repository/offline contract, provider gateways, signed payment/query
transports, WeChat trade-bill reconciliation, direct-provider bootstrap/API
selection, dedicated callback routes, exact schema controller and bounded
one-attempt canary executor are prepared for
`PROD-FIRST-LAUNCH-PAYMENT-CONTRACT-001`. Alipay merchant-sample bill
compatibility, production migration, image deployment, merchant configuration and runtime activation
remain `PROD-FIRST-LAUNCH-PAYMENT-ADAPTER-001`. Neither
phase authorizes merchant
activation, credential use, provider request, real or mock transaction,
production migration, grant, service start or cash movement.

Primary direct-provider references:
[WeChat Pay API v3 SDK and notification contract](https://github.com/wechatpay-apiv3/wechatpay-java),
[WeChat Pay Go API v3 paths](https://github.com/wechatpay-apiv3/wechatpay-go),
[Alipay Trade API](https://github.com/alipay/alipay-sdk-net-all/blob/master/v3/docs/AlipayTradeApi.md),
and [Alipay EasySDK callback/bill API](https://github.com/alipay/alipay-easysdk/blob/master/APIDoc.md).

## Retained legacy Adapay facts and trust boundary

- Adapay is the retained legacy adapter and is not the selected public-launch
  provider. Its historical contract remains below for compatibility and
  regression review; it gives Item31 no readiness credit. Its official API exposes
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
  `cryptography==50.0.0`, which covers the fixes for `CVE-2026-69247` and
  `CVE-2026-69249` required by the native release scan. Production role
  requirements deliberately exclude
  MLflow: the current local training-tool release requires
  `cryptography<47`, so training and payment/runtime dependencies must not
  share one production environment.
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
  liveness, readiness and the three provider callback paths, is disabled by
  default and, in
  production, fails closed unless PostgreSQL reports `current_user =
  noteai_payment`, both direct providers are selected and both modes are LIVE.
  The ordinary API keeps all callback paths as compatibility rejections and
  never processes provider events. Ordering selects an allowlisted provider
  explicitly and reuses the same payment contract; direct providers do not
  inherit Adapay's transaction-device-IP requirement.
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
- `noteai_admin_runtime`: read-only finance/reconciliation truth. Refund initiation
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
direct-provider live-mode compatibility, callback reachability, production migration/ACL,
bounded reconciliation scheduling and alerts. A later minimal real-money test
must have an exact fen cap, named refund plan, pre/post ledger audit, explicit
evidence retention, no automatic retry and separate authorization.
