"""SignalHarbor API server — FastAPI backend powering the agent and dashboard."""

import json
import asyncio
import copy
import inspect
from contextlib import asynccontextmanager
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config
from .moltbook import MoltbookClient, scout_moltbook, extract_projects_from_posts
from .analyzer import analyze_project, analyze_batch, generate_launch_report
from .launcher import SurgeLauncher, launch_pipeline

log = logging.getLogger("signalharbor.server")

from .scheduler import PipelineScheduler

async def _invoke(function, *args, **kwargs):
    """Call async integrations, retaining support for synchronous test doubles."""
    if inspect.iscoroutinefunction(function):
        return await function(*args, **kwargs)
    result = await asyncio.to_thread(function, *args, **kwargs)
    return await result if inspect.isawaitable(result) else result

async def _scheduled_pipeline():
    async with _mutation_lock:
        if _state.get("demo_mode"):
            return {"status": "skipped_demo"}
        return await full_pipeline(ScoutRequest())

_scheduler = PipelineScheduler(_scheduled_pipeline)

@asynccontextmanager
async def lifespan(application):
    _scheduler.start()
    try:
        yield
    finally:
        await _scheduler.stop()


app = FastAPI(
    title="SignalHarbor",
    description="AI Deal Flow Agent for Internet Capital Markets on SURGE",
    version="1.2.2",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# SQLite is the live source of truth; demo data stays process-local.
from .database import StateStore, DatabaseState

DATA_FILE = os.path.join(config.DATA_DIR, "state.json")
_store = StateStore(getattr(config, "DATABASE_PATH", os.path.join(config.DATA_DIR, "signalharbor.db")), legacy_path=DATA_FILE)
_state = DatabaseState(_store)
_mutation_lock = asyncio.Lock()
_demo_snapshot = None

@app.middleware("http")
async def serialize_mutations(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        async with _mutation_lock:
            return await call_next(request)
    return await call_next(request)

from .auth import APIKeyMiddleware
app.add_middleware(APIKeyMiddleware)

def _save_state():
    if not isinstance(_state, DatabaseState) and not _state.get("demo_mode"):
        _store.save_state(dict(_state))

def _require_live():
    if _state.get("demo_mode"):
        raise HTTPException(409, "Clear demo mode before running live operations")


async def _update_state(values):
    """Commit related fields together without blocking the event loop."""
    def commit():
        _state.update(values)
        _save_state()
    await asyncio.to_thread(commit)


def _load_state():
    return _store.load_state()


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class ScoutRequest(BaseModel):
    submolts: list[str] | None = None
    keywords: list[str] | None = None


class AnalyzeRequest(BaseModel):
    project: dict | None = None
    project_id: str | None = None
    min_score: int = Field(default=0, ge=0, le=100)


class LaunchRequest(BaseModel):
    analysis_index: int | None = None
    project_name: str | None = None
    chain: str = Field(default="base", pattern="^(base|solana)$")


class MoltbookPostRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=40000)
    submolt: str = ""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

_web_dir = Path(__file__).parent.parent / "web"
app.mount("/static", StaticFiles(directory=str(_web_dir)), name="static")


@app.get("/favicon.ico")
def favicon():
    """Serve favicon."""
    icon = _web_dir / "logo.svg"
    if icon.exists():
        return FileResponse(icon, media_type="image/svg+xml")
    return JSONResponse({}, status_code=404)


@app.get("/")
def index():
    """Serve the dashboard."""
    html_path = _web_dir / "index.html"
    if html_path.exists():
        return FileResponse(html_path, media_type="text/html")
    return HTMLResponse("<h1>SignalHarbor</h1><p>Dashboard not found. Check web/index.html</p>")


@app.get("/api/health")
def health():
    has_key = bool(config.selected_api_key())
    return {
        "status": "ok",
        "scheduler": _scheduler.status(),
        "launch_mode": "preparation_only",
        "demo_mode": _state.get("demo_mode", False),
        "provider": config.AI_PROVIDER,
        "api_key_configured": has_key,
        "projects_scouted": len(_state["scouted_projects"]),
        "analyses_done": len(_state["analyses"]),
        "launches": len(_state["launches"]),
    }


@app.get("/api/state")
def get_state():
    """Return full agent state with computed fields."""
    launch_ready = sum(
        1 for a in _state.get("analyses", [])
        if a.get("verdict") == "STRONG_LAUNCH" and a.get("overall_score", 0) >= 75
    )
    return copy.deepcopy({**_state, "launch_ready_count": launch_ready})


# ------ Scout ------

@app.post("/api/scout")
async def scout(req: ScoutRequest):
    """Scout Moltbook for promising projects."""
    _require_live()
    projects = await _invoke(scout_moltbook,
        submolts=req.submolts,
        keywords=req.keywords,
    )
    await _update_state({"demo_mode": False, "scouted_projects": projects,
                   "last_scout": datetime.now(timezone.utc).isoformat()})
    return {
        "count": len(projects),
        "projects": projects,
    }


# ------ Analyze ------

@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest):
    """Analyze a project or all scouted projects."""
    _require_live()
    if req.project:
        result = await _invoke(analyze_project,req.project)
        if result.get("error"):
            raise HTTPException(502, result["error"])
        await _update_state({"demo_mode": False,
                       "last_analysis": datetime.now(timezone.utc).isoformat(),
                       "analyses": list(_state["analyses"]) + [result]})
        return result

    if req.project_id:
        proj = next(
            (p for p in _state["scouted_projects"] if str(p.get("id")) == req.project_id),
            None,
        )
        if not proj:
            raise HTTPException(404, f"Project {req.project_id} not found in scouted list")
        result = await _invoke(analyze_project,proj)
        if result.get("error"):
            raise HTTPException(502, result["error"])
        await _update_state({"demo_mode": False,
                       "last_analysis": datetime.now(timezone.utc).isoformat(),
                       "analyses": list(_state["analyses"]) + [result]})
        return result

    # Analyze all scouted projects
    if not _state["scouted_projects"]:
        raise HTTPException(400, "No scouted projects. Run /api/scout first.")

    results = await _invoke(analyze_batch,_state["scouted_projects"], min_score=req.min_score)
    await _update_state({"demo_mode": False, "analyses": results,
                   "last_analysis": datetime.now(timezone.utc).isoformat()})
    return {
        "count": len(results),
        "analyses": results,
    }


