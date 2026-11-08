from contextlib import redirect_stdout
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('backup_registry', Path(__file__).resolve().parents[1] / 'scripts/backup-registry.py')
backup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backup)
REGISTRY = 'crpi32ickihldl29g1fg'


def make_layout(root):
    blobs = root / 'blobs/sha256'
    blobs.mkdir(parents=True)

    def write(value, media_type):
        data = json.dumps(value).encode() if isinstance(value, dict) else value
        digest = 'sha256:' + hashlib.sha256(data).hexdigest()
        (blobs / digest.split(':')[1]).write_bytes(data)
        return {'digest': digest, 'size': len(data), 'mediaType': media_type}

    config = write({'architecture': 'amd64', 'os': 'linux',
                    'config': {'Env': ['APP=fixture']}}, 'application/vnd.oci.image.config.v1+json')
    layer = write(b'compressed-layer-fixture', 'application/vnd.oci.image.layer.v1.tar+gzip')
    manifest = write({'schemaVersion': 2, 'config': config, 'layers': [layer]},
                     'application/vnd.oci.image.manifest.v1+json')
    (root / 'index.json').write_text(json.dumps({'schemaVersion': 2, 'manifests': [manifest]}))
    (root / 'oci-layout').write_text('{"imageLayoutVersion":"1.0.0"}')
    return manifest, layer


class BackupTests(unittest.TestCase):
    def test_backup_inventory_normalizes_only_own_digest_alias(self):
        digest = 'sha256:' + 'a' * 64
        image = {'id': 'crpfixture00000000001', 'name': REGISTRY + '/diploma-app',
                 'digest': digest, 'tags': [digest, 'v1.0.2']}
        with patch.object(backup, 'run', return_value=json.dumps([image])):
            self.assertEqual(backup.inventory(REGISTRY)[0]['tags'], ['v1.0.2'])
        image['tags'] = ['sha256:' + 'b' * 64]
        with patch.object(backup, 'run', return_value=json.dumps([image])):
            with self.assertRaisesRegex(ValueError, 'Invalid image tags'):
                backup.inventory(REGISTRY)

    def test_checks_manifest_config_and_layer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, _ = make_layout(root)
            self.assertEqual(backup.verify_layout(root, manifest['digest']), 3)

    def test_changed_layer_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, layer = make_layout(root)
            (root / 'blobs/sha256' / layer['digest'].split(':')[1]).write_bytes(b'damaged')
            with self.assertRaisesRegex(ValueError, 'damaged'):
                backup.verify_layout(root, manifest['digest'])

    def test_different_manifest_digest_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_layout(root)
            with self.assertRaisesRegex(ValueError, 'expected original manifest'):
                backup.verify_layout(root, 'sha256:' + '0' * 64)

    def simulate(self, root, inventory_changed=False, pull_fails=False):
        private = root / '.secrets'
        private.mkdir()
        (private / 'recreate-latest.json').write_text(json.dumps({'registry_id': REGISTRY}))
        template = root / 'template'
        digest, _ = make_layout(template)
        images = [{'id': 'crpfixture00000000001', 'name': REGISTRY + '/diploma-app',
                   'digest': digest['digest'], 'tags': ['v1.0.1'], 'compressed_size': '20'},
                  {'id': 'crpfixture00000000002', 'name': REGISTRY + '/diploma-app',
                   'digest': digest['digest'], 'compressed_size': '20'}]
        calls = []
        auth_path = None

        def run(arguments, **kwargs):
            nonlocal auth_path
            calls.append(arguments)
            if arguments[:4] == ['yc', 'container', 'image', 'list']:
                if inventory_changed and sum(c[:4] == arguments[:4] for c in calls) == 2:
                    return json.dumps(images[:1])
                return json.dumps(images)
            if arguments[:2] == ['crane', 'version']:
                return 'fixture-version'
            if arguments[:3] == ['yc', 'iam', 'create-token']:
                return 'fixture-token-never-print'
            if arguments[:3] == ['crane', 'auth', 'login']:
                auth_path = Path(kwargs['env']['DOCKER_CONFIG'])
                (auth_path / 'config.json').write_text('fixture-credential')
                return ''
            if arguments[:2] == ['crane', 'pull']:
                if pull_fails:
                    raise SystemExit('simulated pull failure')
                import shutil
                shutil.copytree(template, Path(arguments[3]))
                return ''
            raise AssertionError(arguments)

        stream = io.StringIO()
        with patch.object(backup, 'run', side_effect=run), \
                patch.object(backup.shutil, 'which', return_value='/fixture/tool'), \
                redirect_stdout(stream):
            if inventory_changed or pull_fails:
                with self.assertRaises(SystemExit):
                    backup.backup(root)
                destination = next(private.glob('registry-backup-*'))
            else:
                destination = backup.backup(root)
        self.assertNotIn('fixture-token-never-print', stream.getvalue())
        self.assertFalse(auth_path.exists())
        self.assertTrue(all('delete' not in c and 'destroy' not in c and 'push' not in c for c in calls))
        return destination, images

    def test_backup_preserves_tags_and_untagged_image_without_mutations(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination, images = self.simulate(Path(temporary))
            report = backup.verify_backup(destination)
            self.assertEqual(report['images'], images)

    def test_changed_registry_does_not_get_a_complete_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination, _ = self.simulate(Path(temporary), inventory_changed=True)
            self.assertFalse((destination / 'manifest.json').exists())

    def test_authentication_removed_after_pull_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination, _ = self.simulate(Path(temporary), pull_fails=True)
            self.assertFalse((destination / 'manifest.json').exists())

    def test_inventory_rejects_another_registry(self):
        wrong = [{'id': 'crpfixture00000000001', 'name': 'other/app', 'digest': 'sha256:' + '0' * 64}]
        with patch.object(backup, 'run', return_value=json.dumps(wrong)):
            with self.assertRaisesRegex(SystemExit, 'different registry'):
                backup.inventory(REGISTRY)


if __name__ == '__main__':
    unittest.main()
