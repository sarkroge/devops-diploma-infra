# Эксплуатация стенда

Команды выполняются из корня infra. Для main нужны существующий ключ Terraform
и S3 credentials. Ключи заново при каждом запуске терминала не создаются.

## Окружение main

```bash
export TF_VAR_cloud_id="$(yc config get cloud-id)"
export TF_VAR_folder_id="$(yc config get folder-id)"
unset YC_TOKEN
export YC_SERVICE_ACCOUNT_KEY_FILE="$PWD/.secrets/terraform-key.json"
export AWS_ACCESS_KEY_ID="$(terraform -chdir=terraform/bootstrap output -raw state_access_key)"
export AWS_SECRET_ACCESS_KEY="$(terraform -chdir=terraform/bootstrap output -raw state_secret_key)"
export KUBECONFIG="$HOME/.kube/config"
```

## Состояние и восстановление

```bash
bash scripts/nodes.sh status
kubectl --context=diploma get nodes -o wide
kubectl --context=diploma get pods -A
```

Запуск всех трёх ВМ; уже работающие ВМ скрипт пропускает:

```bash
bash scripts/nodes.sh start
terraform -chdir=terraform/main apply -refresh-only
python3 scripts/make-inventory.py

kubectl --context=diploma wait node/k8s-worker-1 node/k8s-worker-2 \
  --for=condition=Ready --timeout=300s
kubectl --context=diploma -n diploma rollout status deployment/diploma-app --timeout=300s
kubectl --context=diploma -n ingress-system rollout status daemonset/traefik --timeout=300s
kubectl --context=diploma -n monitoring rollout status deployment/monitoring-grafana --timeout=300s
kubectl --context=diploma -n monitoring rollout status statefulset/prometheus-monitoring-prometheus --timeout=300s
python3 scripts/verify-monitoring.py
```

Worker 2 получает динамический публичный IP. Refresh обновляет outputs;
Kubernetes и SSH через control plane используют его постоянный внутренний адрес.
После остановки ВМ pod могут некоторое время показывать устаревшие Running,
а удаляемые pod — Terminating. Сначала проверяется состояние самих ВМ.

## Продлить автозапуск

```bash
terraform -chdir=terraform/bootstrap output worker_availability
```

Проверяется и `enabled`, и `until`. После указанного UTC-срока функция не
отправляет start, даже если таймер включён. Окно на следующие 72 часа:

```bash
python3 scripts/configure-availability.py on --hours 72
unset YC_SERVICE_ACCOUNT_KEY_FILE
export YC_TOKEN="$(yc iam create-token)"
terraform -chdir=terraform/bootstrap plan -out=../../.secrets/availability.tfplan
```

При продлении включённой функции ожидается обновление её версии с новым
`AUTOSTART_UNTIL`. После проверки плана:

```bash
terraform -chdir=terraform/bootstrap apply ../../.secrets/availability.tfplan
terraform -chdir=terraform/bootstrap output worker_availability
unset YC_TOKEN
export YC_SERVICE_ACCOUNT_KEY_FILE="$PWD/.secrets/terraform-key.json"
```

`--hours` принимает 1–168 часов. Локальный auto.tfvars с датой исключён из Git.
Функция выполняется в облаке: включённый Mac для таймера не требуется.
Она ищет только два preemptible-worker с именами и метками проекта, использует
краткоживущий IAM-токен. Runtime-аккаунт имеет compute.operator на каталог;
ограничение выбора двух ВМ реализовано в коде. Cloud Logging выключен.

Проверка функции без запуска ВМ:

```bash
DIPLOMA_FUNCTION_ID="$(terraform -chdir=terraform/bootstrap output -json worker_availability | python3 -c 'import json,sys; print(json.load(sys.stdin)["function_id"])')"
yc serverless function invoke "$DIPLOMA_FUNCTION_ID" \
  --data-file functions/worker-restarter/dry-run.json
```

Для RUNNING ожидается `no_action`, для STOPPED — `would_start`, `missing=[]`.
Dry-run проверяет выбор ВМ и доступ к API, а работу расписания подтверждает
отдельный тест: остановить worker 1, дождаться его запуска без ручного start
или вызова функции, затем проверить Kubernetes. HTTP временно прервётся.

## Остановить стенд

Сначала выключите таймер и примените изменение bootstrap:

```bash
python3 scripts/configure-availability.py off
unset YC_SERVICE_ACCOUNT_KEY_FILE
export YC_TOKEN="$(yc iam create-token)"
terraform -chdir=terraform/bootstrap plan -out=../../.secrets/availability.tfplan
```

Ожидаются обновление функции с `ENABLED=false` и удаление только таймера.
После проверки плана:

```bash
terraform -chdir=terraform/bootstrap apply ../../.secrets/availability.tfplan
unset YC_TOKEN
export YC_SERVICE_ACCOUNT_KEY_FILE="$PWD/.secrets/terraform-key.json"
bash scripts/nodes.sh stop
```

Остановка сохраняет диски и статические адреса; их хранение продолжает
тарифицироваться. По истечении срока функция сама ВМ не останавливает.
Перед намеренным destroy автозапуск также отключается. Подготовка полного
пересоздания — в [recreate.md](recreate.md).
