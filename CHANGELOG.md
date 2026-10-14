# Version history

## 1.2.2 — 2026-10-14

- Rebranded current application, prompts, reports, logs, launcher metadata, setup paths, OpenClaw skill and documentation to SignalHarbor.
- Replaced the previous raster mark with a SignalHarbor SVG.
- Existing databases and external account/skill settings are preserved; Git history remains available for rollback.
- GitHub repository naming and previously published external posts require separate account-level changes.
- Validation: 124 tests pass; current tracked/new file contents contain no former project name, and compilation/diff checks pass.


## 1.2.1 — 2026-10-14

- Default LLM provider switched to OpenRouter with free-only model routing and no automatic paid fallback.
- Secure setup supports OpenRouter key entry and explicit migration from legacy providers.
- Documented required/optional credentials and free configuration; quota and availability limits remain.
- 123 mocked tests pass, including OpenRouter request/authentication payloads, quota errors without paid fallback, and provider switching. Live OpenRouter requests remain unverified without a supplied key.

## 1.2.0 — 2026-10-14

- Phase 1: SQLModel-backed SQLite persistence and legacy JSON migration; demo fixtures remain isolated.
- Async LLM SDKs, Moltbook HTTP and SURGE reads; nonblocking retry delays and async CLI entrypoints.
- Opt-in APScheduler jobs with configurable intervals, serialized pipeline runs and lifecycle cleanup.
- Fail-closed API-key middleware for all HTTP resources, dashboard sign-in and setup-generated keys.
- Mocked regression coverage for persistence/migration, auth, scheduling and async integrations.
- Validation: 106 tests passed on Linux; compilation and diff checks passed. A real-server smoke verified API authentication, demo guards and restart isolation. Browser sign-in remains unverified because Chromium was unavailable.

Scheduled work does not publish reports or deploy tokens. Multi-worker/distributed scheduling and real on-chain deployment remain future work. Native Windows/macOS installation and credentialed external-service flows remain unverified.

## 1.1.0 — 2026-10-13

- Strict five-dimension scoring and tokenomics validation; failures do not become scored results.
- Documented Moltbook feeds, profiles and authenticated publishing; no wallet secrets sent to SURGE.
- Honest preparation-only launch results, full pipeline proposals and explicit report publishing.
- Worker-thread routes keep dashboard requests responsive, serialized state writers and atomic JSON saving.
- Labeled fictional demo fixtures preserve live state on disk; safe dashboard rendering and polling.
- Windows/macOS/Linux setup entrypoints, isolated Python environment and guided credential entry.
- Optional OpenClaw installer, skill registration, onboarding and Gateway start/stop/restart/status.
- Mocked regression tests and a three-OS GitHub Actions test matrix.

Live token deployment, built-in scheduling, database, public API authentication and other roadmap items remain deferred. Native Windows/macOS installation and credentialed provider/Moltbook/OpenClaw flows are not yet verified.

## 1.0.0 — baseline

Original repository commit: `1df5a158b2d69b9ac928e545dddd311d1e009c8e`.
Rollback branch: `rollback/baseline-2026-10-13`.

Use `git revert <commit>` for shared-history rollback; preserve `.env` and runtime data separately.
