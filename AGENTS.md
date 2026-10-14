# SignalHarbor contributor guide

## Scope

SignalHarbor scouts Moltbook, scores projects with an LLM, generates reports and prepares token launch proposals. Current launch operations do not sign transactions or deploy contracts. Publishing to Moltbook is explicit and authenticated. Demo data is fictional.

Phase 1 adds SQLModel/SQLite persistence, async integrations, opt-in APScheduler jobs, API-key middleware and mocked regression coverage. Phases 2–4 in README.md remain future work.

## Modules

- `src/config.py`: environment configuration, provider credentials, API access key, scheduler interval and database path.
- `src/database.py`: SQLModel SQLite storage and one-time migration of legacy `data/state.json`; retain the legacy file as a backup.
- `src/server.py`: FastAPI routes, database-backed live state, process-local demo fixtures, serialized mutations and application lifecycle.
- `src/scheduler.py`: optional periodic pipeline, non-overlapping execution and shutdown cleanup.
- `src/analyzer.py`: async provider SDKs, structured JSON extraction, strict five-dimension scoring/tokenomics validation, async retry delays and report formatting.
- `src/moltbook.py`: async HTTP reads and authenticated publishing; never forward tokens outside the canonical Moltbook origin.
- `src/launcher.py`: validated preparation-only proposals and async SURGE reads. Real deployment remains deferred.
- `web/index.html`: dashboard, API-key entry and safe rendering of external content.
- `scripts/`: async standalone scouting, analysis and pipeline entrypoints; these call integrations directly rather than HTTP API routes.
- `setup.py`, `setup.sh`, `setup.cmd`: isolated Python setup, configuration and optional OpenClaw lifecycle management.

## Running and configuration

Python 3.12+ is required. Run `bash setup.sh` on Linux/macOS, `setup.cmd` on Windows or `python setup.py` with an existing compatible Python. First installation requires internet access. Native Windows/macOS setup and credentialed external-service flows need separate validation.

Use `.env.example` for environment settings. OpenRouter is the default provider; set `OPENROUTER_API_KEY` for live analysis. Its model must be `openrouter/free` or end in `:free`; paid OpenRouter routing and automatic paid-provider fallback are prohibited. Legacy providers require explicit selection. Set `MOLTBOOK_AUTH_TOKEN` for authenticated publishing and `API_KEY` for HTTP access. The setup script provisions an API access key. Enter it in the dashboard or send `X-API-Key` from HTTP clients. Keys are secrets; do not commit or log them.

Scheduler defaults are `SCHEDULER_ENABLED=false` and `SCOUT_INTERVAL_MINUTES=60`. Enabling scheduled analysis is explicit and may incur provider charges. Scheduled jobs do not publish reports or deploy tokens. Run a single server process; distributed scheduling and multi-worker mutation coordination are outside this phase.

Live state defaults to `data/signalharbor.db`; override with `DATABASE_PATH`. Runtime databases, journals, `.env` and legacy JSON are ignored by Git. Stop the server before a database-file backup. Reverting to pre-Phase-1 code does not export newer SQLite records back to JSON.

## Development and verification

- Use async clients and async context managers for external I/O; do not block the event loop with `time.sleep()` or synchronous provider SDKs.
- Preserve demo/live isolation and serialize state-changing operations.
- Keep publishing separate from report generation and launch preparation separate from deployment.
- Run `python -m pytest -q` after installing dependencies and pytest. Mock paid LLM calls and HTTP integrations; never require real keys for tests.
- Test malformed LLM responses, auth failures, migration/restart persistence, scheduler lifecycle and concurrency boundaries.
- Keep changes in reviewable commits and use `git revert` for shared-history rollback.

## Remaining limits

HTTPS/reverse-proxy deployment hardening, multi-tenancy, cross-process coordination, GitHub enrichment and real on-chain deployment are outside Phase 1. Mocked tests do not establish compatibility with live provider/Moltbook/OpenClaw services.
