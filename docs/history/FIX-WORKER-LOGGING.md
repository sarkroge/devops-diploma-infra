# Автозапуск без Cloud Logging

При создании yandex_logging_group и отдельном yc logging group list API
вернул Unavailable. Это не подтверждает причину сбоя сервиса, но показывает,
что ошибка воспроизводится вне Terraform. Для автозапуска Cloud Logging
не требуется: у версии функции устанавливается log_options.disabled=true.

Исправление удаляет группу логов и роль logging.writer из конфигурации.
Функция сохраняет compute.operator, ограничение двух workers, срок until,
режим dry-run и приватное разрешение вызова для аккаунта таймера.
Логи выполнения не сохраняются. Результат ручного вызова возвращается напрямую.
Код Python и ZIP функции не меняются.

## Установка поверх уже применённого шага 11

```bash
unzip -o ~/Downloads/devops-diploma-worker-logging-fix.zip -d ~/netology
cd ~/netology/devops-diploma-infra

git apply --check patches/worker-no-logging.patch &&
git apply patches/worker-no-logging.patch
```

Patch меняет worker-availability.tf, STEP-11.md и раздел README об автозапуске.
Старый worker-availability.patch второй раз применять не нужно. Если git apply
сообщает ошибку, не продолжайте к plan: пришлите вывод для сверки версий файлов.
Не распаковывайте старый step11.zip повторно поверх исправленной конфигурации.

Сохранённое окно доступности остаётся прежним: команда on не требуется.
Подготовьте новый план — старый план создан до частичного apply и исправления:

```bash
umask 077
export TF_VAR_cloud_id="$(yc config get cloud-id)"
export TF_VAR_folder_id="$(yc config get folder-id)"
unset YC_SERVICE_ACCOUNT_KEY_FILE
export YC_TOKEN="$(yc iam create-token)"

terraform -chdir=terraform/bootstrap fmt -check &&
terraform -chdir=terraform/bootstrap validate &&
terraform -chdir=terraform/bootstrap plan -out=../../.secrets/availability.tfplan
```

По показанному частичному apply ожидается **3 to add, 0 to change, 1 to destroy**:

- Создание yandex_function.worker_restarter.
- Создание yandex_function_iam_binding.worker_restarter_invoker.
- Создание yandex_function_trigger.worker_restarter[0].
- Удаление yandex_resourcemanager_folder_iam_member.worker_restarter_logs:
  отзывается только logging.writer, сам сервисный аккаунт остаётся.

ВМ, диски, сеть, реестр и бакет не должны заменяться или удаляться.
Если план отличается, прежде чем применять, разберите адреса и действия.
Если группа логов всё же появилась в state, новая ошибка её чтения потребует
отдельной сверки; не удаляйте state и не выполняйте state rm наугад.

После проверки нового плана:

```bash
terraform -chdir=terraform/bootstrap apply ../../.secrets/availability.tfplan &&
terraform -chdir=terraform/bootstrap output worker_availability
```

Ожидаются enabled=true, прежний until, logging_enabled=false,
log_group_id=null и заполненные function_id/trigger_id.

## Проверка без остановки ВМ

```bash
DIPLOMA_FUNCTION_ID="$(terraform -chdir=terraform/bootstrap output -json worker_availability | python3 -c 'import json,sys; print(json.load(sys.stdin)["function_id"])')" &&
yc serverless function invoke "$DIPLOMA_FUNCTION_ID" \
  --data-file functions/worker-restarter/dry-run.json
```

Оба RUNNING-worker должны присутствовать с action=no_action, missing=[];
для STOPPED в dry-run возвращается would_start без реального запуска.
Сначала проверьте успешный dry-run, затем таймер и автоматический старт
worker-1 по обновлённому STEP-11.md. Наличие функции и таймера само по себе
не подтверждает автоматический старт. Пока тест не выполнен, не заявляйте
автовосстановление проверенным.

Не вызывайте yc logging group list или function logs для этой проверки:
обходной вариант работает без сохранённых логов. Не останавливайте worker-2
с локальными томами мониторинга ради проверки таймера.

После успешной проверки добавьте FIX-WORKER-LOGGING.md и новый patch в Git
вместе с файлами шага 11, как описано в обновлённом STEP-11.md.

Источник: https://yandex.cloud/ru/docs/functions/operations/function/logs-write
