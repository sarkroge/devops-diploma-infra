# Дипломный проект DevOps — Егор Краснов

Учебный стенд в Yandex Cloud: Terraform создаёт инфраструктуру, Ansible
устанавливает Kubernetes, GitHub Actions собирает и развёртывает приложение.
Для мониторинга используется kube-prometheus-stack.

## Ссылки

- [Приложение](http://153.51.116.138/) и [его версия](http://153.51.116.138/version.json).
- [Grafana](http://153.51.116.138/grafana/), пользователь `admin`; пароль передаётся отдельно.
- [Репозиторий приложения](https://github.com/sarkroge/devops-diploma-app).
- [Terraform pipeline](https://github.com/sarkroge/devops-diploma-infra/actions/workflows/terraform.yml).
- [Сборка и деплой приложения](https://github.com/sarkroge/devops-diploma-app/actions/workflows/build.yml).
- [Результаты для проверки](README-REVIEW.md).

Образ: `cr.yandex/crppnmgn0v38rkpjb2r0/diploma-app:v1.0.2`.
Реестр приватный; кластер получает образы через отдельный аккаунт puller.

## Стенд

| Узел | Зона | Внутренний IP | RAM | Прерываемый |
| --- | --- | --- | --- | --- |
| Control plane | ru-central1-a | 10.20.10.10 | 2 ГиБ | Нет |
| Worker 1 | ru-central1-e | 10.20.40.10 | 2 ГиБ | Да |
| Worker 2, мониторинг | ru-central1-a | 10.20.10.12 | 4 ГиБ | Да |

У каждой ВМ: 2 vCPU с долей 20%, HDD 10 ГиБ, Ubuntu 24.04.
Подсети созданы в a/d/e. Worker 1 перенесён из b после отказа создания ВМ,
worker 2 — из d после проблем внешней связности. Мониторингу выделено 4 ГиБ RAM.

Версии: Terraform 1.12.0, Yandex provider 0.243.0, Kubernetes 1.37.2,
containerd 2.4.2, Flannel 0.28.10, Traefik chart 42.2.0,
kube-prometheus-stack chart 92.17.0.

## Структура

| Каталог | Содержимое |
| --- | --- |
| `terraform/bootstrap` | Сервисные аккаунты, бакет state, функция автозапуска |
| `terraform/main` | Сеть, подсети, Registry, ВМ, IP и security groups |
| `ansible` | Установка Kubernetes и подготовка каталогов local PV |
| `kubernetes` | Приложение, Traefik, мониторинг и RBAC для CD |
| `functions/worker-restarter` | Код функции автозапуска workers |
| `scripts`, `tests` | Команды эксплуатации и тесты Python |
| `docs` | Инструкции, диагностика и подтверждения |

## Автоматизация

Push в `main` инфраструктуры запускает validate, plan, apply сохранённого плана
`terraform/main` и повторный plan. Bootstrap применяется локально.
State основной конфигурации хранится в закрытом версионируемом S3-бакете;
bootstrap state — локально. Локальные apply и CI выполняются последовательно:
concurrency workflow не блокирует Terraform на Mac.

Push в репозиторий приложения запускает сборку, smoke-тест и публикацию образа.
Push нового тега также обновляет Deployment по digest протестированного образа,
ожидает rollout и проверяет публичную версию. CD использует отдельный
ServiceAccount с доступом только к Deployment приложения.

Функция каждые две минуты проверяет остановленные workers в пределах заданного
срока. Текущий срок: `terraform -chdir=terraform/bootstrap output worker_availability`.
После его истечения ВМ автоматически не запускаются. Запуск ВМ и восстановление
Kubernetes занимают время; непрерывная доступность не гарантируется.

## Проверка

```bash
kubectl --context=diploma get nodes -o wide
kubectl --context=diploma get pods -A
python3 scripts/verify-monitoring.py
curl -fsS --max-time 20 http://153.51.116.138/healthz
curl -fsS --max-time 20 http://153.51.116.138/version.json
```

8 ноября 2026 года подтверждены три Ready-узла, две реплики, 28/28 healthy targets
и версия `v1.0.2`. Релиз прошёл [build и deploy](https://github.com/sarkroge/devops-diploma-app/actions/runs/42511977448).

Prometheus хранит метрики 24 часа. Local PV расположены на boot-диске worker 2:
остановку ВМ данные переживают, удаление ВМ — нет. 8 ноября выполнены удаление
и создание 13 ресурсов main, восстановление пяти образов и установка нового
кластера. Очистку образов перед Terraform автоматизирует отдельный скрипт;
[порядок пересоздания](docs/recreate.md), [результаты проверки](docs/verification-2026-11-08.md).

## Инструкции

- [Развёртывание из репозитория](docs/deploy.md).
- [Запуск, остановка и продление автозапуска](docs/operations.md).
- [Диагностика](docs/troubleshooting.md).
- [История настройки](docs/history/README.md).
