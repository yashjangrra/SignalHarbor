"""Token launch configuration preparation; live deployment is not implemented."""

import logging
from datetime import datetime, timezone

import httpx

from . import config

log = logging.getLogger("signalharbor.launcher")

# ---------------------------------------------------------------------------
# SURGE Launchpad Client
# ---------------------------------------------------------------------------

class SurgeLauncher:
    """Prepare launch proposals; optional read-only launchpad queries."""

    def __init__(self, api_url: str = "", wallet_key: str = ""):
        self.api_url = (api_url or config.SURGE_API_URL).rstrip("/")
        self.wallet_key = wallet_key or config.WALLET_PRIVATE_KEY
        self._http = httpx.AsyncClient(timeout=60, follow_redirects=True)

    async def close(self):
        await self._http.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        return h

    # ------ Token Launch ------

    def prepare_launch(self, params: dict) -> dict:
        """Prepare a token launch configuration.

        Args:
            params: {
                "name": "ProjectToken",
                "ticker": "PROJ",
                "total_supply": "1000000",
                "bonding_curve": "linear",
                "initial_price_usd": "0.001",
                "description": "...",
                "chain": "base" | "solana" | "bnb",
                "creator_wallet": "0x...",
                "metadata": {...}
            }

        Returns:
            Launch configuration ready for deployment.
        """
        launch_config = {
            "token": {
                "name": params.get("name", "Unnamed Token"),
                "symbol": params.get("ticker", "TKN"),
                "totalSupply": params.get("total_supply", "1000000"),
                "decimals": params.get("decimals", 18),
                "description": params.get("description", ""),
            },
            "launch": {
                "bondingCurve": params.get("bonding_curve", "linear"),
                "initialPriceUsd": params.get("initial_price_usd", "0.001"),
                "chain": params.get("chain", "base"),
                "creatorWallet": params.get("creator_wallet", ""),
            },
            "metadata": params.get("metadata", {}),
            "prepared_at": datetime.now(timezone.utc).isoformat(),
        }
        return launch_config

    def deploy_token(self, launch_config: dict) -> dict:
        """Return preparation only. On-chain execution is a future roadmap item."""
        return {
            "status": "prepared",
            "deployed": False,
            "launch_config": launch_config,
            "next_step": "Review configuration; live token deployment is not implemented.",
        }

    async def get_token_status(self, token_id: str) -> dict:
        """Check the status of a deployed token."""
        url = f"{self.api_url}/v1/tokens/{token_id}/status"
        try:
            r = await self._http.get(url, headers=self._headers())
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    async def list_launches(self, chain: str = "", status: str = "active") -> list[dict]:
        """List existing token launches on SURGE."""
        url = f"{self.api_url}/v1/tokens"
        params = {"status": status}
        if chain:
            params["chain"] = chain
        try:
            r = await self._http.get(url, params=params, headers=self._headers())
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, list) else data.get("tokens", data.get("data", []))
        except Exception as e:
            log.warning(f"SURGE list failed: {e}")
            return []


# ---------------------------------------------------------------------------
# On-chain deployment via Web3 (Base Sepolia testnet)
# ---------------------------------------------------------------------------

def deploy_erc20_base(
    name: str,
    symbol: str,
    total_supply: int,
    rpc_url: str = "",
    private_key: str = "",
) -> dict:
    """Compatibility helper: prepare parameters without RPC calls or signing."""
    return {
        "status": "prepared", "deployed": False, "chain": "base-sepolia",
        "token_name": name, "token_symbol": symbol, "total_supply": total_supply,
        "note": "Live ERC20 deployment is a future roadmap item; no transaction was sent.",
    }


# ---------------------------------------------------------------------------
# High-level launch pipeline
# ---------------------------------------------------------------------------

async def launch_pipeline(analysis: dict, chain: str = "base") -> dict:
    """Full launch pipeline: take an analysis result and prepare/deploy a token.

    Args:
        analysis: Output from analyzer.analyze_project()
        chain: Target chain ("base", "solana", "bnb")

    Returns:
        Launch result dict.
    """
    verdict = analysis.get("verdict", "SKIP")
    if verdict not in ("STRONG_LAUNCH", "PROMISING"):
        return {
            "status": "skipped",
            "reason": f"Verdict is {verdict}, not eligible for launch",
        }

    token_advice = analysis.get("tokenomics_advice", {})
    if not token_advice:
        return {"status": "skipped", "reason": "No tokenomics advice available"}

    # Prepare launch params
    params = {
        "name": analysis.get("project_name", "Unknown"),
        "ticker": token_advice.get("suggested_name", "$TKN").replace("$", ""),
        "total_supply": token_advice.get("suggested_supply", "1000000"),
        "bonding_curve": token_advice.get("bonding_curve", "linear"),
        "initial_price_usd": token_advice.get("initial_price_usd", "0.001"),
        "description": analysis.get("summary", ""),
        "chain": chain,
        "metadata": {
            "signalharbor_score": analysis.get("overall_score", 0),
            "signalharbor_verdict": verdict,
            "source": "signalharbor",
        },
    }

    launcher = SurgeLauncher()
    launch_config = launcher.prepare_launch(params)

    # Preparation only; future deployment must use a verified signing integration.
    try:
        result = launcher.deploy_token(launch_config)
    finally:
        await launcher.close()

    if result.get("error"):
        log.warning(f"SURGE API unavailable, preparing direct deployment config")
        result = {
            "status": "prepared",
            "launch_config": launch_config,
            "params": params,
            "next_step": "Deploy via OpenClaw SURGE skill or Clanker SDK",
        }

    result["analysis_score"] = analysis.get("overall_score", 0)
    result["analysis_verdict"] = verdict
    return result
