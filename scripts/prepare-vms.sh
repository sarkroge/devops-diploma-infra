#!/usr/bin/env bash
# Create/reuse a dedicated local SSH key and prepare non-secret Terraform inputs.
set -euo pipefail
umask 077

project_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
key_path="$project_dir/.secrets/diploma-ssh"
vars_path="$project_dir/terraform/main/local.auto.tfvars.json"
mkdir -p "$project_dir/.secrets"

if [[ -f "$key_path" ]]; then
  if [[ ! -f "$key_path.pub" ]]; then
    ssh-keygen -y -f "$key_path" > "$key_path.pub"
  fi
elif [[ -e "$key_path.pub" ]]; then
  printf '%s\n' 'Public key exists but private key is missing. Restore the private key before continuing.' >&2
  exit 1
else
  ssh-keygen -t ed25519 -N '' -C 'devops-diploma' -f "$key_path"
fi
chmod 600 "$key_path"

admin_ip="${DIPLOMA_ADMIN_IP:-}"
if [[ -z "$admin_ip" ]]; then
  admin_ip="$(curl -4 -fsS --connect-timeout 10 --max-time 20 https://api.ipify.org)"
fi

python3 - "$admin_ip" "$key_path.pub" "$vars_path" <<'PY'
import ipaddress
import json
import os
import sys
from pathlib import Path

address = ipaddress.IPv4Address(sys.argv[1].strip())
if not address.is_global:
    raise SystemExit('Expected a public IPv4 address for SSH access.')
public_key = Path(sys.argv[2]).read_text().strip()
if not public_key.startswith('ssh-ed25519 '):
    raise SystemExit('Expected a public Ed25519 SSH key.')
destination = Path(sys.argv[3])
data = json.loads(destination.read_text()) if destination.exists() else {}
if not isinstance(data, dict):
    raise SystemExit('Existing local.auto.tfvars.json must contain a JSON object.')
data.update(ssh_public_key=public_key, admin_cidrs=[f'{address}/32'])
temporary = destination.with_name(destination.name + '.tmp')
temporary.write_text(json.dumps(data, indent=2) + '\n')
os.chmod(temporary, 0o600)
temporary.replace(destination)
print(f'SSH source allowed: {address}/32')
print(f'Terraform inputs saved: {destination}')
PY

printf '%s\n' 'Public key only was copied into Terraform inputs. Private key stays in .secrets.'
git -C "$project_dir" check-ignore .secrets/diploma-ssh terraform/main/local.auto.tfvars.json
