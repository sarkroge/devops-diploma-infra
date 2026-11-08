#!/usr/bin/env python3
"""Write local bootstrap inputs; does not call Terraform apply or cloud APIs."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('on', 'off'))
    parser.add_argument('--hours', type=int, default=72)
    args = parser.parse_args()
    if not 1 <= args.hours <= 168:
        parser.error('--hours must be between 1 and 168')
    root = Path(__file__).resolve().parents[1]
    target = root / 'terraform/bootstrap/availability.auto.tfvars.json'
    os.umask(0o077)
    data = json.loads(target.read_text()) if target.exists() else {}
    if not isinstance(data, dict):
        raise SystemExit('Existing availability.auto.tfvars.json must be a JSON object')
    data['workers_autostart_enabled'] = args.action == 'on'
    if args.action == 'on':
        deadline = datetime.now(timezone.utc) + timedelta(hours=args.hours)
        data['workers_autostart_until'] = deadline.strftime('%Y-%m-%dT%H:%M:%SZ')
    temporary = target.with_name(target.name + '.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.chmod(0o600)
    temporary.replace(target)
    print('Prepared local setting:', args.action)
    if args.action == 'on':
        print('Autostart deadline (UTC):', data['workers_autostart_until'])
    print('Apply terraform/bootstrap with the user IAM token for this setting to take effect.')
    print('This command has not changed cloud resources.')


if __name__ == '__main__':
    main()
