# Tafuta Kazi — Engineering Decision Log & Architecture Documentation

**Project:** Tafuta Kazi — Autonomous Job Discovery & CV Tailoring Agent
**Owner:** Bill Otiende
**Stack:** Python 3.11 · LangGraph · Groq API · Telegram Bot · SQLite · Typst · APScheduler
**Last Updated:** 2026-08-31

---

## Table of Contents

1. [System Architecture Overview](#1-system-architecture-overview)
2. [Data Flow](#2-data-flow)
3. [Module-by-Module Decision Log](#3-module-by-module-decision-log)
4. [Security Decisions](#4-security-decisions)
5. [LLM Provider Decisions & Model History](#5-llm-provider-decisions--model-history)
6. [Ingestion & Filtering Strategy](#6-ingestion--filtering-strategy)
7. [Known Tradeoffs](#7-known-tradeoffs)
8. [What to Watch Out For](#8-what-to-watch-out-for)
9. [Environment & Configuration Reference](#9-environment--configuration-reference)

---

## 1. System Architecture Overview

Tafuta Kazi is a fully autonomous job application agent that runs on a cron schedule. It scrapes remote job boards, filters listings against a candidate profile, tailors a CV using an LLM, compiles a PDF, dispatches it to Telegram for human approval, and finalises the application record in SQLite — all without manual intervention except the approve/reject decision.

```
┌─────────────────────────────────────────────────────────────┐
│                        main.py                              │
│  AsyncIOScheduler (every N hours) + startup sweep           │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              ingestion/scrappers.py                         │
│  RemoteOK API + Jobicy API → Python-side filtering          │
│  → ingestion/deduplicator.py → SQLite processed_jobs        │
└────────────────────────┬────────────────────────────────────┘
                         │ new_jobs[]
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              core/graph.py  (LangGraph)                     │
│                                                             │
│  tailor_cv ──► generate_pdf ──► send_telegram               │
│                                      │                      │
│                              ⏸ INTERRUPT                    │
│                         (awaits human decision)             │
│                                      │                      │
│                         finalize_application                │
└─────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
   core/llm.py        compiler/pdf_engine.py   gateway/bot.py
   Groq API           Typst → PDF              Telegram Bot
         │                    │                    │
         └────────────────────┴────────────────────┘
                              │
                         SQLite (jobs.db)
                    applications + processed_jobs
```

---

## 2. Data Flow

### Phase 1 — Ingestion
1. `scrape_all_new_jobs()` fires both `fetch_remoteok_jobs()` and `fetch_jobicy_jobs()` concurrently via `asyncio.gather()`
2. Each raw job passes through `_is_relevant_job()` — a three-gate filter (blocklist → title keyword → profile/config keyword)
3. Jobs that pass are checked against `processed_jobs` table via `deduplicator.is_duplicate(url)`
4. New jobs are registered in `processed_jobs` and `applications` (status=PENDING) via `deduplicator.register_job()`
5. A `url_hash` (MD5 of normalised URL) is attached to each job dict and returned

### Phase 2 — LangGraph Workflow (per job)
1. `tailor_cv_node` — sends `profile.json` + job description to Groq, receives structured `TailoredCVContent`
2. `generate_pdf_node` — passes tailored data to `TypstCompilerEngine.compile_cv()`, writes PDF to `output/`
3. `send_telegram_node` — dispatches PDF + inline Approve/Reject buttons to Telegram chat
4. **INTERRUPT** — graph pauses at `interrupt_before=["finalize_application"]`, awaiting human input
5. `handle_callback_query()` in `bot.py` receives button press, injects `approval_status` into graph checkpoint via `update_state()`, resumes graph with `ainvoke(None, config=thread_config)`
6. `finalize_application_node` — updates `applications` table with final status and PDF path

### State Persistence
- LangGraph `MemorySaver` checkpointer holds state in-memory keyed by `thread_id = f"job_thread_{url_hash}"`
- Each job gets its own isolated thread — concurrent jobs don't interfere
- **Watch:** `MemorySaver` is in-process only. If the process restarts between `send_telegram` and `finalize_application`, the checkpoint is lost and the graph cannot be resumed. See Section 8.

---

## 3. Module-by-Module Decision Log

### `config.py`

| Decision | Rationale |
|---|---|
| Pydantic `BaseSettings` | Auto-reads `.env`, validates types at startup, fails fast on missing required fields |
| `BASE_DIR` relative paths | All paths (`OUTPUT_DIR`, `DATABASE_PATH`, etc.) are resolved relative to the project root — no hardcoded absolute paths |
| `ensure_directories()` called at import | Guarantees `data/`, `output/`, `data/templates/` exist before any module tries to write |

**Fixes applied:**
- `defalut` typo → `default` on `DEBUG` field
- `JOB_TITLE` → `JOB_TITLES` to match scraper references
- `MAX_JOBS_PER_RUB` → `MAX_JOBS_PER_RUN`
- Indentation fix on `CRON_INTERVAL_HOURS` block that broke the class

---

### `ingestion/scrappers.py`

| Decision | Rationale |
|---|---|
| Broad API fetch + Python-side filtering | RemoteOK ignores comma-separated `?tags=` as one string; Jobicy `industry=engineering&tag=full-stack` returned 0 results. Fetching broad feeds and filtering in Python is more reliable |
| `_build_profile_keywords()` at module load | Reads `profile.json` once, builds a flat `Set[str]` of all target roles and tech skills. Filter stays in sync with profile without code changes |
| Three-gate `_is_relevant_job()` | Gate 1: blocklist rejection (maintenance, equipment, logistics). Gate 1b: must have tech signal. Gate 2: profile keyword match. Gate 3: config keyword match. Cheap gates run first |
| `asyncio.gather()` for both scrapers | Both API calls run concurrently — halves ingestion latency |
| `url_hash` = MD5 of normalised URL | Strips query params and trailing slashes before hashing — prevents duplicate entries from URL variants of the same job |

**Fixes applied:**
- `fetch_jobicy_jobs`, `_is_relevant_job`, `scrape_all_new_jobs` were outside the class due to indentation errors
- `logger.warning` was inside the relevancy filter `else` block instead of the HTTP status `else` block
- `MAX_JOBS_PER_RUB` → `MAX_JOBS_PER_RUN`
- `job_tile` typo → `job_title` in `register_job()` call
- Missing comma in `register_job()` call
- Jobicy URL: removed broken `geo=apac,emea,latam,usa` (400 Bad Request)
- `_is_relevant_job` was passing `[]` instead of `tags` for Jobicy jobs
- Added `_BLOCKLIST_TITLE_KEYWORDS` to reject non-tech roles before they reach the LLM

---

### `ingestion/deduplicator.py`

| Decision | Rationale |
|---|---|
| SQLite with WAL mode | Write-Ahead Logging allows concurrent reads during writes — important since the bot and scraper both access the DB |
| MD5 hash as primary dedup key | Fast, fixed-length, sufficient for URL deduplication (not a security hash) |
| `processed_jobs` + `applications` as separate tables | `processed_jobs` is the dedup ledger; `applications` tracks the approval lifecycle. Separation allows querying each independently |
| `FOREIGN KEY ... ON DELETE CASCADE` | Deleting a processed job automatically cleans up its application record |

**Fixes applied:**
- `ApplicationDeduplicator` → `JobDeduplicator` in `ingestion/__init__.py` (class name mismatch)

---

### `core/llm.py`

| Decision | Rationale |
|---|---|
| Plain `ChatGroq` + `PydanticOutputParser` | `with_structured_output()` defaults to tool-calling which most Groq-hosted models don't support, causing `tool_use_failed`. JSON prompt + parser is universally compatible |
| Explicit `JSON_SCHEMA` in system prompt | Avoids `PydanticOutputParser.get_format_instructions()` which injects markdown fences that Groq's JSON validator rejects |
| `_strip_fences()` | Removes `<think>...</think>` reasoning blocks (Qwen 3.x) and markdown fences before parsing |
| `_unwrap_json()` | Some models wrap the payload under a top-level key (`{"cv": {...}}`). This method searches one level deep and unwraps if needed |
| `re.DOTALL` on think-block regex | `<think>` blocks span multiple lines — without `DOTALL`, `.` doesn't match newlines and the block isn't stripped |
| `personal_info` / `contact` key mapping | `profile.json` nests contact fields under `personal_info.contact`, not at the top level. Fixed in both `llm.py` result assembly and `pdf_engine.py` contact extraction |
| `logger.debug` on raw response | First 500 chars of raw LLM output logged at DEBUG level — run with `LOG_LEVEL=DEBUG` to inspect model output without cluttering INFO logs |

**Model history (all decommissioned or incompatible):**
- `llama-3.3-70b-versatile` → 404 Not Found (decommissioned)
- `llama3-70b-8192` → 400 decommissioned
- `qwen/qwen3.6-27b` → `tool_use_failed` (no tool-calling support), then `json_validate_failed`, then `{}` empty output after think-block stripping
- **Current:** `openai/gpt-oss-120b` — clean JSON output, no reasoning blocks, confirmed active on account

**Fixes applied:**
- `model_name=` → `model=` (deprecated kwarg in `langchain-groq`)
- `generate_tailored_cv_data` was outside `CVTailoringEngine` class (indentation error)
- `candidate_info` → `personal_info`, `skills` → flattened from `technical_skills`

---

### `core/graph.py`

| Decision | Rationale |
|---|---|
| All nodes as `async def` | LangGraph supports async nodes natively. Sync nodes inside an async event loop cause `RuntimeError: This event loop is already running` |
| `interrupt_before=["finalize_application"]` | Graph pauses after sending Telegram notification, before writing final status. Human decision is injected via `update_state()` then graph resumes with `ainvoke(None)` |
| `MemorySaver` checkpointer | In-memory state persistence across the interrupt boundary. Sufficient for single-process deployment |
| `thread_id = f"job_thread_{url_hash}"` | Each job gets an isolated state thread. Prevents state bleed between concurrent job processing |

**Fixes applied:**
- `asyncio.run(send_approval_request(...))` inside `send_telegram_node` → replaced with `await send_approval_request(...)` (was causing event loop collision)
- `job_agent_graph.stream()` in `main.py` → `await job_agent_graph.ainvoke()` (sync iteration inside async context)

---

### `gateway/bot.py`

| Decision | Rationale |
|---|---|
| `BotContext` class instead of module global | Replaces `global _bot_app_instance` mutation pattern. Class attribute mutation via `_ctx.app = app` avoids the `global` keyword and the race condition risk flagged by static analysis |
| `set_telegram_app_instance()` called inside `build_telegram_application()` | Guarantees the singleton is registered at the same time the app is built — no separate call required |
| `send_approval_request()` uses `_ctx.app.bot` | Reuses the single running `Application` instance instead of creating a new one per call (which caused token conflicts and double-initialisation) |
| Path traversal mitigation via `Path.resolve()` + `is_relative_to()` | `pdf_path` originates from job scrape data flowing through graph state. Resolving and boundary-checking against `OUTPUT_DIR` before opening the file descriptor prevents CWE-22 path traversal |
| Local import of `job_agent_graph` inside `handle_callback_query` | `graph.py` imports `bot.py` at module level. Importing `graph.py` inside `bot.py` at module level creates a circular import. Deferred local import breaks the cycle |
| `update_state(..., as_node="send_telegram")` | Injects the human decision into the checkpoint as if it came from the `send_telegram` node — this is the correct LangGraph pattern for resuming after a human-in-the-loop interrupt |

**Security findings resolved:**
- CWE-22 Path Traversal (High) — resolved via `resolved_path.is_relative_to(allowed_dir)` check
- Dangerous global variable (Low) — resolved via `BotContext` class

---

### `compiler/pdf_engine.py`

| Decision | Rationale |
|---|---|
| Typst for PDF generation | Typst is a modern typesetting system with a clean programmatic API. Avoids LaTeX complexity while producing professional ATS-friendly output |
| Temp file + compile + delete pattern | Typst CLI requires a file path input. Writing to a named temp file and deleting in `finally` ensures no orphaned `.typ` files on disk |
| `_escape_typst()` | Escapes `\`, `"`, `#`, `$`, `@` — all have special meaning in Typst markup. Without this, LLM-generated text with these characters breaks compilation |

**Fixes applied:**
- `candidate_info.get("email")` etc. → now reads from `personal_info.contact` nested dict matching actual `profile.json` structure
- `candidate_info.get("location")` → resolved from nested `{city, country}` dict to a plain string
- `candidate_info.get("name")` → `candidate_info.get("full_name")` matching `profile.json`
- Added `str(c)` cast before `_escape_typst()` as a safety net against any non-string values reaching `.replace()`

---

### `main.py`

| Decision | Rationale |
|---|---|
| `build_telegram_application()` before `asyncio.create_task(run_pipeline_sweep())` | The bot singleton must be registered before any pipeline sweep fires, otherwise `send_telegram_node` raises `RuntimeError: Telegram app instance not set` |
| `asyncio.create_task()` for startup sweep | Fires the first sweep immediately without blocking the event loop setup (scheduler start, signal handlers) |
| Signal handlers via `loop.add_signal_handler()` | Graceful shutdown on `SIGINT`/`SIGTERM` — stops scheduler, stops Telegram polling, shuts down cleanly |
| `NotImplementedError` pass on signal handler | Windows doesn't support `add_signal_handler` — the pass allows the same codebase to run on Windows without crashing |

**Fixes applied:**
- `from ingestion.scrapers import job_scraper` → `from ingestion.scrappers import scrape_all_new_jobs` (wrong filename, wrong symbol)
- `job_agent_graph.stream()` sync iteration → `await job_agent_graph.ainvoke()`

---

## 4. Security Decisions

### Credentials in `.env`
Your `.env` file contains live credentials (`GROQ_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`). These were observed in plaintext during the session.

**Action required:**
- Rotate `GROQ_API_KEY` at [console.groq.com](https://console.groq.com) → API Keys
- Rotate `TELEGRAM_BOT_TOKEN` via `@BotFather` → `/revoke`
- `.env` is in `.gitignore` — confirmed safe from commits

### Path Traversal (CWE-22) — Resolved
`pdf_path` flows from scrape data → graph state → `send_approval_request()`. Before the fix, it was passed directly to `open()`. Now:
```python
resolved_path = Path(pdf_path).resolve()
allowed_dir = settings.OUTPUT_DIR.resolve()
if not resolved_path.is_relative_to(allowed_dir):
    logger.error(...)
    return
```
All four test vectors (`../../etc/passwd`, `../config.py`, `/etc/passwd`, absolute path to project files) were verified blocked.

### Telegram Auth Guard
`handle_callback_query()` checks `update.effective_user.id != settings.TELEGRAM_CHAT_ID` and returns early on mismatch. Only your personal Telegram account can approve/reject applications.

---

## 5. LLM Provider Decisions & Model History

| Model | Status | Failure Mode |
|---|---|---|
| `llama-3.3-70b-versatile` | Decommissioned | 404 Not Found |
| `llama3-70b-8192` | Decommissioned | 400 model_decommissioned |
| `qwen/qwen3.6-27b` | Active but incompatible | `tool_use_failed` → `json_validate_failed` → `{}` empty after think-block stripping |
| `openai/gpt-oss-120b` | **Current — Active** | Clean JSON, no reasoning blocks |

### Why `with_structured_output()` was removed
LangChain's `with_structured_output()` defaults to tool-calling (function calling API). Most Groq-hosted open models don't support tool-calling, returning `tool_use_failed`. The replacement pipeline:
1. Explicit JSON schema embedded in system prompt
2. Plain `ChatGroq.invoke()` returns raw text
3. `_strip_fences()` removes `<think>` blocks and markdown fences
4. `_unwrap_json()` handles models that wrap payload under a top-level key
5. `PydanticOutputParser.parse()` validates and deserialises

### Groq JSON Mode (`response_format: json_object`) — Removed
Groq's JSON mode requires the word "JSON" in the prompt AND rejects outputs containing markdown fences. `PydanticOutputParser.get_format_instructions()` injects fences automatically, causing `json_validate_failed`. Removed in favour of explicit schema in prompt + fence stripping.

---

## 6. Ingestion & Filtering Strategy

### Why broad API fetch instead of query params
| API | Attempted Param | Result | Decision |
|---|---|---|---|
| RemoteOK | `?tags=software,developer,...` | Treated as one string, 0 matches | Fetch `/api` broad feed |
| Jobicy | `&geo=apac,emea,latam,usa` | 400 Bad Request | Removed |
| Jobicy | `&industry=engineering&tag=full-stack` | 0 results | Removed |
| Jobicy | `&tag=software-engineer` | 0 results (wrong slug) | Removed |
| **Both** | **No query params** | **Works — filter in Python** | **Current approach** |

### Three-Gate Filter
```
Gate 0 (blocklist):   "maintenance", "technician", "equipment", "logistics" → REJECT
Gate 1 (tech signal): must contain "software", "developer", "engineer", "react", etc. → else REJECT
Gate 2 (profile):     any keyword from profile.json target_roles + technical_skills → PASS
Gate 3 (config):      any keyword from settings.KEYWORDS → PASS
```
A job must pass Gate 0 and Gate 1, then pass Gate 2 OR Gate 3.

### Profile-Driven Keywords
`_build_profile_keywords()` runs once at module load and extracts a flat `Set[str]` from:
- `profile.json → meta.target_roles` (split into individual words)
- `profile.json → technical_skills.*` (all skill values across all categories)

This means updating `profile.json` automatically updates the filter on next run — no code changes needed.

---

## 7. Known Tradeoffs

### `MemorySaver` vs Persistent Checkpointer
**Current:** `MemorySaver` stores graph state in-process RAM.
**Tradeoff:** If the process crashes or restarts between `send_telegram` and the user pressing Approve/Reject, the checkpoint is gone. The Telegram message will still show buttons, but pressing them will fail silently (no matching thread in memory).
**Mitigation path:** Replace `MemorySaver` with `SqliteSaver` from `langgraph.checkpoint.sqlite` pointing at `jobs.db`. This persists checkpoints across restarts.

### Single-Process Async Architecture
Everything runs in one Python process on one event loop. The Telegram bot polling, APScheduler, and LangGraph all share the same loop.
**Tradeoff:** A blocking call anywhere (e.g. a slow Typst compilation) stalls the entire loop.
**Mitigation:** `pdf_compiler.compile_cv()` is currently synchronous (Typst CLI subprocess). For high job volumes, wrap it in `asyncio.run_in_executor()`.

### `MAX_JOBS_PER_RUN = 3`
Limits LLM API calls and Telegram noise per sweep.
**Tradeoff:** If 20 relevant jobs appear in one sweep, only 3 are processed. The rest are registered in `processed_jobs` (deduped) but never tailored.
**Watch:** Jobs registered but never tailored will be skipped on future sweeps because `is_duplicate()` returns True. Consider a `status=SKIPPED` flow or increase the limit.

### Groq Free Tier Rate Limits
`openai/gpt-oss-120b` is a large model. On Groq's free tier, rate limits are aggressive (requests per minute and tokens per day).
**Watch:** With `MAX_JOBS_PER_RUN=3` and a 6-hour interval, daily token usage is manageable. Increasing either will hit rate limits quickly.

### Jobicy & RemoteOK API Stability
Both are free public APIs with no SLA. RemoteOK has been observed redirecting from `remoteok.io` to `remoteok.com` — `follow_redirects=True` handles this. Jobicy's taxonomy slugs changed during this session.
**Watch:** If ingestion returns 0 jobs consistently, check API response structure first before debugging the filter.

---

## 8. What to Watch Out For

### Critical
- **`MemorySaver` checkpoint loss on restart** — any process restart between Telegram dispatch and user approval loses the graph state. The approve/reject buttons become dead. Migrate to `SqliteSaver` for production.
- **Credentials rotation** — live `GROQ_API_KEY` and `TELEGRAM_BOT_TOKEN` were exposed in plaintext. Rotate both immediately if not already done.
- **Groq model deprecations** — Groq deprecates models frequently (two models were decommissioned during this session). Check [console.groq.com/docs/deprecations](https://console.groq.com/docs/deprecations) before each deployment. The `LLM_MODEL` setting in `.env` allows swapping without code changes.

### High
- **Typst template missing** — `TypstCompilerEngine.__init__` raises `FileNotFoundError` at startup if `data/templates/template.typ` doesn't exist. The entire agent fails to initialise. Ensure the template is committed and present.
- **`profile.json` missing** — `CVTailoringEngine.__init__` raises `FileNotFoundError` at startup. Same impact.
- **`output/` directory** — `settings.ensure_directories()` creates it at startup. If permissions prevent creation, PDF compilation will fail at the `output_path.parent.mkdir()` call in `pdf_engine.py`.
- **Irrelevant jobs still passing filter** — the blocklist covers known non-tech categories but is not exhaustive. "Course Director UX UI" and "Principal Engineer at AI Whistleblower Initiative" passed the filter. The LLM will attempt to tailor CVs for these. Review `processed_jobs` table periodically and expand `_BLOCKLIST_TITLE_KEYWORDS` as needed.

### Medium
- **`asyncio.run()` inside async context** — fully resolved, but if any new synchronous utility function is added that calls `asyncio.run()`, it will crash the event loop. Always use `await` inside async functions.
- **Circular import risk** — `graph.py` imports `bot.py` at module level; `bot.py` imports `graph.py` inside `handle_callback_query` as a deferred local import. If any future refactor moves that import to module level in `bot.py`, a circular import will crash startup.
- **`send_approval_request` called before bot initialised** — `build_telegram_application()` must be called and `await telegram_app.initialize()` must complete before any pipeline sweep fires. The current `main.py` ordering guarantees this, but any refactor that moves the sweep before bot init will cause `RuntimeError: Telegram app instance not set`.
- **LLM output wrapping** — `_unwrap_json()` handles one level of wrapping. If a future model wraps two levels deep (e.g. `{"data": {"cv": {...}}}`), parsing will fail. Extend `_unwrap_json()` if you switch models again.

### Low
- **`jobs.db` in project root** — currently excluded from git via `*.db` in `.gitignore`. The `DATABASE_URL` in `.env` points to `/CodeSync/se-prod/tafuta_kazi/data/jobs.db` (absolute path) while `settings.DATABASE_PATH` defaults to `BASE_DIR/data/jobs.db`. Ensure these are consistent — the app uses `settings.DATABASE_PATH`, not `DATABASE_URL`.
- **APScheduler double-start warning** — the logs show `Scheduler started` twice. This is because `AsyncIOScheduler` is started once during `add_job` (tentative) and once explicitly. Harmless but worth noting.
- **Telegram message caption length** — Telegram caps inline message captions at 1024 characters. If `original_caption + status suffix` exceeds this, `edit_message_caption` will raise a `BadRequest`. Add a truncation guard if job descriptions are long.

---

## 9. Environment & Configuration Reference

### `.env` Required Fields
```
GROQ_API_KEY=<your-groq-api-key>
TELEGRAM_BOT_TOKEN=<your-bot-token>
TELEGRAM_CHAT_ID=<your-numeric-chat-id>
DATABASE_URL=sqlite:////CodeSync/se-prod/tafuta_kazi/data/jobs.db
```

### `.env` Optional Overrides
```
LLM_MODEL=openai/gpt-oss-120b        # swap model without code change
LLM_TEMPERATURE=0.2
CRON_INTERVAL_HOURS=6
MAX_JOBS_PER_RUN=3
DEBUG=False
ENV=production
```

### Key File Paths (resolved from `BASE_DIR = config.py` parent)
| Setting | Default Path |
|---|---|
| `DATABASE_PATH` | `tafuta_kazi/data/jobs.db` |
| `PROFILE_PATH` | `tafuta_kazi/data/profile.json` |
| `TYPST_TEMPLATE_PATH` | `tafuta_kazi/data/templates/template.typ` |
| `OUTPUT_DIR` | `tafuta_kazi/output/` |
| `DATA_DIR` | `tafuta_kazi/data/` |

### Running the Agent
```bash
cd /home/user/CodeSync/se-prod/tafuta_kazi
source venv/bin/activate
python main.py
```

### Debug Mode (inspect raw LLM output)
```bash
# Temporarily set in config.py or override logging level
logging.basicConfig(level=logging.DEBUG)
python main.py
```

### Initialise DB manually
```bash
venv/bin/python data/db_init.py
```

---

*This document reflects the state of the codebase as of the end of this engineering session. Update it as further changes are made.*
