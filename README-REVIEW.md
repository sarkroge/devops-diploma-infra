# Дипломный практикум DevOps в Yandex Cloud

Здравствуйте! Представляю дипломный проект. Автор — Краснов Егор.
Kubernetes установлен самостоятельно на трёх ВМ. Инфраструктура описана
в Terraform, установка кластера — в Ansible, приложение и мониторинг —
в Kubernetes-манифестах и Helm values.

## Доступ

| Материал | Ссылка |
| --- | --- |
| Инфраструктура | [devops-diploma-infra](https://github.com/sarkroge/devops-diploma-infra) |
| Приложение и Dockerfile | [devops-diploma-app](https://github.com/sarkroge/devops-diploma-app) |
| Приложение, HTTP/80 | [153.51.118.243](http://153.51.118.243/) |
| Версия | [version.json](http://153.51.118.243/version.json) |
| Grafana, HTTP/80 | [153.51.118.243/grafana/](http://153.51.118.243/grafana/) |

Grafana: пользователь `admin`, пароль передаю отдельно в закрытом поле сдачи.
Дашборд — «Дипломный проект / Обзор кластера».
Образ: `cr.yandex/crpi32ickihldl29g1fg/diploma-app:v1.0.1`; реестр приватный.

## Выполнение задания

| Требование | Реализация | Подтверждение |
| --- | --- | --- |
| Terraform, сервисный аккаунт и внешний state | Раздельные [bootstrap](terraform/bootstrap) и [main](terraform/main), закрытый версионируемый S3-бакет | [Успешный Terraform pipeline](https://github.com/sarkroge/devops-diploma-infra/actions/runs/41347055031) |
| Сеть и подсети в разных зонах | VPC с подсетями a/d/e, три ВМ | [Конфигурации](terraform/main) |
| Самостоятельный Kubernetes | kubeadm, containerd, Flannel; один control plane и два прерываемых worker | [Ansible recap](docs/evidence/01-ansible-recap.png), [Ready-узлы](docs/evidence/02-kubernetes-ready.png) |
| Собственное приложение и Dockerfile | Статическая страница nginx, health endpoint, версия | [Исходники](https://github.com/sarkroge/devops-diploma-app), [первый релиз](docs/evidence/03-app-v1.0.0.png) |
| Мониторинг | Prometheus, Grafana, Alertmanager, node-exporter, kube-state-metrics | [Проверка компонентов](docs/evidence/04-monitoring-check.png), [дашборд](docs/evidence/05-grafana-dashboard.png) |
| Terraform CI | Каждый push в main: validate, plan, apply и повторный plan | [Workflow](.github/workflows/terraform.yml), [результат](docs/evidence/07-terraform-apply.png) |
| CI/CD приложения | Сборка и публикация на push, деплой по тегу, проверка публичной версии | [Workflow](https://github.com/sarkroge/devops-diploma-app/blob/main/.github/workflows/build.yml), [деплой v1.0.1](docs/evidence/06-app-cd-v1.0.1.png) |

Скриншоты в таблице сделаны 1 ноября 2026 года. Повторная проверка 8 ноября
показала три Ready-узла, две реплики приложения, 28/28 healthy scrape targets,
`/healthz` = `ok`, `/version.json` = `v1.0.1`.

## Особенности стенда

- Worker 2 имеет 4 ГиБ RAM и хранит данные мониторинга на local PV.
- Лимиты sidecars Grafana повышены до 256 МиБ после OOM.
- Workers прерываемые; для времени проверки добавлен автозапуск с ограничением срока.
  Его работа проверена 2 ноября: worker 1 перешёл из STOPPED в RUNNING без ручного start.
  После запуска проверены Kubernetes, мониторинг и приложение.
- Автозапуск продлён 8 ноября до 11 ноября, 16:47 МСК. При необходимости окно
  продлевается по [инструкции](docs/operations.md); краткие перерывы при перезапуске возможны.
- State, ключи, пароли и kubeconfig исключены из Git. Доступ к Registry разделён
  между аккаунтами публикации и чтения; CD не использует admin kubeconfig.
- CI применяет основную инфраструктуру. Ansible и Helm запускаются отдельно.

## Воспроизведение

Порядок установки из Git: [docs/deploy.md](docs/deploy.md).
Подготовка проверки полного пересоздания: [docs/recreate.md](docs/recreate.md).
Фактический цикл `terraform destroy` → `terraform apply` пока не подтверждён.
Существующие успешные apply и повторные plan не заменяют эту проверку.

```bash
kubectl --context=diploma get nodes -o wide
kubectl --context=diploma get pods -A
python3 scripts/verify-monitoring.py
curl -fsS --max-time 20 http://153.51.118.243/healthz
curl -fsS --max-time 20 http://153.51.118.243/version.json
```
