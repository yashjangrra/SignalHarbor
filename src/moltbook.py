"""Moltbook API client — scout projects and post agent reports."""

import logging
import hashlib
from urllib.parse import urlparse

import httpx

from . import config

log = logging.getLogger("signalharbor.moltbook")

# ---------------------------------------------------------------------------
# Moltbook client
# ---------------------------------------------------------------------------

class MoltbookClient:
    """Read from and write to Moltbook submolts."""

    def __init__(self, base_url: str = "", submolt: str = "", auth_token: str = ""):
        self.base_url = (base_url or config.MOLTBOOK_API_URL).rstrip("/")
        self.submolt = submolt or config.MOLTBOOK_SUBMOLT
        self.auth_token = auth_token or getattr(config, "MOLTBOOK_AUTH_TOKEN", "")
        if self.base_url.endswith("/api/v1"):
            self.base_url = self.base_url[:-7]
        self._http = httpx.AsyncClient(timeout=30, follow_redirects=False)

    async def close(self):
        await self._http.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()

    def _headers(self) -> dict:
        # Credentials are only valid for the official HTTPS API origin.
        origin = urlparse(self.base_url)
        if self.auth_token and (origin.scheme, origin.netloc, origin.path) != ("https", "www.moltbook.com", ""):
            raise ValueError("Moltbook credentials require https://www.moltbook.com")
        return {"Authorization": f"Bearer {self.auth_token}"} if self.auth_token else {}

    @staticmethod
    def _posts(data, key="posts") -> list[dict]:
        if isinstance(data, dict):
            data = data.get(key, data.get("data", []))
            if isinstance(data, dict):
                data = data.get(key, [])
        return [p for p in data if isinstance(p, dict)] if isinstance(data, list) else []

    # ------ read ------

    async def fetch_posts(self, submolt: str = "", limit: int = 50, sort: str = "new") -> list[dict]:
        """Fetch recent posts from a submolt."""
        sub = submolt or self.submolt
        url = f"{self.base_url}/api/v1/posts"
        try:
            r = await self._http.get(url, params={"submolt": sub, "limit": limit, "sort": sort}, headers=self._headers())
            r.raise_for_status()
            data = r.json()
            return self._posts(data)
        except Exception as e:
            log.warning(f"Moltbook fetch failed ({sub}): {e}")
            return []

    async def fetch_trending(self, limit: int = 30) -> list[dict]:
        """Fetch trending posts across Moltbook."""
        url = f"{self.base_url}/api/v1/posts"
        try:
            r = await self._http.get(url, params={"limit": limit, "sort": "hot"}, headers=self._headers())
            r.raise_for_status()
            data = r.json()
            return self._posts(data)
        except Exception as e:
            log.warning(f"Moltbook trending fetch failed: {e}")
            return []

    async def search_posts(self, query: str, limit: int = 30) -> list[dict]:
        """Search Moltbook posts by keyword."""
        url = f"{self.base_url}/api/v1/search"
        try:
            r = await self._http.get(url, params={"q": query, "limit": limit, "type": "posts"}, headers=self._headers())
            r.raise_for_status()
            data = r.json()
            return self._posts(data, "results")
        except Exception as e:
            log.warning(f"Moltbook search failed: {e}")
            return []

    # ------ write ------

    async def post_update(self, title: str, body: str, submolt: str = "") -> dict:
        """Submit an authenticated report; preserve verification challenges in response."""
        if not self.auth_token:
            return {"error": "MOLTBOOK_AUTH_TOKEN is required to publish reports"}
        sub = submolt or self.submolt
        url = f"{self.base_url}/api/v1/posts"
        payload = {
            "title": title,
            "content": body,
            "submolt_name": sub,
            "type": "text",
        }
        try:
            r = await self._http.post(url, json=payload, headers=self._headers())
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.warning(f"Moltbook post failed: {e}")
            return {"error": str(e)}

    async def fetch_user_posts(self, username: str, limit: int = 30) -> list[dict]:
        """Fetch a specific author profile and its recent posts."""
        try:
            r = await self._http.get(f"{self.base_url}/api/v1/agents/profile", params={"name": username}, headers=self._headers())
            r.raise_for_status()
            return self._posts(r.json(), "recentPosts")[:limit]
        except Exception as e:
            log.warning("Moltbook profile fetch failed: %s", e)
            return []

    async def post_comment(self, post_id: str, body: str) -> dict:
        """Comment on an existing post."""
        if not self.auth_token:
            return {"error": "MOLTBOOK_AUTH_TOKEN is required to comment"}
        url = f"{self.base_url}/api/v1/posts/{post_id}/comments"
        try:
            r = await self._http.post(url, json={"content": body}, headers=self._headers())
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.warning(f"Moltbook comment failed: {e}")
            return {"error": str(e)}


