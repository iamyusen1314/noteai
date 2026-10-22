# Editable-Design adapter

This directory vendors the complete `skills/editable-design` package from
`yejy53/Editable-Design@c87b16f6d7c198e2b6967f13f1b1baa939d6f31f`.
The upstream Skill, references, templates, renderer, font tools, editor and
verification tools remain intact. `upstream-manifest.json` records every fetched
file and its hash. The Apache-2.0 license and third-party notices are retained;
selected Fontsource fonts carry their OFL licenses into each output project.

The design host loads that whole Skill. It authors the design and performs
source-photo/final-image visual review. This CLI only adapts deterministic
rendering and free text edits to NoteAI's existing cover jobs. It does not design
merchant covers, call a model, run the design host, or return a visual-quality
pass. No global Skill installation is needed.

## Runtime

Use Node >=22.12 and a Chromium browser. Point `EDITABLE_DESIGN_BROWSER` at the
browser executable where automatic discovery is insufficient. Install locally:

```sh
npm ci --prefix model/cover_editable/vendor/editable-design/scripts --ignore-scripts --no-audit --no-fund
npm ci --prefix model/cover_editable/vendor/editable-design/font-kit --ignore-scripts --no-audit --no-fund
```

All package versions are pinned in the upstream lockfiles. `node_modules` is
ignored. The adapter invokes upstream `check-poster.sh`, `check-fonts.sh` and
`check-contract.mjs`. It reuses upstream `_browser.mjs` for DOM inspection and
captures that same checked page with the upstream `pixelDiff` screenshot pattern:
the canvas bounding box, scale 1 and `captureBeyondViewport`. Page margins are
excluded and the normal opaque background is retained. Generation and free text
editing use the same capture path; the PNG dimensions and size are read back.

The complete upstream `render-poster.sh` remains unchanged in the package. Its
raw Chrome CLI path did not produce a PNG in the isolated Linux runtime, and its
cleanup required an unavailable `ps`. The adapter uses the project's existing
Puppeteer browser path instead. Render evidence records `editable_design_browser`
and `page.screenshot`, not a successful invocation of that shell script. This is
an export compatibility change, not a new design workflow or rendering framework;
pixel equality with the old raw CLI is not claimed.

Use the original `font-kit.mjs add` command **before** referencing its generated
`--font-kit-ID` variable. The upstream tool treats the variable's presence as its
idempotency marker. Font installation and model work belong to the design host,
not free text editing.

## Internal tools

Register fixed `execFile` calls for `cover_render` / `cover_edit`:

```sh
node model/cover_editable/cli.mjs render --input /absolute/request.json
node model/cover_editable/cli.mjs edit --input /absolute/request.json
```

Without `--input`, each reads one JSON object from stdin. Stdout is one JSON
result; a failed operation has exit code 1. The caller supplies an authorized
per-job directory and provides OS/process isolation. This trusted local CLI is
not an HTTP endpoint or a tenant filesystem sandbox.

On POSIX, browser operations use a fresh private `0700` directory under `/tmp`
so Chromium's Unix socket paths stay short even when the job directory is deep.
The CLI and the host's check/thumbnail operations share this scope, restore `TMPDIR`
and remove their own scratch directory on normal completion or an exception.
Revisions and evidence remain in the authorized job directory. Forced process
termination still relies on the existing isolated container's temporary-volume
cleanup; it cannot run JavaScript `finally`.

Render request:

```json
{
  "schema_version": "noteai-cover-editable/v1",
  "project_dir": "/absolute/agent-authored-project",
  "output_root": "/absolute/job/revisions",
  "sources": [{"ref": "authorized-media-ref", "path": "assets/photo.jpg", "sha256": "64 lowercase hex characters"}],
  "text_layers": [{"id": "title", "allowed_rect": {"x": 100, "y": 100, "width": 1500, "height": 350}}],
  "protected_regions": [{"x": 400, "y": 700, "width": 900, "height": 1000}]
}
```

