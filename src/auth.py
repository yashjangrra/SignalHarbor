"""Fail-closed, constant-time API key authentication for every HTTP resource."""
import secrets

from starlette.responses import HTMLResponse, JSONResponse
from . import config

LOGIN_HTML = '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SignalHarbor sign in</title><style>body{background:#0d0d0f;color:#eee;font:16px system-ui;max-width:440px;margin:15vh auto;padding:24px}input,button{padding:12px;margin-top:16px;width:100%;box-sizing:border-box}button{cursor:pointer}</style>
<h1>SignalHarbor</h1><p>Enter the dashboard API_KEY configured in your .env file. Your key stays in this tab's memory; re-enter it after refreshing.</p>
<form id="login"><label for="key">API key</label><input id="key" type="password" autocomplete="off" required><button>Unlock dashboard</button></form><p id="error" role="alert"></p>
<script>document.getElementById('login').addEventListener('submit',async event=>{event.preventDefault();const key=document.getElementById('key').value;try{const response=await fetch('/',{headers:{'X-API-Key':key},credentials:'omit',redirect:'error',cache:'no-store'});if(!response.ok)throw new Error('Unable to sign in. Check your API key and server configuration.');const html=await response.text();window.__signalharborKey=key;document.open();document.write(html);document.close();}catch(error){document.getElementById('error').textContent=error.message;}});</script></html>'''


class APIKeyMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        expected = getattr(config, 'API_KEY', '')
        keys = [value for name, value in scope.get('headers', []) if name.lower() == b'x-api-key']
        authorized = bool(expected) and len(keys) == 1 and secrets.compare_digest(keys[0], expected.encode('utf-8'))
        if authorized:
            async def private_send(message):
                if message['type'] == 'http.response.start':
                    message['headers'] = [(k, v) for k, v in message.get('headers', []) if k.lower() != b'cache-control']
                    message['headers'].append((b'cache-control', b'no-store'))
                await send(message)
            await self.app(scope, receive, private_send)
            return
        headers = {'Cache-Control': 'no-store', 'WWW-Authenticate': 'ApiKey', 'X-Content-Type-Options': 'nosniff'}
        if scope['path'] == '/' and scope['method'] == 'GET':
            response = HTMLResponse(LOGIN_HTML, status_code=401 if expected else 503, headers=headers)
        else:
            response = JSONResponse({'detail': 'Invalid or missing API key' if expected else 'API_KEY is not configured'}, status_code=401 if expected else 503, headers=headers)
        await response(scope, receive, send)
