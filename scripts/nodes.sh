#!/usr/bin/env bash
# Start or stop diploma VMs only; does not destroy any resource.
set -euo pipefail
project_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
action="${1:-status}"

case "$action" in
  status)
    folder_id="${TF_VAR_folder_id:-$(yc config get folder-id)}"
    yc compute instance list --folder-id "$folder_id"
    exit 0
    ;;
  start|stop) ;;
  *) printf '%s\n' 'Usage: bash scripts/nodes.sh status|start|stop' >&2; exit 2 ;;
esac

if [[ "$action" == stop ]]; then
  if availability_info="$(terraform -chdir="$project_dir/terraform/bootstrap" output -json worker_availability 2>/dev/null)"; then
    printf '%s' "$availability_info" | python3 -c '
from datetime import datetime, timezone
import json, sys
settings = json.load(sys.stdin)
deadline = datetime.fromisoformat(settings["until"].replace("Z", "+00:00"))
if settings["enabled"] and datetime.now(timezone.utc) < deadline:
    raise SystemExit("Worker autostart is active. Disable it using docs/operations.md before stopping VMs.")
'
  fi
fi

node_data="$(terraform -chdir="$project_dir/terraform/main" output -json nodes)"
node_ids="$(printf '%s' "$node_data" | python3 -c '
import json, sys
nodes = json.load(sys.stdin)
action = sys.argv[1]
order = ["control-plane", "worker-1", "worker-2"]
if action == "stop":
    order.reverse()
for name in order:
    print(nodes[name]["id"])
' "$action")"

while IFS= read -r node_id; do
  status="$(yc compute instance get --id "$node_id" --format=json | python3 -c 'import json, sys; print(json.load(sys.stdin)["status"])')"
  if [[ "$action" == start && "$status" == RUNNING ]] || [[ "$action" == stop && "$status" == STOPPED ]]; then
    printf '%s\n' "$node_id: already $status"
    continue
  fi
  yc compute instance "$action" --id "$node_id"
done <<< "$node_ids"

printf '%s\n' "VM $action operations completed."
if [[ "$action" == start ]]; then
  printf '%s\n' 'worker-2 has a dynamic public IP. Refresh outputs before generating SSH/Ansible inventory:'
  printf '%s\n' 'terraform -chdir=terraform/main apply -refresh-only'
fi
