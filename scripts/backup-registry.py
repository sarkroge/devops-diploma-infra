#!/usr/bin/env python3
"""Save registry images as verified OCI layouts; no deletion or VM operations."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


def run(arguments, **kwargs):
    result = subprocess.run(arguments, capture_output=True, text=True,
                            timeout=kwargs.pop('timeout', 180), **kwargs)
    if result.returncode:
        raise SystemExit(f'{arguments[0]} {arguments[1]} failed:\n{result.stderr[-1500:]}')
    return result.stdout


def image_tags(image, allow_digest_alias=False):
    """Keep ordinary tags; YC may also return this image's own digest as an alias."""
    tags = image.get('tags', [])
    if not isinstance(tags, list):
        raise ValueError('Invalid image tags.')
    if allow_digest_alias:
        tags = [tag for tag in tags if tag != image.get('digest')]
    if any(not isinstance(tag, str) or not re.fullmatch(
            r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}', tag) for tag in tags):
        raise ValueError('Invalid image tags.')
    return tags


def inventory(registry):
    images = json.loads(run(['yc', 'container', 'image', 'list',
                            '--registry-id', registry, '--limit=1000', '--format=json']))
    if not isinstance(images, list) or not images or len(images) >= 1000:
        raise SystemExit('Expected a non-empty registry with fewer than 1000 images.')
    seen = set()
    for item in images:
        if not re.fullmatch(r'[a-z0-9]{10,64}', item.get('id', '')) or item['id'] in seen:
            raise SystemExit('Invalid or duplicate image ID.')
        seen.add(item['id'])
        if not item.get('name', '').startswith(registry + '/'):
            raise SystemExit('Image belongs to a different registry.')
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', item.get('digest', '')):
            raise SystemExit('Unsupported image digest.')
        if 'tags' in item:
            item['tags'] = image_tags(item, allow_digest_alias=True)
    return images


def signature(images):
    return sorted((image['id'], image['name'], image['digest'],
                   tuple(sorted(image.get('tags', [])))) for image in images)


def verify_layout(layout, expected_digest):
    """Check the manifest digest and every referenced manifest/config/layer blob."""
    if layout.is_symlink() or not layout.is_dir():
        raise ValueError('OCI layout must be a regular directory.')
    index = json.loads((layout / 'index.json').read_text())
    entries = index.get('manifests', [])
    if len(entries) != 1 or entries[0].get('digest') != expected_digest:
        raise ValueError('OCI layout does not contain the expected original manifest.')
    visited = set()

    def verify(descriptor, depth=0):
        value = descriptor.get('digest', '')
        if depth > 16 or not re.fullmatch(r'sha256:[0-9a-f]{64}', value):
            raise ValueError('Invalid OCI descriptor.')
        if value in visited:
            return
        path = layout / 'blobs' / 'sha256' / value.split(':', 1)[1]
        if path.is_symlink() or not path.resolve().is_relative_to(layout.resolve()):
            raise ValueError('OCI blob points outside the backup.')
        with path.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != value.split(':', 1)[1] or path.stat().st_size != descriptor.get('size'):
            raise ValueError(f'OCI blob is missing or damaged: {value}')
        visited.add(value)
        media_type = descriptor.get('mediaType', '')
        manifest_types = {'application/vnd.oci.image.manifest.v1+json',
                          'application/vnd.docker.distribution.manifest.v2+json'}
        index_types = {'application/vnd.oci.image.index.v1+json',
                       'application/vnd.docker.distribution.manifest.list.v2+json'}
        if media_type in manifest_types or media_type in index_types:
            data = json.loads(path.read_text())
            children = data['manifests'] if media_type in index_types else data['layers'] + [data['config']]
            for child in children:
                verify(child, depth + 1)

    verify(entries[0])
    return len(visited)


def verify_backup(directory):
    report = json.loads((directory / 'manifest.json').read_text())
    if report.get('format') != 'diploma-registry-oci-v1' or not report.get('images'):
        raise ValueError('Unsupported or incomplete backup manifest.')
    for image in report['images']:
        if not re.fullmatch(r'[a-z0-9]{10,64}', image.get('id', '')):
            raise ValueError('Invalid backup image ID.')
        verify_layout(directory / image['id'], image['digest'])
    return report


def backup(root):
    private = root / '.secrets'
    if private.is_symlink() or not private.is_dir():
        raise SystemExit('Run from the infra repository with its existing .secrets directory.')
    previous = json.loads((private / 'recreate-latest.json').read_text())
    registry = previous.get('registry_id', '')
    if not re.fullmatch(r'[a-z0-9]{10,64}', registry):
        raise SystemExit('Run scripts/prepare-recreate.py first to identify the registry.')
    for executable in ['yc', 'crane']:
        if not shutil.which(executable):
            raise SystemExit(f'Missing command: {executable}. Install crane with: brew install crane')
    images = inventory(registry)
    required = sum(int(item.get('compressed_size', 0)) for item in images) * 1.2
    if shutil.disk_usage(private).free < required + 64 * 1024 * 1024:
        raise SystemExit('Not enough free disk space for the image backup.')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    destination = private / ('registry-backup-' + stamp)
    destination.mkdir(mode=0o700)
    version = run(['crane', 'version']).strip()
    print(f'Backup directory: {destination}', flush=True)
    # Credentials stay in a temporary private config, separate from ~/.docker.
    with tempfile.TemporaryDirectory(prefix='registry-auth-', dir=private) as auth:
        env = os.environ.copy()
        env['DOCKER_CONFIG'] = auth
        token = run(['yc', 'iam', 'create-token']).strip()
        if not token:
            raise SystemExit('yc returned an empty IAM token.')
        run(['crane', 'auth', 'login', 'cr.yandex', '-u', 'iam', '--password-stdin'],
            env=env, input=token + '\n')
        token = None
        for position, image in enumerate(images, 1):
            source = f'cr.yandex/{image["name"]}@{image["digest"]}'
            layout = destination / image['id']
            run(['crane', 'pull', source, str(layout), '--format=oci'], env=env, timeout=1800)
            blobs = verify_layout(layout, image['digest'])
            tags = ', '.join(image.get('tags', [])) or '(untagged)'
            print(f'[{position}/{len(images)}] Verified {image["id"]}: {tags}; blobs={blobs}', flush=True)
    if signature(inventory(registry)) != signature(images):
        raise SystemExit('Registry changed during backup. No complete manifest was written; retry after CI finishes.')
    report = {'format': 'diploma-registry-oci-v1', 'created_at': stamp,
              'registry_id': registry, 'crane_version': version, 'images': images}
    (destination / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    (destination / 'manifest.json').chmod(0o600)
    (private / 'registry-backup-latest.json').write_text(json.dumps({
        'backup_directory': str(destination), 'registry_id': registry,
        'image_count': len(images),
    }, indent=2) + '\n')
    (private / 'registry-backup-latest.json').chmod(0o600)
    print(f'Images saved and verified: {len(images)}')
    print(f'Tags preserved: {sum(len(item.get("tags", [])) for item in images)}')
    print('Temporary authentication config removed. No image or VM was deleted or changed.')
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--infra', type=Path, default=Path.cwd())
    parser.add_argument('--verify', type=Path, help='Verify an existing backup locally, without API calls.')
    args = parser.parse_args()
    os.umask(0o077)
    if args.verify:
        report = verify_backup(args.verify.expanduser().resolve())
        print(f'Local backup verification passed: {len(report["images"])} images')
    else:
        backup(args.infra.expanduser().resolve())


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        raise SystemExit(f'Backup failed: {error}')