@app.get("/api/analyses")
def list_analyses():
    """List all completed analyses."""
    return _state["analyses"]


@app.get("/api/report/{index}")
def get_report(index: int):
    """Get a human-readable report for an analysis."""
    if index < 0 or index >= len(_state["analyses"]):
        raise HTTPException(404, "Analysis not found")
    report = generate_launch_report(_state["analyses"][index])
    return {"report": report, "analysis": _state["analyses"][index]}


# ------ Launch ------

@app.post("/api/launch")
async def launch(req: LaunchRequest):
    """Launch a token based on analysis results."""
    analysis = None

    if req.analysis_index is not None:
        if req.analysis_index < 0 or req.analysis_index >= len(_state["analyses"]):
            raise HTTPException(404, "Analysis not found at that index")
        analysis = _state["analyses"][req.analysis_index]
    elif req.project_name:
        analysis = next(
            (a for a in _state["analyses"] if a.get("project_name") == req.project_name),
            None,
        )
    else:
        # Use the best analysis
        if _state["analyses"]:
            analysis = max(_state["analyses"], key=lambda a: a.get("overall_score", 0))

    if not analysis:
        raise HTTPException(400, "No analysis found. Run /api/analyze first.")

    result = await _invoke(launch_pipeline, analysis, chain=req.chain)
    await _update_state({"launches": list(_state["launches"]) + [{
        "project": analysis.get("project_name"),
        "result": result,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }]})
    return result


@app.get("/api/launches")
def list_launches():
    """List all token launches."""
    return _state["launches"]


# ------ Moltbook ------

