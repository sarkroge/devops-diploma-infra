from contextlib import redirect_stdout
import copy
from datetime import timedelta
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('cycle', BASE / 'scripts/recreate-main.py')
cycle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cycle)
OLD = 'crpi32ickihldl29g1fg'
NEW = 'crpnewregistry00000000'
GITHUB = {repo: 'a' * 40 for repo in cycle.REPOS}


def plan(action):
    changes = []
    for position, address in enumerate(sorted(cycle.EXPECTED)):
        values = {'folder_id': cycle.FOLDER}
        if action == 'delete':
            values['id'] = OLD if address == cycle.REGISTRY else 'resourcefixture' + str(position)
        changes.append({'address': address, 'mode': 'managed',
                        'change': {'actions': [action], 'before': values if action == 'delete' else None,
                                   'after': values if action == 'create' else None}})
    return {'complete': True, 'resource_changes': changes}


class GitHubHttpsTests(unittest.TestCase):
    def test_mac_uses_system_curl_with_certificate_verification(self):
        calls = []
        def run(args, env, timeout):
            calls.append(args)
            return json.dumps({'total_count': 0, 'workflow_runs': []} if '/actions/' in args[-1]
                              else {'commit': {'sha': 'a' * 40}}).encode()
        with patch.object(cycle.sys, 'platform', 'darwin'), patch.object(cycle, 'run', side_effect=run):
            self.assertEqual(cycle.github_snapshot(), GITHUB)
        self.assertEqual(len(calls), 4)
        for args in calls:
            self.assertEqual(args[:2], ['/usr/bin/curl', '--disable'])
            self.assertIn('=https', args)
            self.assertNotIn('--insecure', args)
            self.assertNotIn('-k', args)

    def test_tls_failure_stops_without_insecure_retry(self):
        with patch.object(cycle, 'run', side_effect=ValueError('certificate verification failed')) as command:
            with self.assertRaisesRegex(ValueError, 'certificate'):
                cycle.github_snapshot()
            self.assertEqual(command.call_count, 1)

    def test_active_ci_blocks_the_snapshot(self):
        with patch.object(cycle, 'github_get', return_value={
                'total_count': 1, 'workflow_runs': [{'status': 'in_progress'}]}):
            with self.assertRaisesRegex(ValueError, 'Actions are active'):
                cycle.github_snapshot()


class PlanTests(unittest.TestCase):
    def test_inventory_returns_ordinary_tags_for_review_and_signature(self):
        digest = 'sha256:' + 'a' * 64
        image = {'id': 'crpfixture00000000001', 'name': OLD + '/diploma-app',
                 'digest': digest, 'tags': [digest, 'v1.0.2']}
        with patch.object(cycle, 'run', return_value=json.dumps([image]).encode()):
            actual = cycle.image_inventory(OLD, {})
        self.assertEqual(actual, [dict(image, tags=['v1.0.2'])])
        self.assertEqual(cycle.recovery.image_map(actual, OLD), {digest: frozenset(['v1.0.2'])})

    def test_foreign_digest_alias_blocks_review(self):
        image = {'id': 'crpfixture00000000001', 'name': OLD + '/diploma-app',
                 'digest': 'sha256:' + 'a' * 64, 'tags': ['sha256:' + 'b' * 64]}
        with patch.object(cycle, 'run', return_value=json.dumps([image]).encode()):
            with self.assertRaisesRegex(ValueError, 'Invalid image tags'):
                cycle.image_inventory(OLD, {})

    def test_expected_destroy_and_create(self):
        self.assertEqual(len(cycle.validate_plan(plan('delete'), 'delete', OLD)), 13)
        self.assertEqual(cycle.validate_plan(plan('create'), 'create'), {})

    def test_unexpected_bootstrap_resource_blocks_plan(self):
        value = plan('delete')
        value['resource_changes'].append({'address': 'yandex_storage_bucket.state'})
        with self.assertRaises(ValueError): cycle.validate_plan(value, 'delete', OLD)

    def test_replacement_or_incomplete_or_foreign_folder_blocked(self):
        for mode in ('replacement', 'incomplete', 'folder', 'registry'):
            value = plan('delete')
            if mode == 'replacement': value['resource_changes'][0]['change']['actions'] = ['delete', 'create']
            elif mode == 'incomplete': value['complete'] = False
            elif mode == 'folder': value['resource_changes'][0]['change']['before']['folder_id'] = 'foreign'
            else:
                next(x for x in value['resource_changes'] if x['address'] == cycle.REGISTRY)['change']['before']['id'] = NEW
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                cycle.validate_plan(value, 'delete', OLD)


