#!/usr/bin/env python3
"""Verify cluster/application metrics through a temporary local port-forward."""
import json
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def wait_for_targets(request, forward, timeout=120, interval=5):
    """Wait for scrape targets to recover, keeping the final error details."""
    deadline = time.monotonic() + timeout
    targets = []
    last_error = None
    while True:
        if forward.poll() is not None:
            raise SystemExit('Port-forward stopped while waiting for scrape targets.')
        try:
            targets = request('/api/v1/targets')['data']['activeTargets']
            last_error = None
            if targets and all(target.get('health') == 'up' for target in targets):
                return targets
        except (OSError, ValueError, KeyError) as error:
            last_error = str(error)
            targets = []
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(interval, remaining))
    if last_error is not None:
        raise SystemExit(f'Cannot read scrape targets: {last_error}')
    if not targets:
        raise SystemExit('Prometheus returned no active scrape targets.')
    return targets


def main():
    root = Path(__file__).resolve().parent.parent
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    log_path = root / '.secrets/monitoring-port-forward.log'
    with log_path.open('w') as log:
        forward = subprocess.Popen([
            'kubectl', '--context=diploma', '-n', 'monitoring', 'port-forward',
            'service/monitoring-prometheus', f'{port}:9090', '--address=127.0.0.1',
        ], stdout=log, stderr=log)
        try:
            def request(path):
                with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=5) as response:
                    return json.load(response)

            queries = {
                'Ready nodes': ('sum(kube_node_status_condition{condition="Ready",status="true"})', 3),
                'Node exporters': ('count(node_uname_info)', 3),
                'Available application replicas': (
                    'sum(kube_deployment_status_replicas_available{namespace="diploma",deployment="diploma-app"})', 2),
            }
            deadline = time.monotonic() + 120
            values = {}
            while time.monotonic() < deadline:
                if forward.poll() is not None:
                    raise SystemExit(f'Port-forward stopped; inspect {log_path}')
                try:
                    for name, (query, expected) in queries.items():
                        data = request('/api/v1/query?' + urllib.parse.urlencode({'query': query}))
                        samples = data.get('data', {}).get('result', [])
                        values[name] = float(samples[0]['value'][1]) if samples else None
                    if all(values.get(name) == expected for name, (_, expected) in queries.items()):
                        break
                except (OSError, urllib.error.URLError, ValueError, KeyError):
                    pass
                time.sleep(5)
            else:
                raise SystemExit(f'Metrics have not reached the expected values: {values}. Retry after checking pod status.')
            for name, value in values.items():
                print(f'{name}: {value:g}')
            targets = wait_for_targets(request, forward)
            down = [target for target in targets if target.get('health') != 'up']
            print(f'Healthy scrape targets: {len(targets) - len(down)}/{len(targets)}')
            for target in down:
                labels = target.get('labels', {})
                print(f'Unhealthy: {labels.get("job")} {labels.get("instance")}: {target.get("lastError")}')
            if down:
                raise SystemExit('Scrape targets are still unhealthy after waiting; inspect the errors above.')
            print('Monitoring verification passed.')
        finally:
            forward.terminate()
            try:
                forward.wait(timeout=5)
            except subprocess.TimeoutExpired:
                forward.kill()
                forward.wait()


if __name__ == '__main__':
    main()
