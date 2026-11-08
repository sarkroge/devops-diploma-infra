# Проверка после пересоздания — 8 ноября 2026 года

Основная инфраструктура удалена и создана заново. Bootstrap, бакет state
и сервисные аккаунты сохранены. После этого установлены Kubernetes, приложение
и мониторинг; обновлены доступы CI и выпущен релиз v1.0.2.

## Terraform и образы

Сценарий `recreate-main.py` очистил Registry, применил destroy-план на 13 ресурсов,
проверил пустой main state, создал те же 13 ресурсов и проверил `No changes`.
Пять исходных образов с пятью обычными тегами восстановлены из OCI-копий.
Digest manifest и привязка каждого исходного тега проверены чтением из реестра.

Первая проверка восстановления остановилась после загрузки образов: API YC
добавил digest в поле `tags`, а парсер принимал только обычные теги. После
исправления выполнен `--finish-restoration`: повторная проверка уже загруженных
образов и Terraform, без повторного удаления или создания ресурсов.

| Ресурс | До цикла | После цикла |
| --- | --- | --- |
| Control plane | `fhmlr5h4hftihsovoocl` | `fhmr21bjj14mn1l1vs0q` |
| Worker 1 | `bg0069bqmaanke192228` | `bg046eie1c53st64dlti` |
| Worker 2 | `fhmi0rorg27uu061p7pl` | `fhm4snag15l05uten7o3` |
| Registry | `crpi32ickihldl29g1fg` | `crppnmgn0v38rkpjb2r0` |

Первоначально worker 1 получил адрес `93.77.162.54`. HTTP с control plane работал,
с Mac и мобильной сети — нет. После отдельной замены статического IP на
`153.51.116.138` публичный HTTP заработал. ID ВМ не изменился, повторный plan
вернул `No changes`. Точная причина недоступности прежнего адреса не установлена.

Очистку образов выполняет скрипт перед Terraform: эти образы публикуются CI
и не являются ресурсами state. Проверен весь сценарий, включая эту очистку;
обычный destroy непустого Registry без неё не проверялся как успешный.
Приватные планы, state, резервные копии и журналы сохранены локально в `.secrets`.

## Новый кластер и сервисы

После Ansible все три узла стали Ready. Inventory направляет SSH к обоим workers
через control plane. Старые host keys заменены только для пересозданных ВМ,
после сверки с ключами из serial console YC.

После установки Traefik и kube-prometheus-stack проверка показала:

```text
Ready nodes: 3
Node exporters: 3
Available application replicas: 2
Healthy scrape targets: 28/28
Monitoring verification passed.
```

Grafana `/grafana/api/health` вернула `database: ok`. Три PVC мониторинга Bound.
История мониторинга началась заново: local PV находились на удалённых boot-дисках.
Обновление Traefik проверено со стратегией `maxUnavailable: 1`, `maxSurge: 0`,
чтобы новый pod не ожидал занятый старым pod порт 80 на том же узле.

## CI/CD и автозапуск

В Actions приложения обновлены `YC_REGISTRY_ID`, `APP_URL` и `KUBE_CONFIG` нового
кластера. Push тега `v1.0.2` запустил [workflow #6](https://github.com/sarkroge/devops-diploma-app/actions/runs/42511977448):
оба jobs, build и deploy, завершились успешно. Публичный `/version.json`
вернул `{"version":"v1.0.2"}`.

- [Скриншот build/deploy](evidence/09-app-cd-v1.0.2.png).
- [Скриншот публичной версии](evidence/10-app-version-v1.0.2.png).

Автозапуск включён до `2026-11-11T17:25:30Z` с интервалом две минуты.
Dry-run нашёл оба новых worker по текущим ID, вернул `RUNNING`, `no_action`,
`missing: []`. Это проверка обнаружения и чтения API; остановка и автозапуск
новых ВМ этим dry-run не проверялись. Реальный тест таймера проведён 2 ноября
на прежнем worker 1, до пересоздания.
