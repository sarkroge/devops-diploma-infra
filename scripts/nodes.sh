#!/usr/bin/env bash
# Start or stop diploma VMs only; does not destroy any resource.
set -euo pipefail
project_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
action="${1:-status}"

case "$action" in
  status)
    yc compute instance list --folder-id "${TF_VAR_folder_id:?Set TF_VAR_folder_id first}"
    exit 0
    ;;
  start|stop) ;;
  *) printf '%s\n' 'Usage: bash scripts/nodes.sh status|start|stop' >&2; exit 2 ;;
esac

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
  yc compute instance "$action" --id "$node_id"
done <<< "$node_ids"

printf '%s\n' "VM $action operations completed."
if [[ "$action" == start ]]; then
  printf '%s\n' 'worker-2 has a dynamic public IP. Refresh outputs before generating SSH/Ansible inventory:'
  printf '%s\n' 'terraform -chdir=terraform/main apply -refresh-only'
fi
