from contextlib import redirect_stdout
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('recovery', BASE / 'scripts/registry-recovery.py')
recovery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recovery)
OLD = 'crpi32ickihldl29g1fg'
NEW = 'crpnewregistry00000000'


def fixture_image(root, identifier, tag):
    layout = root / identifier
    blobs = layout / 'blobs/sha256'
    blobs.mkdir(parents=True)
    content = json.dumps({'architecture': 'amd64', 'config': {'Env': [identifier]}}).encode()
    digest = hashlib.sha256(content).hexdigest()
    (blobs / digest).write_bytes(content)
    manifest = json.dumps({'schemaVersion': 2, 'config': {
        'digest': 'sha256:' + digest, 'size': len(content),
        'mediaType': 'application/vnd.oci.image.config.v1+json'}, 'layers': []}).encode()
    value = 'sha256:' + hashlib.sha256(manifest).hexdigest()
    (blobs / value.split(':')[1]).write_bytes(manifest)
    (layout / 'index.json').write_text(json.dumps({'manifests': [{
        'digest': value, 'size': len(manifest),
        'mediaType': 'application/vnd.oci.image.manifest.v1+json'}]}))
    item = {'id': identifier, 'name': OLD + '/diploma-app', 'digest': value}
    if tag:
        item['tags'] = [tag]
    return item, manifest