@app.post("/api/moltbook/post")
async def moltbook_post(req: MoltbookPostRequest):
    """Post an update to Moltbook."""
    _require_live()
    client = MoltbookClient()
    try:
        result = await _invoke(client.post_update,req.title, req.body, req.submolt)
    finally:
        await _invoke(client.close)
    if result.get("error"):
        raise HTTPException(502, result["error"])
    await _update_state({"moltbook_posts": list(_state["moltbook_posts"]) + [{
        "title": req.title,
        "body": req.body[:200],
        "result": result,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }]})
    return result


@app.get("/api/moltbook/posts")
async def moltbook_user_posts():
    """Fetch signalharbor's published posts from Moltbook."""
    client = MoltbookClient()
    try:
        posts = await _invoke(client.fetch_user_posts,config.MOLTBOOK_AGENT_NAME, limit=30)
    finally:
        await _invoke(client.close)
    # Normalize each post to a consistent shape
    result = []
    for p in posts:
        post_id = p.get("id", "")
        # Extract short ID (first 8 chars of UUID)
        short_id = post_id.split("-")[0] if post_id else ""
        title = p.get("title", "")
        body = p.get("body", p.get("content", ""))
        created = p.get("created_at", p.get("createdAt", ""))
        submolt = p.get("submolt", {})
        sub_name = submolt.get("name", "lablab") if isinstance(submolt, dict) else str(submolt or "lablab")
        result.append({
            "id": post_id,
            "short_id": short_id,
            "title": title,
            "body": (body or "")[:300],
            "created_at": created,
            "submolt": sub_name,
            "url": f"https://www.moltbook.com/post/{post_id}" if short_id else "",
            "votes": p.get("votes", p.get("upvotes", 0)),
        })
    return {"posts": result, "count": len(result), "demo_mode": False}


@app.post("/api/moltbook/report")
async def moltbook_report(req: AnalyzeRequest):
    """Generate and post a report to Moltbook for the best analysis."""
    if not _state["analyses"]:
        raise HTTPException(400, "No analyses available. Run /api/analyze first.")

    idx = max(range(len(_state["analyses"])), key=lambda i: _state["analyses"][i].get("overall_score", 0))
    if req.project_id:
        for i, a in enumerate(_state["analyses"]):
            if a.get("project_name") == req.project_id:
                idx = i
                break
        else:
            raise HTTPException(404, "Analysis not found")

    analysis = _state["analyses"][idx]
    report = generate_launch_report(analysis)

    if _state.get("demo_mode"):
        raise HTTPException(409, "Demo reports cannot be published")
    client = MoltbookClient()
    title = f"[SignalHarbor] Analysis: {analysis.get('project_name', '?')} — {analysis.get('verdict', '?')}"
    try:
        result = await _invoke(client.post_update,title, report)
    finally:
        await _invoke(client.close)
    if result.get("error"):
        raise HTTPException(502, result["error"])

    await _update_state({"moltbook_posts": list(_state["moltbook_posts"]) + [{
        "title": title,
        "body": report[:200],
        "result": result,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }]})
    return {"post_result": result, "report": report}


# ------ Demo Data ------

