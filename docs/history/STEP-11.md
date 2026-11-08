# Шаг 11. Автозапуск workers на время проверки

Стенд остаётся на прерываемых workers, как требует задание. Cloud Function
проверяет их каждые две минуты и отправляет start только для STOPPED-машин.
Это восстановление после остановки, а не гарантия непрерывной доступности.
При отсутствии свободных ресурсов запуск может задержаться; после старта
требуется время на загрузку ОС и восстановление Kubernetes.

Перед продолжением после ошибки Cloud Logging примените исправление из
[FIX-WORKER-LOGGING.md](FIX-WORKER-LOGGING.md). Старый архив шага 11 содержит
первоначальную конфигурацию; установку исправления выполняют после его распаковки.

## Что добавлено

В `terraform/bootstrap/worker-availability.tf`:

- Runtime ServiceAccount: compute.operator на каталог.
- Отдельный аккаунт таймера с правом вызова только новой функции.
- Приватная функция Python 3.12, 128 МБ RAM, таймаут 60 секунд.
- Cloud Logging отключён через log_options.disabled=true; группа логов не требуется.
- Таймер каждые две минуты, создаётся при включении.

При первом включении ожидается **6 to add, 0 to change, 0 to destroy**.
Существующие ВМ, сеть, state-бакет и реестр этот шаг не изменяет.
Права аккаунта diploma-terraform не расширяются. Bootstrap выполняется от
пользователя, как при первоначальном создании IAM и бакета.

Код ограничивает запуск двумя именами — diploma-worker-1 и diploma-worker-2 —
с метками project=devops-diploma, role=worker и preemptible=true. IAM-роль
compute.operator действует на весь каталог и также разрешает stop/restart;
ограничение выбора именно этих двух workers реализовано кодом. Control plane
отфильтровывается. Отдельные ключи для новых аккаунтов не создаются: функция
получает краткоживущий IAM-токен через context.token.

Функция ищет ВМ по именам и меткам, а не по сохранённым ID. После пересоздания
основной инфраструктуры новые ID будут обнаружены автоматически. Во время
намеренного destroy автозапуск следует отключать.

## 1. Установить файлы и включить окно на 72 часа

```bash
unzip -o ~/Downloads/devops-diploma-infra-step11.zip -d ~/netology
cd ~/netology/devops-diploma-infra

git pull --ff-only &&
git apply --check patches/worker-availability.patch &&
git apply patches/worker-availability.patch
```

Patch меняет только README, добавляет проверки Python в CI и делает nodes.sh
идемпотентным с проверкой активного автозапуска перед stop. При ошибке patch
остановитесь и пришлите текст; новые файлы остаются отдельно добавленными.

```bash
python3 scripts/build-worker-restarter.py --check
python3 -m unittest discover -s tests -p test_worker_restarter.py -v
python3 scripts/configure-availability.py on --hours 72
```

Последняя команда только записывает локальный gitignored файл
terraform/bootstrap/availability.auto.tfvars.json. Она не применяет Terraform.
Срок вычисляется на Mac и печатается в UTC. Можно указать 1–168 часов.

## 2. Подготовить план bootstrap

Убедитесь, что Terraform CI завершён. Из корня infra:

```bash
umask 077
export TF_VAR_cloud_id="$(yc config get cloud-id)"
export TF_VAR_folder_id="$(yc config get folder-id)"
unset YC_SERVICE_ACCOUNT_KEY_FILE
export YC_TOKEN="$(yc iam create-token)"
mkdir -p .secrets

terraform -chdir=terraform/bootstrap init -lockfile=readonly
terraform -chdir=terraform/bootstrap fmt -check
terraform -chdir=terraform/bootstrap validate
terraform -chdir=terraform/bootstrap plan -out=../../.secrets/availability.tfplan
```

При установке с нуля ожидаются 6 новых ресурсов. После частичного apply старой
версии ожидаются 3 to add, 0 to change, 1 to destroy: удаляется только выдача
logging.writer для worker_restarter_logs. ВМ и сервисные аккаунты не удаляются.
Если план отличается, сначала разберите его. Сохраните окончание плана для проверки.

## 3. Применить сохранённый план и проверить без остановки ВМ

После проверки плана:

```bash
terraform -chdir=terraform/bootstrap apply ../../.secrets/availability.tfplan
terraform -chdir=terraform/bootstrap output worker_availability
```

Outputs не содержат токенов или приватных ключей. Для отчёта сохраните apply
и worker_availability с enabled=true и сроком until.

Вызов функции в режиме dry-run:

```bash
yc serverless function invoke \
  "$(terraform -chdir=terraform/bootstrap output -json worker_availability | python3 -c 'import json,sys; print(json.load(sys.stdin)["function_id"])')" \
  --data-file functions/worker-restarter/dry-run.json
```

Ожидаются оба worker и action=no_action для RUNNING. Для STOPPED в dry-run будет
would_start: этот вызов ничего не запускает. Если missing непустой, проверяйте
имена/метки, а не останавливайте ВМ для теста. Ошибка доступа после apply может
означать задержку распространения IAM; при повторяющейся ошибке пришлите её текст.

Посмотреть таймер:

```bash
yc serverless trigger get \
  "$(terraform -chdir=terraform/bootstrap output -json worker_availability | python3 -c 'import json,sys; print(json.load(sys.stdin)["trigger_id"])')"
```

Первичная активация нового триггера может занять несколько минут. Cloud Logging
отключён: накопленных логов функции нет. Dry-run возвращает результат напрямую.
Работу таймера проверяем следующим тестом автоматического старта ВМ.

