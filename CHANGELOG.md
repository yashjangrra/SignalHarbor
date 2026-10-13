# Version history

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
