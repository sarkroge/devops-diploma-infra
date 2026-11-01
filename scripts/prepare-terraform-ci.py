#!/usr/bin/env python3
"""Prepare existing credentials for GitHub Secrets without printing their values."""
import ipaddress
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def output(name):
    return subprocess.check_output(
        ['terraform', '-chdir=terraform/bootstrap', 'output', '-raw', name],
        cwd=ROOT, text=True,
    ).strip()


def save(path, content):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(content)
    temporary.chmod(0o600)
    temporary.replace(path)


def main():
    os.umask(0o077)
    inputs = json.loads((ROOT / 'terraform/main/local.auto.tfvars.json').read_text())
    if not isinstance(inputs, dict):
        raise SystemExit('local.auto.tfvars.json must contain a JSON object.')
    if not inputs.get('ssh_public_key', '').startswith('ssh-ed25519 '):
        raise SystemExit('Existing public SSH key is missing. Do not generate a replacement key.')
    if not inputs.get('admin_cidrs'):
        raise SystemExit('Existing admin_cidrs are missing.')
    for cidr in inputs['admin_cidrs']:
        if ipaddress.IPv4Network(cidr).prefixlen != 32:
            raise SystemExit('Expected an IPv4 /32 administrator address.')
    # auto.tfvars overrides TF_VAR_*; yc is only a fallback for cloud/folder IDs.
    for name in ('cloud_id', 'folder_id'):
        value = inputs.get(name) or os.environ.get('TF_VAR_' + name)
        if not value:
            value = subprocess.check_output(
                ['yc', 'config', 'get', name.replace('_', '-')], text=True,
            ).strip()
        if not value:
            raise SystemExit('Missing ' + name)
        inputs[name] = value
    key_text = (ROOT / '.secrets/terraform-key.json').read_text()
    key = json.loads(key_text)
    if key.get('service_account_id') != output('terraform_service_account_id'):
        raise SystemExit('The key belongs to a different service account.')
    if not key.get('private_key') or not key.get('id'):
        raise SystemExit('The existing authorized service account key is incomplete.')
    files = {
        'TF_SA_JSON_CREDENTIALS': key_text,
        'AWS_ACCESS_KEY_ID': output('state_access_key'),
        'AWS_SECRET_ACCESS_KEY': output('state_secret_key'),
        'TF_INPUTS_JSON': json.dumps(inputs, indent=2) + '\n',
    }
    if any(not value for value in files.values()):
        raise SystemExit('An existing Terraform credential is empty.')
    bucket = output('state_bucket_name')
    destination = ROOT / '.secrets/terraform-ci'
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination.chmod(0o700)
    for name, value in files.items():
        path = destination / name
        save(path, value)
        print('Prepared GitHub Secret:', name)
    print('GitHub Variable TF_STATE_BUCKET:', bucket)
    print('Files saved under .secrets/terraform-ci/ with mode 0600. Values were not printed.')
    print('No cloud resources or keys were created.')


if __name__ == '__main__':
    main()