DEMO_PROJECTS = [
    {
        "id": "demo-1",
        "title": "AgentSwap — Decentralized Agent-to-Agent Token Exchange",
        "body": "AgentSwap enables AI agents to autonomously swap tokens across chains. Built on Base with OpenClaw integration. Live demo: agents trading $ASWP tokens in real-time. Bonding curve launches on SURGE next week. Already 200+ agents onboarded during beta.",
        "author": "agentswap_dev",
        "github_urls": ["https://github.com/agentswap/core"],
        "token_mentions": ["ASWP"],
        "votes": 847,
        "comments": 134,
        "created_at": "2026-02-20T14:30:00Z",
        "url": "https://moltbook.com/m/lablab/agentswap-launch",
        "submolt": "lablab",
        "source": "moltbook",
    },
    {
        "id": "demo-2",
        "title": "MoltAnalytics — On-chain Intelligence Dashboard for Moltbook",
        "body": "Track trending projects, sentiment analysis, and deal flow across Moltbook submolts. Uses Claude for NLP analysis of posts. Deployed on Vercel with real-time data feeds. Planning $MOLT token launch for premium features. Hackathon submission for SURGE x OpenClaw.",
        "author": "data_miner42",
        "github_urls": ["https://github.com/moltanalytics/dashboard"],
        "token_mentions": ["MOLT"],
        "votes": 523,
        "comments": 89,
        "created_at": "2026-02-19T09:15:00Z",
        "url": "https://moltbook.com/m/lablab/moltanalytics",
        "submolt": "lablab",
        "source": "moltbook",
    },
    {
        "id": "demo-3",
        "title": "SkillForge — AI Agent Skill Marketplace on SURGE",
        "body": "Create, share, and monetize OpenClaw agent skills. Each skill gets its own token on SURGE with bonding curve pricing. Top skills: code-review, security-audit, deploy-agent. Built with FastAPI + React. $FORGE token powers the marketplace economy.",
        "author": "skillforge_team",
        "github_urls": ["https://github.com/skillforge/marketplace"],
        "token_mentions": ["FORGE"],
        "votes": 1203,
        "comments": 256,
        "created_at": "2026-02-21T11:00:00Z",
        "url": "https://moltbook.com/m/defi/skillforge",
        "submolt": "defi",
        "source": "moltbook",
    },
    {
        "id": "demo-4",
        "title": "ChainGuard — Autonomous Security Auditing Agent",
        "body": "AI agent that continuously audits smart contracts on Base and Solana. Reports vulnerabilities to Moltbook. Built for the SURGE hackathon. Uses static analysis + LLM reasoning. Free tier available, $GUARD token for premium continuous monitoring.",
        "author": "chainguard_ai",
        "github_urls": ["https://github.com/chainguard-ai/auditor"],
        "token_mentions": ["GUARD"],
        "votes": 312,
        "comments": 45,
        "created_at": "2026-02-18T16:45:00Z",
        "url": "https://moltbook.com/m/agents/chainguard",
        "submolt": "agents",
        "source": "moltbook",
    },
    {
        "id": "demo-5",
        "title": "YieldPilot — Autonomous DeFi Yield Optimizer Agent",
        "body": "Agent that scans DeFi protocols across chains and auto-rebalances for optimal yield. OpenClaw skill interface. Currently in alpha with $50k TVL. Exploring $YIELD token for governance. No GitHub yet, closed source during hackathon.",
        "author": "yield_pilot",
        "github_urls": [],
        "token_mentions": ["YIELD"],
        "votes": 178,
        "comments": 23,
        "created_at": "2026-02-17T08:00:00Z",
        "url": "https://moltbook.com/m/defi/yieldpilot",
        "submolt": "defi",
        "source": "moltbook",
    },
]

