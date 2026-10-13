import json

import httpx
import pytest


@pytest.fixture(autouse=True)
def clean_proxy_env(monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)

from src.launcher import SurgeLauncher, deploy_erc20_base, launch_pipeline
from src.moltbook import MoltbookClient


def client_for(handler, token="test-key", base="https://www.moltbook.com"):
    client = MoltbookClient(base_url=base, auth_token=token)
    client._http.close()
    client._http = httpx.Client(transport=httpx.MockTransport(handler))
    return client


def test_moltbook_documented_read_paths_and_auth():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"posts": [{"id": "1"}]})
    client = client_for(handler)
    assert client.fetch_posts("agents") == [{"id": "1"}]
    assert client.fetch_trending() == [{"id": "1"}]
    assert requests[0].url.path == "/api/v1/posts"
    assert requests[0].url.params["submolt"] == "agents"
    assert requests[1].url.params["sort"] == "hot"
    assert all(r.headers["Authorization"] == "Bearer test-key" for r in requests)
    client.close()


def test_moltbook_report_comment_payloads_preserve_verification():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(201, json={"verification_required": True, "verification": {"code": "pending"}})
    client = client_for(handler)
    result = client.post_update("Report", "Report text", "crypto")
    assert result["verification_required"] is True
    assert requests[0].url.path == "/api/v1/posts"
    assert json.loads(requests[0].content) == {"title": "Report", "content": "Report text", "submolt_name": "crypto", "type": "text"}
    client.post_comment("123", "Comment")
    assert json.loads(requests[1].content) == {"content": "Comment"}
    client.close()


def test_moltbook_refuses_credential_leak_and_unauthenticated_writes(monkeypatch):
    def no_request(request):
        raise AssertionError("Request must not be sent")
    client = client_for(no_request, base="https://evil.example")
    assert "error" in client.post_update("title", "body")
    client.close()
    monkeypatch.setattr("src.moltbook.config.MOLTBOOK_AUTH_TOKEN", "", raising=False)
    client = client_for(no_request, token="")
    assert "MOLTBOOK_AUTH_TOKEN" in client.post_update("title", "body")["error"]
    assert "error" in client.post_comment("1", "body")
    client.close()


def test_moltbook_profile_does_not_mistake_keyword_matches_for_authors():
    def handler(request):
        assert request.url.path == "/api/v1/agents/profile"
        assert request.url.params["name"] == "alice"
        return httpx.Response(200, json={"recentPosts": [{"id": "alice-post"}]})
    client = client_for(handler)
    assert client.fetch_user_posts("alice") == [{"id": "alice-post"}]
    client.close()


def test_launcher_never_transmits_wallet_key_or_claims_deployment():
    launcher = SurgeLauncher(wallet_key="private-wallet-key")
    assert "Authorization" not in launcher._headers()
    def no_request(request):
        raise AssertionError("Preparation must never send a transaction or API write")
    launcher._http.close()
    launcher._http = httpx.Client(transport=httpx.MockTransport(no_request))
    result = launcher.deploy_token(launcher.prepare_launch({"name": "Example"}))
    assert result["status"] == "prepared" and result["deployed"] is False
    assert "contractAddress" not in result
    launcher._http.close()
    result = deploy_erc20_base("Example", "EX", 100, private_key="invalid-key")
    assert result["status"] == "prepared" and result["deployed"] is False


def test_launch_pipeline_prepares_eligible_and_skips_ineligible():
    result = launch_pipeline({"verdict": "PROMISING", "project_name": "Test", "tokenomics_advice": {"suggested_name": "$TEST"}, "overall_score": 75})
    assert result["status"] == "prepared"
    assert result["launch_config"]["token"]["symbol"] == "TEST"
    assert result["analysis_score"] == 75
    assert launch_pipeline({"verdict": "SKIP"})["status"] == "skipped"