## 4. Проверить автоматический запуск одной ВМ

Сначала дождитесь работы таймера и успешного dry-run для обоих workers.
Тест намеренно остановит worker-1, поэтому HTTP через его IP временно прервётся.
Worker-2 с локальными PV мониторинга в тесте не останавливается.

```bash
yc compute instance stop --name diploma-worker-1 --folder-id "$TF_VAR_folder_id"
yc compute instance list --folder-id "$TF_VAR_folder_id"
```

Сохраните STOPPED. Затем через несколько минут повторите только list:

```bash
yc compute instance list --folder-id "$TF_VAR_folder_id"
```

Не запускайте ВМ или функцию вручную во время этого теста. Дождитесь RUNNING;
сохраните вывод STOPPED и последующий RUNNING с временем проверки. Это проверка
восстановления через таймер при отсутствии других механизмов запуска.
Если за 5–10 минут запуска нет, проверьте активность таймера и выполните только
dry-run: он покажет доступность Compute API и выбор workers. Сам dry-run не
доказывает вызов по расписанию. При нехватке ресурсов возможны задержки.
Для восстановления доступа после неуспешного теста worker-1 можно запустить
вручную, отметив, что тест таймера не пройден.

После RUNNING:

```bash
kubectl --context=diploma wait node/k8s-worker-1 --for=condition=Ready --timeout=300s
kubectl --context=diploma -n diploma rollout status deployment/diploma-app --timeout=300s
kubectl --context=diploma -n ingress-system rollout status daemonset/traefik --timeout=300s
python3 scripts/verify-monitoring.py
curl -fsS --max-time 20 http://153.51.118.243/healthz
curl -fsS --max-time 20 http://153.51.118.243/version.json
```

По окончании bootstrap-команд верните окружение основного Terraform:

```bash
unset YC_TOKEN
export YC_SERVICE_ACCOUNT_KEY_FILE="$PWD/.secrets/terraform-key.json"
```

## 5. Сохранить в Git

После успешной проверки:

```bash
git add README.md STEP-11.md RECREATE-PREFLIGHT.md \
  terraform/bootstrap/worker-availability.tf functions/worker-restarter \
  scripts/build-worker-restarter.py scripts/configure-availability.py \
  scripts/prepare-recreate.py scripts/nodes.sh tests/test_worker_restarter.py \
  .github/workflows/terraform.yml patches/worker-availability.patch \
  patches/worker-no-logging.patch FIX-WORKER-LOGGING.md &&
python3 scripts/check-git-files.py &&
git commit -m "Recover stopped preemptible workers during review window" &&
git push origin main
```

function.zip намеренно сохраняется в Git. Он не содержит ключей и состоит
только из index.py. Дополнительный Terraform provider archive не требуется;
CI проверяет совпадение ZIP с исходником и запускает тесты.
Локальный срок включения хранится в gitignored auto.tfvars, bootstrap CI не применяет.

## Продлить или полностью отключить

Продлить на следующие 72 часа: выполните on заново и plan/apply bootstrap
с пользовательским IAM-токеном. Новый срок берётся от времени этой команды.

Для отключения перед экономией/пересозданием:

```bash
python3 scripts/configure-availability.py off
unset YC_SERVICE_ACCOUNT_KEY_FILE
export YC_TOKEN="$(yc iam create-token)"
terraform -chdir=terraform/bootstrap plan
terraform -chdir=terraform/bootstrap apply
unset YC_TOKEN
export YC_SERVICE_ACCOUNT_KEY_FILE="$PWD/.secrets/terraform-key.json"
```

Ожидаются обновление версии функции (ENABLED=false) и удаление только таймера.
После этого workers можно останавливать через bash scripts/nodes.sh stop.
Не запускайте terraform destroy для всего bootstrap: там находится защищённый
бакет state и необходимые сервисные аккаунты.

По истечении until функция перестаёт отправлять start, но таймер продолжает
вызывать её до отключения. Уже запущенные ВМ по сроку функция не останавливает.
Вызовы функции и работающие ВМ тарифицируются по условиям провайдера;
точная стоимость этим решением не ограничивается.

## Далее: destroy/apply

В [RECREATE-PREFLIGHT.md](RECREATE-PREFLIGHT.md) подготовлена отдельная проверка:
защищённые копии state/ключей, список образов и план удаления основной конфигурации.
Она не удаляет ресурсы. Сам цикл destroy/apply остаётся неподтверждённым до
фактического выполнения и полного восстановления стенда.

## Проверки подготовки и источники

Локально: 10 тестов отбора workers/ограничения срока/dry-run/ошибок API,
Terraform fmt и HCL parsing, синтаксис оболочки, совпадение ZIP с исходником.
Полный Terraform validate выполняется на Mac: в среде подготовки плагин Terraform
не может открыть Unix socket. Облачные права и реальный таймер проверяются после apply.

- https://yandex.cloud/ru/docs/compute/concepts/preemptible-vm
- https://yandex.cloud/ru/docs/compute/security/
- https://yandex.cloud/ru/docs/functions/lang/python/context
- https://yandex.cloud/ru/docs/functions/security/
- https://yandex.cloud/ru/docs/functions/operations/trigger/timer-create
- https://github.com/yandex-cloud/terraform-provider-yandex/tree/v0.243.0/docs/resources

- https://yandex.cloud/ru/docs/functions/operations/function/logs-write
