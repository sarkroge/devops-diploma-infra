# Развёртывание стенда

Команды выполняются из корня `devops-diploma-infra`, кроме явно указанного
каталога Ansible. Инструкция описывает установку из Git. Для уже работающего
стенда используются [команды эксплуатации](operations.md).

## Подготовка

Нужны Git, yc CLI, Terraform 1.12.0, Python 3, Ansible, kubectl и Helm.
Для локальных проверок приложения нужен Docker. ВМ используют amd64,
Mac для управления стендом может быть arm64.

```bash
git clone https://github.com/sarkroge/devops-diploma-infra.git
cd devops-diploma-infra
umask 077
mkdir -p .secrets
yc config get cloud-id
yc config get folder-id
```

Профиль yc должен иметь права на создание IAM-аккаунтов, бакета и ресурсов
в выбранном каталоге. Если Terraform Registry недоступен, настройки зеркала
провайдера находятся в `ci/terraform-provider-installation.hcl`.
Для их использования в текущем терминале:

```bash
export TF_CLI_CONFIG_FILE="$PWD/ci/terraform-provider-installation.hcl"
```

## Bootstrap

Bootstrap создаёт аккаунты Terraform/CI/puller, закрытый бакет с versioning,
статический S3-ключ и приватную функцию автозапуска. По умолчанию таймер выключен.
Bootstrap state локальный; сохраните его вместе с ключами в защищённой копии.

```bash
export TF_VAR_cloud_id="$(yc config get cloud-id)"
export TF_VAR_folder_id="$(yc config get folder-id)"
unset YC_SERVICE_ACCOUNT_KEY_FILE
export YC_TOKEN="$(yc iam create-token)"

python3 scripts/build-worker-restarter.py --check
terraform -chdir=terraform/bootstrap init -lockfile=readonly
terraform -chdir=terraform/bootstrap validate
terraform -chdir=terraform/bootstrap plan -out=../../.secrets/bootstrap.tfplan
```

После проверки адресов и действий плана:

```bash
terraform -chdir=terraform/bootstrap apply ../../.secrets/bootstrap.tfplan
```

Для доступа Terraform к API создайте авторизованный ключ, если его ещё нет:

```bash
if [ ! -f .secrets/terraform-key.json ]; then
  yc iam key create \
    --service-account-id "$(terraform -chdir=terraform/bootstrap output -raw terraform_service_account_id)" \
    --output .secrets/terraform-key.json
  chmod 600 .secrets/terraform-key.json
fi
```

## Основная инфраструктура

```bash
export YC_SERVICE_ACCOUNT_KEY_FILE="$PWD/.secrets/terraform-key.json"
unset YC_TOKEN
export AWS_ACCESS_KEY_ID="$(terraform -chdir=terraform/bootstrap output -raw state_access_key)"
export AWS_SECRET_ACCESS_KEY="$(terraform -chdir=terraform/bootstrap output -raw state_secret_key)"
export TF_STATE_BUCKET="$(terraform -chdir=terraform/bootstrap output -raw state_bucket_name)"

bash scripts/prepare-vms.sh
terraform -chdir=terraform/main init -lockfile=readonly \
  -backend-config="bucket=$TF_STATE_BUCKET"
terraform -chdir=terraform/main validate
terraform -chdir=terraform/main plan -out=../../.secrets/main.tfplan
```

`prepare-vms.sh` создаёт или повторно использует `.secrets/diploma-ssh`,
сохраняет публичный ключ и адрес администратора `/32` в локальный auto.tfvars.
При VPN разрешённый адрес можно задать через `DIPLOMA_ADMIN_IP`.

После проверки плана:

```bash
terraform -chdir=terraform/main apply ../../.secrets/main.tfplan
terraform -chdir=terraform/main plan
terraform -chdir=terraform/main output nodes
```

Ожидается `No changes` при повторном плане. В Object Storage объект основного
state — `diploma/main/terraform.tfstate`. Ключи, auto.tfvars и state исключены
из Git. Bootstrap provider работает от пользователя; main — от сервисного аккаунта.
Параллельные локальные apply и запуски infrastructure CI исключаются.

## Kubernetes

```bash
python3 scripts/make-inventory.py
cd ansible
ansible all -m ping
ansible-playbook site.yml --syntax-check
ansible-playbook site.yml
cd ..
python3 scripts/install-kubeconfig.py
export KUBECONFIG="$HOME/.kube/config"
kubectl --context=diploma get nodes -o wide
kubectl --context=diploma get pods -A
```