DEMO_ANALYSES = [
    {
        "project_name": "SkillForge",
        "summary": "A marketplace for OpenClaw agent skills with tokenized pricing via SURGE bonding curves. Strong concept with clear utility and impressive community traction.",
        "scores": {
            "market_fit": 88,
            "team_signal": 75,
            "technical_quality": 82,
            "tokenomics_feasibility": 90,
            "traction": 85,
        },
        "overall_score": 85,
        "verdict": "STRONG_LAUNCH",
        "tokenomics_advice": {
            "suggested_name": "$FORGE",
            "suggested_supply": "10000000",
            "bonding_curve": "sigmoid",
            "initial_price_usd": "0.005",
            "rationale": "Sigmoid curve rewards early skill creators while preventing pump-and-dump. 10M supply allows wide distribution across skill marketplace participants.",
        },
        "risks": [
            "Marketplace liquidity depends on skill quality and adoption",
            "Competing with free/open-source skill sharing",
            "Regulatory uncertainty around tokenized digital goods",
        ],
        "strengths": [
            "Clear token utility — $FORGE is the native marketplace currency",
            "Strong community traction with 1200+ votes",
            "Built on proven OpenClaw infrastructure",
            "Revenue model: platform fees on skill transactions",
        ],
        "recommendation": "Strong launch candidate. The skill marketplace fills a genuine need in the OpenClaw ecosystem. Recommend launching with a sigmoid bonding curve to incentivize early contributors.",
        "_source_project_id": "demo-3",
        "_analyzed_at": "2026-02-22T10:00:00Z",
    },
    {
        "project_name": "AgentSwap",
        "summary": "Decentralized exchange purpose-built for AI agent token trading. Innovative concept leveraging autonomous agents as market participants.",
        "scores": {
            "market_fit": 82,
            "team_signal": 70,
            "technical_quality": 78,
            "tokenomics_feasibility": 75,
            "traction": 72,
        },
        "overall_score": 76,
        "verdict": "STRONG_LAUNCH",
        "tokenomics_advice": {
            "suggested_name": "$ASWP",
            "suggested_supply": "5000000",
            "bonding_curve": "exponential",
            "initial_price_usd": "0.01",
            "rationale": "Exponential curve suits a DEX token where value scales with trading volume. 5M supply keeps token scarce as agent adoption grows.",
        },
        "risks": [
            "Agent-to-agent trading volume may be low initially",
            "Cross-chain bridging introduces security risks",
            "Dependent on OpenClaw agent ecosystem growth",
        ],
        "strengths": [
            "Novel concept — first DEX designed for AI agents",
            "Working beta with 200+ agents onboarded",
            "GitHub repo shows active development",
            "Strong Moltbook engagement (847 votes)",
        ],
        "recommendation": "Launch-ready with strong fundamentals. The agent-first DEX concept is timely as the OpenClaw ecosystem grows. Recommend launching on Base first, then expanding cross-chain.",
        "_source_project_id": "demo-1",
        "_analyzed_at": "2026-02-22T10:05:00Z",
    },
    {
        "project_name": "MoltAnalytics",
        "summary": "Intelligence dashboard providing sentiment analysis and deal flow tracking for Moltbook. Useful tool for investors and agents monitoring the ICM ecosystem.",
        "scores": {
            "market_fit": 72,
            "team_signal": 65,
            "technical_quality": 70,
            "tokenomics_feasibility": 58,
            "traction": 68,
        },
        "overall_score": 67,
        "verdict": "PROMISING",
        "tokenomics_advice": {
            "suggested_name": "$MOLT",
            "suggested_supply": "20000000",
            "bonding_curve": "linear",
            "initial_price_usd": "0.001",
            "rationale": "Linear curve for accessible entry. Premium analytics features gated by token holdings.",
        },
        "risks": [
            "Analytics tools face competition from free alternatives",
            "Token utility is limited to premium feature access",
            "Dependency on Moltbook API stability",
        ],
        "strengths": [
            "Addresses real need for ICM market intelligence",
            "Claude-powered NLP analysis is differentiated",
            "Already deployed and functional",
            "Good community reception on Moltbook",
        ],
        "recommendation": "Promising but needs stronger token utility before launch. Consider adding governance features or staking for priority data access.",
        "_source_project_id": "demo-2",
        "_analyzed_at": "2026-02-22T10:10:00Z",
    },
    {
        "project_name": "ChainGuard",
        "summary": "Autonomous smart contract security auditing agent. Important infrastructure but early-stage with limited traction.",
        "scores": {
            "market_fit": 75,
            "team_signal": 55,
            "technical_quality": 60,
            "tokenomics_feasibility": 45,
            "traction": 35,
        },
        "overall_score": 55,
        "verdict": "PROMISING",
        "tokenomics_advice": {
            "suggested_name": "$GUARD",
            "suggested_supply": "50000000",
            "bonding_curve": "linear",
            "initial_price_usd": "0.0005",
            "rationale": "High supply for broad accessibility. Security is a utility that benefits from wide token distribution.",
        },
        "risks": [
            "Limited traction with only 312 votes",
            "Security auditing requires high accuracy — liability concerns",
            "No clear revenue model beyond token sales",
        ],
        "strengths": [
            "Addresses critical need in DeFi security",
            "AI-powered auditing is scalable",
            "GitHub repo shows working code",
        ],
        "recommendation": "Needs more development and traction before token launch. Focus on proving audit accuracy and building a track record.",
        "_source_project_id": "demo-4",
        "_analyzed_at": "2026-02-22T10:15:00Z",
    },
    {
        "project_name": "YieldPilot",
        "summary": "Autonomous DeFi yield optimizer. Interesting concept but closed source and limited evidence of capability.",
        "scores": {
            "market_fit": 60,
            "team_signal": 30,
            "technical_quality": 25,
            "tokenomics_feasibility": 40,
            "traction": 20,
        },
        "overall_score": 34,
        "verdict": "NEEDS_WORK",
        "tokenomics_advice": {
            "suggested_name": "$YIELD",
            "suggested_supply": "100000000",
            "bonding_curve": "linear",
            "initial_price_usd": "0.0001",
            "rationale": "Not recommended for launch yet. Very low entry price given early stage.",
        },
        "risks": [
            "Closed source — no way to verify claims",
            "No GitHub, no verifiable technical quality",
            "Low community engagement (178 votes)",
            "$50k TVL is unverified",
        ],
        "strengths": [
            "DeFi yield optimization is a large market",
            "OpenClaw integration is interesting",
        ],
        "recommendation": "Not ready for token launch. Must open-source the code, provide verifiable TVL data, and build community trust.",
        "_source_project_id": "demo-5",
        "_analyzed_at": "2026-02-22T10:20:00Z",
    },
]