class RecoveryTests(unittest.TestCase):
    def scenario(self, root, restore=False, unexpected=False, bad_remote=False, bad_local=False,
                 aliases=False, verify_only=False):
        private = root / '.secrets'
        private.mkdir()
        directory = private / 'registry-backup-fixture'
        items = []; manifests = {}
        for identifier, tag in [('crpfixture00000000001', 'v1.0.1'), ('crpfixture00000000002', '')]:
            item, manifest = fixture_image(directory, identifier, tag)
            items.append(item); manifests[item['digest']] = manifest
        (directory / 'manifest.json').write_text(json.dumps({
            'format': 'diploma-registry-oci-v1', 'registry_id': OLD, 'images': items}))
        (private / 'registry-backup-latest.json').write_text(json.dumps({'backup_directory': str(directory)}))
        (private / 'terraform-key.json').write_text('fixture-not-a-real-key')
        if bad_local:
            p = directory / items[0]['id'] / 'blobs/sha256' / items[0]['digest'].split(':')[1]
            p.write_bytes(b'damaged')
        target = NEW if restore else OLD
        remote = ([dict(item, name=target + '/diploma-app', tags=list(item.get('tags', [])))
                   for item in items] if verify_only else ([] if restore else copy.deepcopy(items)))
        if aliases:
            for item in remote:
                item.setdefault('tags', []).append(item['digest'])
        if unexpected:
            if restore:
                remote = [dict(items[0], name=NEW + '/diploma-app', tags=['unrelated-tag'])]
            else:
                remote[0]['tags'] = ['changed-tag']
        calls = []; auth_paths = []

        def run(args, env=None, input=None, timeout=180):
            calls.append(args)
            if args[0] == 'terraform':
                key = args[-1]
                return {'state_access_key': b'fixture-access', 'state_secret_key': b'fixture-secret',
                        'registry_id': target.encode()}[key]
            if args[:3] == ['yc', 'container', 'registry']:
                return b'{"folder_id":"folder"}'
            if args[:4] == ['yc', 'container', 'image', 'list']:
                return json.dumps(remote).encode()
            if args[:3] == ['yc', 'iam', 'create-token']:
                return b'fixture-token-never-print'
            if args[:3] == ['crane', 'auth', 'login']:
                auth = Path(env['DOCKER_CONFIG']); auth_paths.append(auth)
                (auth / 'config.json').write_bytes(input)
                return b''
            if args[:2] == ['crane', 'push']:
                digest = args[-1].split('@')[1]
                if restore and not any(item['digest'] == digest for item in remote):
                    item = next(x for x in items if x['digest'] == digest)
                    remote.append(dict(item, name=target + '/diploma-app',
                                       tags=[digest] if aliases else []))
                return b''
            if args[:2] == ['crane', 'tag']:
                digest = args[2].split('@')[1]
                next(x for x in remote if x['digest'] == digest)['tags'].append(args[3])
                return b''
            if args[:2] == ['crane', 'manifest']:
                if bad_remote:
                    return b'changed-manifest'
                if '@' in args[2]:digest = args[2].split('@')[1]
                else:digest = next(x['digest'] for x in remote if args[2].rsplit(':', 1)[1] in x.get('tags', []))
                return manifests[digest]
            raise AssertionError(args)

        stream = io.StringIO()
        with patch.object(recovery, 'run', side_effect=run), \
                patch.object(recovery.shutil, 'which', return_value='/fixture/tool'), \
                patch.dict(recovery.os.environ, {'TF_VAR_folder_id': 'folder'}), redirect_stdout(stream):
            if unexpected or bad_remote or bad_local:
                with self.assertRaises(ValueError):recovery.recover(root, not restore, verify_only)
            else:
                result = recovery.recover(root, not restore, verify_only)
                self.assertTrue(result['verified'])
        self.assertNotIn('fixture-token-never-print', stream.getvalue())
        self.assertTrue(all(not p.exists() for p in auth_paths))
        self.assertTrue(all('delete' not in call and 'destroy' not in call for call in calls))
        return calls, remote, items

    def test_upload_from_backup_preserves_existing_tags_without_tag_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls, actual, expected = self.scenario(Path(tmp))
            self.assertEqual(actual, expected)
            self.assertEqual(sum(c[:2] == ['crane', 'push'] for c in calls), 2)
            self.assertFalse(any(c[:2] == ['crane', 'tag'] for c in calls))

    def test_restore_to_new_registry_keeps_an_untagged_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls, actual, expected = self.scenario(Path(tmp), restore=True)
            self.assertEqual(recovery.image_map(actual, NEW), recovery.image_map(expected, OLD))
            self.assertEqual(sum(c[:2] == ['crane', 'tag'] for c in calls), 1)

    def test_modified_source_inventory_blocks_uploads(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls, _, _ = self.scenario(Path(tmp), unexpected=True)
            self.assertFalse(any(c[0] == 'crane' for c in calls))

    def test_unrelated_target_tag_blocks_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls, _, _ = self.scenario(Path(tmp), restore=True, unexpected=True)
            self.assertFalse(any(c[0] == 'crane' for c in calls))

    def test_remote_manifest_digest_mismatch_is_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:self.scenario(Path(tmp), bad_remote=True)

    def test_damaged_backup_blocks_all_api_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls, _, _ = self.scenario(Path(tmp), bad_local=True)
            self.assertEqual(calls, [])

    def test_yc_digest_aliases_are_accepted_after_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls, actual, expected = self.scenario(Path(tmp), restore=True, aliases=True)
            self.assertEqual(recovery.image_map(actual, NEW, allow_digest_alias=True), recovery.image_map(expected, OLD))

    def test_verify_existing_aliases_never_uploads_or_changes_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls, _, _ = self.scenario(Path(tmp), restore=True, aliases=True, verify_only=True)
            self.assertFalse(any(c[:2] in (['crane', 'push'], ['crane', 'tag']) for c in calls))
            self.assertEqual(sum(c[:2] == ['crane', 'manifest'] for c in calls), 3)

    def test_foreign_digest_alias_and_invalid_tags_still_fail(self):
        original = {'name': NEW + '/diploma-app', 'digest': 'sha256:' + 'a' * 64}
        for tags in [['sha256:' + 'b' * 64], ['invalid:release'], [None], None]:
            with self.subTest(tags=tags), self.assertRaises(ValueError):
                recovery.image_map([dict(original, tags=tags)], NEW, allow_digest_alias=True)

    def test_backup_manifest_is_strict_about_digest_aliases(self):
        digest = 'sha256:' + 'a' * 64
        with self.assertRaises(ValueError):
            recovery.image_map([{'name': OLD + '/diploma-app', 'digest': digest, 'tags': [digest]}], OLD)

    def test_unrelated_tag_still_blocks_verification_even_with_own_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls, _, _ = self.scenario(Path(tmp), restore=True, unexpected=True, aliases=True, verify_only=True)
            self.assertFalse(any(c[0] == 'crane' for c in calls))


if __name__ == '__main__':unittest.main()
