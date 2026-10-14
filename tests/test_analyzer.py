import json
from unittest.mock import AsyncMock

import pytest

from src import analyzer


def valid_response(score=75):
    return {
        'project_name': 'Example', 'summary': 'Evidence based summary',
        'scores': {key: score for key in analyzer.SCORE_WEIGHTS},
        'overall_score': 100, 'verdict': 'STRONG_LAUNCH',
        'tokenomics_advice': {
            'suggested_name': '$TEST', 'suggested_supply': '1000000',
            'bonding_curve': 'linear', 'initial_price_usd': '0.001',
            'rationale': 'Utility recommendation',
        },
        'risks': ['Unverified repository'], 'strengths': ['Clear use case'],
        'recommendation': 'Verify code before proceeding',
    }


@pytest.mark.parametrize('score,verdict', [(0, 'SKIP'), (24.99, 'SKIP'), (25, 'NEEDS_WORK'),
    (49.99, 'NEEDS_WORK'), (50, 'PROMISING'), (74.99, 'PROMISING'), (75, 'STRONG_LAUNCH'), (100, 'STRONG_LAUNCH')])
@pytest.mark.anyio
async def test_verdict_is_computed(score, verdict, monkeypatch):
    monkeypatch.setattr(analyzer, '_call_llm', AsyncMock(return_value=json.dumps(valid_response(score))))
    result = await analyzer.analyze_project({'id': 'p1', 'title': 'Example'})
    assert result['overall_score'] == score
    assert result['verdict'] == verdict
    assert result['_source_project_id'] == 'p1'
    assert result['_analyzed_at'].endswith('+00:00')


def test_documented_weights():
    response = valid_response()
    response['scores'] = dict(zip(analyzer.SCORE_WEIGHTS, [100, 0, 100, 0, 100]))
    assert analyzer._validate_analysis(response)['overall_score'] == 60


@pytest.mark.parametrize('bad', [True, '90', None, -1, 101, float('nan'), float('inf')])
@pytest.mark.anyio
async def test_invalid_scores_are_errors(bad, monkeypatch):
    response = valid_response()
    response['scores']['traction'] = bad
    monkeypatch.setattr(analyzer, '_call_llm', AsyncMock(return_value=json.dumps(response)))
    result = await analyzer.analyze_project({'title': 'Example'})
    assert result['verdict'] == 'ERROR'
    assert 'error' in result


@pytest.mark.parametrize('field,value', [('suggested_supply', '1.5'), ('suggested_supply', '-2'),
    ('suggested_supply', str(2**256)), ('initial_price_usd', 'NaN'), ('initial_price_usd', 'Infinity'),
    ('initial_price_usd', 0), ('bonding_curve', 'fake'), ('suggested_name', '$BAD TICKER')])
def test_invalid_token_parameters_rejected(field, value):
    response = valid_response()
    response['tokenomics_advice'][field] = value
    with pytest.raises(ValueError):
        analyzer._validate_analysis(response)


@pytest.mark.parametrize('field', ['scores', 'summary', 'risks', 'strengths', 'tokenomics_advice', 'recommendation'])
def test_missing_required_data_rejected(field):
    response = valid_response()
    del response[field]
    with pytest.raises(ValueError):
        analyzer._validate_analysis(response)


@pytest.mark.parametrize('wrapper', ['{}', '```json\n{}\n```', 'Here is the assessment: {} trailing {{broken'])
def test_json_wrappers(wrapper):
    response = valid_response()
    assert analyzer._extract_json(wrapper.replace('{}', json.dumps(response), 1)) == response


@pytest.mark.parametrize('response', ['', None, 'not json', '[]', 'null'])
def test_invalid_json(response):
    assert 'error' in analyzer._extract_json(response)


@pytest.mark.anyio
async def test_batch_excludes_failures_and_sorts(monkeypatch):
    responses = iter([{'error': 'bad', 'overall_score': 0}, {'overall_score': 60}, {'overall_score': 90}])
    monkeypatch.setattr(analyzer, 'analyze_project', AsyncMock(side_effect=lambda _: next(responses)))
    monkeypatch.setattr(analyzer.asyncio, 'sleep', AsyncMock())
    assert await analyzer.analyze_batch([{}, {}, {}]) == [{'overall_score': 90}, {'overall_score': 60}]


def test_no_provider_fallback(monkeypatch):
    monkeypatch.setattr(analyzer.config, 'AI_PROVIDER', 'anthropic')
    monkeypatch.setattr(analyzer.config, 'ANTHROPIC_API_KEY', '')
    monkeypatch.setattr(analyzer.config, 'OPENAI_API_KEY', 'present')
    with pytest.raises(RuntimeError, match='ANTHROPIC_API_KEY'):
        analyzer._get_llm_client()


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_batch_delay_keeps_event_loop_responsive(monkeypatch):
    import asyncio
    real_sleep = asyncio.sleep
    heartbeat = asyncio.Event()

    async def delay(_):
        # A sibling coroutine must run while the analyzer's throttle is pending.
        await real_sleep(0.01)
        assert heartbeat.is_set()

    async def beat():
        await real_sleep(0)
        heartbeat.set()

    monkeypatch.setattr(analyzer, 'analyze_project', AsyncMock(return_value={'overall_score': 60}))
    monkeypatch.setattr(analyzer.asyncio, 'sleep', delay)
    task = asyncio.create_task(beat())
    assert len(await analyzer.analyze_batch([{}, {}])) == 2
    await task


@pytest.mark.anyio
@pytest.mark.parametrize('provider', ['anthropic', 'openai', 'openrouter'])
async def test_async_sdk_is_awaited_and_closed(provider, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(analyzer.config, 'AI_PROVIDER', provider)
    monkeypatch.setattr(analyzer.config, 'AI_MODEL', '')
    client = SimpleNamespace(close=AsyncMock())
    if provider == 'anthropic':
        client.messages = SimpleNamespace(create=AsyncMock(return_value=SimpleNamespace(
            content=[SimpleNamespace(text='response')])) )
        create = client.messages.create
    else:
        client.chat = SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(
            return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='response'))]))))
        create = client.chat.completions.create
    monkeypatch.setattr(analyzer, '_get_llm_client', lambda: (provider, client))
    assert await analyzer._call_llm('system', 'user') == 'response'
    create.assert_awaited_once()
    client.close.assert_awaited_once()
    create.side_effect = RuntimeError('provider unavailable')
    with pytest.raises(RuntimeError, match='provider unavailable'):
        await analyzer._call_llm('system', 'user')
    assert client.close.await_count == 2
