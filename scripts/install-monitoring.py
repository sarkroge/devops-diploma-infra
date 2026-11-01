#!/usr/bin/env python3
"""Install the pinned monitoring stack using local data volumes and a private admin Secret."""
import base64
import ipaddress
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

CHART_VERSION = '92.17.0'


def write_private(path, content):
    temporary = path.with_name(path.name + '.tmp')
    fd = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(content)
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def main():
    root = Path(__file__).resolve().parent.parent
    private = root / '.secrets'
    private.mkdir(mode=0o700, exist_ok=True)
    kubectl = ['kubectl', '--context=diploma']
    subprocess.run(kubectl + ['get', '--raw=/readyz'], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(['ansible-playbook', 'monitoring-storage.yml'], cwd=root / 'ansible', check=True)
    subprocess.run(kubectl + ['apply', '-f', str(root / 'kubernetes/monitoring/namespace.yaml')], check=True)
    subprocess.run(kubectl + ['apply', '-f', str(root / 'kubernetes/monitoring/storage.yaml')], check=True)

    result = subprocess.run(kubectl + [
        '-n', 'monitoring', 'get', 'secret', 'grafana-admin', '--ignore-not-found', '-o', 'json',
    ], text=True, capture_output=True)
    if result.returncode:
        raise SystemExit('Cannot read Grafana Secret; check cluster access before retrying.')
    password_file = private / 'grafana-admin-password'
    if result.stdout.strip():
        try:
            data = json.loads(result.stdout)['data']
            username = base64.b64decode(data['admin-user']).decode()
            password = base64.b64decode(data['admin-password']).decode()
        except (KeyError, ValueError, UnicodeError):
            raise SystemExit('Existing Grafana Secret has an unexpected format.')
    else:
        username = 'admin'
        password = password_file.read_text().strip() if password_file.exists() else secrets.token_urlsafe(24)
        secret = {
            'apiVersion': 'v1', 'kind': 'Secret',
            'metadata': {'name': 'grafana-admin', 'namespace': 'monitoring'},
            'type': 'Opaque',
            'stringData': {'admin-user': username, 'admin-password': password},
        }
        saved = subprocess.run(kubectl + ['apply', '-f', '-'],
                               input=json.dumps(secret), text=True, capture_output=True)
        if saved.returncode:
            raise SystemExit('Cannot create Grafana Secret; secret contents were suppressed.')
    write_private(password_file, password)
    print(f'Grafana login: {username}; password saved in {password_file}', flush=True)

    web_ip = str(ipaddress.IPv4Address(subprocess.check_output([
        'terraform', f'-chdir={root / "terraform/main"}', 'output', '-raw', 'web_ip',
    ], text=True).strip()))
    runtime = private / 'monitoring-runtime.values.json'
    write_private(runtime, json.dumps({'grafana': {'grafana.ini': {'server': {
        'root_url': f'http://{web_ip}/grafana/', 'domain': web_ip,
    }}}}, indent=2) + '\n')
    subprocess.run(['helm', 'repo', 'add', 'prometheus-community',
                    'https://prometheus-community.github.io/helm-charts', '--force-update'], check=True)
    subprocess.run(['helm', 'repo', 'update', 'prometheus-community'], check=True)
    subprocess.run([
        'helm', 'upgrade', '--install', 'monitoring', 'prometheus-community/kube-prometheus-stack',
        '--version', CHART_VERSION, '--kube-context', 'diploma', '--namespace', 'monitoring',
        '--values', str(root / 'kubernetes/monitoring/values.yaml'), '--values', str(runtime),
        '--wait', '--timeout', '15m',
    ], check=True)
    for name in ['prometheus-monitoring-prometheus', 'alertmanager-monitoring-alertmanager']:
        subprocess.run(kubectl + ['-n', 'monitoring', 'wait', '--for=create',
                                 f'statefulset/{name}', '--timeout=300s'], check=True)
        subprocess.run(kubectl + ['-n', 'monitoring', 'rollout', 'status',
                                 f'statefulset/{name}', '--timeout=600s'], check=True)

    dashboard = {
        'apiVersion': 'v1', 'kind': 'ConfigMap',
        'metadata': {'name': 'diploma-overview-dashboard', 'namespace': 'monitoring',
                     'labels': {'grafana_dashboard': '1'}},
        'data': {'diploma-overview.json': (root / 'kubernetes/monitoring/diploma-overview.json').read_text()},
    }
    subprocess.run(kubectl + ['apply', '-f', '-'], input=json.dumps(dashboard), text=True, check=True)
    subprocess.run(kubectl + ['apply', '-f', str(root / 'kubernetes/monitoring/grafana-ingress.yaml')], check=True)
    subprocess.run(kubectl + ['-n', 'monitoring', 'get', 'pods,pvc,ingress', '-o', 'wide'], check=True)
    print(f'Grafana: http://{web_ip}/grafana/', flush=True)
    subprocess.run([sys.executable, str(root / 'scripts/verify-monitoring.py')], check=True)


if __name__ == '__main__':
    main()
