# Шаг 8. Автоматический деплой приложения по Git-тегу

Мониторинг проверен: дашборд отображает три Ready-узла, две реплики приложения,
CPU и память узлов. Grafana доступна через /grafana/ на HTTP-порту 80.

В этом шаге настраивается CD в GitHub Actions. Новый тег, например v1.0.1,
запускает сборку, тестирование, публикацию и деплой. Deployment получает образ
по digest из job сборки. После rollout проверяются HTTP и версия приложения.

## 1. Создать доступ CI к Kubernetes

После распаковки архива из корня инфраструктурного проекта:

```bash
cd ~/netology/devops-diploma-infra
export KUBECONFIG="$HOME/.kube/config"
python3 scripts/create-cd-kubeconfig.py
```

Скрипт применяет kubernetes/cicd/deployer.yaml и создаёт ServiceAccount
github-deployer, Role, RoleBinding и отдельный Secret с его API-токеном.
В kubeconfig помещаются только этот токен, CA кластера и публичный API endpoint.
Административный kubeconfig не копируется в GitHub.

Права ограничены get/list/watch/patch на Deployment diploma-app в namespace
diploma. Скрипт проверяет разрешения на patch/watch и отсутствие прямого
API-доступа к Secrets и Nodes. Ожидаемый вывод содержит yes, yes, no, no.

Для внешнего CI без сервиса обмена идентичностью используется явно созданный
долгоживущий ServiceAccount token. Он хранится в GitHub Actions Secret, а
локальный файл .secrets/kubeconfig-github-deployer имеет права 0600.
Для отзыва доступа удалите Secret github-deployer-token в namespace diploma.
Повторное создание токена требует обновить GitHub Secret KUBE_CONFIG.

## 2. Настроить GitHub Actions

В репозитории sarkroge/devops-diploma-app откройте:
Settings → Secrets and variables → Actions.

Скопируйте kubeconfig целиком в буфер обмена Mac:

```bash
pbcopy < .secrets/kubeconfig-github-deployer
```

На вкладке Secrets создайте Repository secret:

- Name: KUBE_CONFIG
- Secret: вставьте содержимое буфера обмена.

На вкладке Variables создайте Repository variable:

- Name: APP_URL
- Value: http://153.51.118.243

Если IP изменился, используйте адрес, который напечатал create-cd-kubeconfig.py.
Ранее настроенные YC_REGISTRY_ID и YC_SA_JSON_CREDENTIALS нужны job сборки.
Содержимое kubeconfig не публикуйте в репозитории и на скриншотах.

## 3. Применить патч приложения

Подключение GitHub разрешило чтение, но вернуло 403 на создание ветки.
Поэтому изменения workflow и README передаются патчем patches/app-cd.patch,
подготовленным относительно текущего main репозитория приложения.

Сначала обновите локальный main и проверьте чистоту рабочей копии:

```bash
cd ~/netology/devops-diploma-app
git switch main
git pull --ff-only
git status --short
```

Если есть незакоммиченные изменения, передайте вывод перед применением патча.
Для чистой рабочей копии:

```bash
git apply --check ../devops-diploma-infra/patches/app-cd.patch
git apply ../devops-diploma-infra/patches/app-cd.patch
git diff --stat
git diff -- .github/workflows/build.yml README.md
```

Патч меняет только .github/workflows/build.yml и README.md.
Workflow получает outputs с digest опубликованного образа и job deploy,
который запускается только на push тега и после успешного build.
kubectl 1.37.2 устанавливается в runner. Деплой выполняет set image и
rollout status для существующего Deployment. Затем smoke-test.sh проверяет
health, главную страницу, версию и 404 по APP_URL.

```bash
git add .github/workflows/build.yml README.md
git commit -m "Deploy tested application releases to Kubernetes"
git push origin main
```

Push в main запускает сборку и публикацию. Job deploy для этой ветки
будет пропущен: развёртывание запускается по тегу.

## 4. Проверить полный CI/CD

После успешной сборки main создайте новый тег на коммите с обновлённым workflow:

```bash
git tag v1.0.1
git push origin v1.0.1
```

В Actions → Build, test, publish and deploy должны успешно завершиться
оба job: build и deploy. В deploy видны смена образа, rollout и HTTP-проверки.
Старый тег v1.0.0 указывает на старый workflow без CD; для демонстрации
используйте новый тег, не перемещая старый.

Проверка результата из корня инфраструктурного проекта:

```bash
cd ~/netology/devops-diploma-infra
kubectl --context=diploma -n diploma get deployment diploma-app \
  -o 'jsonpath={.spec.template.spec.containers[0].image}{"\n"}'
curl -fsS --max-time 15 http://153.51.118.243/version.json
open http://153.51.118.243/
```

В Deployment ожидается адрес с @sha256, а в version.json — v1.0.1.
Страница приложения также должна показывать v1.0.1.

Сохраните скриншоты успешных build/deploy и страницы с новой версией.
Это подтверждает автоматический деплой после создания Git-тега.

## Проверки перед выдачей

Workflow проверен actionlint и bash -n. Проверены структура RBAC и формирование
отдельного kubeconfig с правами файла 0600 без вывода токена. Патч проверен
на текущих файлах main. Фактические права API, сетевой доступ из GitHub runner,
rollout и версия приложения проверяются описанными командами и workflow.
