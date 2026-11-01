#!/usr/bin/env python3
"""Create the image pull Secret without putting private key data in argv or logs."""
import base64
import json
import subprocess
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent.parent
    key_file = root / '.secrets/registry-pull-key.json'
    if not key_file.is_file():
        raise SystemExit('Create .secrets/registry-pull-key.json using STEP-06.md first.')
    key_file.chmod(0o600)
    password = key_file.read_text()
    key = json.loads(password)
    expected = subprocess.check_output([
        'terraform', f'-chdir={root / "terraform/bootstrap"}',
        'output', '-raw', 'registry_pull_service_account_id',
    ], text=True).strip()
    if key.get('service_account_id') != expected or not key.get('private_key'):
        raise SystemExit('The key must belong to diploma-registry-pull.')
    kubectl = ['kubectl', '--context=diploma']
    subprocess.run(kubectl + ['get', '--raw=/readyz'], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(kubectl + ['apply', '-f', str(root / 'kubernetes/app/namespace.yaml')], check=True)
    auth = base64.b64encode(('json_key:' + password).encode()).decode()
    docker_config = {'auths': {'cr.yandex': {
        'username': 'json_key', 'password': password, 'auth': auth,
    }}}
    secret = {
        'apiVersion': 'v1', 'kind': 'Secret',
        'metadata': {'name': 'yc-registry', 'namespace': 'diploma'},
        'type': 'kubernetes.io/dockerconfigjson',
        'data': {'.dockerconfigjson': base64.b64encode(json.dumps(docker_config).encode()).decode()},
    }
    # Suppress stderr too: API validation errors can include the submitted payload.
    result = subprocess.run(
        kubectl + ['apply', '-f', '-'], input=json.dumps(secret),
        text=True, capture_output=True,
    )
    if result.returncode:
        raise SystemExit('Secret creation failed. Check cluster access and SA key; key data was suppressed.')
    print('Secret diploma/yc-registry is configured. Credentials were not printed.')


if __name__ == '__main__':
    main()
