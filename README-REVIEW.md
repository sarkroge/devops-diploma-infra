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
| Приложение, HTTP/80 | [153.51.116.138](http://153.51.116.138/) |
| Версия | [version.json](http://153.51.116.138/version.json) |
| Grafana, HTTP/80 | [153.51.116.138/grafana/](http://153.51.116.138/grafana/) |

Grafana: пользователь `admin`, пароль передаю отдельно в закрытом поле сдачи.
Дашборд — «Дипломный проект / Обзор кластера».
Образ: `cr.yandex/crppnmgn0v38rkpjb2r0/diploma-app:v1.0.2`; реестр приватный.

## Выполнение задания

| Требование | Реализация | Подтверждение |
| --- | --- | --- |
| Terraform, сервисный аккаунт и внешний state | Раздельные [bootstrap](terraform/bootstrap) и [main](terraform/main), закрытый версионируемый S3-бакет | [Успешный Terraform pipeline](https://github.com/sarkroge/devops-diploma-infra/actions/runs/41347055031) |
| Удаление и повторное создание main | 13 ресурсов, автоматическая очистка и восстановление Registry | [Сценарий](docs/recreate.md), [проверка 8 ноября](docs/verification-2026-11-08.md) |
| Сеть и подсети в разных зонах | VPC с подсетями a/d/e, три ВМ | [Конфигурации](terraform/main) |
| Самостоятельный Kubernetes | kubeadm, containerd, Flannel; один control plane и два прерываемых worker | [Ansible recap](docs/evidence/01-ansible-recap.png), [Ready-узлы](docs/evidence/02-kubernetes-ready.png) |
| Собственное приложение и Dockerfile | Статическая страница nginx, health endpoint, версия | [Исходники](https://github.com/sarkroge/devops-diploma-app), [первый релиз](docs/evidence/03-app-v1.0.0.png) |
| Мониторинг | Prometheus, Grafana, Alertmanager, node-exporter, kube-state-metrics | [Проверка компонентов](docs/evidence/04-monitoring-check.png), [дашборд](docs/evidence/05-grafana-dashboard.png) |
| Terraform CI | Каждый push в main: validate, plan, apply и повторный plan | [Workflow](.github/workflows/terraform.yml), [результат](docs/evidence/07-terraform-apply.png) |
| CI/CD приложения | Сборка и публикация на push, деплой по тегу, проверка публичной версии | [Workflow](https://github.com/sarkroge/devops-diploma-app/blob/main/.github/workflows/build.yml), [деплой v1.0.2](docs/evidence/09-app-cd-v1.0.2.png), [Actions](https://github.com/sarkroge/devops-diploma-app/actions/runs/42511977448) |

Скриншоты первоначальной установки сделаны 1 ноября 2026 года; они сохранены
как история. Подтверждения релиза v1.0.2 — от 8 ноября. После пересоздания
проверены три Ready-узла, две реплики приложения, 28/28 healthy scrape targets,
Grafana health = `ok`. [Публичная версия](docs/evidence/10-app-version-v1.0.2.png) — `v1.0.2`.

## Особенности стенда

- Worker 2 имеет 4 ГиБ RAM и хранит данные мониторинга на local PV.
- Лимиты sidecars Grafana повышены до 256 МиБ после OOM.
- Workers прерываемые; для времени проверки добавлен автозапуск с ограничением срока.
  Его работа проверена 2 ноября: worker 1 перешёл из STOPPED в RUNNING без ручного start.
  После запуска проверены Kubernetes, мониторинг и приложение.
- Автозапуск продлён 8 ноября до 11 ноября, 20:25:30 МСК. При необходимости окно
  продлевается по [инструкции](docs/operations.md); краткие перерывы при перезапуске возможны.
- State, ключи, пароли и kubeconfig исключены из Git. Доступ к Registry разделён
  между аккаунтами публикации и чтения; CD не использует admin kubeconfig.
- CI применяет основную инфраструктуру. Ansible и Helm запускаются отдельно.

## Воспроизведение

Порядок установки из Git: [docs/deploy.md](docs/deploy.md).
Проверенный сценарий пересоздания: [docs/recreate.md](docs/recreate.md).
Он сохраняет образы, очищает Registry и применяет destroy/create планы main.
Это автоматизация вокруг Terraform: опубликованные CI образы не находятся
в его state, поэтому одного destroy непустого реестра недостаточно.
Bootstrap сохраняется; Kubernetes и сервисы устанавливаются следующим этапом.
Результаты цикла и последующей установки: [проверка 8 ноября](docs/verification-2026-11-08.md).

```bash
kubectl --context=diploma get nodes -o wide
kubectl --context=diploma get pods -A
python3 scripts/verify-monitoring.py
curl -fsS --max-time 20 http://153.51.116.138/healthz
curl -fsS --max-time 20 http://153.51.116.138/version.json
```
