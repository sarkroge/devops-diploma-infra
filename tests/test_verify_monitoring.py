import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('verify_monitoring', ROOT / 'scripts/verify-monitoring.py')
monitoring = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(monitoring)


def response(health='up'):
    return {'data': {'activeTargets': [{
        'health': health,
        'labels': {'job': 'monitoring-grafana', 'instance': '10.244.2.46:3000'},
        'lastError': '' if health == 'up' else 'connect: connection refused',
    }]}}


class MonitoringTargetsTests(unittest.TestCase):
    def setUp(self):
        self.forward = SimpleNamespace(poll=Mock(return_value=None))

    def test_healthy_targets_need_no_retry(self):
        request = Mock(return_value=response())
        with patch.object(monitoring.time, 'sleep') as sleep:
            targets = monitoring.wait_for_targets(request, self.forward)
        self.assertEqual(targets[0]['health'], 'up')
        sleep.assert_not_called()
        request.assert_called_once()

    def test_grafana_recovers_after_an_initial_refused_connection(self):
        request = Mock(side_effect=[response('down'), response()])
        with patch.object(monitoring.time, 'monotonic', side_effect=[0, 1]), \
                patch.object(monitoring.time, 'sleep') as sleep:
            targets = monitoring.wait_for_targets(request, self.forward)
        self.assertEqual(targets[0]['health'], 'up')
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(5)

    def test_persistent_failure_keeps_the_last_target_error(self):
        request = Mock(return_value=response('down'))
        with patch.object(monitoring.time, 'monotonic', side_effect=[0, 120]), \
                patch.object(monitoring.time, 'sleep') as sleep:
            targets = monitoring.wait_for_targets(request, self.forward)
        self.assertEqual(targets[0]['health'], 'down')
        self.assertIn('connection refused', targets[0]['lastError'])
        sleep.assert_not_called()

    def test_empty_target_list_is_not_reported_as_success(self):
        request = Mock(return_value={'data': {'activeTargets': []}})
        with patch.object(monitoring.time, 'monotonic', side_effect=[0, 120]):
            with self.assertRaisesRegex(SystemExit, 'no active scrape targets'):
                monitoring.wait_for_targets(request, self.forward)

    def test_temporary_prometheus_api_error_can_recover(self):
        request = Mock(side_effect=[OSError('connection reset'), response()])
        with patch.object(monitoring.time, 'monotonic', side_effect=[0, 1]), \
                patch.object(monitoring.time, 'sleep'):
            targets = monitoring.wait_for_targets(request, self.forward)
        self.assertEqual(targets[0]['health'], 'up')

    def test_stopped_port_forward_fails_without_waiting(self):
        self.forward.poll.return_value = 1
        request = Mock()
        with self.assertRaisesRegex(SystemExit, 'Port-forward stopped'):
            monitoring.wait_for_targets(request, self.forward)
        request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
