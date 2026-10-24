# NoteAI cover Skill host

This is an adapter around the real, fixed OpenCode **2.1.2** SDK, not a replacement
agent loop. It loads the complete locally pinned `editable-design/SKILL.md` and
lets that agent author the cover project. `model/cover_editable` remains the
original Skill renderer/font/check implementation. No global Skill, CLI, account,
provider configuration, or credential is used.

## Runtime

The exact SDK and plugin dependencies are declared and locked here. Install the
lockfile into an approved task-local runtime using `npm ci --ignore-scripts
--no-audit --no-fund`, with empty npm user/global configuration. There is no
installation or provider call at module import. Set
`NOTEAI_COVER_HOST_NODE_MODULES=/absolute/task/runtime/node_modules`; the worker
checks SDK/plugin versions before startup. The integration selects Node through
`NOTEAI_COVER_NODE` and launches `worker.mjs`. Node 25.7.0 on macOS was actually
tested; other Node/OS combinations need their own runtime check.
The package's >=22.12 declaration is not a Linux compatibility proof: readiness
also checks the real `node:sqlite` in-memory database and array-result APIs used
by the SDK. The full SDK and renderer still need a provider-free target-host test.

The Promise SDK entry is intentional: `@opencode/sdk/promise` accepts the second
embed override argument, while the 2.1.2 root `OpenCode.create` wrapper drops it.
Explicit Config/Global service overrides disable project, system, global and
Claude configuration and isolate all SDK data in this job's state directory.
Model catalog fetching, catalog snapshots and file watchers are disabled.

The child process removes inherited configuration and provider credentials before
importing the SDK. It retains only PATH/TMPDIR, the explicit runtime path and
`EDITABLE_DESIGN_BROWSER` / `PUPPETEER_EXECUTABLE_PATH` / `NO_SANDBOX` /
`EDITABLE_DESIGN_NO_SANDBOX`. It never
receives an Ark API key. Its only provider is a localhost OpenAI-compatible
transport; all other providers and native tools are removed. Default deny plus
six explicit tool permissions also disables OpenCode's automatically appended
Code Mode `execute` tool, which otherwise includes `fetch`. A second tool hook
rejects any unlisted tool. The trusted local renderer subprocess still requires
normal job/process filesystem isolation from its caller; this module is not an
OS sandbox.

All six tools share one local queue, including render/check subprocesses and the
completed render's thumbnail. Parallel SDK tool calls cannot fan out local
browser work or race font/file writes. A queued tool checks the task deadline
again when it acquires the slot; a rejected tool releases it for the next call.

## JSON-lines protocol

Only protocol JSON goes to stdout; SDK error diagnostics go to stderr. The first
input is:

```json
{
  "type": "start",
  "job_id": "cover-job-id",
  "state_dir": "/absolute/private/job-state",
  "work_dir": "/absolute/private/job-project",
  "skill_dir": "/absolute/noteai/model/cover_editable/vendor/editable-design",
  "editable_cli": "/absolute/noteai/model/cover_editable/cli.mjs",
  "model_id": "explicit-authorized-model-id",
  "prompt": "The existing report facts, cover brief and product tool mapping",
  "images": [{"path": "assets/original-1.jpg", "name": "original-1.jpg"}],
  "max_model_requests": null,
  "deadline_epoch_ms": 1792639999000,
  "mode": "run"
}
```