class FinishRestorationTests(unittest.TestCase):
    def scenario(self, root, problem=None):
        # Match main(): macOS temporary paths may resolve from /var to /private/var.
        root = root.resolve()
        private = root / '.secrets'; private.mkdir()
        session = private / 'recreate-fixture'; session.mkdir()
        images = [{'name': OLD + '/diploma-app', 'digest': 'sha256:' + 'a' * 64,
                   'id': 'crpfixtureimage000001', 'tags': ['v1.0.1']}]
        originals = cycle.validate_plan(plan('delete'), 'delete', OLD)
        review = {'format': 'diploma-recreate-main-v1', 'root': str(root),
                  'phase': 'creating_main' if problem == 'phase' else 'restoring_images',
                  'registry_id': OLD, 'resource_ids': originals, 'images': images,
                  'backup_directory': str(private / 'backup'), 'source_hash': 'source', 'github': GITHUB}
        cycle.save(session / 'cycle-review.json', review)
        cycle.save(private / 'recreate-cycle-latest.json', {'review': str(session / 'cycle-review.json')})
        cycle.save(private / 'registry-backup-latest.json', {'backup_directory': str(private / 'backup')})
        resources = [{'address': address, 'mode': 'managed', 'values': {
            'id': NEW if address == cycle.REGISTRY else 'newresourcefixture' + str(i), 'folder_id': cycle.FOLDER}}
            for i, address in enumerate(sorted(cycle.EXPECTED))]
        if problem == 'old_id': resources[0]['values']['id'] = originals[resources[0]['address']]
        calls = []
        def tf(root, env, directory, *args, **kwargs):
            calls.append(['terraform', directory, *args])
            if args[:2] == ('show', '-json'):
                return json.dumps({'values': {'root_module': {'resources': resources}}}).encode()
            if args[0] == 'plan':
                if problem == 'changes': raise ValueError('plan exit 2')
                return b''
            if args[0] == 'output':
                return {'registry_id': NEW, 'web_ip': '192.0.2.2', 'control_plane_ip': '192.0.2.1'}[args[-1]].encode()
            raise AssertionError(args)
        def run(args, env, **kwargs):
            calls.append(args)
            self.assertIn('--verify-only', args)
            cycle.save(private / 'registry-restore-latest.json', {
                'verified': True, 'verification_only': True, 'target_registry': NEW, 'source_registry': OLD})
            return b'Restore verification passed\n'
        with patch.object(cycle, 'autostart_off'), patch.object(cycle, 'source_hash', return_value='source'), \
             patch.object(cycle, 'github_snapshot', return_value=GITHUB), \
             patch.object(cycle.recovery.backup, 'verify_backup', return_value={'images': images, 'registry_id': OLD}), \
             patch.object(cycle, 'tf', side_effect=tf), patch.object(cycle, 'run', side_effect=run), \
             redirect_stdout(io.StringIO()):
            if problem:
                with self.assertRaises(ValueError): cycle.finish_restoration(root, {})
            else: cycle.finish_restoration(root, {})
        self.assertFalse(any('apply' in c or 'delete' in c or '--restore' in c for c in calls))
        actual = json.loads((session / 'cycle-review.json').read_text())
        return calls, actual

    def test_finish_checks_existing_images_and_state_without_cloud_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls, result = self.scenario(Path(tmp))
            self.assertEqual(result['phase'], 'main_and_images_recreated')
            self.assertTrue(any('-detailed-exitcode' in c for c in calls))
            self.assertEqual(result['new_registry_id'], NEW)

    def test_finish_accepts_temporary_root_through_directory_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); real = base / 'real'; real.mkdir()
            alias = base / 'alias'; alias.symlink_to(real, target_is_directory=True)
            _, result = self.scenario(alias)
            self.assertEqual(result['phase'], 'main_and_images_recreated')

    def test_incomplete_cycle_or_old_resource_cannot_be_finalized(self):
        for problem in ('phase', 'old_id'):
            with self.subTest(problem=problem), tempfile.TemporaryDirectory() as tmp:
                calls, result = self.scenario(Path(tmp), problem)
                self.assertFalse(any('--verify-only' in c for c in calls))
                self.assertNotEqual(result['phase'], 'main_and_images_recreated')

    def test_plan_changes_prevent_success_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, result = self.scenario(Path(tmp), 'changes')
            self.assertEqual(result['phase'], 'restoring_images')


