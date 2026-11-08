#!/usr/bin/env python3
"""Build a private Ansible inventory from Terraform's nodes output."""
import ipaddress
import json
import os
import shlex
import subprocess
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent.parent
    private_key = root / '.secrets/diploma-ssh'
    if not private_key.is_file():
        raise SystemExit('Missing .secrets/diploma-ssh; restore the SSH private key first.')
    result = subprocess.run(
        ['terraform', f'-chdir={root / "terraform/main"}', 'output', '-json', 'nodes'],
        check=True, capture_output=True, text=True,
    )
    nodes = json.loads(result.stdout)
    expected = {'control-plane', 'worker-1', 'worker-2'}
    if set(nodes) != expected:
        raise SystemExit('Expected the three diploma nodes in Terraform outputs.')
    control_plane_ip = str(ipaddress.IPv4Address(nodes['control-plane']['public_ip']))
    proxy_command = shlex.join([
        'ssh', '-i', str(private_key),
        '-o', 'BatchMode=yes',
        '-o', 'IdentitiesOnly=yes',
        '-o', 'ConnectTimeout=15',
        '-o', 'StrictHostKeyChecking=accept-new',
        '-W', '%h:%p', f'ubuntu@{control_plane_ip}',
    ])
    children = {'control_plane': {'hosts': {}}, 'workers': {'hosts': {}}}
    for name in sorted(nodes):
        node = nodes[name]
        public_ip = str(ipaddress.IPv4Address(node['public_ip']))
        private_ip = str(ipaddress.IPv4Address(node['internal_ip']))
        group = 'control_plane' if name == 'control-plane' else 'workers'
        children[group]['hosts'][node['hostname']] = {
            'ansible_host': public_ip,
            'node_ip': private_ip,
            'node_public_ip': public_ip,
        }
        if group == 'workers':
            # Connect to both workers through the control plane.
            host = children[group]['hosts'][node['hostname']]
            host['ansible_host'] = private_ip
            host['ansible_ssh_common_args'] = shlex.join(['-o', 'ProxyCommand=' + proxy_command])
    inventory = {'all': {'vars': {
        'ansible_user': 'ubuntu',
        'ansible_ssh_private_key_file': str(private_key),
        'ansible_python_interpreter': '/usr/bin/python3',
    }, 'children': children}}
    target = root / '.secrets/ansible-inventory.json'
    temporary = target.with_name(target.name + '.tmp')
    fd = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(inventory, stream, indent=2)
        stream.write('\n')
    os.chmod(temporary, 0o600)
    temporary.replace(target)
    print(f'Inventory written: {target}')
    for group, data in children.items():
        for hostname, host in data['hosts'].items():
            route = f' via control-plane {control_plane_ip}' if 'ansible_ssh_common_args' in host else ''
            print(f'{group}: {hostname} -> {host["ansible_host"]}{route} (private {host["node_ip"]})')


if __name__ == '__main__':
    main()
