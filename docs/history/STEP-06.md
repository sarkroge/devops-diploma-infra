# Шаг 6. Деплой приложения и HTTP-доступ

Образ v1.0.0 уже опубликован в Yandex Container Registry. В этом шаге:

- Terraform создаёт отдельный аккаунт diploma-registry-pull с ролью
  container-registry.images.puller на каталог.
- Ключ этого аккаунта используется только для скачивания образов Kubernetes.
- Traefik устанавливается официальным Helm chart 42.2.0 (Traefik v3.7.16).
- Traefik работает как DaemonSet на worker-узлах и принимает HTTP на hostPort 80.
- Приложение работает в namespace diploma, Deployment содержит две реплики.
- Service типа ClusterIP и Ingress направляют HTTP-запросы в приложение.

Адрес входа берётся из terraform/main output web_ip — статический IP worker-1.
Для текущего стенда это http://153.51.118.243/. Домен не требуется.
Публичный IP control plane предназначен для Kubernetes API.
Остановка или прерывание worker-1 делает этот единственный публичный адрес
недоступным до запуска узла. Это учебный стенд без облачного балансировщика.

## 1. Сервисный аккаунт для скачивания образов

После распаковки архива:

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
сервисный аккаунт и его роль. Если план отличается, пришлите его перед apply.

```bash
terraform -chdir=terraform/bootstrap apply

yc iam key create \
  --service-account-id "$(terraform -chdir=terraform/bootstrap output -raw registry_pull_service_account_id)" \
  --output .secrets/registry-pull-key.json

unset YC_TOKEN
export YC_SERVICE_ACCOUNT_KEY_FILE="$PWD/.secrets/terraform-key.json"
```

Ключ создаётся один раз на этом шаге и хранится в gitignored .secrets.
В отличие от аккаунта CI, этот аккаунт не может публиковать или удалять образы.

## 2. Secret и Ingress Controller

Все следующие команды выполняйте из корня инфраструктурного проекта.
Скрипты явно используют kubectl context diploma.

```bash
export KUBECONFIG="$HOME/.kube/config"
python3 scripts/create-registry-secret.py
bash scripts/install-ingress.sh
```

Первый скрипт проверяет владельца ключа, создаёт namespace и Secret yc-registry.
Для Yandex Container Registry используется имя пользователя json_key,
паролем служит JSON авторизованного ключа целиком. Секрет передаётся в kubectl
через stdin; приватный ключ не выводится в терминал и не попадает в argv.

Второй скрипт устанавливает закреплённую версию Helm chart и ожидает готовности
DaemonSet. Значения находятся в kubernetes/ingress/traefik-values.yaml.
Service имеет тип ClusterIP. Панель Traefik, Gateway API и CRD provider выключены.
CRD не устанавливаются, контроллер обрабатывает стандартный Kubernetes Ingress.
Ожидаются два пода Traefik в Running — по одному на каждом worker-узле.

## 3. Приложение

```bash
python3 scripts/deploy-app.py v1.0.0

kubectl --context=diploma -n diploma get pods -o wide
kubectl --context=diploma -n diploma get service,ingress
```

Скрипт берёт адрес репозитория образов из Terraform outputs и выбранный тег.
Он собирает манифесты через Kustomize в client dry-run, подставляет актуальный
образ в Deployment, применяет конфигурацию и ожидает успешного rollout.
Базовые YAML находятся в kubernetes/app; для текущего реестра они также содержат
рабочий исходный адрес образа v1.0.0.

У приложения две реплики с предпочтительным распределением между workers.
Процесс работает от UID 101 с read-only root filesystem и отдельным emptyDir
для /tmp/nginx. Настроены startup, readiness и liveness probes, ограничения
ресурсов, Restricted Pod Security и отключение ServiceAccount token в подах.

## 4. Проверка HTTP и скриншоты

```bash
WEB_IP="$(terraform -chdir=terraform/main output -raw web_ip)"
curl -fsS --max-time 15 "http://$WEB_IP/healthz"
curl -fsS --max-time 15 "http://$WEB_IP/version.json"
open "http://$WEB_IP/"
```

Ожидается ok и JSON с version=v1.0.0. В браузере — страница дипломного проекта.

Сохраните скриншоты:

1. Два Running-пода приложения и Service/Ingress.
2. Страница приложения, в адресной строке виден HTTP URL.
3. Ответ version.json со значением v1.0.0.

При ошибке сначала передайте её вывод. Для диагностики:

```bash
kubectl --context=diploma -n diploma get events --sort-by=.lastTimestamp
kubectl --context=diploma -n diploma describe pods
kubectl --context=diploma -n ingress-system logs daemonset/traefik --tail=60
```

Не выводите содержимое Secret или JSON ключа на скриншоты.
Нормальные describe/events показывают ссылки на Secret, а не его содержимое.

## Границы этого шага

Мониторинг и Grafana добавляются следующим шагом. Автоматический деплой
приложения по тегу подключим после проверки этих Kubernetes-манифестов.
Сейчас деплой запускается командой deploy-app.py с Mac.

Локально проверены синтаксис HCL/YAML/Python/Bash и рендер Helm chart для
Kubernetes 1.37.2; проверены DaemonSet, hostPort 80, ClusterIP и отключённый
Gateway. Фактическая установка, скачивание образа, Pod Security admission
и доступ из интернета требуют выполнения команд на вашем стенде.

Документация:

- https://traefik.github.io/charts/
- https://github.com/traefik/traefik-helm-chart
- https://doc.traefik.io/traefik/reference/install-configuration/providers/kubernetes/kubernetes-ingress/
- https://yandex.cloud/en/docs/managed-kubernetes/operations/private-registries
- https://kubernetes.io/docs/tasks/configure-pod-container/pull-image-private-registry/