The host's `index.html` must follow the upstream fixed-canvas contract and use
live text leaves with unique `data-layer-id` values. `poster.json` must declare
1776×2368, scale 1 and no print DPI. All positions and rectangles are **canvas
pixels**. `sources` contains 1–9 frozen, authorized originals. The CLI checks
their hashes and permits only these image files as shipping images. Reference
concepts stay in `reference/`, never replace merchant photo pixels. Fonts are
local project files with a loaded self-hosted first font family on each text
layer; implicit system-font substitution and `local()` font sources are rejected.
Active HTML, remote/data resources and path traversal are
rejected. A restrictive CSP and inspection request interception provide a second
network boundary. The renderer does not enforce permissions to original sources;
NoteAI must do that before materializing the job directory.

The adapter snapshots HTML, poster config, assets and the existing brief,
design/asset plan, prompts, reference and render-review evidence into a fresh
UUID revision. It checks loaded images/fonts, the original upstream contract,
actual text bounds/overflow, allowed regions and protected-region intersections.
Those regions are host design inputs; semantic subject detection and factual
verification remain visual-QC responsibilities. The actual output PNG must be
1776×2368 and <=10 MiB.

Successful result fields:

```json
{
  "ok": true,
  "schema_version": "noteai-cover-editable/v1",
  "revision": "uuid",
  "revision_dir": "/absolute/job/revisions/uuid",
  "parent_revision": null,
  "png_path": "/absolute/job/revisions/uuid/out/poster.png",
  "png_sha256": "hex",
  "html_path": "/absolute/job/revisions/uuid/index.html",
  "manifest_path": "/absolute/job/revisions/uuid/render-manifest.json",
  "manifest_sha256": "hex",
  "width": 1776,
  "height": 2368,
  "qc_status": "NOT_VISUALLY_REVIEWED",
  "model_calls": 0,
  "external_requests": 0
}
```

`render-manifest.json` contains `constraints`, actual DOM `checks.boxes` (text,
rectangle, ink rectangles, family/size/weight), original command receipts,
`files: [{path, bytes, sha256}]`, parent lineage and any edit delta. `files`
contains relative paths, excluding the manifest/result themselves to avoid
recursive hashes. Persist the whole bundle and exact manifest bytes for reopen.

There is **no clean text-free base PNG** in this path. A legacy `base_bytes`
storage field may hold the final PNG as an opaque compatibility artifact if
clearly marked; free edits must restore the HTML/assets bundle and use this
renderer, never the old Pillow composition path.

## Free text edits

```json
{
  "schema_version": "noteai-cover-editable/v1",
  "output_root": "/absolute/job/revisions",
  "parent_revision_dir": "/absolute/job/revisions/parent-uuid",
  "expected_parent_manifest_sha256": "hex",
  "initial_qc_ref": "optional external initial-QC evidence reference",
  "edits": [{"layer_id": "title", "text": "修改文字\n指定断行", "dx": 12, "dy": 8}]
}
```

Only `text`, `dx`, `dy` on registered text leaves are allowed. Text replacement
requires a plain text/BR leaf so it cannot silently flatten a rich multi-span
design. Upstream semantic text leaves should be marked separately. Source-photo
layers, font files, canvas and protection constraints cannot change. Before
editing, the expected parent manifest and all recorded artifacts are verified.
A new revision is rendered by the same upstream renderer and retains the parent;
failure never overwrites its PNG. Free edits are deterministic and make zero
model calls. They return `USER_ADJUSTED_NOT_VISUALLY_REVIEWED`, preserve original
QC references/deltas, and never inherit or invent a fresh visual pass.

The optional initial-QC reference is only an opaque evidence link; the renderer
does not authenticate it or promote it to a pass. NoteAI's separate initial
source/final visual gate controls generation delivery and settlement.

## Offline technical verification

```sh
node model/cover_editable/offline-smoke.mjs /absolute/new-evidence-directory
```

This uses a synthetic image, Chinese variable fonts and the complete original
render/check tools. It verifies single/nine-material manifests, immutable prior
output, zero-model text/linebreak/move edits, stale revisions, source tampering,
forbidden image edits and region rejection. It does not produce a merchant
sample or prove aesthetic quality, model compatibility, PC/H5 or production
capacity. Technical test evidence remains in the task tmp directory.
