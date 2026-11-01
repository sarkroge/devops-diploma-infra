#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_root"

kubectl --context=diploma get --raw=/readyz >/dev/null
web_ip="$(terraform -chdir=terraform/main output -raw web_ip)"

helm repo add traefik https://traefik.github.io/charts --force-update
helm repo update traefik
helm upgrade --install traefik traefik/traefik \
  --version 42.2.0 \
  --kube-context diploma \
  --namespace ingress-system --create-namespace \
  --skip-crds \
  --values kubernetes/ingress/traefik-values.yaml \
  --set-string "providers.kubernetesIngress.ingressEndpoint.ip=$web_ip" \
  --wait --timeout 10m

kubectl --context=diploma -n ingress-system rollout status daemonset/traefik --timeout=300s
kubectl --context=diploma -n ingress-system get pods -o wide
printf 'HTTP entry point: http://%s/\n' "$web_ip"
