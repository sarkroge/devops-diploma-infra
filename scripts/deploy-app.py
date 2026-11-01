#!/usr/bin/env python3
"""Deploy a selected release from the current Terraform registry output."""
import ipaddress
import json
import re
import subprocess
import sys
from pathlib import Path


def parse_manifests(output):
    """Normalize kubectl's JSON stream, single object, or List to one List."""
    decoder = json.JSONDecoder()
    remaining = output.lstrip()
    items = []
    while remaining:
        resource, end = decoder.raw_decode(remaining)
        if not isinstance(resource, dict):
            raise ValueError('Expected a Kubernetes JSON object.')
        if resource.get('kind') == 'List':
            resources = resource.get('items')
            if not isinstance(resources, list):
                raise ValueError('Kubernetes List must contain an items array.')
        else:
            resources = [resource]
        if any(not isinstance(item, dict) or not item.get('kind') for item in resources):
            raise ValueError('Invalid Kubernetes resource in kubectl output.')
        items.extend(resources)
        remaining = remaining[end:].lstrip()
    if not items:
        raise ValueError('kubectl returned no Kubernetes resources.')
    return {'apiVersion': 'v1', 'kind': 'List', 'items': items}


def main():
    root = Path(__file__).resolve().parent.parent
    tag = sys.argv[1] if len(sys.argv) == 2 else 'v1.0.0'
    if len(sys.argv) > 2 or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}', tag):
        raise SystemExit('Usage: python3 scripts/deploy-app.py [Docker-tag]')
    repository = subprocess.check_output([
        'terraform', f'-chdir={root / "terraform/main"}',
        'output', '-raw', 'app_image_repository',
    ], text=True).strip()
    image = f'{repository}:{tag}'
    kubectl = ['kubectl', '--context=diploma']
    subprocess.run(kubectl + ['get', '--raw=/readyz'], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(kubectl + ['-n', 'diploma', 'get', 'secret', 'yc-registry'], check=True, stdout=subprocess.DEVNULL)
    # Client dry-run produces structured JSON without creating resources.
    output = subprocess.check_output(kubectl + [
        'create', '--dry-run=client', '-k', str(root / 'kubernetes/app'), '-o', 'json',
    ], text=True)
    try:
        manifest = parse_manifests(output)
    except ValueError as error:
        raise SystemExit(f'Cannot parse kubectl manifests: {error}') from error
    deployments = [x for x in manifest['items'] if x['kind'] == 'Deployment' and x['metadata']['name'] == 'diploma-app']
    if len(deployments) != 1:
        raise SystemExit('Expected one diploma-app Deployment in the manifests.')
    deployments[0]['spec']['template']['spec']['containers'][0]['image'] = image
    subprocess.run(kubectl + ['apply', '-f', '-'], input=json.dumps(manifest), text=True, check=True)
    subprocess.run(kubectl + ['-n', 'diploma', 'rollout', 'status', 'deployment/diploma-app', '--timeout=300s'], check=True)
    subprocess.run(kubectl + ['-n', 'diploma', 'get', 'pods,service,ingress', '-o', 'wide'], check=True)
    web_ip = str(ipaddress.IPv4Address(subprocess.check_output([
        'terraform', f'-chdir={root / "terraform/main"}', 'output', '-raw', 'web_ip',
    ], text=True).strip()))
    print(f'Image: {image}')
    print(f'Application: http://{web_ip}/')
    print(f'Version: http://{web_ip}/version.json')


if __name__ == '__main__':
    main()
