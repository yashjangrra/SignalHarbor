#!/usr/bin/env python3
"""Idempotent local bootstrap. Run setup.sh or setup.cmd if Python is missing.

Network access is required on first use. --openclaw enables the official optional
OpenClaw installer and guided authentication; OS/service prompts may be required.
Existing settings and credentials are preserved; guided setup fills missing keys.
"""
import argparse
import getpass
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import urllib.error
import venv
import webbrowser
import warnings

ROOT = Path(__file__).resolve().parent


def run(command, **kwargs):
    # Do not echo commands: future provider credential arguments must stay private.
    subprocess.run([str(part) for part in command], check=True, cwd=ROOT, **kwargs)


def create_env(root=ROOT):
    path = root / '.env'
    if path.exists():
        return False
    content = (root / '.env.example').read_text(encoding='utf-8')
    content = re.sub(r'(?m)^(ANTHROPIC_API_KEY|OPENAI_API_KEY|OPENROUTER_API_KEY)=.*$', r'\1=', content)
    content = re.sub(r'(?m)^SECRET_KEY=.*$', 'SECRET_KEY=' + secrets.token_urlsafe(32), content)
    content = re.sub(r'(?m)^API_KEY=.*$', 'API_KEY=' + secrets.token_urlsafe(32), content) if re.search(r'(?m)^API_KEY=', content) else content.rstrip('\n') + '\nAPI_KEY=' + secrets.token_urlsafe(32) + '\n'
    # Exclusive creation also preserves a concurrent user's config.
    try:
        with path.open('x', encoding='utf-8') as handle:
            if os.name != 'nt':
                os.chmod(path, 0o600)
            handle.write(content)
    except FileExistsError:
        return False
    return True



def ensure_api_key(root=ROOT):
    """Provision missing dashboard auth atomically while preserving existing values."""
    path = root / '.env'
    if not path.exists():
        return False
    content = path.read_text(encoding='utf-8')
    if os.environ.get('API_KEY') or env_values(content).get('API_KEY'):
        return False
    line = 'API_KEY=' + secrets.token_urlsafe(32)
    content = re.sub(r'(?m)^API_KEY=.*$', line, content) if re.search(r'(?m)^API_KEY=', content) else content.rstrip('\n') + '\n' + line + '\n'
    descriptor, temporary = tempfile.mkstemp(prefix='.env-auth-', dir=root)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            handle.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return True


def env_values(content):
    values = {}
    for match in re.finditer(r"(?m)^([A-Z_][A-Z0-9_]*)=(.*)$", content):
        value = match.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[match.group(1)] = value
    return values


def hidden_input(prompt):
    # Never accept getpass fallback that would echo a credential.
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            return getpass.getpass(prompt)
        except getpass.GetPassWarning as error:
            raise RuntimeError("Secure credential input requires an interactive terminal.") from error


def configure_credentials(root=ROOT, select_provider=False):
    """Fill missing keys, or explicitly switch provider while retaining old credentials."""
    path = root / '.env'
    content = path.read_text(encoding='utf-8')
    values = env_values(content)
    updates = {}
    provider_keys = {'openrouter': 'OPENROUTER_API_KEY', 'anthropic': 'ANTHROPIC_API_KEY', 'openai': 'OPENAI_API_KEY'}
    active = os.environ.get('AI_PROVIDER') or values.get('AI_PROVIDER', 'openrouter')
    key_name = provider_keys.get(active)
    has_key = key_name and (os.environ.get(key_name) or values.get(key_name))
    if select_provider or not has_key:
        choice = input('AI provider: [1/Enter] OpenRouter free models, [2] Anthropic, [3] OpenAI: ').strip()
        selected = {'': 'openrouter', '1': 'openrouter', '2': 'anthropic', '3': 'openai'}.get(choice)
        if selected:
            key_name = provider_keys[selected]
            existing = os.environ.get(key_name) or values.get(key_name)
            key = existing or hidden_input('Provider API key (hidden; Enter to skip): ').strip()
            if key:
                updates['AI_PROVIDER'] = selected
                if not existing:
                    updates[key_name] = key
                if selected != active:
                    updates['AI_MODEL'] = 'openrouter/free' if selected == 'openrouter' else ''
                elif selected == 'openrouter' and not values.get('AI_MODEL'):
                    updates['AI_MODEL'] = 'openrouter/free'
    if not (os.environ.get('MOLTBOOK_AUTH_TOKEN') or values.get('MOLTBOOK_AUTH_TOKEN')):
        token = hidden_input('Optional Moltbook token (hidden; Enter to skip): ').strip()
        if token:
            updates['MOLTBOOK_AUTH_TOKEN'] = token
    if not updates:
        return False
    for key, value in updates.items():
        if any(character in value for character in ('\n', '\r', '\0')):
            raise RuntimeError('Credential values cannot contain line breaks or null characters.')
        # Quoted dotenv values protect #, spaces, quotes and backslashes.
        escaped = value.replace('\\', '\\\\').replace('"', '\\"')
        line = key + '="' + escaped + '"'
        pattern = r'(?m)^' + re.escape(key) + r'=.*$'
        if re.search(pattern, content):
            content = re.sub(pattern, lambda _: line, content)
        else:
            content = content.rstrip('\n') + '\n' + line + '\n'
    # Atomic replacement, with restrictive POSIX permissions from mkstemp.
    descriptor, temporary = tempfile.mkstemp(prefix='.env-setup-', dir=root)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            handle.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print('Credentials saved. Existing credentials preserved.')
    return True


