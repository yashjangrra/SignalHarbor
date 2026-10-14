"""Bootstrap tests do not download or install anything."""
import importlib.util
from pathlib import Path
import subprocess

import pytest

spec = importlib.util.spec_from_file_location('signalharbor_setup', Path(__file__).parents[1] / 'setup.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def test_env_created_private_and_placeholders_cleared(tmp_path):
    (tmp_path / '.env.example').write_text('ANTHROPIC_API_KEY=sk-ant-...\nOPENAI_API_KEY=sk-...\nOPENROUTER_API_KEY=sk-or-...\nSECRET_KEY=dev\nPORT=8899\n')
    assert setup.create_env(tmp_path)
    text = (tmp_path / '.env').read_text()
    assert 'sk-ant-' not in text and 'sk-...' not in text and 'sk-or-' not in text
    assert 'SECRET_KEY=dev' not in text
    assert 'PORT=8899' in text
    if setup.os.name != 'nt':
        assert (tmp_path / '.env').stat().st_mode & 0o777 == 0o600


def test_existing_env_untouched(tmp_path):
    (tmp_path / '.env').write_text('SECRET_KEY=my-existing-secret\n')
    assert not setup.create_env(tmp_path)
    assert (tmp_path / '.env').read_text() == 'SECRET_KEY=my-existing-secret\n'


def test_service_action_does_not_install_or_launch(monkeypatch):
    actions = []
    monkeypatch.setattr(setup, 'manage_openclaw', actions.append)
    monkeypatch.setattr(setup, 'prepare_python', lambda: pytest.fail('should not install'))
    assert setup.main(['--openclaw', 'stop']) == 0
    assert actions == ['stop']


def test_invalid_port_rejected():
    with pytest.raises(SystemExit):
        setup.main(['--port', '0'])


def test_existing_openclaw_not_reinstalled(monkeypatch):
    monkeypatch.setattr(setup, 'find_openclaw', lambda: '/existing/openclaw')
    assert setup.openclaw_install() == '/existing/openclaw'


def test_installer_failure_propagates(monkeypatch):
    monkeypatch.setattr(setup.subprocess, 'run', lambda *a, **kw: (_ for _ in ()).throw(subprocess.CalledProcessError(1, 'installer')))
    with pytest.raises(subprocess.CalledProcessError):
        setup.run(['installer'])


def test_fresh_openclaw_uses_background_onboarding_and_global_skill(monkeypatch, tmp_path):
    commands = []
    monkeypatch.setattr(setup.Path, 'home', lambda: tmp_path)
    monkeypatch.setattr(setup, 'openclaw_install', lambda: '/cli/openclaw')
    monkeypatch.setattr(setup, 'run', commands.append)
    setup.manage_openclaw('setup')
    assert commands[0][1:] == ['onboard', '--classic', '--install-daemon', '--skip-ui', '--auth-choice', 'openrouter-api-key']
    assert commands[1][1:] == ['models', 'set', 'openrouter/openrouter/free']
    assert '--global' in commands[2]
    assert commands[-1][1:] == ['gateway', 'status']


def test_existing_openclaw_configuration_and_skill_preserved(monkeypatch, tmp_path):
    commands = []
    (tmp_path / '.openclaw/skills/signalharbor').mkdir(parents=True)
    (tmp_path / '.openclaw/openclaw.json').write_text('{}')
    monkeypatch.setattr(setup.Path, 'home', lambda: tmp_path)
    monkeypatch.setattr(setup, 'openclaw_install', lambda: '/cli/openclaw')
    monkeypatch.setattr(setup, 'run', commands.append)
    setup.manage_openclaw('setup')
    assert all('onboard' not in command and 'skills' not in command and 'models' not in command for command in commands)


def test_guided_credentials_hidden_and_existing_values_preserved(monkeypatch, tmp_path, capsys):
    (tmp_path / '.env').write_text('AI_PROVIDER=anthropic\nANTHROPIC_API_KEY=\nOPENAI_API_KEY=\nSECRET_KEY=keep\n')
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    monkeypatch.delenv('MOLTBOOK_AUTH_TOKEN', raising=False)
    monkeypatch.setattr('builtins.input', lambda _: '3')
    secrets = iter(['test-secret-key', 'private-token'])
    monkeypatch.setattr(setup.getpass, 'getpass', lambda _: next(secrets))
    assert setup.configure_credentials(tmp_path)
    content = (tmp_path / '.env').read_text()
    assert 'AI_PROVIDER="openai"' in content
    assert 'OPENAI_API_KEY="test-secret-key"' in content
    assert 'MOLTBOOK_AUTH_TOKEN="private-token"' in content
    assert 'SECRET_KEY=keep' in content
    output = capsys.readouterr().out
    assert 'test-secret-key' not in output and 'private-token' not in output


def test_guided_setup_preserves_existing_credentials(monkeypatch, tmp_path):
    original = 'AI_PROVIDER=openai\nOPENAI_API_KEY=existing-key\nMOLTBOOK_AUTH_TOKEN=existing-token\n'
    (tmp_path / '.env').write_text(original)
    monkeypatch.setattr('builtins.input', lambda _: pytest.fail('credentials already exist'))
    monkeypatch.setattr(setup.getpass, 'getpass', lambda _: pytest.fail('credentials already exist'))
    assert not setup.configure_credentials(tmp_path)
    assert (tmp_path / '.env').read_text() == original


def test_no_launch_never_prompts(monkeypatch):
    monkeypatch.setattr(setup, 'prepare_python', lambda: Path('/unused/python'))
    monkeypatch.setattr(setup, 'create_env', lambda: True)
    monkeypatch.setattr(setup.sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr(setup, 'configure_credentials', lambda: pytest.fail('no-launch must not prompt'))
    assert setup.main(['--configure', '--no-launch']) == 0


def test_credential_line_injection_rejected(monkeypatch, tmp_path):
    (tmp_path / '.env').write_text('AI_PROVIDER=anthropic\n')
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    monkeypatch.delenv('MOLTBOOK_AUTH_TOKEN', raising=False)
    monkeypatch.setattr('builtins.input', lambda _: '1')
    secrets = iter(['key\nPORT=1', ''])
    monkeypatch.setattr(setup.getpass, 'getpass', lambda _: next(secrets))
    with pytest.raises(RuntimeError):
        setup.configure_credentials(tmp_path)
    assert (tmp_path / '.env').read_text() == 'AI_PROVIDER=anthropic\n'


def test_dashboard_key_generated_and_preserved(tmp_path, monkeypatch):
    monkeypatch.delenv('API_KEY', raising=False)
    (tmp_path / '.env').write_text('PORT=8899\nAPI_KEY=\n')
    assert setup.ensure_api_key(tmp_path)
    content = (tmp_path / '.env').read_text()
    assert len(setup.env_values(content)['API_KEY']) >= 32
    assert not setup.ensure_api_key(tmp_path)
    assert (tmp_path / '.env').read_text() == content
    if setup.os.name != 'nt':
        assert (tmp_path / '.env').stat().st_mode & 0o777 == 0o600


def test_browser_opens_when_authenticated_server_ready(monkeypatch):
    import urllib.error
    opened = []
    monkeypatch.setattr(setup.urllib.request, 'urlopen', lambda *a, **k: (_ for _ in ()).throw(urllib.error.HTTPError(a[0], 401, 'Unauthorized', {'WWW-Authenticate': 'ApiKey'}, None)))
    monkeypatch.setattr(setup.webbrowser, 'open', opened.append)
    process = type('Process', (), {'poll': lambda self: None})()
    setup.browser_when_ready(8899, process)
    assert opened == ['http://127.0.0.1:8899']


def test_browser_does_not_open_unrelated_unauthorized_service(monkeypatch):
    import urllib.error
    monkeypatch.setattr(setup.urllib.request, 'urlopen', lambda *a, **k: (_ for _ in ()).throw(urllib.error.HTTPError(a[0], 401, 'Unauthorized', {}, None)))
    monkeypatch.setattr(setup.webbrowser, 'open', lambda _: pytest.fail('unrelated service'))
    monkeypatch.setattr(setup.time, 'sleep', lambda _: None)
    process = type('Process', (), {'poll': lambda self: None})()
    setup.browser_when_ready(8899, process)


def test_explicit_configuration_switches_provider_without_deleting_keys(monkeypatch, tmp_path):
    (tmp_path / '.env').write_text('AI_PROVIDER=anthropic\nANTHROPIC_API_KEY=legacy-key\nAI_MODEL=claude-model\nMOLTBOOK_AUTH_TOKEN=token\n')
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    monkeypatch.setattr('builtins.input', lambda _: '')
    monkeypatch.setattr(setup.getpass, 'getpass', lambda _: 'router-key')
    assert setup.configure_credentials(tmp_path, select_provider=True)
    values = setup.env_values((tmp_path / '.env').read_text())
    assert values['AI_PROVIDER'] == 'openrouter'
    assert values['AI_MODEL'] == 'openrouter/free'
    assert values['OPENROUTER_API_KEY'] == 'router-key'
    assert values['ANTHROPIC_API_KEY'] == 'legacy-key'


def test_default_setup_uses_openrouter_hidden_prompt(monkeypatch, tmp_path):
    (tmp_path / '.env').write_text('AI_PROVIDER=openrouter\nOPENROUTER_API_KEY=\nMOLTBOOK_AUTH_TOKEN=token\n')
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    monkeypatch.setattr('builtins.input', lambda _: '')
    monkeypatch.setattr(setup.getpass, 'getpass', lambda _: 'router-key')
    assert setup.configure_credentials(tmp_path)
    values = setup.env_values((tmp_path / '.env').read_text())
    assert values['AI_PROVIDER'] == 'openrouter'
    assert values['AI_MODEL'] == 'openrouter/free'