# ---------------------------------------------------------------------------
# Project extraction helpers
# ---------------------------------------------------------------------------

def _strip_html(text: str) -> str:
    """Strip HTML tags (Moltbook returns <mark> in search results)."""
    import re
    return re.sub(r'<[^>]+>', '', text)


def extract_projects_from_posts(posts: list[dict]) -> list[dict]:
    """Parse Moltbook posts to extract potential project references.

    Looks for: GitHub links, token mentions, project descriptions,
    hackathon submissions, launch announcements.
    """
    import re

    projects = []
    seen = set()

    for post in posts:
        body = _strip_html(post.get("body", "") or post.get("content", "") or "")
        title = _strip_html(post.get("title", "") or "")
        author = post.get("author", {})
        if isinstance(author, dict):
            author_name = author.get("username", author.get("name", "unknown"))
        else:
            author_name = str(author)

        # Extract GitHub URLs
        gh_urls = re.findall(r'https?://github\.com/[\w\-]+/[\w\-]+', body)

        # Extract token mentions ($TOKEN)
        tokens = re.findall(r'\$([A-Z]{2,10})', body)

        # Look for project-like content
        has_project_signals = any([
            gh_urls,
            tokens,
            any(kw in body.lower() for kw in [
                "launch", "deploy", "built", "ship", "release",
                "token", "contract", "dapp", "agent", "skill",
                "hackathon", "submission", "demo",
            ]),
        ])

        if not has_project_signals:
            continue

        # Deduplicate by content hash
        content_hash = hashlib.md5(f"{title}{body[:200]}".encode()).hexdigest()[:12]
        if content_hash in seen:
            continue
        seen.add(content_hash)

        projects.append({
            "id": post.get("id", content_hash),
            "title": title,
            "body": body[:2000],
            "author": author_name,
            "github_urls": gh_urls,
            "token_mentions": tokens,
            "votes": post.get("votes", post.get("upvotes", 0)),
            "comments": post.get("comment_count", post.get("comments", 0)),
            "created_at": post.get("created_at", post.get("createdAt", "")),
            "url": post.get("url", post.get("permalink", "")),
            "submolt": post.get("submolt", {}).get("name", "") if isinstance(post.get("submolt"), dict) else "",
            "source": "moltbook",
        })

    return projects


async def scout_moltbook(submolts: list[str] | None = None, keywords: list[str] | None = None) -> list[dict]:
    """Full scouting pipeline: fetch from multiple sources and extract projects."""
    client = MoltbookClient()
    try:
        return await _scout_with_client(client, submolts, keywords)
    finally:
        await client.close()


async def _scout_with_client(client, submolts, keywords):
    all_posts = []

    # 1. Fetch from target submolts (new + hot for variety)
    target_submolts = submolts or [
        "lablab", "cryptocurrency", "defi", "agents", "startups",
        "general", "technology", "crypto", "openclaw-explorers", "dailymolting",
    ]
    for sub in target_submolts:
        for sort in ["new", "hot"]:
            posts = await client.fetch_posts(sub, limit=50, sort=sort)
            all_posts.extend(posts)
        log.info(f"Fetched posts from m/{sub}")

    # 2. Fetch trending
    trending = await client.fetch_trending(limit=50)
    all_posts.extend(trending)
    log.info(f"Fetched {len(trending)} trending posts")

    # 3. Search by keywords
    search_keywords = keywords or [
        "token launch", "new project", "hackathon", "deploy", "agent skill",
        "ICM", "bonding curve", "launchpad", "open source", "smart contract",
        "SURGE", "OpenClaw", "tokenomics",
    ]
    for kw in search_keywords:
        results = await client.search_posts(kw, limit=25)
        all_posts.extend(results)

    raw_count = len(all_posts)

    # 4. Extract projects
    projects = extract_projects_from_posts(all_posts)
    log.info(f"Extracted {len(projects)} project candidates from {raw_count} raw posts")

    # 5. Sort by quality signals (GitHub URLs, votes, token mentions)
    projects.sort(key=lambda p: (
        len(p.get("github_urls", [])) * 50 +  # GitHub = strongest signal
        len(p.get("token_mentions", [])) * 20 +
        min(p.get("votes", 0), 500) +
        min(p.get("comments", 0), 100) * 2
    ), reverse=True)

    return projects
