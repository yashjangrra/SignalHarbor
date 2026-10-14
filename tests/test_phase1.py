"""Phase 1 acceptance: protected API, responsive async work, durable live state."""
import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from src import server
from src.database import DatabaseState, StateStore
from test_server import client


@pytest.fixture(autouse=True)
def clear_proxy_env(monkeypatch):
    for name in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'):
        monkeypatch.delenv(name, raising=False)


def test_every_registered_route_requires_api_key(client):
    # Includes OpenAPI, Swagger, dashboard and mounted static assets.
    for route in server.app.routes:
        path = route.path.replace('{index}', '0')
        if path == '/static':
            path += '/index.html'
        for method in getattr(route, 'methods', {'GET'}):
            if method in {'HEAD', 'OPTIONS'}:
                continue
            response = client.request(method, path, headers={'X-API-Key': ''})
            assert response.status_code == 401, (method, path, response.status_code)
            response = client.request(method, path, headers={'X-API-Key': 'wrong'})
            assert response.status_code == 401, (method, path, response.status_code)
    assert client.get('/api/health').status_code == 200
    assert client.get('/openapi.json').status_code == 200


def test_missing_key_configuration_fails_closed(client, monkeypatch):
    monkeypatch.setattr(server.config, 'API_KEY', '')
    response = client.get('/api/state')
    assert response.status_code == 503


def test_live_state_survives_restart_but_demo_does_not(client, tmp_path, monkeypatch):
    server._state['scouted_projects'] = [{'id': 'real-project', 'title': 'Live'}]
    server._state['analyses'] = [{'project_name': 'Live', 'overall_score': 81}]
    server._save_state()
    assert client.post('/api/demo').status_code == 200
    assert client.get('/api/state').json()['demo_mode'] is True
    restarted_store = StateStore(tmp_path / 'state.db')
    try:
        recovered = restarted_store.load_state()
        assert recovered['demo_mode'] is False
        assert recovered['scouted_projects'] == [{'id': 'real-project', 'title': 'Live'}]
        assert recovered['analyses'][0]['project_name'] == 'Live'
        assert restarted_store.query('analyses', min_score=80)[0]['project_name'] == 'Live'
        monkeypatch.setattr(server, '_store', restarted_store)
        monkeypatch.setattr(server, '_state', DatabaseState(restarted_store))
        monkeypatch.setattr(server, '_demo_snapshot', None)
        assert client.get('/api/state').json()['scouted_projects'] == recovered['scouted_projects']
    finally:
        restarted_store.close()


@pytest.mark.asyncio
async def test_reads_remain_responsive_during_async_pipeline(tmp_path, monkeypatch):
    store = StateStore(tmp_path / 'responsive.db')
    monkeypatch.setattr(server, '_store', store)
    monkeypatch.setattr(server, '_state', DatabaseState(store))
    monkeypatch.setattr(server, '_mutation_lock', asyncio.Lock())
    monkeypatch.setattr(server.config, 'API_KEY', 'key')
    entered, release = asyncio.Event(), asyncio.Event()

    async def scout(**kwargs):
        entered.set()
        await release.wait()
        return []

    monkeypatch.setattr(server, 'scout_moltbook', scout)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url='http://test', headers={'X-API-Key': 'key'}) as api:
        pipeline = asyncio.create_task(api.post('/api/pipeline', json={}))
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            health = await asyncio.wait_for(api.get('/api/health'), timeout=2)
            assert health.status_code == 200
            assert not pipeline.done()
        finally:
            release.set()
            response = await asyncio.wait_for(pipeline, timeout=2)
            store.close()
        assert response.json()['status'] == 'no_projects_found'