def environment_python(root=ROOT):
    return root / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def prepare_python():
    target = environment_python()
    if not target.exists():
        venv.EnvBuilder(with_pip=True).create(ROOT / '.venv')
    version_check = subprocess.run([str(target), '-c', 'import sys;sys.exit(sys.version_info < (3,12))'], cwd=ROOT)
    if version_check.returncode:
        raise RuntimeError('Existing .venv uses Python older than 3.12. Rename it as a backup and rerun setup.')
    run([target, '-m', 'pip', 'install', '-r', ROOT / 'requirements.txt'])
    return target


def find_openclaw():
    for directory in (Path.home() / '.local/bin', Path.home() / '.openclaw/bin',
                      Path.home() / '.npm-global/bin', Path(os.environ.get('APPDATA', str(Path.home()))) / 'npm'):
        os.environ['PATH'] = str(directory) + os.pathsep + os.environ.get('PATH', '')
    return shutil.which('openclaw')


def openclaw_install():
    executable = find_openclaw()
    if executable:
        return executable
    windows = os.name == 'nt'
    url = 'https://openclaw.ai/install.ps1' if windows else 'https://openclaw.ai/install.sh'
    with tempfile.TemporaryDirectory(prefix='signalharbor-openclaw-') as directory:
        script = Path(directory) / ('install.ps1' if windows else 'install.sh')
        with urllib.request.urlopen(url, timeout=60) as response:
            script.write_bytes(response.read())
        if windows:
            run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', script, '-NoOnboard'])
        else:
            run(['bash', script, '--no-onboard'])
    executable = find_openclaw()
    if not executable:
        raise RuntimeError('OpenClaw installer finished but CLI is not on PATH. Restart your terminal and rerun.')
    return executable


def manage_openclaw(action):
    executable = openclaw_install() if action == 'setup' else find_openclaw()
    if not executable:
        raise RuntimeError('OpenClaw is not installed. Run with --openclaw setup first.')
    if action == 'setup':
        # Guided setup owns credential entry and preserves existing configuration.
        # Skip onboarding when already configured; never reset an existing agent.
        if not (Path.home() / '.openclaw/openclaw.json').exists():
            print('OpenClaw needs OpenRouter authorization. Follow its guided prompts; free models have limits.')
            run([executable, 'onboard', '--classic', '--install-daemon', '--skip-ui', '--auth-choice', 'openrouter-api-key'])
            run([executable, 'models', 'set', 'openrouter/openrouter/free'])
        else:
            print('Existing OpenClaw configuration preserved. To use free OpenRouter models, run:')
            print('openclaw models auth login --provider openrouter --method api-key')
            print('openclaw models set openrouter/openrouter/free')
            print('OpenRouter auto and other models may be paid; select the free router explicitly.')
        managed_skill = Path.home() / '.openclaw/skills/signalharbor'
        if not managed_skill.exists():
            run([executable, 'skills', 'install', str(ROOT / 'skill'), '--as', 'signalharbor', '--global'])
        else:
            print('Existing SignalHarbor OpenClaw skill preserved; review before replacing it.')
        run([executable, 'gateway', 'install'])
        run([executable, 'gateway', 'start'])
        run([executable, 'gateway', 'status'])
    else:
        run([executable, 'gateway', action])


def browser_when_ready(port, process):
    url = f'http://127.0.0.1:{port}'
    for _ in range(60):
        if process.poll() is not None:
            return
        try:
            with urllib.request.urlopen(url + '/api/health', timeout=1) as response:
                if response.status == 200:
                    webbrowser.open(url)
                    return
        except urllib.error.HTTPError as error:
            if error.code == 401 and error.headers.get('WWW-Authenticate') == 'ApiKey':
                webbrowser.open(url)
                return
            time.sleep(0.5)
        except OSError:
            time.sleep(0.5)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--openclaw', choices=['setup', 'start', 'stop', 'restart', 'status'],
                        help='Opt in to optional OpenClaw installation or manage its Gateway service')
    parser.add_argument('--configure', action='store_true', help='Select AI provider and guide API credential setup in an interactive terminal')
    parser.add_argument('--no-launch', action='store_true', help='Install/configure only')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--port', type=int, default=8899)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    if sys.version_info < (3, 12):
        parser.error('Python 3.12+ required; use setup.sh or setup.cmd to provision it automatically.')
    # Service-only actions should neither install dependencies nor start dashboard.
    if args.openclaw and args.openclaw != 'setup':
        manage_openclaw(args.openclaw)
        return 0
    python = prepare_python()
    created = create_env()
    ensure_api_key()
    if not args.no_launch and sys.stdin.isatty() and (created or args.configure):
        configure_credentials(select_provider=args.configure)
    (ROOT / 'data').mkdir(exist_ok=True)
    if args.openclaw:
        manage_openclaw(args.openclaw)
    print('Setup complete. Existing settings preserved. To add live credentials later, rerun with --configure.')
    if args.no_launch:
        return 0
    print('Unlock the dashboard with API_KEY from .env (or your API_KEY environment variable). Do not share it.')
    env = os.environ.copy()
    env['PORT'] = str(args.port)
    process = subprocess.Popen([str(python), str(ROOT / 'app.py'), '--host', '127.0.0.1', '--port', str(args.port)], cwd=ROOT, env=env)
    if not args.no_browser:
        threading.Thread(target=browser_when_ready, args=(args.port, process), daemon=True).start()
    print(f'Dashboard: http://127.0.0.1:{args.port} — press Ctrl+C to stop.')
    try:
        return process.wait()
    except KeyboardInterrupt:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print('Setup failed: a command, download, or file operation failed. Check the preceding output and rerun.', file=sys.stderr)
        sys.exit(1)
