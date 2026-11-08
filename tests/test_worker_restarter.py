import copy
from datetime import datetime, timezone
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('worker_restarter', ROOT / 'functions/worker-restarter/index.py')
restarter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(restarter)


def worker(name='diploma-worker-1', status='STOPPED', identifier='worker-new-id'):
    return {
        'id': identifier, 'name': name, 'folderId': 'folder', 'status': status,
        'labels': {'project': 'devops-diploma', 'role': 'worker'},
        'schedulingPolicy': {'preemptible': True},
    }


class RestarterTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            'FOLDER_ID': 'folder', 'PROJECT_LABEL': 'devops-diploma',
            'ENABLED': 'true', 'AUTOSTART_UNTIL': '2026-11-05T00:00:00Z',
        }, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.clock = patch.object(restarter, 'utc_now', return_value=datetime(2026, 11, 2, tzinfo=timezone.utc))
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.context = SimpleNamespace(token={'access_token': 'fixture-token-never-print'})

    def test_disabled_or_expired_performs_no_api_requests(self):
        with patch.object(restarter, 'request') as api:
            os.environ['ENABLED'] = 'false'
            self.assertEqual(restarter.handler({}, self.context)['status'], 'disabled')
            os.environ['ENABLED'] = 'true'
            os.environ['AUTOSTART_UNTIL'] = '2026-11-01T00:00:00Z'
            self.assertEqual(restarter.handler({}, self.context)['status'], 'expired')
            api.assert_not_called()

    def test_only_stopped_worker_started_using_newly_discovered_id(self):
        first = worker()
        second = worker('diploma-worker-2', 'RUNNING', 'worker-two')
        with patch.object(restarter, 'request', side_effect=[{'instances': [first, second]}, first, {'id': 'operation'}, second]) as api:
            result = restarter.handler({}, self.context)
        posts = [call for call in api.call_args_list if call.args[1] == 'POST']
        self.assertEqual(len(posts), 1)
        self.assertTrue(posts[0].args[2].endswith('/worker-new-id:start'))
        self.assertEqual([item['action'] for item in result['workers']], ['start_requested', 'no_action'])

    def test_control_plane_other_projects_and_normal_vms_excluded(self):
        candidates = [worker('diploma-control-plane'), worker('some-other-vm')]
        for field, value in [('folderId', 'other-folder'), ('labels', {'project': 'other', 'role': 'worker'}),
                             ('labels', {'project': 'devops-diploma', 'role': 'control-plane'}),
                             ('schedulingPolicy', {'preemptible': False})]:
            vm = worker(); vm[field] = value; candidates.append(vm)
        with patch.object(restarter, 'request', return_value={'instances': candidates}) as api:
            result = restarter.handler({}, self.context)
        self.assertEqual(result['workers'], [])
        self.assertEqual(api.call_count, 1)

    def test_dry_run_never_starts_a_vm(self):
        vm = worker()
        with patch.object(restarter, 'request', side_effect=[{'instances': [vm]}, vm]) as api:
            result = restarter.handler({'dry_run': True}, self.context)
        self.assertEqual(result['workers'][0]['action'], 'would_start')
        self.assertTrue(all(call.args[1] == 'GET' for call in api.call_args_list))

    def test_identity_rechecked_before_start(self):
        vm = worker()
        changed = copy.deepcopy(vm); changed['labels']['project'] = 'different'
        with patch.object(restarter, 'request', side_effect=[{'instances': [vm]}, changed]) as api:
            result = restarter.handler({}, self.context)
        self.assertEqual(result['workers'][0]['action'], 'skipped_changed_identity')
        self.assertEqual(api.call_count, 2)

    def test_starting_worker_is_not_started_again(self):
        vm = worker()
        starting = dict(vm, status='STARTING')
        with patch.object(restarter, 'request', side_effect=[{'instances': [vm]}, starting]) as api:
            result = restarter.handler({}, self.context)
        self.assertEqual(result['workers'][0]['action'], 'no_action')
        self.assertEqual(api.call_count, 2)

    def test_pagination_discovers_worker_on_second_page(self):
        vm = worker()
        with patch.object(restarter, 'request', side_effect=[{'nextPageToken': 'page2'}, {'instances': [vm]}, vm, {'id': 'op'}]) as api:
            restarter.handler({}, self.context)
        self.assertIn('pageToken=page2', api.call_args_list[1].args[2])

    def test_duplicate_worker_name_is_rejected_without_starts(self):
        with patch.object(restarter, 'request', return_value={'instances': [worker(), worker(identifier='another-id')]}) as api:
            with self.assertRaisesRegex(RuntimeError, 'Duplicate'):
                restarter.handler({}, self.context)
        self.assertEqual(api.call_count, 1)

    def test_start_race_is_not_fatal(self):
        vm = worker()
        with patch.object(restarter, 'request', side_effect=[{'instances': [vm]}, vm, restarter.APIError(409)]):
            result = restarter.handler({}, self.context)
        self.assertEqual(result['workers'][0]['action'], 'retry_next_tick')

    def test_one_failed_worker_does_not_skip_the_other(self):
        one = worker(); two = worker('diploma-worker-2', identifier='two')
        with patch.object(restarter, 'request', side_effect=[{'instances': [one, two]}, one, restarter.APIError(403), two, {'id': 'op'}]) as api:
            with self.assertRaisesRegex(RuntimeError, 'Some worker requests failed'):
                restarter.handler({}, self.context)
        posts = [call for call in api.call_args_list if call.args[1] == 'POST']
        self.assertEqual(len(posts), 2)


if __name__ == '__main__':
    unittest.main()