@pytest.mark.asyncio
async def test_scheduler_skips_demo_and_never_publishes(tmp_path, monkeypatch):
    store = StateStore(tmp_path / 'scheduled.db')
    monkeypatch.setattr(server, '_store', store)
    monkeypatch.setattr(server, '_state', DatabaseState(store))
    monkeypatch.setattr(server, '_mutation_lock', asyncio.Lock())
    scout = AsyncMock(return_value=[{'id': 'candidate'}])
    monkeypatch.setattr(server, 'scout_moltbook', scout)
    monkeypatch.setattr(server, 'analyze_batch', AsyncMock(return_value=[{
        'project_name': 'Candidate', 'overall_score': 80, 'verdict': 'PROMISING',
        'scores': {}, 'tokenomics_advice': {'suggested_name': '$CAND', 'suggested_supply': '1000', 'initial_price_usd': '0.01', 'bonding_curve': 'linear'}, 'risks': [], 'strengths': [],
    }]))
    publish = AsyncMock(side_effect=AssertionError('Automatic pipeline must not publish'))
    monkeypatch.setattr(server.MoltbookClient, 'post_update', publish)
    try:
        result = await server._scheduled_pipeline()
        assert result['status'] == 'complete'
        assert all(item['deployed'] is False for item in result['launch_configurations'])
        publish.assert_not_called()
        monkeypatch.setattr(server, '_state', {'demo_mode': True})
        assert (await server._scheduled_pipeline())['status'] == 'skipped_demo'
        assert scout.await_count == 1
    finally:
        store.close()


@pytest.mark.parametrize('path', ['/api/scout', '/api/analyze', '/api/pipeline'])
def test_demo_rejects_live_work_without_touching_integrations_or_disk(client, monkeypatch, path):
    server._state['scouted_projects'] = [{'id': 'live'}]
    live = server._store.load_state()
    assert client.post('/api/demo').status_code == 200
    before = client.get('/api/state').json()
    scout = AsyncMock(return_value=[])
    analyze = AsyncMock(return_value=[])
    monkeypatch.setattr(server, 'scout_moltbook', scout)
    monkeypatch.setattr(server, 'analyze_batch', analyze)
    response = client.post(path, json={})
    assert response.status_code == 409
    scout.assert_not_awaited()
    analyze.assert_not_awaited()
    assert client.get('/api/state').json() == before
    assert server._store.load_state() == live
    assert client.post('/api/demo/clear').status_code == 200
    assert client.get('/api/state').json()['scouted_projects'] == [{'id': 'live'}]


@pytest.mark.asyncio
@pytest.mark.parametrize('first', ['manual', 'scheduled'])
async def test_manual_and_scheduled_work_share_serialization(tmp_path, monkeypatch, first):
    store = StateStore(tmp_path / 'overlap.db')
    monkeypatch.setattr(server, '_store', store)
    monkeypatch.setattr(server, '_state', DatabaseState(store))
    monkeypatch.setattr(server, '_mutation_lock', asyncio.Lock())
    monkeypatch.setattr(server.config, 'API_KEY', 'key')
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0
    active = 0
    peak = 0

    async def scout(**kwargs):
        nonlocal calls, active, peak
        calls += 1
        active += 1
        peak = max(peak, active)
        if calls == 1:
            entered.set()
            await release.wait()
        active -= 1
        return []

    monkeypatch.setattr(server, 'scout_moltbook', scout)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url='http://test', headers={'X-API-Key': 'key'}) as api:
        async def manual():
            result = await api.post('/api/pipeline', json={})
            assert result.status_code == 200
            return result.json()
        starters = {'manual': manual, 'scheduled': server._scheduled_pipeline}
        tasks = []
        try:
            tasks.append(asyncio.create_task(starters[first]()))
            await asyncio.wait_for(entered.wait(), 2)
            tasks.append(asyncio.create_task(starters['scheduled' if first == 'manual' else 'manual']()))
            await asyncio.sleep(0.05)
            assert calls == 1
            assert not tasks[1].done()
            release.set()
            results = await asyncio.wait_for(asyncio.gather(*tasks), 2)
            assert all(result['status'] == 'no_projects_found' for result in results)
            assert calls == 2
            assert peak == 1
        finally:
            release.set()
            await asyncio.gather(*tasks, return_exceptions=True)
            store.close()