@app.post("/api/demo")
def load_demo():
    """Load demo data for presentation/video purposes."""
    global _demo_snapshot, _state
    if not _state.get("demo_mode"):
        _demo_snapshot = _state
        _state = copy.deepcopy(_state)
    _state["demo_mode"] = True
    _state["scouted_projects"] = copy.deepcopy(DEMO_PROJECTS)
    _state["analyses"] = copy.deepcopy(DEMO_ANALYSES)
    _state["launches"] = [
        {
            "project": "SkillForge",
            "result": {
                "status": "prepared",
                "launch_config": {
                    "token": {"name": "SkillForge", "symbol": "FORGE", "totalSupply": "10000000"},
                    "launch": {"bondingCurve": "sigmoid", "initialPriceUsd": "0.005", "chain": "base"},
                },
                "next_step": "Deploy via OpenClaw SURGE skill or Clanker SDK",
                "analysis_score": 85,
                "analysis_verdict": "STRONG_LAUNCH",
            },
            "timestamp": "2026-02-22T12:00:00Z",
        },
        {
            "project": "AgentSwap",
            "result": {
                "status": "prepared",
                "launch_config": {
                    "token": {"name": "AgentSwap", "symbol": "ASWP", "totalSupply": "5000000"},
                    "launch": {"bondingCurve": "exponential", "initialPriceUsd": "0.01", "chain": "base"},
                },
                "next_step": "Deploy via OpenClaw SURGE skill or Clanker SDK",
                "analysis_score": 76,
                "analysis_verdict": "STRONG_LAUNCH",
            },
            "timestamp": "2026-02-22T12:30:00Z",
        },
    ]
    _state["moltbook_posts"] = [
        {
            "title": "Introducing SignalHarbor — AI Deal Flow Agent for Internet Capital Markets",
            "body": "We're building SignalHarbor for the SURGE x OpenClaw hackathon on lablab.ai...",
            "result": {"status": "posted", "post_id": "3b38d762"},
            "timestamp": "2026-02-24T16:00:00Z",
        },
        {
            "title": "SignalHarbor Pipeline Demo: Scouted 85 projects, analyzed 5, found 2 launch-ready",
            "body": "We just ran the full SignalHarbor pipeline on live Moltbook data...",
            "result": {"status": "posted", "post_id": "2fb408a0"},
            "timestamp": "2026-02-24T16:05:00Z",
        },
        {
            "title": "SignalHarbor Scoring Model: 5 Dimensions for Evaluating Tokenization Potential",
            "body": "Here's how SignalHarbor evaluates projects for token launches on SURGE...",
            "result": {"status": "posted", "post_id": "13cdbcc5"},
            "timestamp": "2026-02-24T16:10:00Z",
        },
        {
            "title": "[SignalHarbor] Analysis: SkillForge — STRONG_LAUNCH",
            "body": "# [LAUNCH] SignalHarbor Analysis: SkillForge — Overall Score: 85/100...",
            "result": {"status": "posted", "post_id": "demo-post-1"},
            "timestamp": "2026-02-24T16:15:00Z",
        },
    ]
    _state["last_scout"] = "2026-02-22T09:00:00Z"
    _state["last_analysis"] = "2026-02-22T10:00:00Z"
    _save_state()
    return {
        "status": "demo_loaded",
        "projects": len(DEMO_PROJECTS),
        "analyses": len(DEMO_ANALYSES),
        "launches": len(_state["launches"]),
        "posts": len(_state["moltbook_posts"]),
    }


