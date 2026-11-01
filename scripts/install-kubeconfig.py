#!/usr/bin/env python3
"""Prepare public-API access and merge the diploma context into ~/.kube/config."""
import datetime
import ipaddress
import json
import os
import shutil
import subprocess
from pathlib import Path


def run(args, env=None):
    return subprocess.run(args, check=True, capture_output=True, text=True, env=env).stdout


def write_private(path, text):
    fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(text)
    os.chmod(path, 0o600)


def main():
    root = Path(__file__).resolve().parent.parent
    source = root / '.secrets/kubeconfig-internal'
    target = root / '.secrets/kubeconfig-diploma'
    if not source.is_file():
        raise SystemExit('Run ansible-playbook site.yml successfully first: kubeconfig is missing.')
    os.chmod(source, 0o600)
    public_ip = str(ipaddress.IPv4Address(run([
        'terraform', f'-chdir={root / "terraform/main"}',
        'output', '-raw', 'control_plane_ip',
    ]).strip()))
    config = json.loads(run(['kubectl', f'--kubeconfig={source}', 'config', 'view', '--raw', '-o', 'json']))
    if any(len(config.get(key, [])) != 1 for key in ('clusters', 'users', 'contexts')):
        raise SystemExit('Expected a kubeadm admin kubeconfig with one cluster, user and context.')
    config['clusters'][0]['name'] = 'diploma'
    config['clusters'][0]['cluster']['server'] = f'https://{public_ip}:6443'
    config['users'][0]['name'] = 'diploma-admin'
    config['contexts'][0]['name'] = 'diploma'
    config['contexts'][0]['context'].update(cluster='diploma', user='diploma-admin')
    config['current-context'] = 'diploma'
    write_private(target, json.dumps(config, indent=2) + '\n')

    # Verify TLS, authentication and public API reachability before changing the default file.
    run(['kubectl', f'--kubeconfig={target}', '--request-timeout=30s', 'get', '--raw=/readyz'])
    default = Path.home() / '.kube/config'
    default.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    existing = [default] if default.exists() else []
    for value in os.environ.get('KUBECONFIG', '').split(os.pathsep):
        if value:
            candidate = Path(value).expanduser().resolve()
            if candidate.exists() and candidate != target and candidate not in existing:
                existing.append(candidate)
    environment = dict(os.environ)
    # Put the new diploma entries first so reruns update that context.
    environment['KUBECONFIG'] = os.pathsep.join(map(str, [target, *existing]))
    merged = run(['kubectl', 'config', 'view', '--raw', '--flatten', '--merge'], env=environment)
    if default.exists() and default.read_text() != merged:
        timestamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        backup = root / f'.secrets/kubeconfig-backup-{timestamp}'
        shutil.copyfile(default, backup)
        os.chmod(backup, 0o600)
        print(f'Previous default kubeconfig backed up: {backup}')
    temporary = default.with_name('config.diploma.tmp')
    write_private(temporary, merged)
    temporary.replace(default)
    print(f'Context diploma saved in {default}')
    print('Use: export KUBECONFIG="$HOME/.kube/config"')
    print('Verify: kubectl get nodes -o wide')


if __name__ == '__main__':
    main()
