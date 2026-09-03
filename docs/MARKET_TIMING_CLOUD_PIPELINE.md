# Market Timing Cloud Pipeline

目标：市场时机证据由独立云端数据管道每日生成，不由 API 用户请求进程本地采集。API 只消费新鲜行业证据；公开抓取失败时，worker 会生成带 `industry_baseline` 来源标记的行业基线证据包，保证分行业快照每日更新，但不得伪装成平台官方热搜。

## Runtime Roles

- `noteai`：API 服务。默认 `NOTEAI_API_STARTS_TREND_SCHEDULER=0`，不启动抓取器。
- `xhs-trends`：无浏览器 `xhs-http-runtime`。运行
  `python market_timing_worker.py --daemon`，只通过固定的 Spider_XHS
  direct HTTP 只读适配器采集。六域本轮真实证据门通过后，最多补齐
  90 个带 `industry_baseline` 标签的行，并原子写入共享 PostgreSQL。
- 托管生产不使用 Object Storage/CDN 快照上传。本轮精确 payload、
  SHA、大小和六域计数存入 `xhs_trends_snapshot_evidence`。

## Required Production Env

```text
NOTEAI_MARKET_TIMING_REQUIRED=1
NOTEAI_API_STARTS_TREND_SCHEDULER=0
NOTEAI_HOT_KEYWORD_FRESH_HOURS=30
NOTEAI_MARKET_TIMING_MIN_DOMAIN_KEYWORDS=12
NOTEAI_MARKET_TIMING_SNAPSHOT_URL=
NOTEAI_MARKET_TIMING_SNAPSHOT_UPLOAD_URL=
NOTEAI_MARKET_TIMING_WORKER_INTERVAL_MINUTES=360
NOTEAI_XHS_ACQUISITION_ADAPTER=spider_xhs_http
NOTEAI_XHS_COLLECTION_SUSPENDED=1
NOTEAI_XHS_SEARCH_SEEDS_PER_CATEGORY=2
```

## Worker Command

Long-running worker:

```bash
cd /app/model
python market_timing_worker.py --daemon --interval 360
```

Collection is fail-closed: missing, empty, unknown and true-like
`NOTEAI_XHS_COLLECTION_SUSPENDED` values cause zero XHS HTTP attempts. Only
explicit `0`, `false`, `off`, or `no` unlocks, and direct traffic additionally
requires `NOTEAI_RUNTIME_ROLE=xhs-http`. API/Admin roles cannot collect;
`xhs-http` cannot fall back to a browser when the adapter is empty or wrong.
Legacy browser collection requires an explicit local/legacy runtime role.

Any non-empty upload URL is rejected before a managed production run is
claimed. Local/legacy snapshot export is not the managed service contract.

## API Behavior

1. API calls `compute_market_timing()`.
2. API accepts freshness only when `last_run_id` matches the latest succeeded
   Trends run.
3. Missing contract-table permission or missing succeeded evidence fails
   closed.
4. If no fresh bound evidence is available, API returns:

```json
{
  "code": "MARKET_TIMING_EVIDENCE_UNAVAILABLE",
  "message": "未获取到当前行业的新鲜市场时机证据"
}
```

This is intentional. Commercial delivery must fail visibly rather than fabricate or reuse stale trend evidence.

## Evidence Semantics

- `hot_search`: public hot-search style signal when the public web surface exposes it. Treat as high-confidence but not guaranteed.
- `search_recommend` / `search_phrase` / `homefeed_phrase`: public discovery signals. Treat as fresh industry samples, not official trend rankings.
- `industry_baseline`: deterministic fill material used only after the current
  run already passes the six-domain real-XHS gate. It cannot satisfy that
  gate and must never be displayed as platform hot search.