@app.post("/api/demo/clear")
def clear_demo():
    global _demo_snapshot, _state
    if _demo_snapshot is None:
        raise HTTPException(409, "No live snapshot available in this process")
    _state = _demo_snapshot
    _demo_snapshot = None
    _save_state()
    return {"status": "restored"}


# ------ Pipeline (full cycle) ------

@app.post("/api/pipeline")
async def full_pipeline(req: ScoutRequest):
    """Run the full SignalHarbor pipeline: Scout -> Analyze -> Report.

    This is the main autonomous pipeline the OpenClaw agent triggers.
    """
    _require_live()
    # 1. Scout
    projects = await _invoke(scout_moltbook,submolts=req.submolts, keywords=req.keywords)
    await _update_state({"demo_mode": False, "scouted_projects": projects,
                   "last_scout": datetime.now(timezone.utc).isoformat()})

    if not projects:
        return {"status": "no_projects_found", "step": "scout"}

    # 2. Analyze top candidates (max 8, sorted by quality from scout)
    top_projects = projects[:8]
    analyses = await _invoke(analyze_batch,top_projects, min_score=0)  # Keep all results, even low scores
    failures = [a for a in analyses if a.get("error")]
    if len(analyses) < len(top_projects):
        failures.append({"error": "Some candidates failed analysis; inspect server logs", "count": len(top_projects) - len(analyses)})
    analyses = [a for a in analyses if not a.get("error")]
    analyses.sort(key=lambda a: a.get("overall_score", 0), reverse=True)
    await _update_state({"analyses": analyses,
                   "last_analysis": datetime.now(timezone.utc).isoformat()})

    if not analyses:
        return {"status": "analysis_failed", "step": "analyze", "scouted": len(projects), "errors": failures}

    # 3. Generate reports for top results
    reports = []
    for analysis in analyses[:3]:
        report = generate_launch_report(analysis)
        reports.append({
            "project": analysis.get("project_name"),
            "score": analysis.get("overall_score"),
            "verdict": analysis.get("verdict"),
            "report": report,
        })

    configurations = []
    launches = list(_state["launches"])
    for analysis in analyses:
        if analysis.get("verdict") in ("STRONG_LAUNCH", "PROMISING"):
            result = await _invoke(launch_pipeline, analysis)
            configurations.append(result)
            launches.append({"project": analysis.get("project_name"), "result": result,
                             "timestamp": datetime.now(timezone.utc).isoformat()})
    if configurations:
        await _update_state({"launches": launches})

    return {
        "status": "partial" if failures else "complete",
        "errors": failures,
        "launch_configurations": configurations,
        "scouted": len(projects),
        "analyzed": len(analyses),
        "reports": reports,
        "best_project": analyses[0].get("project_name") if analyses else None,
        "best_score": analyses[0].get("overall_score") if analyses else 0,
    }
