# Шаг 5. Тестовое приложение и публикация образа

Кластер проверен 01.11.2026: три Ready-узла, Kubernetes 1.37.2, containerd 2.4.2,
системные pod Running без рестартов. Control plane и worker-2 находятся в зоне a,
worker-1 в зоне e. Внутренние адреса: 10.20.10.10, 10.20.40.10, 10.20.10.12.
Сохраните скриншоты PLAY RECAP, kubectl get nodes -o wide и kubectl get pods -A.

Архив этого шага содержит отдельную папку devops-diploma-app и два дополнения
к инфраструктурному проекту: terraform/bootstrap/app-ci.tf и эту инструкцию.

## 1. Создать сервисный аккаунт CI

Выполняйте из корня инфраструктурного проекта:

```bash
cd ~/netology/devops-diploma-infra
umask 077
export TF_VAR_cloud_id="$(yc config get cloud-id)"
export TF_VAR_folder_id="$(yc config get folder-id)"

unset YC_SERVICE_ACCOUNT_KEY_FILE
export YC_TOKEN="$(yc iam create-token)"

terraform -chdir=terraform/bootstrap fmt
terraform -chdir=terraform/bootstrap validate
terraform -chdir=terraform/bootstrap plan
```

Ожидается 2 to add, 0 to change, 0 to destroy:
сервисный аккаунт diploma-app-ci и его роль container-registry.images.pusher
на каталог. ВМ не меняются. Аккаунт может управлять образами и репозиториями,
но не имеет доступа к Terraform state и управлению ВМ.
Если изменения отличаются от ожидаемых, перед применением пришлите план.

```bash
terraform -chdir=terraform/bootstrap apply

yc iam key create \
  --service-account-id "$(terraform -chdir=terraform/bootstrap output -raw app_ci_service_account_id)" \
  --output .secrets/app-ci-key.json

unset YC_TOKEN
export YC_SERVICE_ACCOUNT_KEY_FILE="$PWD/.secrets/terraform-key.json"
```

Авторизованный ключ создаётся один раз на этом шаге. Файл содержит приватный
ключ, находится в gitignored .secrets и нужен для Repository secret.
Его содержимое не выводите на скриншоты и не добавляйте в Git.

## 2. Создать отдельный репозиторий приложения

На https://github.com/new создайте Public-репозиторий devops-diploma-app
под аккаунтом sarkroge. Оставьте его пустым: без README, .gitignore и лицензии.
Не выполняйте первый push до настройки variable и secret ниже.

Settings → Secrets and variables → Actions → Variables → New repository variable:

- Name: YC_REGISTRY_ID
- Value: crpi32ickihldl29g1fg

ID можно перепроверить из корня инфраструктурного проекта:

```bash
terraform -chdir=terraform/main output -raw registry_id
```

Затем скопируйте JSON ключа в буфер обмена Mac, не выводя его в терминал:

```bash
pbcopy < .secrets/app-ci-key.json
```

Settings → Secrets and variables → Actions → Secrets → New repository secret:

- Name: YC_SA_JSON_CREDENTIALS
- Secret: вставьте скопированный JSON целиком.

Этот аккаунт предназначен для публикации образов. Для скачивания образов
кластером на следующем шаге подготовим отдельный доступ только на чтение.

## 3. Отправить приложение в GitHub

Для новой распакованной папки приложения:

```bash
cd ~/netology/devops-diploma-app
git init -b main
git add Dockerfile nginx.conf html scripts .github .dockerignore .gitignore README.md
git commit -m "Add nginx application and image build pipeline"
git remote add origin https://github.com/sarkroge/devops-diploma-app.git
git push -u origin main
```

Для push используйте уже настроенную авторизацию GitHub. Если Git сообщает
об ошибке авторизации, пришлите текст ошибки без токенов.

## 4. Проверить CI и реестр

Откройте Actions → Build, test and publish и дождитесь завершения.
Сборка выполняется на GitHub runner ubuntu-24.04 для linux/amd64;
локальный Docker на Mac не требуется. Workflow проверяет nginx -t,
HTTP /healthz, главную страницу, JSON версии и HTTP 404.
В реестр отправляется тот же образ, который прошёл проверки.

При push в любую ветку публикуется тег sha-<полный SHA коммита>.
Для Git-тега дополнительно публикуется одноимённый тег образа.
При pull request выполняются сборка и тесты без публикации.
CD в этом шаге ещё нет: добавим его после Kubernetes-манифестов.

```bash
yc container image list --repository-name crpi32ickihldl29g1fg/diploma-app
```

Ожидаемый адрес:
cr.yandex/crpi32ickihldl29g1fg/diploma-app:sha-<SHA-коммита>

После успешной первой сборки можно проверить тег:

```bash
git tag v1.0.0
git push origin v1.0.0
```

После успешной сборки тега будет доступен образ
cr.yandex/crpi32ickihldl29g1fg/diploma-app:v1.0.0.
На этом этапе тег публикует образ; автоматический деплой добавим дальше.

## Скриншоты

1. Bootstrap: Apply complete с двумя новыми ресурсами.
2. Успешный workflow и раскрытые шаги сборки, проверки и публикации.
3. Список образов в реестре с sha-тегом (позже также v1.0.0).

## Проверки перед выдачей файлов

Локально проверены синтаксис HCL/YAML и Bash, структура Dockerfile и архива.
Запуск Docker здесь недоступен; фактическую сборку и HTTP-проверки выполнит
GitHub Actions. Публикация образа и применение Terraform требуют выполнения
описанных команд в вашем окружении.

Документация:

- https://github.com/docker-library/official-images/blob/master/library/nginx
- https://github.com/yc-actions/yc-cr-login
- https://yandex.cloud/ru/docs/container-registry/security/