Inventory создаётся из Terraform outputs. Оба worker доступны по внутренним IP
через SSH ProxyCommand на control plane. Playbook устанавливает containerd,
kubeadm, Flannel и присоединяет workers. В `PLAY RECAP` ожидаются
`failed=0`, `unreachable=0`, затем три Ready-узла.

## Образ приложения

Аккаунты публикации и чтения созданы bootstrap. Если ключей ещё нет:

```bash
if [ ! -f .secrets/app-ci-key.json ]; then
  yc iam key create \
    --service-account-id "$(terraform -chdir=terraform/bootstrap output -raw app_ci_service_account_id)" \
    --output .secrets/app-ci-key.json
  chmod 600 .secrets/app-ci-key.json
fi
if [ ! -f .secrets/registry-pull-key.json ]; then
  yc iam key create \
    --service-account-id "$(terraform -chdir=terraform/bootstrap output -raw registry_pull_service_account_id)" \
    --output .secrets/registry-pull-key.json
  chmod 600 .secrets/registry-pull-key.json
fi

terraform -chdir=terraform/main output registry_id
```

В репозитории приложения настройте Actions variable `YC_REGISTRY_ID` и secret
`YC_SA_JSON_CREDENTIALS` из `.secrets/app-ci-key.json`. Pipeline собирает и публикует
образ на push. Для существующего `v1.0.1` можно повторно запустить build workflow
на этом теге через workflow_dispatch; такой запуск публикует образ, но CD не выполняет.
Порядок выпуска нового тега описан в [README приложения](https://github.com/sarkroge/devops-diploma-app).

## Приложение и Ingress

После появления выбранного образа в текущем Registry:

```bash
python3 scripts/create-registry-secret.py
bash scripts/install-ingress.sh
python3 scripts/deploy-app.py v1.0.1
```

Скрипт deploy подставляет Registry из outputs и переданный тег в манифесты.
После CI/CD версия может быть другой: повторный deploy выбранного тега меняет
образ Deployment. Базовый image в YAML не служит записью последнего CD-релиза.

```bash
WEB_IP="$(terraform -chdir=terraform/main output -raw web_ip)"
curl -fsS --max-time 20 "http://$WEB_IP/healthz"
curl -fsS --max-time 20 "http://$WEB_IP/version.json"
```

## Мониторинг

```bash
python3 scripts/install-monitoring.py
python3 scripts/verify-monitoring.py
```

Скрипт подготавливает каталоги local PV через Ansible, устанавливает закреплённый
chart, добавляет дашборд и Ingress. Пароль Grafana сохраняется в
`.secrets/grafana-admin-password`, URL — `http://<web_ip>/grafana/`.
Проверка ожидает три Ready-узла, три node-exporter, две реплики и здоровые targets.
После перезапуска восстановление targets может занять до двух минут ожидания.

## CI/CD

Для CD приложения создайте ограниченный kubeconfig:

```bash
python3 scripts/create-cd-kubeconfig.py
```

В Actions приложения добавьте secret `KUBE_CONFIG` из
`.secrets/kubeconfig-github-deployer` и variable `APP_URL` из вывода скрипта.
Новый push тега запускает сборку, публикацию, rollout и проверку публичной версии.

Для infrastructure CI:

```bash
python3 scripts/prepare-terraform-ci.py
```

Скрипт готовит файлы для Secrets в `.secrets/terraform-ci/`:

| Настройка GitHub Actions | Источник |
| --- | --- |
| Secret `TF_SA_JSON_CREDENTIALS` | одноимённый файл, существующий авторизованный ключ |
| Secret `AWS_ACCESS_KEY_ID` | одноимённый файл, S3 access key |
| Secret `AWS_SECRET_ACCESS_KEY` | одноимённый файл, S3 secret key |
| Secret `TF_INPUTS_JSON` | одноимённый файл, текущие параметры main |
| Variable `TF_STATE_BUCKET` | имя бакета, напечатанное скриптом |

Push в main применяет main-конфигурацию автоматически. При изменении локальных
параметров ВМ или SSH нужно обновить `TF_INPUTS_JSON`, чтобы CI использовал те же
входные данные. Bootstrap в CI только валидируется, его apply выполняется локально.

## Доступность при проверке

Workers остаются прерываемыми. Для времени проверки включите ограниченное окно
автозапуска по [operations.md](operations.md). После нового развёртывания
актуализируйте ссылки из outputs и передайте пароль Grafana отдельно.

Полное пересоздание основной конфигурации проверено 8 ноября 2026 года:
[порядок](recreate.md), [результаты](verification-2026-11-08.md).
