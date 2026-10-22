# Token Dashboard — SPEC v1.0 (prototype)

Owner: Sol · Rigor: **prototype** (core flows, basic tests; no fault-injection) · Route: Sol → Flash → Luna → UAT

## Goal
Show token usage and estimated cost for the 4 Hermes bots on a page at `http://127.0.0.1:8787`, split Claude vs GPT. Bots: sol and flash use Claude; astra and luna use GPT via Nous.

## Confirmed decisions (user)
D1 Prototype. D2 Data: Hermes profiles `astra, sol, flash, luna` only. D3 Views: totals by family, per bot/model, time chart (day/hour toggle), top sessions. D4 Auto-refresh every 30 s.

## Data (read-only)
- DB: `%LOCALAPPDATA%/hermes/profiles/<p>/state.db`. Open with `sqlite3.connect('file:...?mode=ro', uri=True)` — **never write**; the DB is live (WAL). On a `database is locked` / busy error, retry once, then report that profile as unavailable. Never crash.
- Totals, per model, top sessions: table `session_model_usage` (session_id, model, billing_provider, api_call_count, input/output/cache_read/cache_write/reasoning tokens, estimated_cost_usd, first_seen, last_seen [epoch s]). Join `sessions` (id → source, display_name, started_at) for labels.
- Time chart: table `sessions` has no per-call timestamps. Use `messages` (session_id, timestamp, token_count). Sum `token_count` per bucket per bot; if it's NULL, use `len(content)//4`. Label the chart honestly: "กิจกรรมตามเวลา (token ของข้อความ — ประมาณ)". It is an activity proxy, not billed usage.
- Family: model contains `claude` → Claude; `gpt` or `openai/` → GPT; anything else → Other.
- Cost: show `estimated_cost_usd` with the label "ประมาณการ ไม่ใช่ยอดเรียกเก็บจริง". The Claude route is a subscription.
- Timezone: Asia/Bangkok (UTC+7) for buckets and display.

## Architecture
- `server.py`: Python **stdlib only** (http.server, sqlite3, json), Python 3.11+. Binds **127.0.0.1 only**, port from `--port` (default 8787).
- Endpoints:
  - `GET /` → static/index.html
  - `GET /api/usage?bucket=day|hour&days=N` (default day, 7) → JSON
    ```
    {generated_at, profiles:[{name, family, model, available, error?}],
     totals:{claude:{input,output,cache_read,cache_write,reasoning,calls,cost}, gpt:{...}, all:{...}},
     by_bot:[{bot, model, family, ...same fields}],
     series:{bucket, labels:[...], bots:{sol:[...], ...}},
     top_sessions:[{bot, session_id_short, source, title, model, total_tokens, cost, last_seen_iso}] (top 20 by input+output+cache_read+cache_write)}
    ```
  - Anything else → 404. No write endpoints.
- `static/index.html`: vanilla JS + CSS, **no CDN or external requests**. Charts are inline SVG.
  - Thai UI; numbers formatted (1.2M, 34.5K).
  - Cards: Claude, GPT, total.
  - Per-bot table; stacked bar chart with day/hour toggle; top sessions table.
  - Fetches every 30 s and shows "อัปเดตล่าสุด HH:MM:SS".
  - On fetch error: a visible banner, keep the last data, retry next tick.
  - Render text via textContent.
- `README.md` (Thai): how to run (`python server.py`) and what each number means.
- `tests/`: unittest with temporary SQLite fixtures in the same schema.

## Acceptance criteria
- AC-01 (must): `/api/usage` totals per family equal the sums of fixture rows; Claude/GPT classification is correct.
- AC-02 (must): server opens DBs read-only — a test proves a write attempt through its connection fails — and binds 127.0.0.1.
- AC-03 (must): a missing or locked profile DB → that profile shows `available:false`; the others still render and the response is 200.
- AC-04 (must): day/hour series bucket in UTC+7 correctly for fixture timestamps around midnight.
- AC-05 (must): the page loads, renders cards/table/chart/top sessions from the API, auto-refreshes about every 30 s, and shows an error banner without blanking. Playwright smoke test with the API mocked or a fixture server.
- AC-06 (nice): runs against the real local DBs and shows non-zero data for all 4 bots (manual / UAT).

## Out of scope
Claude Code / Codex logs, other team's bots, auth, persistence, exports, editing data.
