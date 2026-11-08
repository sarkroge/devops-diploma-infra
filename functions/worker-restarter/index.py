"""Start only the two stopped, labelled preemptible diploma workers."""
from datetime import datetime, timezone
import json
import os
import urllib.error
import urllib.parse
import urllib.request

API = 'https://compute.api.cloud.yandex.net/compute/v1/instances'
WORKERS = frozenset(('diploma-worker-1', 'diploma-worker-2'))


class APIError(Exception):
    def __init__(self, status):
        self.status = status
        super().__init__(f'Compute API HTTP {status}')


def request(token, method, url):
    data = b'{}' if method == 'POST' else None
    call = urllib.request.Request(url, data=data, method=method, headers={
        'Authorization': f'Bearer {token}', 'Content-Type': 'application/json',
    })
    try:
        with urllib.request.urlopen(call, timeout=8) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        # Never include request headers, IAM token or raw API response in logs.
        raise APIError(error.code) from None


def list_instances(token, folder):
    instances = []
    page = ''
    for _ in range(10):
        query = {'folderId': folder, 'pageSize': '100'}
        if page:
            query['pageToken'] = page
        result = request(token, 'GET', API + '?' + urllib.parse.urlencode(query))
        instances.extend(result.get('instances', []))
        page = result.get('nextPageToken', '')
        if not page:
            return instances
    raise RuntimeError('Instance listing exceeded the diploma folder page limit')


def eligible(vm, folder, project):
    labels = vm.get('labels', {})
    return (
        vm.get('name') in WORKERS
        and vm.get('folderId') == folder
        and labels.get('project') == project
        and labels.get('role') == 'worker'
        and vm.get('schedulingPolicy', {}).get('preemptible') is True
    )


def utc_now():
    return datetime.now(timezone.utc)


def handler(event, context):
    if os.environ.get('ENABLED') != 'true':
        return {'status': 'disabled', 'workers': []}
    deadline = datetime.fromisoformat(os.environ['AUTOSTART_UNTIL'].replace('Z', '+00:00'))
    if deadline.tzinfo is None:
        raise ValueError('AUTOSTART_UNTIL must have a timezone')
    if utc_now() >= deadline:
        return {'status': 'expired', 'workers': []}

    token = context.token['access_token']
    folder = os.environ['FOLDER_ID']
    project = os.environ['PROJECT_LABEL']
    dry_run = isinstance(event, dict) and event.get('dry_run') is True
    candidates = [vm for vm in list_instances(token, folder) if eligible(vm, folder, project)]
    names = [vm['name'] for vm in candidates]
    if len(names) != len(set(names)):
        raise RuntimeError('Duplicate worker names: refusing ambiguous VM selection')

    results = []
    failed = False
    for vm in sorted(candidates, key=lambda item: item['name']):
        item = {'name': vm['name'], 'id': vm['id']}
        try:
            # Re-read before start; a previous invocation may already be starting it.
            current = request(token, 'GET', API + '/' + urllib.parse.quote(vm['id'], safe=''))
            item['status'] = current.get('status', 'UNKNOWN')
            if not eligible(current, folder, project):
                item['action'] = 'skipped_changed_identity'
            elif current.get('status') != 'STOPPED':
                item['action'] = 'no_action'
            elif utc_now() >= deadline:
                item['action'] = 'skipped_expired'
            elif dry_run:
                item['action'] = 'would_start'
            else:
                operation = request(token, 'POST', API + '/' + urllib.parse.quote(vm['id'], safe='') + ':start')
                item.update(action='start_requested', operation_id=operation.get('id'))
        except APIError as error:
            item.update(action='retry_next_tick' if error.status == 409 else 'failed', http_status=error.status)
            failed = failed or error.status != 409
        except (OSError, ValueError, KeyError):
            item['action'] = 'failed_request'
            failed = True
        results.append(item)

    result = {
        'status': 'error' if failed else 'ok', 'dry_run': dry_run,
        'workers': results, 'missing': sorted(WORKERS - set(names)),
    }
    # Running workers are deliberately quiet to reduce log volume.
    if dry_run or result['missing'] or any(item['action'] != 'no_action' for item in results):
        print(json.dumps(result, sort_keys=True))
    if failed:
        raise RuntimeError('Some worker requests failed; inspect the structured log and next timer tick')
    return result
