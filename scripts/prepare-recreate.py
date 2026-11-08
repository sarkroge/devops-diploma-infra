#!/usr/bin/env python3
"""Read-only preparation: private state backups, image inventory and destroy plan."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def run(arguments, env=None):
    return subprocess.check_output(arguments, cwd=ROOT, env=env, text=True)


def output(directory, name, env=None):
    return run(['terraform', f'-chdir=terraform/{directory}', 'output', '-raw', name], env).strip()


def save(path, text):
    path.write_text(text)
    path.chmod(0o600)


def main():
    os.umask(0o077)
    key_file = ROOT / '.secrets/terraform-key.json'
    key = json.loads(key_file.read_text())
    if key.get('service_account_id') != output('bootstrap', 'terraform_service_account_id'):
        raise SystemExit('Terraform key does not belong to the bootstrap Terraform service account.')
    env = os.environ.copy()
    env.pop('YC_TOKEN', None)
    env['YC_SERVICE_ACCOUNT_KEY_FILE'] = str(key_file)
    env['AWS_ACCESS_KEY_ID'] = output('bootstrap', 'state_access_key')
    env['AWS_SECRET_ACCESS_KEY'] = output('bootstrap', 'state_secret_key')
    for variable in ('cloud_id', 'folder_id'):
        env.setdefault('TF_VAR_' + variable, run(['yc', 'config', 'get', variable.replace('_', '-')]).strip())

    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    destination = ROOT / '.secrets' / ('recreate-' + stamp)
    destination.mkdir(mode=0o700)
    for directory in ('bootstrap', 'main'):
        state = run(['terraform', f'-chdir=terraform/{directory}', 'state', 'pull'], env)
        json.loads(state)
        save(destination / f'{directory}.tfstate', state)
    # Copy top-level credential files only, avoiding recursive backup directories.
    credentials = destination / 'credentials'
    credentials.mkdir(mode=0o700)
    for path in (ROOT / '.secrets').iterdir():
        if path.is_file() and not path.is_symlink() and path.suffix not in ('.tfplan', '.plan', '.log'):
            target = credentials / path.name
            shutil.copyfile(path, target)
            target.chmod(0o600)
    for directory in ('bootstrap', 'main'):
        for source in (ROOT / 'terraform' / directory).glob('*.tfvars*'):
            if source.is_file() and not source.is_symlink():
                target = destination / f'{directory}-{source.name}'
                shutil.copyfile(source, target)
                target.chmod(0o600)

    registry = output('main', 'registry_id', env)
    images = json.loads(run(['yc', 'container', 'image', 'list', '--registry-id', registry, '--format=json']))
    if not isinstance(images, list):
        raise SystemExit('Unexpected image-list response; backups were kept, no resource was changed.')
    save(destination / 'registry-images.json', json.dumps(images, indent=2) + '\n')

    plan = destination / 'destroy.tfplan'
    result = subprocess.run([
        'terraform', '-chdir=terraform/main', 'plan', '-destroy', '-input=false',
        '-no-color', '-out=' + str(plan),
    ], cwd=ROOT, env=env, capture_output=True, text=True)
    save(destination / 'destroy-plan.txt', result.stdout + result.stderr)
    if result.returncode:
        print('Preparation failed; see private destroy-plan.txt in:', destination)
        print(result.stderr[-3000:])
        raise SystemExit(result.returncode)
    plan.chmod(0o600)
    details = json.loads(run(['terraform', '-chdir=terraform/main', 'show', '-json', str(plan)], env))
    resources = [
        {'address': change['address'], 'actions': change['change']['actions']}
        for change in details.get('resource_changes', [])
        if change.get('change', {}).get('actions') != ['no-op']
    ]
    report = {
        'backup_directory': str(destination), 'registry_id': registry,
        'image_count': len(images), 'planned_changes': resources,
        'executed_destroy': False, 'executed_apply': False,
        'note': 'State snapshots are not backups of VM disks, PV data or image layers.',
    }
    save(destination / 'report.json', json.dumps(report, indent=2) + '\n')
    save(ROOT / '.secrets/recreate-latest.json', json.dumps(report, indent=2) + '\n')
    print('Private backups and read-only destroy plan:', destination)
    print('Registry images:', len(images))
    print('Planned resource changes:', len(resources))
    for resource in resources:
        print('  ' + resource['address'] + ': ' + ','.join(resource['actions']))
    print('No destroy/apply was executed; no images were deleted.')
    if images:
        print('Before actual destroy: prepare image preservation/rebuild and registry cleanup.')
    print('Before actual destroy: disable autostart and exclude concurrent infrastructure CI runs.')


if __name__ == '__main__':
    main()
