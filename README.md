# Дипломный проект DevOps — Егор Краснов

Инфраструктура Yandex Cloud, самостоятельная установка Kubernetes через Ansible,
развёртывание приложения и мониторинга. Учебный стенд с ограниченным бюджетом.

## Репозитории и доступ

- [Инфраструктура, Ansible и Kubernetes](https://github.com/sarkroge/devops-diploma-infra).
- [Описание выполнения и доказательства для проверки](README-REVIEW.md).
- [Приложение, Dockerfile и CI/CD](https://github.com/sarkroge/devops-diploma-app).
- [Тестовое приложение](http://153.51.118.243/).
- [Grafana](http://153.51.118.243/grafana/), пользователь `admin`.
  Пароль передаётся преподавателю отдельно, в Git его нет.
- Образ: `cr.yandex/crpi32ickihldl29g1fg/diploma-app:v1.0.1`.
  Реестр приватный; Kubernetes использует отдельный аккаунт с ролью puller.

Подтверждены: три Ready-узла, две реплики приложения, графики CPU и памяти,
28/28 healthy scrape targets; сборка и автоматический деплой приложения по тегу
`v1.0.1` с проверкой публичной версии. Terraform workflow успешно выполнил
validate, подключение S3 backend, plan, apply и повторный plan без изменений.

## Состав проекта

| Каталог | Назначение |
| --- | --- |
| `terraform/bootstrap` | Сервисные аккаунты, закрытый бакет state и права |
| `terraform/main` | VPC, три подсети, Registry, три ВМ, IP и security groups |
| `ansible` | containerd, kubeadm, Kubernetes, Flannel, подготовка локальных PV |
| `kubernetes/app` | Deployment, Service, Ingress и ServiceAccount приложения |
| `kubernetes/ingress` | Helm values Traefik |
| `kubernetes/monitoring` | Helm values, PV/PVC, Grafana Ingress и дашборд |
| `kubernetes/cicd` | Ограниченная роль для GitHub Actions приложения |
| `.github/workflows/terraform.yml` | Проверка и применение инфраструктуры |
| `scripts` | Подготовка переменных, inventory, деплой и проверки |

## Ресурсы и версии

| Узел | Зона | Внутренний IP | RAM | Прерываемый |
| --- | --- | --- | --- | --- |
| `k8s-control-plane` | `ru-central1-a` | `10.20.10.10` | 2 ГиБ | Нет |
| `k8s-worker-1` | `ru-central1-e` | `10.20.40.10` | 2 ГиБ | Да |
| `k8s-worker-2` | `ru-central1-a` | `10.20.10.12` | 4 ГиБ | Да |

Каждая ВМ: 2 vCPU, гарантированная доля 20%, HDD 10 ГиБ, Ubuntu 24.04.
На worker-2 размещён мониторинг. Подсеть `ru-central1-d` сохранена; worker-2
перенесён в `a` после проблем внешней связности. Worker-1 перенесён из `b` в `e`
после отказа создания ВМ в зоне `b`. Выбран вариант самостоятельной установки
Kubernetes на трёх ВМ.

Версии стенда: Terraform 1.12.0, Yandex provider 0.243.0,
Kubernetes 1.37.2, containerd 2.4.2, Flannel 0.28.10,
Traefik chart 42.2.0, kube-prometheus-stack chart 92.17.0.

## State и права Terraform

Bootstrap выполняется локально с IAM-токеном пользователя. Его локальный state
и защищённая резервная копия не публикуются. Основной Terraform работает от
`diploma-terraform`: `compute.editor`, `vpc.admin`, `container-registry.editor`
на каталог и `storage.editor` только на бакет state. Роли `admin`/`editor`
на всё облако этому аккаунту не выдаются.

Основной state: закрытый версионируемый бакет
`sarkroge-diploma-state-b1g90k05go90aj6v84m2`,
объект `diploma/main/terraform.tfstate`. Bootstrap и основная конфигурация
разделены: удаление основных ресурсов не удаляет бакет и аккаунты.

Распределённая блокировка state не настроена. Запуски Terraform workflow
сериализованы через GitHub Actions concurrency с очередью. Это не блокирует
локальный Terraform: локальный apply/destroy и операции state выполняются
только после завершения всех CI-запусков. Изменения main автоматически
применяются; destroy не входит в workflow.

## Воспроизведение стенда

Подробные команды и моменты для скриншотов: `STEP-02.md` — `STEP-09.md`.
Документы ранних шагов описывают промежуточную конфигурацию; текущие `.tf`,
playbook и manifests являются итоговой конфигурацией. Для нового каталога
используются его собственные cloud/folder IDs, ключи и outputs.

1. Установить yc, Terraform, Ansible, kubectl, Helm, Python 3 и Git.
   Для bootstrap экспортировать `TF_VAR_cloud_id`, `TF_VAR_folder_id`
   и пользовательский `YC_TOKEN`; выполнить init/plan/apply в `terraform/bootstrap`.
2. Создать авторизованные ключи Terraform, app CI и puller по инструкциям шагов.
   Сохранить bootstrap state и ключи защищённо.
3. Выполнить `bash scripts/prepare-vms.sh`; экспортировать авторизованный ключ
   Terraform и S3 credentials из bootstrap, убрать `YC_TOKEN`.
   Инициализировать `terraform/main` с `-backend-config="bucket=$TF_STATE_BUCKET"`,
   затем plan/apply.
4. Выполнить `python3 scripts/make-inventory.py`, затем из `ansible`:
   `ansible all -m ping` и `ansible-playbook site.yml`.
5. Выполнить `python3 scripts/install-kubeconfig.py`, проверить
   `kubectl --context=diploma get nodes -o wide` и `get pods -A`.
6. Настроить CI приложения, собрать и опубликовать образ в Registry.
7. Выполнить `python3 scripts/create-registry-secret.py`,
   `bash scripts/install-ingress.sh`, `python3 scripts/deploy-app.py v1.0.1`.
8. Выполнить `python3 scripts/install-monitoring.py` и
   `python3 scripts/verify-monitoring.py`. Проверить дашборд в Grafana.
9. Подготовить ограниченный kubeconfig через
   `python3 scripts/create-cd-kubeconfig.py`, добавить в Secrets репозитория
   приложения. Новый Git-тег запускает build/publish/deploy.
10. Подключить инфраструктурный workflow по [STEP-09.md](STEP-09.md).

Terraform CI не устанавливает Kubernetes заново: Ansible и Helm выполняются
отдельными командами. После пересоздания ВМ эти этапы повторяются.

## Мониторинг и данные

kube-prometheus-stack: Prometheus Operator, Prometheus, Grafana, Alertmanager,
kube-state-metrics и node-exporter на всех трёх узлах. Дашборд
`Дипломный проект / Обзор кластера` поставляется через ConfigMap.

Prometheus: история 24 часа, ограничение TSDB 512 МБ. Локальные PV на boot-диске
worker-2: Prometheus 2 ГиБ, Grafana 512 МиБ, Alertmanager 128 МиБ. Это заявленные
ёмкости PV, а не файловые квоты. Данные переживают пересоздание pod и остановку
той же ВМ, но теряются при удалении/замене ВМ. Лимит памяти Grafana sidecars —
256 МиБ каждый.

## CI/CD

Приложение: каждый push запускает сборку, проверки nginx/HTTP и публикацию.
Pull request проходит сборку и тесты без публикации. Push тега также
развёртывает протестированный образ по digest и проверяет `/version.json`.
GitHub deployer может изменять только Deployment `diploma-app` в namespace
`diploma`, без доступа к Secrets и узлам.

Инфраструктура: каждый push в main запускает форматирование, проверку двух
Terraform-конфигураций, plan, применение сохранённого плана `terraform/main`
и повторный план. Pull request получает проверки без облачных credentials
и без apply. Bootstrap в CI не применяется. State и plan не публикуются
как Actions artifacts.

## Экономия

Из корня проекта: `bash scripts/nodes.sh status`, затем
`bash scripts/nodes.sh stop` после работы. Для продолжения —
`bash scripts/nodes.sh start`, обновление inventory и проверка Ready-узлов.
Остановка не удаляет диски и IP; их хранение может продолжать тарифицироваться.
Публичные страницы недоступны при остановленных worker-узлах.

## Материалы для сдачи

- Ссылки на оба репозитория и образ, доступ к приложению и Grafana.
- Скриншоты apply и повторного No changes, объекта state в бакете.
- Ansible recap, Ready-узлы и системные pod.
- Дашборд Grafana и страница приложения с версией.
- Успешные build/deploy по тегу и Terraform workflow с apply.
- Готовность воспроизвести ресурсы из конфигураций. Удаление работающего стенда
  для демонстрации выполняется отдельно с учётом потери локальных PV.

## Документация

- [Terraform в Yandex Cloud](https://yandex.cloud/ru/docs/terraform/).
- [S3 backend](https://developer.hashicorp.com/terraform/language/backend/s3).
- [GitHub Actions concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).
- [kube-prometheus-stack](https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack).
- [Экономия ресурсов — Нетология](https://github.com/netology-code/devops-materials/blob/master/cloudwork.MD).
