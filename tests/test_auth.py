"""Authentication covers API, documentation and static/dashboard resources."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src import config
from src.auth import APIKeyMiddleware


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, 'API_KEY', 'private-test-key', raising=False)
    app = FastAPI()
    @app.get('/api/health')
    def health():
        return {'status': 'ok'}
    @app.get('/')
    def dashboard():
        return {'dashboard': 'private'}
    app.add_middleware(APIKeyMiddleware)
    return TestClient(app)


@pytest.mark.parametrize('path', ['/api/health', '/docs', '/openapi.json', '/static/logo.svg', '/unknown'])
def test_all_resources_require_key(client, path):
    assert client.get(path).status_code == 401
    assert client.get(path, headers={'X-API-Key': 'wrong'}).status_code == 401


def test_valid_header_and_no_caching(client):
    response = client.get('/api/health', headers={'X-API-Key': 'private-test-key'})
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'


def test_key_in_url_or_cookie_is_not_accepted(client):
    assert client.get('/api/health?api_key=private-test-key').status_code == 401
    assert client.get('/api/health', headers={'Cookie': 'API_KEY=private-test-key'}).status_code == 401


def test_login_contains_no_secret_or_storage(client):
    response = client.get('/')
    assert response.status_code == 401
    assert 'private-test-key' not in response.text
    assert 'type="password"' in response.text
    assert 'localStorage' not in response.text and 'sessionStorage' not in response.text


def test_unconfigured_fails_closed(client, monkeypatch):
    monkeypatch.setattr(config, 'API_KEY', '')
    assert client.get('/api/health').status_code == 503


def test_duplicate_key_headers_rejected(client):
    response = client.get('/api/health', headers=[('X-API-Key', 'private-test-key'), ('X-API-Key', 'private-test-key')])
    assert response.status_code == 401
