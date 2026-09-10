# Spider_XHS HTTP adapter provenance and boundary

## Current repair candidate — September11 full engineering authorization

Owner now authorizes necessary upstream adaptation and finite normal-read experiments
under the persistent RMB100 task cap; the older spent one-call boundary below is
historical. v5.0.0 at `7077c88f82771f547cc1afdadaec4025be2355e6` was downloaded into
`/Users/openclaw/Downloads/noteai-xhs-repair-20260911/upstream` with69 relevant
source files verified against Git blob hashes. No upstream installer/demo was run.

`model/vendor/spider_xhs/v5/upstream.json` pins14 byte-identical state/signing/
RAP/reference assets. `headers.py` contains unchanged pure definitions extracted
from upstream params.py and core/http.py; custom runtime.py and bridge.js preserve
stdin-only secret handling and restrict signing to PC user/me and feed. Upstream
argv credentials, arbitrary program injection, Creator/login/write APIs and retry
behavior are not included. Existing legacy assets remain for unchanged callers.

Explicit `NOTEAI_XHS_PROTOCOL=pc_v5` selects the new Tracking-only chain: DSL GET,
existing legal Cookie user/me GET, fixed owned-note feed POST. It uses fresh parsed
DSL (never executes downloaded DSL script), real user_id-derived xy-direction,
complete current B1/MNS/x-s-common/RAP context, upstream UA/header order and pinned
curl_cffi0.15.0 chrome146 transport. No invented gid, fingerprint-ready state or
security profile: tier follows the actual existing cookies. Required web_session,
real persistent safety and operator stops precede network calls. Each physical
request is projected into existing task output/journal; no raw response/header/
Cookie/Token/signature/user content is retained. Owned note identity and numeric
metrics must be verified for a repair success; it is still not a snapshot.

This is a coupled compatibility experiment, not a proved explanation of historical
code-3. 22 targeted Python3.11.14 offline tests pass; real candidate validation and
live results remain pending. Historical facts below are unchanged.

## September11 generation1 failure: upstream comparison

