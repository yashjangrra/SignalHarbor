from unittest.mock import Mock

import pytest

from src import analyzer, config


def test_openrouter_transport_uses_canonical_origin(monkeypatch):
    import openai
    monkeypatch.setattr(config, 'AI_PROVIDER', 'openrouter')
    monkeypatch.setattr(config, 'AI_MODEL', '')
    monkeypatch.setattr(config, 'OPENROUTER_API_KEY', 'router-test-key')
    constructor = Mock()
    monkeypatch.setattr(openai, 'AsyncOpenAI', constructor)
    provider, client = analyzer._get_llm_client()
    assert provider == 'openrouter'
    assert client is constructor.return_value
    constructor.assert_called_once_with(api_key='router-test-key', base_url='https://openrouter.ai/api/v1', max_retries=0)


@pytest.mark.parametrize('model', ['', 'openrouter/free', 'vendor/model:free'])
def test_openrouter_accepts_only_free_models(model, monkeypatch):
    monkeypatch.setattr(config, 'AI_PROVIDER', 'openrouter')
    monkeypatch.setattr(config, 'AI_MODEL', model)
    assert config.selected_model() == (model or 'openrouter/free')


@pytest.mark.parametrize('model', ['gpt-4o', 'vendor/model', 'openrouter/auto', 'vendor/model:free:paid'])
def test_paid_routes_rejected_before_client_construction(model, monkeypatch):
    import openai
    monkeypatch.setattr(config, 'AI_PROVIDER', 'openrouter')
    monkeypatch.setattr(config, 'AI_MODEL', model)
    constructor = Mock()
    monkeypatch.setattr(openai, 'AsyncOpenAI', constructor)
    with pytest.raises(RuntimeError, match='paid models are disabled'):
        analyzer._get_llm_client()
    constructor.assert_not_called()


@pytest.mark.parametrize('provider,model', [('anthropic', 'claude-sonnet-4-20250514'), ('openai', 'gpt-4o')])
def test_legacy_provider_defaults_are_independent(provider, model, monkeypatch):
    monkeypatch.setattr(config, 'AI_PROVIDER', provider)
    monkeypatch.setattr(config, 'AI_MODEL', '')
    assert config.selected_model() == model


def test_router_key_never_falls_back(monkeypatch):
    monkeypatch.setattr(config, 'AI_PROVIDER', 'openrouter')
    monkeypatch.setattr(config, 'AI_MODEL', '')
    monkeypatch.setattr(config, 'OPENROUTER_API_KEY', '')
    monkeypatch.setattr(config, 'ANTHROPIC_API_KEY', 'other')
    monkeypatch.setattr(config, 'OPENAI_API_KEY', 'other')
    assert not config.selected_api_key()
    with pytest.raises(RuntimeError, match='OPENROUTER_API_KEY'):
        analyzer._get_llm_client()


def test_unknown_provider_has_no_key_and_is_rejected(monkeypatch):
    monkeypatch.setattr(config, 'AI_PROVIDER', 'unknown')
    assert not config.selected_api_key()
    with pytest.raises(RuntimeError, match='AI_PROVIDER'):
        config.selected_model()


def test_health_reports_selected_openrouter_credential(monkeypatch):
    from src import server
    monkeypatch.setattr(config, 'AI_PROVIDER', 'openrouter')
    monkeypatch.setattr(config, 'OPENROUTER_API_KEY', 'router-test-key')
    monkeypatch.setattr(config, 'ANTHROPIC_API_KEY', 'legacy-key')
    assert server.health()['provider'] == 'openrouter'
    assert server.health()['api_key_configured'] is True
    monkeypatch.setattr(config, 'OPENROUTER_API_KEY', '')
    assert server.health()['api_key_configured'] is False


def test_database_upgrade_preserves_existing_file(tmp_path, monkeypatch):
    monkeypatch.delenv('DATABASE_PATH', raising=False)
    assert config.resolve_database_path(str(tmp_path)) == str(tmp_path / 'signalharbor.db')
    original = tmp_path / 'existing-state.db'
    original.touch()
    assert config.resolve_database_path(str(tmp_path)) == str(original)
    (tmp_path / 'other-state.db').touch()
    with pytest.raises(RuntimeError, match='Multiple existing databases'):
        config.resolve_database_path(str(tmp_path))
    monkeypatch.setenv('DATABASE_PATH', str(original))
    assert config.resolve_database_path(str(tmp_path)) == str(original)


@pytest.mark.asyncio
async def test_openrouter_http_payload_and_quota_failure_have_no_paid_fallback(monkeypatch):
    import json
    import httpx
    import openai
    monkeypatch.setattr(config, 'AI_PROVIDER', 'openrouter')
    monkeypatch.setattr(config, 'AI_MODEL', '')
    requests = []
    status = 200
    def handler(request):
        requests.append(request)
        assert request.url == 'https://openrouter.ai/api/v1/chat/completions'
        assert request.headers['Authorization'] == 'Bearer test-router-key'
        assert json.loads(request.content)['model'] == 'openrouter/free'
        if status == 429:
            return httpx.Response(429, json={'error': {'message': 'Free quota exceeded'}})
        return httpx.Response(200, json={'id': 'test', 'model': 'vendor/model:free', 'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': '{}'}, 'finish_reason': 'stop'}]})
    clients = []
    def create_client():
        client = openai.AsyncOpenAI(api_key='test-router-key', base_url='https://openrouter.ai/api/v1', max_retries=0,
                                    http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        clients.append(client)
        return 'openrouter', client
    monkeypatch.setattr(analyzer, '_get_llm_client', create_client)
    assert await analyzer._call_llm('system', 'user') == '{}'
    status = 429
    with pytest.raises(openai.RateLimitError):
        await analyzer._call_llm('system', 'user')
    assert len(requests) == 2
    assert all(client.is_closed() for client in clients)
