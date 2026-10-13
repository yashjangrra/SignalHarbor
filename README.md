# SurgeScout

**AI Deal Flow Agent for Internet Capital Markets**

SurgeScout is an autonomous AI agent built on [OpenClaw](https://github.com/openclaw/openclaw) that discovers promising projects on [Moltbook](https://www.moltbook.com), analyzes their tokenization potential, and prepares token launch proposals for the [SURGE](https://surge.xyz) launchpad.

> The current release runs on demand. OpenClaw can schedule it; a built-in scheduler and real on-chain deployment remain future work.

Current scope: scout → analyze → advise → prepare → generate reports. Publishing reports is a separate authenticated action. Demo data is fictional and explicitly labeled.

## How It Works

SurgeScout runs a continuous pipeline:

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

- **On-demand Scouting** — Scans 5+ Moltbook submolts for project signals
- **LLM Analysis** — Deep project evaluation via Claude or GPT
- **Tokenomics Engine** — Generates ticker, supply, bonding curve recommendations
- **Launch Preparation** — Generates proposed Base/Solana token settings; does not deploy or sign transactions
- **Moltbook Reporting** — Submits authenticated reports to your configured submolt; account claiming and verification may be required
- **Web Dashboard** — Real-time visualization of agent activity
- **OpenClaw Skill** — Drop-in skill for any OpenClaw agent
- **Pipeline API** — One endpoint scouts, analyzes, generates reports and prepares eligible launch proposals; publishing is separate

## Quick Start

Clone or download this repository, then run one command from its folder:

| System | Command |
|---|---|
| Linux / macOS | `bash setup.sh` |
| Windows | `setup.cmd` |
| Existing Python 3.12+ | `python setup.py` |

The script provisions Python when needed, creates an isolated environment, installs dependencies, creates configuration without overwriting it, starts the local dashboard and opens your browser. On first interactive launch the script securely asks for your provider and API key; use `--configure` later to add missing credentials. Live analysis needs a provider API key; reporting needs a claimed Moltbook account and token. First installation needs internet access. OS permissions and account authorization may still prompt you.

For OpenClaw installation, skill installation, guided authorization and Gateway service setup, append `--openclaw setup`. Manage it with `--openclaw start`, `stop`, `restart` or `status`. Use `--no-launch` to install without starting the dashboard, `--no-browser` to suppress browser opening, or `--port 3000` for another port. Existing OpenClaw configuration and installed skills are preserved.

Windows, macOS and Linux are targeted; native Windows/macOS execution has not been verified in this release. OpenClaw is optional for the standalone dashboard. Scheduling through OpenClaw is explicit; setup does not silently schedule paid AI calls or publish reports.

### Install as OpenClaw Skill

```bash
# Copy skill to OpenClaw workspace
cp -r skill/ ~/.openclaw/workspace/skills/surgescout/

# Or tell your OpenClaw agent:
# "Install the SurgeScout skill from /path/to/SurgeScout/skill"
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
SurgeScout/
├── app.py                      # Entry point (uvicorn server)
├── src/
│   ├── config.py               # Configuration from .env
│   ├── server.py               # FastAPI server + all routes
│   ├── moltbook.py             # Moltbook API client + project extraction
│   ├── analyzer.py             # LLM-powered analysis engine
│   └── launcher.py             # SURGE launchpad + on-chain deployment
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
- **Backend**: Python + FastAPI
- **AI**: Anthropic Claude / OpenAI GPT (configurable)
- **Launch proposals**: Base/Solana configuration only; real on-chain integration is future work
- **Social**: Moltbook API (agent posting)
- **Frontend**: Tailwind CSS, Chart.js, marked.js

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `AI_PROVIDER` | `anthropic` | LLM provider |
| `ANTHROPIC_API_KEY` | - | Claude API key |
| `OPENAI_API_KEY` | - | OpenAI API key |
| `MOLTBOOK_API_URL` | `https://www.moltbook.com` | Moltbook API |
| `MOLTBOOK_AUTH_TOKEN` | - | Claimed agent bearer token; never sent outside canonical Moltbook origin |
| `MOLTBOOK_AGENT_NAME` | `surgescout` | Profile used by dashboard |
| `MOLTBOOK_SUBMOLT` | `lablab` | Default submolt |
| `SURGE_API_URL` | `https://api.surge.xyz` | SURGE API |
| `BASE_RPC_URL` | `https://sepolia.base.org` | Base RPC |
| `WALLET_PRIVATE_KEY` | - | Reserved for future deployment; current release does not use it |

## Validation and Rollback

Run `python -m pip install pytest` then `python -m pytest -q`. Tests mock paid LLM calls and external integrations. The local server binds to loopback by default; authenticated public hosting remains roadmap work. Keep it local until that is implemented.

Major changes are separate commits. Review `CHANGELOG.md` and `git log --oneline`. To undo a change without rewriting shared history, use `git revert <commit-sha>` then push the revert. Configuration and runtime state are ignored by Git; back up `.env` and `data/state.json` separately.

## Future Roadmap

Development is organized into 4 phases, each building on the last.

### Phase 1 — Foundation & Reliability

Make the core pipeline production-ready.

- **SQLite Database** — Replace the in-memory `_state` dict + JSON file with SQLite via SQLModel for persistent, queryable storage across restarts
- **Async I/O** — Convert all LLM calls, Moltbook fetches, and SURGE requests from blocking `httpx.Client` + `time.sleep()` to non-blocking `httpx.AsyncClient` + `asyncio`
- **Background Scheduler** — Add `APScheduler` so the scout→analyze pipeline runs automatically on a configurable interval instead of requiring manual triggers
- **Moltbook Auth** — Wire up `MOLTBOOK_AUTH_TOKEN` so posting to Moltbook actually authenticates
- **API Key Middleware** — Protect all endpoints behind a simple `X-API-Key` header check
- **Tests** — Add `pytest` integration tests for endpoints, analyzer, and Moltbook client with mocked HTTP/LLM calls

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

Turn SurgeScout from a hackathon project into a real product.

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
