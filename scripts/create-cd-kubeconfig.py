#!/usr/bin/env python3
"""Prepare namespace-scoped CI credentials without exporting admin credentials."""
import base64
import ipaddress
import json
import os
import subprocess
import time
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent.parent
    private = root / '.secrets'
    private.mkdir(mode=0o700, exist_ok=True)
    kubectl = ['kubectl', '--context=diploma']
    subprocess.run(kubectl + ['get', 'namespace', 'diploma'], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(kubectl + ['apply', '-f', str(root / 'kubernetes/cicd/deployer.yaml')], check=True)
    data = {}
    for attempt in range(30):
        output = subprocess.check_output(kubectl + [
            '-n', 'diploma', 'get', 'secret', 'github-deployer-token', '-o', 'json',
        ], text=True)
        data = json.loads(output).get('data', {})
        if data.get('token') and data.get('ca.crt'):
            break
        time.sleep(2)
    else:
        raise SystemExit('Service account token was not populated; check controller-manager.')
    server_ip = str(ipaddress.IPv4Address(subprocess.check_output([
        'terraform', f'-chdir={root / "terraform/main"}', 'output', '-raw', 'control_plane_ip',
    ], text=True).strip()))
    config = {
        'apiVersion': 'v1', 'kind': 'Config',
        'clusters': [{'name': 'diploma', 'cluster': {
            'server': f'https://{server_ip}:6443', 'certificate-authority-data': data['ca.crt'],
        }}],
        'users': [{'name': 'github-deployer', 'user': {
            'token': base64.b64decode(data['token']).decode(),
        }}],
        'contexts': [{'name': 'diploma-ci', 'context': {
            'cluster': 'diploma', 'user': 'github-deployer', 'namespace': 'diploma',
        }}],
        'current-context': 'diploma-ci',
    }
    target = private / 'kubeconfig-github-deployer'
    temporary = target.with_name(target.name + '.tmp')
    fd = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(config, stream, indent=2)
        stream.write('\n')
    temporary.chmod(0o600)
    ci = ['kubectl', f'--kubeconfig={temporary}']
    checks = [
        (['auth', 'can-i', 'patch', 'deployment/diploma-app', '-n', 'diploma'], 'yes'),
        (['auth', 'can-i', 'watch', 'deployment/diploma-app', '-n', 'diploma'], 'yes'),
        (['auth', 'can-i', 'get', 'secrets', '-n', 'diploma'], 'no'),
        (['auth', 'can-i', 'get', 'nodes'], 'no'),
    ]
    for args, expected in checks:
        result = subprocess.run(ci + args, text=True, capture_output=True)
        if result.stdout.strip() != expected or result.returncode not in (0, 1):
            temporary.unlink(missing_ok=True)
            raise SystemExit('CI permission check failed; credentials were not printed.')
        print(f'{" ".join(args)}: {expected}')
    subprocess.run(ci + ['-n', 'diploma', 'get', 'deployment', 'diploma-app'], check=True, stdout=subprocess.DEVNULL)
    temporary.replace(target)
    web_ip = str(ipaddress.IPv4Address(subprocess.check_output([
        'terraform', f'-chdir={root / "terraform/main"}', 'output', '-raw', 'web_ip',
    ], text=True).strip()))
    print(f'CI kubeconfig saved: {target}')
    print('GitHub Actions secret: KUBE_CONFIG (copy the whole file with pbcopy).')
    print(f'GitHub Actions variable APP_URL: http://{web_ip}')


if __name__ == '__main__':
    main()