`max_model_requests: null` removes the optional count limit. Python owns the
cumulative monetary reservation and deadline. A finite fixture limit is enforced
before the next bridge dispatch. `context_tokens` and `output_tokens` are optional
explicit model bounds; defaults are 262144 and 65536. Python retains its smaller
131072 input admission bound. `compaction_output_tokens` defaults to 8192 and is
set explicitly on the SDK summary hook (the SDK's larger default is not used).
Independent final QC requests use 32768. Python's before-call estimate, native
reservation and recorded upper estimate all use the actual request output limit;
these are reservations, not a new monetary budget or a claim of supplier spend.

The 65536 design limit includes thinking. It fits the current generic Chat API
parameter range, while the specific model supports larger output and the Agent
guide recommends 128000 or more subject to the business case. These documentary
differences do not prove this account has accepted the new limit in a real call.
Thinking remains enabled/high. A `length` response is a known, metered failure
(`COVER_AGENT_OUTPUT_LIMIT_REACHED`), never partial tool execution or an SDK
automatic paid continuation. Only enumerated finish reason and bounded numeric
usage diagnostics survive cleanup; no response text or thinking is retained.

For `doubao-seed-2-1-pro-260915`, the official Agent guide requires original
`encrypted_content` replay; `reasoning_content` alone is only a summary. The
fixed SDK cannot carry that flat field. The same Python Bridge therefore keeps
allowed original assistant messages in job-local bounded RAM, restores them before
both preflight and dispatch, and strips the opaque field from replies to this
Node host. No opaque block enters SDK history, tools, logs or saved artifacts.
Matching checks whole ordered tool-call groups, strict JSON argument values and
the visible text; harmless SDK JSON formatting is normalized, while changed,
partial, conflicting or unknown turns stop locally. The same Bridge survives
the existing one-correction/two-host flow. A lost process/cache is not rebuilt
from a pending request, and never authorizes replay. No upstream SDK change or
new dependency is needed.

Official references: [Agent invocation](https://docs.volcengine.com/docs/ark/agent-model-invocation-practice?lang=zh),
[model list](https://docs.volcengine.com/docs/ark/model-list?lang=en),
[Chat API](https://docs.volcengine.com/docs/ark/chat-api?lang=en).

Before any dispatch intent, the actual SDK wire body emits `model_preflight`
with `id`, `label`, method, path and body. Python applies the same pure validator
and input meter used by its hard provider admission, without reserving money or
creating a physical call. It replies `model_preflight_response` with the same
`id` and `allowed:true`, or `allowed:false`, code
`COVER_AGENT_INPUT_LIMIT_EXCEEDED` and fixed integer `measurement` fields.
Other validation failures remain fatal. No Invocation failure or UNKNOWN is
cleared to recover a local rejection.

Only that known local input rejection becomes a localhost 400 with SDK-compatible
`context_length_exceeded` and explicit `noteai_local_admission` identity. This
uses OpenCode's existing overflow compaction; it is not a supplier response or
Volcengine native compaction. Rejected preflights have no physical ordinal,
dispatch intent or charge. They retain content-free measurements in the existing
cleanup receipt. The provider's 131072 conservative bound is unchanged.

At most one admitted compaction request is allowed per task. Its paid response
uses the same provider admission and ledger; an automatic SDK summary NUDGE is
blocked before dispatch. In the SDK summary input only, successful `cover_write`
arguments may become file references when the corresponding receipt and current
ordinary file both match the full text's exact bytes and SHA. Missing, overwritten
or failed writes stay untouched. The resulting transcript is provided as a fresh
user summary document, with recorded tools represented as text rather than live
assistant/tool turns. Initial media parts remain images; already viewed tool-image
outputs become file/hash references rather than base64 text. This avoids both
reusing signed tool IDs with changed arguments and the SDK's inability to drop a
single long exchange. Saved files and the original session remain unchanged.
After compaction, the primary context hook restores the
exact full Skill and original task facts/title/source index. It does not reinsert
old image payloads: original files remain available to `cover_view`, and actual
original/concept/final/thumbnail inspection and independent QC still apply.

Every admitted model request emits `model_request` with `id`, cumulative `ordinal`,
`label` (primary/compaction/generate/title), method, path and the full JSON body.
Python must account and dispatch it once, then reply:

```json
{"type":"model_response","id":"request-id","status":200,"body":{"id":"provider-id","choices":[],"usage":{}}}
```

The SDK requests a stream. The bridge sends Python `stream:false` and converts its
complete normal chat response to SSE locally. This does not add a physical model
call. Request image data URLs contain exact bytes so Python can verify that the
authorized originals and generated concept actually reached a vision request.
SDK automatic image resizing is explicitly disabled. Its width/height/base64
bounds permit the caller's already checked <=36 megapixel, <=10 MiB originals
without re-encoding; Python remains responsible for the total pixel bound.
Never store these whole bodies in a public artifact or product JSON record.

`unknown:true` instead of status/body marks an unknown supplier result. Timeout,
stdin disconnect or an unanswered request also preserve UNKNOWN. The worker
vetoes all SDK automatic retries. Actual compaction/auxiliary requests share the
same HTTP bridge and billing path. Titles are local deterministic strings.

Tools are `cover_read`, `cover_write`, `cover_view`, `cover_seedream`,
`cover_render`, `cover_check`. They map to safe local file operations, actual
image input, the single nonshipping concept, and original font/check/render
scripts. `cover_check` supports poster/fonts/contract and ten preinstalled
Fontsource font IDs; it never installs a new font package. HTML is guarded with a
network/script blocking CSP before any browser check. The renderer independently
checks source hashes, output resources, fonts, live text geometry and PNG size.
Agent writes cannot touch hidden files/directories, host state, NoteAI input or
session records, QC records, frozen revisions, preview output, or original assets.

`cover_seedream` emits `tool_request` with `arguments:{prompt}`. Python supplies
the authorized originals and saves the returned concept locally. The agent cannot
choose remote input URLs. A second concept request in the same job is refused.
Reply `tool_response` with the same id and `result` (normally including the saved
relative concept path). UNKNOWN must use `unknown:true`.

`cover_render` emits `tool_request` with the normalized renderer request. Python
must verify that the concept was genuinely sent in a model request and reply
`result:{allowed:true}`. Only then does the host call the pinned local CLI. The
CLI result is returned to the agent and emitted as `render_finished.artifact`.
Paths returned to the agent are job-relative. The Python artifact retains the
original absolute CLI paths. The same existing browser dependency creates a
real 240x320 PNG preview without a model or new dependency. The event and final
result also include `preview` with its path/hash/source hash; viewing the latest
final PNG automatically returns both full and preview pixels to the model.
`result.artifact` is the last successful render's original result JSON (including
revision, manifest hash and paths). Render success is not a visual-QC pass.

Other events are `ready`, `request_hook`, `retry_veto`, `protocol_error` and final
`result`. Final context contains bounded summaries and image/Skill hashes, not
large image data URLs or the entire Skill body.

## Recovery and revision

State includes the SDK SQLite session and an atomically replaced
`host-checkpoint.json`. A request is marked pending **before** it is emitted.
An unknown/pending model or paid-tool request refuses any new dispatch on restart.
Resolve it in the original Python ledger before arranging a recovery; never delete
the marker to make another paid request.

Use the same start fields with `mode:"inspect"` to read a known session without
sending another prompt. `mode:"revise", session_id:"original-session-id"` permits
one explicit local revision only after known COMPLETE, no pending request, and a
matching stored session. It reuses that actual SDK session and cumulative ordinal;
it does not create a fresh task or replay the original prompt. Python must decide
that a revision is warranted by independent QC. A second revision is refused.

This task's host proof is offline. It establishes SDK operation and boundaries,
not real model compatibility, design aesthetics, product persistence/settlement,
cross-user concurrency, Linux deployment, or a paid supplier result.

## Focused verification

```sh
NOTEAI_COVER_HOST_NODE_MODULES=/absolute/task/runtime/node_modules \
python3 model/cover_agent_host/test_host.py
```

The fixture uses the actual SDK with a mocked Python transport. It verifies full
Skill + original pixels, safe tool execution + viewed-image bytes in the next
request, only the six allowed tools, normal completion, 503 retry veto, a finite
physical request limit, UNKNOWN persistence/no replay, zero-call reopen,
same-session revision, active-HTML rejection and internal-file write denial.
These fixture calls have zero
model cost and must not be recorded as real model or visual-quality acceptance.
