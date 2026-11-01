# Шаг 2: S3 backend, сеть и Container Registry

Этот архив дополняет существующий `devops-diploma-infra`. В нём нет файлов
`bootstrap`, `.git`, локального state или ключей. Распакуйте его в `~/netology`,
чтобы новая папка `terraform/main` появилась внутри существующего проекта.
Первый `bootstrap` уже должен быть применён и показывать `No changes`.

## Что создаёт основная конфигурация

- Одну сеть `diploma-network`.
- Три подсети в зонах `ru-central1-a`, `ru-central1-b`, `ru-central1-d`.
- Один реестр `diploma-registry` в Yandex Container Registry.

Ожидается пять новых ресурсов. ВМ, диски и балансировщики пока не создаются.
Тарифы хранения образов начнут иметь значение после загрузки образов; реестр
пока пустой. Весь этап выполняется в том же каталоге, что и bootstrap.

`bootstrap` хранит свой state локально. `terraform/main` использует отдельный
state в существующем бакете, ключ `diploma/main/terraform.tfstate`. Переносить
bootstrap state или запускать `init -migrate-state` не нужно.

## Авторизованный ключ и окружение

Выполняйте команды из корня проекта. Ключ сервисного аккаунта создаётся один раз
через учётную запись пользователя `yc`, как исходные credentials Terraform.
Создание этого авторизованного ключа — внешний подготовительный шаг, а не ресурс
основного state. Не повторяйте команду создания ключа без необходимости.

```bash
cd ~/netology/devops-diploma-infra
umask 077
mkdir -p .secrets
yc iam key create \
  --service-account-id "$(terraform -chdir=terraform/bootstrap output -raw terraform_service_account_id)" \
  --output .secrets/terraform-key.json
chmod 600 .secrets/terraform-key.json
git check-ignore .secrets/terraform-key.json
```

Последняя команда должна показать `.secrets/terraform-key.json`. Если команда
создания ключа завершилась с ошибкой, остановитесь до её устранения. Файл ключа
не отправляйте в переписку или Git.

Основному провайдеру нужен авторизованный JSON-ключ; S3 backend использует другую
пару credentials — статический ключ, созданный bootstrap:

```bash
export TF_VAR_cloud_id="$(yc config get cloud-id)"
export TF_VAR_folder_id="$(yc config get folder-id)"
export YC_SERVICE_ACCOUNT_KEY_FILE="$PWD/.secrets/terraform-key.json"
export AWS_ACCESS_KEY_ID="$(terraform -chdir=terraform/bootstrap output -raw state_access_key)"
export AWS_SECRET_ACCESS_KEY="$(terraform -chdir=terraform/bootstrap output -raw state_secret_key)"
export TF_STATE_BUCKET="$(terraform -chdir=terraform/bootstrap output -raw state_bucket_name)"
unset YC_TOKEN
```

Значения ключей считываются в переменные без вывода в терминал. Не запускайте
`env`, `set`, `export -p`, `set -x` или `terraform output -json` для отчётного
скриншота: они могут раскрыть credentials. Переменные действуют в текущем окне
терминала; при новом запуске повторите только блок экспорта, без создания ключа.

## Инициализация и план

```bash
terraform -chdir=terraform/main init -backend-config="bucket=$TF_STATE_BUCKET"
terraform -chdir=terraform/main fmt
terraform -chdir=terraform/main validate
terraform -chdir=terraform/main plan
```

Ожидаются сообщения об успешной настройке S3 backend и:

```text
Plan: 5 to add, 0 to change, 0 to destroy.
```

Провайдер закреплён на `0.243.0`, уже установленной на Mac для bootstrap.
Дополнительные checksum для Linux подготовим перед CI/CD. До этого предупреждение
о наличии checksum только для `darwin_arm64` не блокирует локальную работу.

Эта конфигурация пока не включает распределённую блокировку state. Выполняйте
операции Terraform последовательно из одного терминала. Перед запуском CI/CD
настроим сериализацию запусков и проверим выбранный механизм блокировки отдельно.
Не запускайте локальный apply одновременно с pipeline.

## Применение и доказательство хранения state

После проверки плана:

```bash
terraform -chdir=terraform/main apply
```

Проверьте план и подтвердите вводом `yes`. Затем:

```bash
terraform -chdir=terraform/main output
terraform -chdir=terraform/main plan
```

Ожидаются `Apply complete! Resources: 5 added...` и затем `No changes`.

Откройте Object Storage → бакет из bootstrap → `diploma/main/terraform.tfstate`.
Само содержимое state не публикуйте: для отчёта достаточно списка объектов с
видимым путём и успешного вывода Terraform. `init` на пустом backend ещё не
доказывает запись state; объект должен появиться после успешного `apply`.

Сохраните скриншоты:

1. Успешная настройка S3 backend при `init`.
2. Окончание `apply` и обычные Outputs.
3. Повторный `plan` с `No changes`.
4. Наличие объекта state в бакете, без его содержимого.

После переключения на сервисный аккаунт не запускайте `bootstrap plan/apply`
с его правами. Для изменения bootstrap верните пользовательский IAM-токен:

```bash
unset YC_SERVICE_ACCOUNT_KEY_FILE
export YC_TOKEN="$(yc iam create-token)"
```

Перед возвращением к `terraform/main` снова экспортируйте путь к ключу и уберите
`YC_TOKEN`. Основной state и bootstrap state остаются раздельными.

## Локальная проверка архива

Проверены синтаксис HCL и структура архива. Облачные `init`, `validate`, `plan`,
`apply`, полномочия аккаунта и доступ к бакету проверяются в окружении пользователя.
До успешного `apply` новые ресурсы не считаются созданными.

## Документация

- https://yandex.cloud/ru/docs/terraform/authentication
- https://yandex.cloud/ru/docs/terraform/tutorials/terraform-state-storage
- https://developer.hashicorp.com/terraform/language/backend/s3
- https://yandex.cloud/en/docs/overview/concepts/geo-scope
