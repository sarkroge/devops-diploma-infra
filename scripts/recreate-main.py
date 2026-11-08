#!/usr/bin/env python3
"""Review, then recreate only this diploma's 13 main resources and registry images."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('registry_recovery', HERE / 'registry-recovery.py')
recovery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recovery)
FOLDER = 'b1g90k05go90aj6v84m2'
REPOS = ('sarkroge/devops-diploma-infra', 'sarkroge/devops-diploma-app')
ERROR_DIRECTORY = None
REGISTRY = 'yandex_container_registry.diploma'
EXPECTED = {
    REGISTRY, 'yandex_vpc_network.diploma',
    *('yandex_compute_instance.nodes["' + key + '"]' for key in ('control-plane', 'worker-1', 'worker-2')),
    *('yandex_vpc_address.nodes["' + key + '"]' for key in ('control-plane', 'worker-1')),
    *('yandex_vpc_subnet.diploma["' + key + '"]' for key in ('a', 'd', 'e')),
    *('yandex_vpc_security_group.' + key for key in ('kubernetes_api', 'nodes', 'web')),
}


def now():
    return datetime.now(timezone.utc)


def save(path, value):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.chmod(0o600)
    temporary.replace(path)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def run(arguments, env, log=None, timeout=180):
    try:
        result = subprocess.run(arguments, env=env, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        if log:
            log.write_bytes((error.stdout or b'') + b'\n' + (error.stderr or b''))
            log.chmod(0o600)
        raise
    if log:
        log.write_bytes(result.stdout + b'\n' + result.stderr)
        log.chmod(0o600)
    if result.returncode:
        # Plan/show/state output can contain secrets; keep it in the private log.
        if log is None and ERROR_DIRECTORY is not None:
            log = ERROR_DIRECTORY / ('recreate-error-' + now().strftime('%Y%m%dT%H%M%S%fZ') + '.log')
            log.write_bytes(result.stdout + b'\n' + result.stderr)
            log.chmod(0o600)
        location = f' Inspect {log}.' if log else ''
        raise ValueError(f'{arguments[0]} {arguments[1]} failed (exit {result.returncode}).{location}')
    return result.stdout


def tf(root, env, directory, *args, **kwargs):
    return run(['terraform', f'-chdir={root / "terraform" / directory}', *args], env, **kwargs)


def environment(root):
    env = os.environ.copy()
    # Do not inherit command flags such as -target or -refresh=false.
    for name in list(env):
        if name == 'YC_TOKEN' or name.startswith('TF_CLI_ARGS'):
            env.pop(name)
    key_file = root / '.secrets/terraform-key.json'
    key = json.loads(key_file.read_text())
    expected = tf(root, env, 'bootstrap', 'output', '-raw', 'terraform_service_account_id').decode().strip()
    if key.get('service_account_id') != expected:
        raise ValueError('Terraform key does not match the bootstrap account.')
    env['YC_SERVICE_ACCOUNT_KEY_FILE'] = str(key_file)
    for suffix, output in [('ACCESS_KEY_ID', 'state_access_key'), ('SECRET_ACCESS_KEY', 'state_secret_key')]:
        env['AWS_' + suffix] = tf(root, env, 'bootstrap', 'output', '-raw', output).decode().strip()
    for name in ('folder_id', 'cloud_id'):
        env.setdefault('TF_VAR_' + name, run(['yc', 'config', 'get', name.replace('_', '-')], env).decode().strip())
    if env['TF_VAR_folder_id'] != FOLDER:
        raise ValueError('This utility is restricted to the existing diploma folder.')
    for directory in ('bootstrap', 'main'):
        if tf(root, env, directory, 'workspace', 'show').strip() != b'default':
            raise ValueError('Expected the default Terraform workspace.')
    return env


def github_get(repo, path):
    # macOS Python may have a separate, incomplete CA bundle. Use Apple's curl
    # with its normal certificate verification; never fall back to --insecure.
    curl = '/usr/bin/curl' if sys.platform == 'darwin' else shutil.which('curl')
    if not curl:
        raise ValueError('curl is required for the public GitHub checks.')
    content = run([curl, '--disable', '--proto', '=https', '--fail', '--silent', '--show-error',
                   '--connect-timeout', '10', '--max-time', '30',
                   '--header', 'Accept: application/vnd.github+json',
                   '--header', 'User-Agent: diploma-recreate-check',
                   'https://api.github.com/repos/' + repo + path], os.environ.copy(), timeout=40)
    return json.loads(content)


def github_snapshot():
    snapshot = {}
    for repo in REPOS:
        def get(path):
            return github_get(repo, path)
        runs = get('/actions/runs?per_page=100')
        if not isinstance(runs.get('total_count'), int) or runs['total_count'] > 100:
            raise ValueError('Cannot completely inspect Actions history; stop and review CI.')
        if len(runs.get('workflow_runs', [])) != runs['total_count']:
            raise ValueError('Incomplete Actions response.')
        if any(item.get('status') != 'completed' for item in runs['workflow_runs']):
            raise ValueError(f'Actions are active in {repo}; wait for completion.')
        head = get('/branches/main')['commit']['sha']
        if not re.fullmatch(r'[a-f0-9]{40}', head):
            raise ValueError('Unexpected branch response.')
        snapshot[repo] = head
    return snapshot


def autostart_off(root, env):
    value = json.loads(tf(root, env, 'bootstrap', 'output', '-json', 'worker_availability'))
    if value.get('enabled') is not False or value.get('trigger_id') is not None:
        raise ValueError('Disable worker autostart in bootstrap first.')


def source_hash(root, env):
    files = {}
    for directory in ('bootstrap', 'main'):
        base = root / 'terraform' / directory
        paths = set(base.glob('*.tf')) | set(base.glob('*.tf.json')) | set(base.glob('*.tfvars*'))
        paths |= {base / '.terraform.lock.hcl', base / '.terraform/terraform.tfstate'}
        for path in sorted(paths):
            if path.is_file():
                files[str(path.relative_to(root))] = digest(path.read_bytes())
    # Only store a hash of variable values, not the values themselves.
    value = {'files': files, 'variables': {k: v for k, v in env.items() if k.startswith('TF_VAR_')}}
    return digest(json.dumps(value, sort_keys=True).encode())


def state_hash(root, env):
    value = json.loads(tf(root, env, 'main', 'state', 'pull'))
    return digest(json.dumps(value, sort_keys=True).encode())


def validate_plan(details, action, registry=None):
    if details.get('errored') or details.get('complete') is False or details.get('deferred_changes'):
        raise ValueError('The Terraform plan is incomplete or has errors.')
    changes = details.get('resource_changes', [])
    addresses = [change['address'] for change in changes]
    if len(addresses) != len(EXPECTED) or set(addresses) != EXPECTED:
        raise ValueError('Plan must contain exactly the reviewed 13 main resources.')
    identities = {}
    for item in changes:
        if item.get('mode') != 'managed' or item['change']['actions'] != [action]:
            raise ValueError('Unexpected plan action; mixed updates/replacements are not accepted.')
        values = item['change']['before' if action == 'delete' else 'after']
        if values.get('folder_id') != FOLDER:
            raise ValueError('A planned resource is outside the diploma folder.')
        if action == 'delete':
            identifier = values.get('id', '')
            if not re.fullmatch(r'[a-z0-9]{10,64}', identifier):
                raise ValueError('A planned resource has no valid existing ID.')
            identities[item['address']] = identifier
    if action == 'delete' and identities[REGISTRY] != registry:
        raise ValueError('The destroy plan targets a different registry.')
    return identities


def image_inventory(registry, env):
    images = json.loads(run(['yc', 'container', 'image', 'list', '--registry-id', registry,
                             '--limit=1000', '--format=json'], env))
    recovery.image_map(images, registry, allow_digest_alias=True)
    ids = [image.get('id', '') for image in images]
    if len(set(ids)) != len(ids) or any(not re.fullmatch(r'[a-z0-9]{10,64}', value) for value in ids):
        raise ValueError('Unexpected image IDs.')
    return [dict(image, tags=recovery.backup.image_tags(image, allow_digest_alias=True))
            for image in images]


def load_backup(root):
    private = root / '.secrets'
    latest = json.loads((private / 'registry-backup-latest.json').read_text())
    directory = Path(latest['backup_directory']).resolve()
    report = recovery.backup.verify_backup(directory)
    expected = recovery.image_map(report['images'], report['registry_id'])
    proof = json.loads((private / 'registry-upload-test-latest.json').read_text())
    age = (now() - datetime.fromisoformat(proof['checked_at'])).total_seconds()
    if not (0 <= age <= 86400) or proof.get('verified') is not True or proof.get('test_upload') is not True:
        raise ValueError('A successful upload test within the last 24 hours is required.')
    if (Path(proof['backup_directory']).resolve() != directory
            or proof.get('source_registry') != report['registry_id']
            or proof.get('target_registry') != report['registry_id']
            or proof.get('image_count') != len(expected)
            or proof.get('tags') != sum(len(tags) for tags in expected.values())):
        raise ValueError('Upload test does not match the current backup.')
    return directory, report


def prepare(root, env):
    autostart_off(root, env)
    github = github_snapshot()
    directory, backup = load_backup(root)
    registry = tf(root, env, 'main', 'output', '-raw', 'registry_id').decode().strip()
    if registry != backup['registry_id']:
        raise ValueError('Current registry differs from the tested backup.')
    metadata = json.loads(run(['yc', 'container', 'registry', 'get', '--id', registry, '--format=json'], env))
    if metadata.get('folder_id') != FOLDER:
        raise ValueError('Registry is outside the diploma folder.')
    images = image_inventory(registry, env)
    if recovery.image_map(images, registry) != recovery.image_map(backup['images'], registry):
        raise ValueError('Registry changed since the backup; make a new backup and upload test.')
    initial_state = state_hash(root, env)
    initial_source = source_hash(root, env)
    # Reuse the repository's read-only state/key/tfvars backup and fresh destroy plan.
    result = run(['python3', str(root / 'scripts/prepare-recreate.py')], env, timeout=1800)
    preflight = json.loads((root / '.secrets/recreate-latest.json').read_text())
    session = Path(preflight['backup_directory']).resolve()
    (session / 'preparation.log').write_bytes(result)
    (session / 'preparation.log').chmod(0o600)
    plan = session / 'destroy.tfplan'
    details = json.loads(tf(root, env, 'main', 'show', '-json', str(plan)))
    identities = validate_plan(details, 'delete', registry)
    if state_hash(root, env) != initial_state or source_hash(root, env) != initial_source:
        raise ValueError('State or configuration changed during preparation; review was not saved.')
    if github_snapshot() != github:
        raise ValueError('CI or branch changed during preparation; review was not saved.')
    if recovery.backup.signature(image_inventory(registry, env)) != recovery.backup.signature(images):
        raise ValueError('Registry changed during preparation; review was not saved.')
    review = {'format': 'diploma-recreate-main-v1', 'root': str(root), 'phase': 'prepared',
              'created_at': now().isoformat(), 'session': str(session),
              'backup_directory': str(directory), 'registry_id': registry, 'images': images,
              'resource_ids': identities, 'github': github, 'source_hash': initial_source,
              'state_hash': initial_state, 'destroy_plan_sha256': digest(plan.read_bytes())}
    save(session / 'cycle-review.json', review)
    save(root / '.secrets/recreate-cycle-latest.json', {'review': str(session / 'cycle-review.json')})
    print(f'Review: {session / "cycle-review.json"}')
    print('Autostart: off; GitHub Actions: idle in both repositories')
    print(f'Image backups and upload test: {len(images)} images, {sum(len(x.get("tags", [])) for x in images)} tags')
    for address in sorted(identities):
        print(f'  delete {address} [{identities[address]}]')
    print('Plan checked: 13 to destroy. Bootstrap is outside this plan.')
    print('Read-only preparation complete. No images or resources were deleted or created.')


def execute(root, env):
    pointer = json.loads((root / '.secrets/recreate-cycle-latest.json').read_text())
    review_path = Path(pointer['review']).resolve()
    if not review_path.is_relative_to(root / '.secrets'):
        raise ValueError('Review must be inside this repository .secrets directory.')
    review = json.loads(review_path.read_text())
    age = (now() - datetime.fromisoformat(review['created_at'])).total_seconds()
    if (review.get('format') != 'diploma-recreate-main-v1' or review.get('root') != str(root)
            or review.get('phase') != 'prepared' or not 0 <= age <= 14400):
        raise ValueError('A fresh, unused review from --plan is required (maximum four hours).')
    session = review_path.parent
    plan = session / 'destroy.tfplan'
    directory, backup = load_backup(root)
    if str(directory) != review['backup_directory'] or backup['registry_id'] != review['registry_id']:
        raise ValueError('Backup selection changed since review.')
    if recovery.image_map(backup['images'], review['registry_id']) != recovery.image_map(review['images'], review['registry_id']):
        raise ValueError('Backup image/tag manifest changed since review.')
    if source_hash(root, env) != review['source_hash'] or state_hash(root, env) != review['state_hash']:
        raise ValueError('Terraform configuration, variables, backend or state changed since review.')
    if digest(plan.read_bytes()) != review['destroy_plan_sha256']:
        raise ValueError('Saved destroy plan changed.')
    if validate_plan(json.loads(tf(root, env, 'main', 'show', '-json', str(plan))),
                     'delete', review['registry_id']) != review['resource_ids']:
        raise ValueError('Saved plan no longer matches the review.')
    autostart_off(root, env)
    if github_snapshot() != review['github']:
        raise ValueError('A GitHub branch changed since review; stop and prepare again.')
    registry = review['registry_id']
    remaining = review['images'].copy()
    if recovery.backup.signature(image_inventory(registry, env)) != recovery.backup.signature(remaining):
        raise ValueError('Registry image IDs, tags or digests changed since review.')

    def phase(value):
        review['phase'] = value
        review['updated_at'] = now().isoformat()
        save(review_path, review)
        print('Phase:', value, flush=True)

    # Once execution starts, this review cannot be reused to delete a new cluster.
    phase('cleaning_registry')
    for image in review['images']:
        if recovery.backup.signature(image_inventory(registry, env)) != recovery.backup.signature(remaining):
            raise ValueError('Registry changed during cleanup; stop without deleting further images.')
        run(['yc', 'container', 'image', 'delete', image['id']], env,
            log=session / ('delete-' + image['id'] + '.log'), timeout=300)
        remaining = [x for x in remaining if x['id'] != image['id']]
        deadline = time.monotonic() + 60
        while recovery.backup.signature(image_inventory(registry, env)) != recovery.backup.signature(remaining):
            if time.monotonic() >= deadline:
                raise ValueError('Registry deletion did not settle; stop and inspect its inventory.')
            time.sleep(3)
        print('Deleted backed-up image:', image['id'], flush=True)
    if github_snapshot() != review['github']:
        raise ValueError('CI or branch changed; stop before Terraform destroy.')
    autostart_off(root, env)
    phase('destroying_main')
    tf(root, env, 'main', 'apply', '-input=false', '-no-color', str(plan),
       log=session / 'destroy-apply.log', timeout=3600)
    empty_state = json.loads(tf(root, env, 'main', 'state', 'pull'))
    if any(x.get('mode') == 'managed' for x in empty_state.get('resources', [])):
        raise ValueError('Main state is not empty after destroy; stop before creation.')
    save(session / 'main-after-destroy.tfstate', empty_state)
    if github_snapshot() != review['github']:
        raise ValueError('CI or branch changed; stop before Terraform create.')
    autostart_off(root, env)
    if source_hash(root, env) != review['source_hash']:
        raise ValueError('Configuration changed during execution; stop before Terraform create.')
    phase('planning_create')
    creation = session / 'create.tfplan'
    tf(root, env, 'main', 'plan', '-input=false', '-no-color', '-out=' + str(creation),
       log=session / 'create-plan.log', timeout=1800)
    creation.chmod(0o600)
    validate_plan(json.loads(tf(root, env, 'main', 'show', '-json', str(creation))), 'create')
    phase('creating_main')
    tf(root, env, 'main', 'apply', '-input=false', '-no-color', str(creation),
       log=session / 'create-apply.log', timeout=3600)
    phase('checking_no_changes')
    tf(root, env, 'main', 'plan', '-input=false', '-no-color', '-detailed-exitcode',
       log=session / 'no-changes.log', timeout=1800)
    new_registry = tf(root, env, 'main', 'output', '-raw', 'registry_id').decode().strip()
    if new_registry == registry:
        raise ValueError('Registry ID did not change; inspect the recreate evidence.')
    phase('restoring_images')
    output = run(['python3', str(HERE / 'registry-recovery.py'), '--infra', str(root), '--restore'],
                 env, log=session / 'registry-restore.log', timeout=3600)
    print(output.decode(), end='')
    evidence = json.loads((root / '.secrets/registry-restore-latest.json').read_text())
    if not evidence.get('verified') or evidence.get('target_registry') != new_registry:
        raise ValueError('No matching successful registry restore report.')
    review['new_registry_id'] = new_registry
    review['outputs'] = {name: tf(root, env, 'main', 'output', '-raw', name).decode().strip()
                         for name in ('control_plane_ip', 'web_ip')}
    phase('main_and_images_recreated')
    print('Terraform cycle passed: 13 destroyed, 13 created; final plan has no changes.')
    print('New registry:', new_registry)
    print('New IPs:', json.dumps(review['outputs']))
    print('Kubernetes, application and monitoring still need installation. Autostart remains off.')
    print('Private evidence:', session)


def finish_restoration(root, env):
    """Verify an already recreated main and existing images, without cloud writes."""
    pointer = json.loads((root / '.secrets/recreate-cycle-latest.json').read_text())
    review_path = Path(pointer['review']).resolve()
    if not review_path.is_relative_to(root / '.secrets'):
        raise ValueError('Review must be inside this repository private directory.')
    review = json.loads(review_path.read_text())
    if (review.get('format') != 'diploma-recreate-main-v1' or review.get('root') != str(root)
            or review.get('phase') not in ('restoring_images', 'main_and_images_recreated')):
        raise ValueError('Only an execution that reached image restoration can be finalized.')
    autostart_off(root, env)
    if source_hash(root, env) != review['source_hash'] or github_snapshot() != review['github']:
        raise ValueError('Configuration, CI or GitHub branch changed; inspect before finalizing.')
    state = json.loads(tf(root, env, 'main', 'show', '-json'))
    module = state.get('values', {}).get('root_module', {})
    resources = [item for item in module.get('resources', []) if item.get('mode') == 'managed']
    addresses = [item['address'] for item in resources]
    if module.get('child_modules') or len(addresses) != 13 or set(addresses) != EXPECTED:
        raise ValueError('Current main must contain exactly the 13 recreated resources.')
    for item in resources:
        values = item.get('values', {})
        identifier = values.get('id', '')
        if (values.get('folder_id') != FOLDER or not re.fullmatch(r'[a-z0-9]{10,64}', identifier)
                or identifier == review['resource_ids'].get(item['address'])):
            raise ValueError('Current resources do not all have new IDs; inspect the cycle.')
    latest = json.loads((root / '.secrets/registry-backup-latest.json').read_text())
    backup_directory = Path(latest['backup_directory']).resolve()
    if str(backup_directory) != review['backup_directory']:
        raise ValueError('Backup selection changed since the cycle.')
    backup = recovery.backup.verify_backup(backup_directory)
    if (backup['registry_id'] != review['registry_id'] or
            recovery.image_map(backup['images'], backup['registry_id']) !=
            recovery.image_map(review['images'], review['registry_id'])):
        raise ValueError('Backup content differs from the cycle review.')
    session = review_path.parent
    print('Phase: verifying_existing_images', flush=True)
    content = run(['python3', str(HERE / 'registry-recovery.py'), '--infra', str(root), '--verify-only'],
                  env, log=session / 'registry-verify.log', timeout=1800)
    print(content.decode(), end='')
    registry = tf(root, env, 'main', 'output', '-raw', 'registry_id').decode().strip()
    evidence = json.loads((root / '.secrets/registry-restore-latest.json').read_text())
    if (evidence.get('verified') is not True or evidence.get('verification_only') is not True
            or evidence.get('target_registry') != registry or registry == review['registry_id']
            or evidence.get('source_registry') != review['registry_id']):
        raise ValueError('No matching verification report for the recreated registry.')
    print('Phase: checking_no_changes', flush=True)
    tf(root, env, 'main', 'plan', '-input=false', '-no-color', '-detailed-exitcode',
       log=session / 'no-changes-after-recovery.log', timeout=1800)
    review['new_registry_id'] = registry
    review['outputs'] = {name: tf(root, env, 'main', 'output', '-raw', name).decode().strip()
                         for name in ('control_plane_ip', 'web_ip')}
    review['phase'] = 'main_and_images_recreated'
    review['updated_at'] = now().isoformat()
    review['completion_method'] = 'verified_existing_images_after_digest_alias_parser_fix'
    save(review_path, review)
    print('Phase: main_and_images_recreated')
    print('Recreated main and restored images verified; final Terraform plan has no changes.')
    print('New registry:', registry)
    print('New IPs:', json.dumps(review['outputs']))
    print('Kubernetes, application and monitoring still need installation. Autostart remains off.')
    print('Private evidence:', session)


def main():
    global ERROR_DIRECTORY
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--infra', type=Path, default=Path.cwd())
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--plan', action='store_true', help='Read-only backups and plan review.')
    group.add_argument('--execute', action='store_true', help='Delete images and 13 main resources; recreate them and restore images.')
    group.add_argument('--finish-restoration', action='store_true',
                       help='Verify already recreated resources and images; no cloud resource writes.')
    args = parser.parse_args()
    os.umask(0o077)
    root = args.infra.expanduser().resolve()
    if not (root / '.secrets').is_dir() or (root / '.secrets').is_symlink():
        raise ValueError('Expected the infra repository and its existing private directory.')
    ERROR_DIRECTORY = root / '.secrets'
    for command in ('terraform', 'yc', 'crane', 'python3'):
        if not shutil.which(command):
            raise ValueError('Missing command: ' + command)
    # Prevent two copies of this utility from running together on this laptop.
    import fcntl
    with (root / '.secrets/recreate-cycle.lock').open('a') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        env = environment(root)
        action = finish_restoration if args.finish_restoration else (prepare if args.plan else execute)
        action(root, env)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        raise SystemExit(f'Stopped: {error}\nDo not reuse an execution that already started. Keep private logs and diagnose the recorded phase.')
