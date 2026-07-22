# Spider_XHS HTTP adapter provenance and boundary

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
