# SignalHarbor

Current application branding is SignalHarbor. Existing installations retain their configured database, claimed Moltbook identity and external OpenClaw skills. When the new default database does not exist, a sole existing `data/*.db` is reused; multiple candidates require `DATABASE_PATH` to prevent accidental data loss. Renaming the GitHub repository or an external account requires separate account settings; current links point to the maintainer and Moltbook home rather than unverified renamed pages.

**AI Deal Flow Agent for Internet Capital Markets**

SignalHarbor is an autonomous AI agent built on [OpenClaw](https://github.com/openclaw/openclaw) that discovers promising projects on [Moltbook](https://www.moltbook.com), analyzes their tokenization potential, and prepares token launch proposals for the [SURGE](https://surge.xyz) launchpad.

> Phase 1 adds SQLite persistence, async integrations, API-key protection and an opt-in background scheduler. Real on-chain deployment remains future work.

Current scope: scout → analyze → advise → prepare → generate reports. Publishing reports is a separate authenticated action. Demo data is fictional and explicitly labeled.

## How It Works

SignalHarbor runs this pipeline on demand or at an explicitly enabled interval:

```
Scout → Analyze → Advise → Launch → Report
  │         │         │        │        │
  │         │         │        │        └─ Generate reports; publishing is explicit
  │         │         │        └─ Prepare launch configuration (no transaction)
  │         │         └─ Generate tokenomics recommendations
  │         └─ LLM-powered scoring (5 dimensions, 0-100)
  └─ Monitor Moltbook submolts for project signals
```

### Scoring Model

Each project is evaluated on 5 dimensions:

| Dimension | Weight | What It Measures |
|-----------|--------|-----------------|
| Market Fit | 25% | Real demand, clear users, market size |
| Team Signal | 20% | Reputation, GitHub activity, past wins |
| Technical Quality | 25% | Working code, deployed contracts, clean architecture |
| Tokenomics Feasibility | 20% | Token utility, revenue model, sustainability |
| Traction | 10% | Moltbook engagement, social proof |

**Verdicts:**
- **STRONG_LAUNCH** (75+) — Ready for token deployment
- **PROMISING** (50-74) — Worth watching
- **NEEDS_WORK** (25-49) — Not ready yet
- **SKIP** (<25) — No tokenization potential

## Features

- **Scouting** — Scans Moltbook submolts for project signals, on demand or with opt-in scheduling
- **LLM Analysis** — Deep project evaluation via OpenRouter free models (default); explicit legacy provider support
- **Tokenomics Engine** — Generates ticker, supply, bonding curve recommendations
- **Launch Preparation** — Generates proposed Base/Solana token settings; does not deploy or sign transactions
- **Moltbook Reporting** — Submits authenticated reports to your configured submolt; account claiming and verification may be required
- **Web Dashboard** — Real-time visualization of agent activity
- **OpenClaw Skill** — Drop-in skill for any OpenClaw agent
- **Pipeline API** — One endpoint scouts, analyzes, generates reports and prepares eligible launch proposals; publishing is separate
- **Reliable State** — SQLite through SQLModel stores live projects, analyses, proposals and posting history across restarts
- **API Protection** — Configurable `X-API-Key` authentication for API requests

## Quick Start

Clone or download this repository, then run one command from its folder:

| System | Command |
|---|---|
| Linux / macOS | `bash setup.sh` |
| Windows | `setup.cmd` |
| Existing Python 3.12+ | `python setup.py` |

The script provisions Python when needed, creates an isolated environment, installs dependencies, creates configuration without overwriting it, starts the local dashboard and opens your browser. On first interactive launch the script securely asks for your provider and API key; use `--configure` later to switch an existing installation to OpenRouter or add missing credentials. OpenRouter free-model analysis needs an OpenRouter API key; reporting needs a claimed Moltbook account and token. First installation needs internet access. OS permissions and account authorization may still prompt you.

For OpenClaw installation, skill installation, guided authorization and Gateway service setup, append `--openclaw setup`. Manage it with `--openclaw start`, `stop`, `restart` or `status`. Use `--no-launch` to install without starting the dashboard, `--no-browser` to suppress browser opening, or `--port 3000` for another port. Existing OpenClaw configuration and installed skills are preserved.

Windows, macOS and Linux are targeted; native Windows/macOS execution has not been verified in this release. OpenClaw is optional for the standalone dashboard. Scheduling through OpenClaw is explicit; setup does not silently schedule paid AI calls or publish reports.

### Install as OpenClaw Skill

```bash
# Copy skill to OpenClaw workspace
cp -r skill/ ~/.openclaw/workspace/skills/signalharbor/

# Or tell your OpenClaw agent:
# "Install the SignalHarbor skill from /path/to/SignalHarbor/skill"
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web dashboard |
| `/api/health` | GET | Health check |
| `/api/state` | GET | Full agent state |
| `/api/scout` | POST | Scout Moltbook for projects |
| `/api/analyze` | POST | Analyze project(s) |
| `/api/analyses` | GET | List all analyses |
| `/api/report/{idx}` | GET | View analysis report |
| `/api/launch` | POST | Prepare token configuration; no transaction |
| `/api/launches` | GET | List all launches |
| `/api/moltbook/post` | POST | Post to Moltbook |
| `/api/moltbook/report` | POST | Post report to Moltbook |
| `/api/pipeline` | POST | Scout, analyze, generate reports, prepare proposals |
| `/api/demo` | POST | Load labeled fictional fixtures; live disk state preserved |
| `/api/demo/clear` | POST | Restore live state in the current process |

## Architecture

```
SignalHarbor/
├── app.py                      # Entry point (uvicorn server)
├── src/
│   ├── config.py               # Configuration from .env
│   ├── server.py               # FastAPI server + all routes
│   ├── database.py             # SQLModel SQLite storage + legacy migration
│   ├── scheduler.py            # Opt-in APScheduler pipeline jobs
│   ├── moltbook.py             # Moltbook API client + project extraction
│   ├── analyzer.py             # LLM-powered analysis engine
│   └── launcher.py             # Launch proposals + async SURGE reads
├── skill/
│   ├── SKILL.md                # OpenClaw skill definition
│   └── references/
│       ├── surge-integration.md
│       └── scoring-model.md
├── web/
│   └── index.html              # Dashboard UI (Tailwind + Chart.js)
├── data/                       # Persisted agent state
├── requirements.txt
├── .env.example
├── LICENSE
└── README.md
```

## Tech Stack

- **Optional orchestration**: [OpenClaw](https://github.com/openclaw/openclaw) — self-hosted AI agent
- **Backend**: Python + FastAPI, SQLModel/SQLite, APScheduler
- **AI**: OpenRouter free models through the async OpenAI-compatible SDK (default)
- **Launch proposals**: Base/Solana configuration only; real on-chain integration is future work
- **Social**: Moltbook API (agent posting)
- **Frontend**: Tailwind CSS, Chart.js, marked.js

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `AI_PROVIDER` | `openrouter` | Default free provider; legacy Anthropic/OpenAI are explicit opt-ins |
| `AI_MODEL` | `openrouter/free` for OpenRouter | OpenRouter accepts only this router or model IDs ending in `:free` |
| `OPENROUTER_API_KEY` | - | Required for live OpenRouter analysis |
| `ANTHROPIC_API_KEY` | - | Claude API key |
| `OPENAI_API_KEY` | - | OpenAI API key |
| `MOLTBOOK_API_URL` | `https://www.moltbook.com` | Moltbook API |
| `MOLTBOOK_AUTH_TOKEN` | - | Claimed agent bearer token; never sent outside canonical Moltbook origin |
| `MOLTBOOK_AGENT_NAME` | `signalharbor` | Profile used by dashboard |
| `MOLTBOOK_SUBMOLT` | `lablab` | Default submolt |
| `SURGE_API_URL` | `https://api.surge.xyz` | SURGE API |
| `BASE_RPC_URL` | `https://sepolia.base.org` | Base RPC |
| `WALLET_PRIVATE_KEY` | - | Reserved for future deployment; current release does not use it |
| `API_KEY` | empty | Required API/dashboard access key; setup generates one; empty fails closed |
| `DATABASE_PATH` | `data/signalharbor.db` | SQLite database file |
| `SCHEDULER_ENABLED` | `false` | Explicitly enable recurring paid analysis |
| `SCOUT_INTERVAL_MINUTES` | `60` | Positive interval between scheduled pipelines |

## Free API configuration

The default uses OpenRouter's zero-price `openrouter/free` router. Requests use only that router or a specific model ID ending in `:free`; paid OpenRouter models and `openrouter/auto` are rejected before any LLM request. There is no automatic fallback to a paid provider. Anthropic/OpenAI remain available only when explicitly selected for compatibility.

Create a key at [OpenRouter keys](https://openrouter.ai/keys), then run `python setup.py --configure` (or `bash setup.sh --configure` / `setup.cmd --configure`). Choose OpenRouter and enter the key in the hidden prompt. Existing installations preserve their provider until explicitly switched. Environment variables override `.env`; remove an old exported `AI_PROVIDER` or `AI_MODEL` if it keeps selecting a legacy provider/model.

```dotenv
AI_PROVIDER=openrouter
OPENROUTER_API_KEY=your_key_here
AI_MODEL=openrouter/free
```

| Service / credential | Needed now? | Free configuration |
|---|---|---|
| OpenRouter / `OPENROUTER_API_KEY` | Live LLM analysis | `openrouter/free`; rate limits, capacity and model variation apply |
| Moltbook / `MOLTBOOK_AUTH_TOKEN` | Publishing only | Public scouting requires no token; publishing uses your claimed agent token, not a developer identity-app key |
| Local API / `API_KEY` | Dashboard/API access | Random local secret generated by setup; no external account or charge |
| SQLite | Live state | Local database; no database API subscription |
| OpenClaw | Optional orchestration | Self-hosted; its LLM provider must also be configured for a free model |
| SURGE, Base/Solana RPC, wallet key | Not used by the current pipeline | Proposals are prepared locally; no RPC subscription, launchpad key or wallet key needed |
| GitHub API key | Not needed for Phase 1 | GitHub enrichment remains Phase 2 |

Free inference is quota-limited, not unlimited production capacity. Free-router model selection can change between requests, so scoring consistency is not guaranteed. Keep the scheduler off for manual demos, or choose a long interval within your account's quota; retries and other applications also consume it. Inspect remaining free requests at OpenRouter's authenticated `GET /api/v1/key` endpoint. Do not enable paid fallbacks or purchase credits to run this default configuration.

Sources: [Free router](https://openrouter.ai/openrouter/free), [OpenRouter limits](https://openrouter.ai/docs/api_reference/limits), [OpenClaw provider setup](https://docs.openclaw.ai/providers/openrouter). Free tiers and availability may change. No real OpenRouter key is included, and credentialed inference requires separate validation.

## Validation and Rollback

Run `python -m pip install -r requirements.txt pytest pytest-asyncio` then `python -m pytest -q`. Tests mock paid LLM calls and external integrations, including state persistence, legacy migration, API authentication and scheduler behavior. Native Windows/macOS setup and credentialed provider, Moltbook and OpenClaw flows require separate validation.

The setup script generates `API_KEY` in `.env` without overwriting an existing key. If starting manually, configure a long random `API_KEY`, restart the server and enter that key in the dashboard when prompted. Programmatic API requests send the same key:

```bash
curl -H "X-API-Key: YOUR_API_KEY" http://127.0.0.1:8899/api/state
```

Every HTTP resource requires the key, including health, docs and static assets. An unauthenticated request to `/` receives only a sign-in page (HTTP 401), with no application state. An unset `API_KEY` denies access (HTTP 503). The dashboard keeps the key in tab memory; refreshing requires signing in again. CLI scripts (`scripts/scout.py`, `scripts/analyze.py`, `scripts/pipeline.py`) invoke integrations directly, so they use provider/Moltbook credentials rather than the HTTP API key. Keep the default loopback binding for local use. Public hosting additionally needs HTTPS and deployment-specific hardening.

Hosting templates omit unauthenticated HTTP health probes because `/api/health` requires the key. Configure authenticated monitoring and a persistent volume for `DATABASE_PATH` before hosted use; an ephemeral filesystem will lose data on redeployment. Live browser sign-in still needs separate browser validation.

Scheduling is disabled by default. Set `SCHEDULER_ENABLED=true` and `SCOUT_INTERVAL_MINUTES=60`, then restart to enable it. Scheduled runs can incur provider charges. They prepare proposals and reports but do not publish reports or deploy tokens; demo mode pauses scheduled work. Clear demo mode before running live scouting, analysis or publishing. Run a single server process for scheduling and state mutations; multi-worker/distributed scheduling is outside Phase 1.

Major changes are separate commits. Review `CHANGELOG.md` and `git log --oneline`. To undo a change without rewriting shared history, use `git revert <commit-sha>` then push the revert. Configuration and runtime state are ignored by Git; back up `.env` and the SQLite database separately. Stop the server before copying `data/signalharbor.db` (or your configured database file). Preserve the legacy `data/state.json` backup when migrating; reverting to pre-Phase-1 code does not convert new SQLite records back into JSON.

## Future Roadmap

Development is organized into 4 phases, each building on the last.

### Phase 1 — Foundation & Reliability

Implemented foundation; live-service and native-platform verification remain separate from mocked local tests.

- **SQLite Database** — SQLModel-backed SQLite storage with persistent live state and migration from legacy `data/state.json`; fictional demo fixtures stay outside live persistence.
- **Async I/O** — Async provider SDKs and `httpx.AsyncClient` for Moltbook/SURGE, with `asyncio.sleep()` for retry pacing.
- **Background Scheduler** — APScheduler runs scout→analyze→prepare→report at a configurable interval when explicitly enabled; serialized mutations avoid overlapping pipelines.
- **Moltbook Auth** — Authenticated publishing uses `MOLTBOOK_AUTH_TOKEN` and the canonical Moltbook origin; publishing stays explicit.
- **API Key Middleware** — `X-API-Key` protects every HTTP resource, with a state-free dashboard sign-in page; missing configuration fails closed.
- **Tests** — Mocked integration and regression coverage for endpoints, analyzer, Moltbook, database migration and scheduling.

### Phase 2 — Smarter Intelligence

Improve scouting accuracy and analysis quality.

- **GitHub Enrichment** — For each GitHub URL found during scouting, fetch real repo data (stars, forks, last commit, language) via the GitHub API and feed it into the LLM context
- **Multi-Stage Analysis** — Split the single mega-prompt into 3 focused stages: (1) factual extraction, (2) scoring, (3) tokenomics design — reducing hallucination and improving consistency
- **Cross-Source Scouting** — Add GitHub trending and Moltbook user profile enrichment as additional signal sources beyond submolt scanning
- **Scoring Calibration** — Store past analyses and include few-shot examples of known `STRONG_LAUNCH` projects in the system prompt for more consistent scoring
- **Semantic Deduplication** — Replace the MD5 content hash with embedding-based similarity (cosine >0.9 = duplicate) to catch reformatted reposts

### Phase 3 — Real On-Chain Integration

Make the Launch step deploy actual tokens and close the full loop.

- **ERC20 Deployment** — Ship real pre-compiled ERC20 bytecode and deploy via Web3.py on Base Sepolia testnet instead of returning mock results
- **SURGE API** — Implement the actual SURGE launchpad API endpoints with proper wallet-signature authentication
- **Transaction Tracking** — Store `contract_address`, `tx_hash`, and `chain_id` in the database; add `GET /api/launches/{id}/status` for monitoring
- **Multi-Chain** — Add Solana deployment support via `solana-py` alongside Base
- **Launch Notifications** — Auto-post launch announcements to Moltbook with contract address + block explorer link; support configurable webhook URLs

### Phase 4 — Scale, UX & Ecosystem

Turn SignalHarbor from a hackathon project into a real product.

- **React Frontend** — Replace the 841-line monolithic `index.html` with a Next.js + shadcn/ui app: project browser, analysis history, launch tracker, settings page
- **WebSocket Updates** — Replace dashboard polling with a `/ws` WebSocket connection streaming real-time pipeline events
- **Watchlist & Alerts** — Let users watch specific projects or submolts and receive email/webhook alerts when `STRONG_LAUNCH` projects appear
- **Analytics Dashboard** — Scout hit rate, score distributions, launch success rate, and top-performing submolts
- **Multi-Tenancy** — Per-user Moltbook accounts, wallets, watched submolts, and private analyses
- **OpenClaw Skill v2** — Publish to the OpenClaw skill marketplace with agentic loop support and `skill.json` manifest

## SURGE x OpenClaw Hackathon

This project was built for the **SURGE x OpenClaw Hackathon** on [lablab.ai](https://lablab.ai/ai-hackathons/surge-moltbook-hackathon).

- **Track**: Internet Capital Markets for Creators/Products
- **Prize Pool**: $50,000 in $SURGE tokens
- **Technologies**: OpenClaw, SURGE, Moltbook

## License

MIT
