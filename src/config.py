"""SignalHarbor configuration."""

import os
import math
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# LLM
AI_PROVIDER = os.getenv("AI_PROVIDER", "openrouter").strip().lower()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "")

def selected_api_key() -> str:
    """Return only the explicitly selected provider's credential."""
    return {
        "openrouter": OPENROUTER_API_KEY,
        "anthropic": ANTHROPIC_API_KEY,
        "openai": OPENAI_API_KEY,
    }.get(AI_PROVIDER, "")


def selected_model() -> str:
    """Resolve provider defaults, enforcing free-only OpenRouter routing."""
    defaults = {
        "openrouter": "openrouter/free",
        "anthropic": "claude-sonnet-4-20250514",
        "openai": "gpt-4o",
    }
    if AI_PROVIDER not in defaults:
        raise RuntimeError("AI_PROVIDER must be openrouter, anthropic or openai.")
    model = AI_MODEL.strip() or defaults[AI_PROVIDER]
    if AI_PROVIDER == "openrouter" and model != "openrouter/free" and not model.endswith(":free"):
        raise RuntimeError("OpenRouter requires openrouter/free or a model ID ending in :free; paid models are disabled.")
    return model


# Moltbook
MOLTBOOK_API_URL = os.getenv("MOLTBOOK_API_URL", "https://www.moltbook.com")
MOLTBOOK_AUTH_TOKEN = os.getenv("MOLTBOOK_AUTH_TOKEN", "")
MOLTBOOK_AGENT_NAME = os.getenv("MOLTBOOK_AGENT_NAME", "signalharbor")
MOLTBOOK_SUBMOLT = os.getenv("MOLTBOOK_SUBMOLT", "lablab")

# SURGE / On-chain
SURGE_API_URL = os.getenv("SURGE_API_URL", "https://api.surge.xyz")
BASE_RPC_URL = os.getenv("BASE_RPC_URL", "https://sepolia.base.org")
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.devnet.solana.com")
WALLET_PRIVATE_KEY = os.getenv("WALLET_PRIVATE_KEY", "")

# Server
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8899"))
SECRET_KEY = os.getenv("SECRET_KEY", "signalharbor-dev-key")
API_KEY = os.getenv("API_KEY", "")
SCHEDULER_ENABLED = os.getenv("SCHEDULER_ENABLED", "false").lower() in ("1", "true", "yes")
SCOUT_INTERVAL_MINUTES = float(os.getenv("SCOUT_INTERVAL_MINUTES", "60"))
if not math.isfinite(SCOUT_INTERVAL_MINUTES) or SCOUT_INTERVAL_MINUTES <= 0:
    raise ValueError("SCOUT_INTERVAL_MINUTES must be positive")

# Paths
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)
def resolve_database_path(data_dir: str) -> str:
    """Preserve a sole existing database when upgrading a renamed installation."""
    if os.getenv("DATABASE_PATH"):
        return os.environ["DATABASE_PATH"]
    preferred = Path(data_dir) / "signalharbor.db"
    if preferred.exists():
        return str(preferred)
    existing = list(Path(data_dir).glob("*.db"))
    if len(existing) == 1:
        return str(existing[0])
    if existing:
        raise RuntimeError("Multiple existing databases found; set DATABASE_PATH explicitly to preserve your live state.")
    return str(preferred)


DATABASE_PATH = resolve_database_path(DATA_DIR)