class ExecutionTests(unittest.TestCase):
    def scenario(self, root, problem=None):
        # Match main(): macOS temporary paths may resolve from /var to /private/var.
        root = root.resolve()
        private = root / '.secrets'; private.mkdir()
        session = private / 'recreate-fixture'; session.mkdir()
        binary = session / 'destroy.tfplan'; binary.write_bytes(b'fixture-plan')
        images = [{'id': 'crpfixtureimage000001', 'name': OLD + '/diploma-app',
                   'digest': 'sha256:' + '1' * 64, 'tags': ['v1.0.1']},
                  {'id': 'crpfixtureimage000002', 'name': OLD + '/diploma-app',
                   'digest': 'sha256:' + '2' * 64}]
        backup = {'registry_id': OLD, 'images': images}
        review = {'format': 'diploma-recreate-main-v1', 'root': str(root), 'phase': 'prepared',
                  'created_at': cycle.now().isoformat(), 'session': str(session),
                  'backup_directory': str(private / 'backup'), 'registry_id': OLD, 'images': images,
                  'resource_ids': cycle.validate_plan(plan('delete'), 'delete', OLD),
                  'github': GITHUB, 'source_hash': 'source', 'state_hash': 'state',
                  'destroy_plan_sha256': cycle.digest(binary.read_bytes())}
        if problem == 'expired': review['created_at'] = (cycle.now() - timedelta(hours=5)).isoformat()
        if problem == 'reused': review['phase'] = 'destroying_main'
        cycle.save(session / 'cycle-review.json', review)
        cycle.save(private / 'recreate-cycle-latest.json', {'review': str(session / 'cycle-review.json')})
        actual = copy.deepcopy(images)
        if problem == 'changed_image': actual[0]['tags'] = ['unrelated-tag']
        if problem == 'plan_tampering': binary.write_bytes(b'changed')
        calls = []

        def inventory(registry, env): return copy.deepcopy(actual)

        def run(args, env, log=None, timeout=180):
            calls.append(args)
            if args[:4] == ['yc', 'container', 'image', 'delete']:
                if problem == 'delete_failure': raise ValueError('simulated deletion error')
                actual[:] = [x for x in actual if x['id'] != args[-1]]
                return b''
            if args[0] == 'python3':
                cycle.save(private / 'registry-restore-latest.json', {'verified': True, 'target_registry': NEW})
                return b'Restore passed: fixture\n'
            raise AssertionError(args)

        def tf(root, env, directory, *args, **kwargs):
            calls.append(['terraform', directory, *args])
            if args[:2] == ('show', '-json'):
                value = plan('delete' if args[-1].endswith('destroy.tfplan') else 'create')
                if problem == 'bad_create' and args[-1].endswith('create.tfplan'):
                    value['resource_changes'][0]['change']['actions'] = ['update']
                return json.dumps(value).encode()
            if args[:2] == ('state', 'pull'):
                return json.dumps({'resources': [{'mode': 'managed'}] if problem == 'not_empty' else []}).encode()
            if args[0] == 'plan':
                for arg in args:
                    if arg.startswith('-out='): Path(arg.split('=', 1)[1]).write_bytes(b'fixture-create')
                return b''
            if args[0] == 'apply': return b''
            if args[:2] == ('output', '-raw'):
                return {'registry_id': NEW, 'control_plane_ip': '192.0.2.1', 'web_ip': '192.0.2.2'}[args[-1]].encode()
            raise AssertionError(args)

        with patch.object(cycle, 'load_backup', return_value=(private / 'backup', backup)), \
             patch.object(cycle, 'source_hash', return_value='changed' if problem == 'source' else 'source'), \
             patch.object(cycle, 'state_hash', return_value='changed' if problem == 'state' else 'state'), \
             patch.object(cycle, 'github_snapshot', return_value=GITHUB), \
             patch.object(cycle, 'autostart_off', side_effect=ValueError('enabled') if problem == 'autostart' else None), \
             patch.object(cycle, 'image_inventory', side_effect=inventory), \
             patch.object(cycle, 'run', side_effect=run), patch.object(cycle, 'tf', side_effect=tf), \
             redirect_stdout(io.StringIO()):
            if problem:
                with self.assertRaises(ValueError): cycle.execute(root, {})
            else:
                cycle.execute(root, {})
                self.assertEqual(json.loads((session / 'cycle-review.json').read_text())['phase'],
                                 'main_and_images_recreated')
        return calls, json.loads((session / 'cycle-review.json').read_text())

    def test_full_cycle_order_and_untagged_image_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls, review = self.scenario(Path(tmp))
            deletes = [i for i, c in enumerate(calls) if c[:4] == ['yc', 'container', 'image', 'delete']]
            applies = [i for i, c in enumerate(calls) if c[:3] == ['terraform', 'main', 'apply']]
            self.assertEqual(len(deletes), 2)
            self.assertEqual(len(applies), 2)
            self.assertLess(max(deletes), min(applies))
            self.assertTrue(any(c[:3] == ['terraform', 'main', 'plan'] and '-detailed-exitcode' in c for c in calls))
            self.assertFalse(any(c[:2] == ['terraform', 'bootstrap'] for c in calls))
            self.assertEqual(review['new_registry_id'], NEW)

    def test_execute_accepts_temporary_root_through_directory_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); real = base / 'real'; real.mkdir()
            alias = base / 'alias'; alias.symlink_to(real, target_is_directory=True)
            _, review = self.scenario(alias)
            self.assertEqual(review['phase'], 'main_and_images_recreated')

    def test_changed_inputs_expiry_autostart_or_used_review_stop_before_deletion(self):
        for problem in ('source', 'state', 'changed_image', 'plan_tampering', 'expired', 'reused', 'autostart'):
            with self.subTest(problem=problem), tempfile.TemporaryDirectory() as tmp:
                calls, _ = self.scenario(Path(tmp), problem)
                self.assertFalse(any('delete' in c or 'apply' in c for c in calls))

    def test_failed_image_delete_never_starts_terraform_destroy(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls, review = self.scenario(Path(tmp), 'delete_failure')
            self.assertFalse(any('apply' in c for c in calls))
            self.assertEqual(review['phase'], 'cleaning_registry')

    def test_nonempty_state_blocks_new_plan_and_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls, review = self.scenario(Path(tmp), 'not_empty')
            self.assertEqual(sum(c[:3] == ['terraform', 'main', 'apply'] for c in calls), 1)
            self.assertFalse(any(c[:3] == ['terraform', 'main', 'plan'] for c in calls))
            self.assertEqual(review['phase'], 'destroying_main')

    def test_unexpected_creation_plan_blocks_create_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls, review = self.scenario(Path(tmp), 'bad_create')
            self.assertEqual(sum(c[:3] == ['terraform', 'main', 'apply'] for c in calls), 1)
            self.assertEqual(review['phase'], 'planning_create')

    def test_readonly_preparation_cannot_delete_or_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); private = root / '.secrets'; private.mkdir()
            session = private / 'recreate-fixture'; session.mkdir()
            (session / 'destroy.tfplan').write_bytes(b'fixture')
            cycle.save(private / 'recreate-latest.json', {'backup_directory': str(session)})
            images = [{'id': 'crpfixtureimage000001', 'name': OLD + '/diploma-app',
                       'digest': 'sha256:' + '1' * 64}]
            calls = []
            def run(args, env, **kwargs):
                calls.append(args)
                return json.dumps({'folder_id': cycle.FOLDER}).encode() if args[0] == 'yc' else b'prepared'
            def tf(root, env, directory, *args):
                calls.append(['terraform', directory, *args])
                return OLD.encode() if args[0] == 'output' else json.dumps(plan('delete')).encode()
            with patch.object(cycle, 'autostart_off'), patch.object(cycle, 'github_snapshot', return_value=GITHUB), \
                 patch.object(cycle, 'load_backup', return_value=(private / 'backup', {'images': images, 'registry_id': OLD})), \
                 patch.object(cycle, 'image_inventory', return_value=images), patch.object(cycle, 'source_hash', return_value='source'), \
                 patch.object(cycle, 'state_hash', return_value='state'), patch.object(cycle, 'run', side_effect=run), \
                 patch.object(cycle, 'tf', side_effect=tf), redirect_stdout(io.StringIO()):
                cycle.prepare(root, {})
            self.assertFalse(any('delete' in c or 'apply' in c for c in calls))
            self.assertEqual(json.loads((session / 'cycle-review.json').read_text())['phase'], 'prepared')


if __name__ == '__main__': unittest.main()