After this comparison, the only authorized extra diagnostic returned HTTP200,
successfalse/code-3 atSeptember11 00:13:35 Beijing using the unchanged original
signing/request path. This establishes a business rejection, not a parser false
negative. The old24h exact code remains unknown. Additional read-only scan of40
relevant Python/Markdown files at7077c88 found no-3 definition or documented fix;
the sole literal-3 source occurrence was a URL slice. [Issue36](https://github.com/cv-cat/Spider_XHS/issues/36)
is HTTP461/code0, and [Issue127](https://github.com/cv-cat/Spider_XHS/issues/127)
is successTrue/code0/emptydata; neither can explain this failure. Response message
was present but unmatched by fixed safe tags; no raw message was retained.
The signing compatibility changes below remain candidates, not a demonstrated
cause. The extra request allowance is exhausted; no comparison retry was sent.

Actual failed image source is NoteAI `fcc863f65ad1d3d788e8936ef1284a9ab27ad025`,
published digest `a2ee0f2ef94191af45b2af1dce192379194bd103e5084204f7ff224457ab6a88`.
Its chain is NoteAI's crawler_worker → crawler → spider_xhs_http → custom
stdin Node wrapper. The worker and HTTP adapter are NoteAI code, not an upstream
worker. Only the two assets pinned below are copied byte-for-byte; fresh raw
GitHub reads at the locked commit matched both SHA256 values. No upstream tag
was recorded for that lock; the exact commit, not a guessed version, is authoritative.

GitHub REST/raw reads found [v5.0.0](https://github.com/cv-cat/Spider_XHS/releases/tag/v5.0.0),
published September7 17:27:34 UTC, tag/master
`7077c88f82771f547cc1afdadaec4025be2355e6`. This is a formal release after the
locked commit, not merely an Issue claim. It includes [PR184](https://github.com/cv-cat/Spider_XHS/pull/184)
(head `b0b33cbe3b090834b3bf4e27ae3624466b44090f`) and [PR178](https://github.com/cv-cat/Spider_XHS/pull/178)
(merge `4267f89830c04262ac01e578e60cf7d0eb2eb5e0`, head
`71d6140ff76bd026494ecb08f43fb6e71c6344ad`). No later merged-but-unreleased
master revision was found at this check. Public source was compared in process
memory, not installed or executed; no persistent download directory was created.

| Relevant change at v5 commit | Actual NoteAI inclusion / association |
|---|---|
| [feed endpoint/body](https://github.com/cv-cat/Spider_XHS/blob/7077c88f82771f547cc1afdadaec4025be2355e6/apis/xhs_pc_apis.py#L503) | Same `/api/sns/web/v1/feed`, note ID, image formats, topic, default pc_search and empty missing xsec_token. No proved endpoint/parameter fix. |
| [auth/context](https://github.com/cv-cat/Spider_XHS/blob/7077c88f82771f547cc1afdadaec4025be2355e6/apis/xhs_pc_apis.py#L120), [xy-direction](https://github.com/cv-cat/Spider_XHS/blob/7077c88f82771f547cc1afdadaec4025be2355e6/xhs_utils/xhs_pc/params.py#L306), [release state](https://github.com/cv-cat/Spider_XHS/blob/7077c88f82771f547cc1afdadaec4025be2355e6/xhs_utils/xhs_pc/state.py#L447) | New signing/session context, user-derived direction and newer browser/release profile; absent from frozen NoteAI (a1-only context, direction13, Chrome138). Plausible compatibility candidate, not a confirmed root cause without the upstream error. |
| [bootstrap](https://github.com/cv-cat/Spider_XHS/blob/7077c88f82771f547cc1afdadaec4025be2355e6/xhs_utils/xhs_pc/auth.py#L438), [DSL fetch](https://github.com/cv-cat/Spider_XHS/blob/7077c88f82771f547cc1afdadaec4025be2355e6/xhs_utils/xhs_pc/dsl.py#L115) | Default auth constructor calls user/me; missing DSL can cause another GET. Cannot run this path under a one-request limit. |
| [Node runtime](https://github.com/cv-cat/Spider_XHS/blob/7077c88f82771f547cc1afdadaec4025be2355e6/xhs_utils/xhs_pc/runtime.py#L109) | Upstream payload includes cookie/a1 in argv; must preserve NoteAI stdin isolation. Whole HTTP layer additionally requires curl_cffi. No wholesale upgrade or single-asset substitution adopted. |

Pure v5 next_sign_context/signing can operate locally only with matching lawful
DSL/user/release inputs; their availability here is unproven. It is a coupled
signature context change, not evidence that replacing two JS files fixes this error.
[Open PR149](https://github.com/cv-cat/Spider_XHS/pull/149) is unmerged collection work;
[PR140](https://github.com/cv-cat/Spider_XHS/pull/140) concerns npm installation.
[Issue144](https://github.com/cv-cat/Spider_XHS/issues/144) and
[Issue143](https://github.com/cv-cat/Spider_XHS/issues/143) are user detail-failure
reports without this run's missing business code; [Issue173](https://github.com/cv-cat/Spider_XHS/issues/173)
concerns build DNS/APT, outside this response failure. None proves this root cause.

Original retained stdout is 556 bytes, SHA256
`43fc4c26024e2fe5d51874c8f93f340ba651a9f65bee19f3f0da4aef03738b54`, stderr0.
It contains only fixed error/round counters; no HTTP status, raw business code
or message survived. Frozen response classification proves a 2xx JSON object
with success=false or an unaccepted code, not exact HTTP200 or an expired session.
The separate diagnostic retains numeric codes/status and fixed message concepts;
it does not change success rules, signing, old evidence or the published image.

## Locked source

- NoteAI implementation baseline: `93b03d5c40fb64fa264c0ada1c055f8e7696b161`.
- NoteAI checkout inspected before implementation: `f3a1a3bb28acd4a2b7e33221d0d8d0100a79c9a9` (Handoff-only descendant of the baseline).
- Upstream repository: `https://github.com/cv-cat/Spider_XHS`.
- Upstream commit: `9504b5249103f34a0a4e7062939258061559e2fd`.
- Upstream tree: `7db08187cb5332a5a3c89a5923987e098ffddf14`.
- Upstream `static/xhs_main_260411.js` SHA256: `723dc6ef64836b0998aa4ba85796e2ffd99bfb20f222d69adcbcf66ea589292d`.
- Upstream `static/xhs_rap.js` SHA256: `e79fe1c79c97a73fbf5fdb6420af114ff591902aa60b436ac4b803a99b806d2e`.
- `crypto-js` is fixed to `4.2.0`, tarball integrity `sha512-KALDyEYgpY+Rlob/iriUtjV6d5Eq+Y191A5g4UqLAi8CyGP9N1+FdVbkc1SxKc2r4YAYqG8JzO2KGL+AizD70Q==`.

Only the two named JavaScript assets are copied byte-for-byte. The production
image does not contain Spider_XHS creator, login, Pugongying, Qianfan, xray
pack, websectiga, proxy, browser, or write-operation modules. Asset hashes are
checked in code and in the Docker build specification.

The repository had no public `LICENSE` file at the locked commit. The product
owner states that a separate commercial authorization for Spider_XHS has been
obtained and is held outside this repository; no contract or credential is
stored here. That authorization is not evidence of Xiaohongshu platform
authorization. The product owner explicitly accepts the non-official API,
account-restriction, interface-change and platform-rule risks.

## Enforced production scope

The adapter exposes only these read operations:

1. homefeed recommendations;
2. search recommendations;
3. note search;
4. note detail;
5. local, secret-free session health;
6. bounded pagination (maximum three pages and sixty items per call).

There is no login, publishing, upload, like, collect, comment, message,
creator, proxy rotation/account pool, challenge/captcha bypass, or arbitrary
endpoint interface. Only `GET` and `POST` are accepted for the fixed allowlist.
The client disables environment proxy inheritance and redirects. Challenge,
login, cooldown, unknown adapter, invalid session, signer-integrity failure,
wrong runtime role and operator suspension all fail closed without a browser
fallback. Direct calls require `NOTEAI_RUNTIME_ROLE=xhs-http`. Collection stays
locked unless `NOTEAI_XHS_COLLECTION_SUSPENDED` is explicitly `0`, `false`,
`off`, or `no`; missing, empty and unknown values remain suspended.

Cookies and `a1` are read through the existing secret-settings boundary. The
Node signer receives `a1` through stdin, never argv or environment. Fixed-code
errors and health output contain no Cookie, `a1`, `xsec_token`, signature, or
connection value. `x-xray-traceid` is a local random trace only; no dynamic
challenge or trace acquisition is attempted.

Production targets install no Playwright Python package, Chromium binary or
browser graphics stack, and their role/entrypoint allowlists expose no browser
command. `runtime-common` still copies the application source tree, so legacy
local crawler source containing browser launch code remains present but is not
reachable through a production role. Python Playwright remains explicitly
opt-in legacy local tooling, and npm Playwright remains a repository E2E test
dependency; neither is installed in a production image target.

## Release rule

The final production-image revision is the new independently verified NoteAI
release commit created after this implementation. It must not be replaced by
the Handoff-only checkout, the `93b03d5` baseline, or a relabelled historical
image. Real XHS session validation remains a separately approved, bounded
post-build/pre-deployment task; no real XHS call is part of this change.
