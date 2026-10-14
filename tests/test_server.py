import copy
import asyncio
from unittest.mock import AsyncMock
import pytest
from fastapi.testclient import TestClient
from src import server
from src.database import StateStore, DatabaseState

@pytest.fixture
def client(monkeypatch, tmp_path):
    for name in ("ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "http_proxy", "https_proxy"):
        monkeypatch.delenv(name, raising=False)
    store = StateStore(tmp_path / 'state.db')
    monkeypatch.setattr(server, '_store', store)
    monkeypatch.setattr(server, '_state', DatabaseState(store))
    monkeypatch.setattr(server, '_demo_snapshot', None)
    monkeypatch.setattr(server, '_mutation_lock', asyncio.Lock())
    monkeypatch.setattr(server.config, 'API_KEY', 'integration-test-key')
    monkeypatch.setattr(server.config, 'SCHEDULER_ENABLED', False)
    with TestClient(server.app, headers={'X-API-Key': 'integration-test-key'}) as client:
        yield client
    store.close()

def test_pipeline_and_preparation(client, monkeypatch):
    monkeypatch.setattr(server, 'scout_moltbook', AsyncMock(return_value=[{'id':'a'}]))
    analysis = {'project_name':'Example','overall_score':80,'verdict':'STRONG_LAUNCH','scores':{},'tokenomics_advice':{'suggested_name':'EX','suggested_supply':'100','bonding_curve':'linear','initial_price_usd':'1'},'risks':[], 'strengths':[]}
    monkeypatch.setattr(server, 'analyze_batch', AsyncMock(return_value=[analysis]))
    result = client.post('/api/pipeline', json={})
    assert result.status_code == 200
    assert result.json()['status'] == 'complete'
    assert result.json()['launch_configurations'][0]['deployed'] is False
    assert client.post('/api/launch', json={'analysis_index':0}).json()['deployed'] is False
    assert client.get('/api/report/0').status_code == 200

def test_demo_preserves_live_disk_and_restores(client):
    server._state['scouted_projects'] = [{'id':'live'}]
    server._save_state()
    assert client.post('/api/demo', json={}).status_code == 200
    assert client.get('/api/state').json()['demo_mode'] is True
    assert server._store.load_state()['scouted_projects'] == [{'id':'live'}]
    assert client.post('/api/moltbook/report', json={}).status_code == 409
    assert client.post('/api/demo/clear').status_code == 200
    assert client.get('/api/state').json()['scouted_projects'] == [{'id':'live'}]

def test_errors_and_validation(client, monkeypatch):
    monkeypatch.setattr(server, 'analyze_project', AsyncMock(return_value={'error':'missing credential'}))
    assert client.post('/api/analyze',json={'project':{'title':'x'}}).status_code == 502
    assert client.get('/api/analyses').json() == []
    assert client.post('/api/launch',json={'chain':'unknown'}).status_code == 422
    assert client.post('/api/analyze',json={'min_score':101}).status_code == 422
    assert client.post('/api/moltbook/report',json={}).status_code == 400
    assert client.get('/api/report/-1').status_code == 404

def test_batch_failure_not_success(client, monkeypatch):
    monkeypatch.setattr(server,'scout_moltbook',AsyncMock(return_value=[{'id':'a'}]))
    monkeypatch.setattr(server,'analyze_batch',AsyncMock(return_value=[]))
    assert client.post('/api/pipeline',json={}).json()['status'] == 'analysis_failed'
