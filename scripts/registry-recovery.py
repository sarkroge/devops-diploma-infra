#!/usr/bin/env python3
"""Check OCI backup uploads or restore them to the current Terraform registry."""
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
import tempfile
import time

SPEC = importlib.util.spec_from_file_location('registry_backup', Path(__file__).with_name('backup-registry.py'))
backup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backup)


def run(arguments, env=None, input=None, timeout=180):
    result = subprocess.run(arguments, env=env, input=input, capture_output=True, timeout=timeout)
    if result.returncode:
        message = result.stderr.decode(errors='replace')[-1500:]
        raise SystemExit(f'{arguments[0]} {arguments[1]} failed:\n{message}')
    return result.stdout


def tf_output(root, directory, name, env=None):
    return run(['terraform', f'-chdir={root / "terraform" / directory}',
                'output', '-raw', name], env=env).decode().strip()


def image_map(images, registry, allow_digest_alias=False):
    if not isinstance(images, list) or len(images) >= 1000:
        raise ValueError('Expected a list of fewer than 1000 images.')
    result = {}
    for image in images:
        if image.get('name') != registry + '/diploma-app':
            raise ValueError('This tool only handles diploma-app in the selected registry.')
        digest = image.get('digest', '')
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest) or digest in result:
            raise ValueError('Invalid or duplicate image digest.')
        tags = backup.image_tags(image, allow_digest_alias=allow_digest_alias)
        result[digest] = frozenset(tags)
    return result


def current_images(registry):
    return image_map(json.loads(run(['yc', 'container', 'image', 'list',
                                    '--registry-id', registry, '--limit=1000', '--format=json'])),
                     registry, allow_digest_alias=True)


def check_remote(reference, expected, env):
    # Read manifest bytes from the registry rather than trusting the input digest.
    content = run(['crane', 'manifest', reference], env=env)
    if 'sha256:' + hashlib.sha256(content).hexdigest() != expected:
        raise ValueError('Uploaded manifest digest differs from the original backup.')


def wait_for_images(registry, expected, timeout=60):
    deadline = time.monotonic() + timeout
    while True:
        if current_images(registry) == expected:
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError('Registry image/tag inventory differs from the backup after upload.')
        time.sleep(min(3, remaining))


def recover(root, test_upload, verify_only=False):
    private = root / '.secrets'
    if private.is_symlink() or not private.is_dir():
        raise ValueError('Expected the infra repository and its existing .secrets directory.')
    for executable in ['terraform', 'yc', 'crane']:
        if not shutil.which(executable):
            raise ValueError(f'Missing command: {executable}')
    latest = json.loads((private / 'registry-backup-latest.json').read_text())
    directory = Path(latest['backup_directory']).expanduser().resolve()
    report = backup.verify_backup(directory)
    old_registry = report['registry_id']
    if not re.fullmatch(r'[a-z0-9]{10,64}', old_registry):
        raise ValueError('Invalid source registry ID.')
    expected = image_map(report['images'], old_registry)
    print(f'Local copies verified: {len(expected)} images', flush=True)

    env = os.environ.copy()
    env.pop('YC_TOKEN', None)
    key = private / 'terraform-key.json'
    if not key.is_file():
        raise ValueError('Existing Terraform service account key is missing.')
    env['YC_SERVICE_ACCOUNT_KEY_FILE'] = str(key)
    env['AWS_ACCESS_KEY_ID'] = tf_output(root, 'bootstrap', 'state_access_key')
    env['AWS_SECRET_ACCESS_KEY'] = tf_output(root, 'bootstrap', 'state_secret_key')
    registry = tf_output(root, 'main', 'registry_id', env)
    if not re.fullmatch(r'[a-z0-9]{10,64}', registry):
        raise ValueError('Invalid registry ID from Terraform outputs.')
    registry_data = json.loads(run(['yc', 'container', 'registry', 'get',
                                    '--id', registry, '--format=json']))
    folder = os.environ.get('TF_VAR_folder_id') or run(['yc', 'config', 'get', 'folder-id']).decode().strip()
    if registry_data.get('folder_id') != folder:
        raise ValueError('Target registry is outside the configured folder.')
    existing = current_images(registry)
    if verify_only:
        if existing != expected:
            raise ValueError('Verification requires all original images and tags to be present.')
    elif test_upload:
        if registry != old_registry or existing != expected:
            raise ValueError('Upload test requires the original registry with its unchanged image/tag inventory.')
    elif any(digest not in expected or not tags.issubset(expected[digest])
             for digest, tags in existing.items()):
        raise ValueError('Target has images or tags outside this backup; restore was not started.')
    mode = 'verify existing images' if verify_only else ('test upload' if test_upload else 'restore')
    print(f'Target registry: {registry}; mode: {mode}', flush=True)

    with tempfile.TemporaryDirectory(prefix='registry-auth-', dir=private) as auth:
        env['DOCKER_CONFIG'] = auth
        token = run(['yc', 'iam', 'create-token']).strip()
        if not token:
            raise ValueError('yc returned an empty IAM token.')
        run(['crane', 'auth', 'login', 'cr.yandex', '-u', 'iam', '--password-stdin'],
            env=env, input=token + b'\n')
        token = None
        repository = f'cr.yandex/{registry}/diploma-app'
        for position, image in enumerate(report['images'], 1):
            reference = repository + '@' + image['digest']
            if not verify_only:
                run(['crane', 'push', str(directory / image['id']), reference], env=env, timeout=1800)
            check_remote(reference, image['digest'], env)
            if not test_upload and not verify_only:
                for tag in image.get('tags', []):
                    run(['crane', 'tag', reference, tag], env=env)
            for tag in image.get('tags', []):
                check_remote(repository + ':' + tag, image['digest'], env)
            label = 'Existing digest and tags verified' if verify_only else 'Upload and digest verified'
            print(f'[{position}/{len(expected)}] {label}: {image["id"]}', flush=True)
    wait_for_images(registry, expected)
    result = {'checked_at': datetime.now(timezone.utc).isoformat(),
              'backup_directory': str(directory), 'source_registry': old_registry,
              'target_registry': registry, 'test_upload': test_upload, 'verification_only': verify_only,
              'digest_alias_policy': 'ignore_only_exact_image_digest',
              'image_count': len(expected), 'tags': sum(len(tags) for tags in expected.values()),
              'verified': True}
    target = private / ('registry-upload-test-latest.json' if test_upload else 'registry-restore-latest.json')
    target.write_text(json.dumps(result, indent=2) + '\n')
    target.chmod(0o600)
    label = 'Restore verification' if verify_only else ('Upload test' if test_upload else 'Restore')
    print(f'{label} passed: {len(expected)} images, {result["tags"]} tags')
    print('Temporary authentication config removed. No images were deleted; no VM operations were performed.')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--infra', type=Path, default=Path.cwd())
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--test-upload', action='store_true')
    mode.add_argument('--restore', action='store_true')
    mode.add_argument('--verify-only', action='store_true', help='Read existing remote images and tags without uploading.')
    args = parser.parse_args()
    os.umask(0o077)
    recover(args.infra.expanduser().resolve(), args.test_upload, args.verify_only)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        raise SystemExit(f'Registry recovery failed: {error}')
