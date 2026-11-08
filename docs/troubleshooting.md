# Диагностика

## Приложение не открывается

```bash
yc compute instance list --folder-id "$(yc config get folder-id)"
kubectl --context=diploma get nodes -o wide
kubectl --context=diploma get pods -A -o wide
terraform -chdir=terraform/bootstrap output worker_availability
```

Если workers STOPPED, сначала запускаются ВМ. У прерываемых ВМ остановки
ожидаемы; просроченный `until` запрещает функции запускать их снова.
Порядок восстановления и продления — в [operations.md](operations.md).

## Workers Ready, но Grafana или приложение ещё не готовы

```bash
kubectl --context=diploma -n monitoring get pods -o wide
kubectl --context=diploma -n monitoring logs deployment/monitoring-grafana -c grafana --tail=60
kubectl --context=diploma get events -A --sort-by=.metadata.creationTimestamp
python3 scripts/verify-monitoring.py
```

После запуска Grafana первый scrape может вернуть connection refused.
Проверка повторяет запросы к targets до двух минут. Если ошибка сохраняется,
её текст и job/instance выводятся перед завершением с ошибкой.
`Ready` узла не означает, что все приложения на нём уже восстановились.

При `OOMKilled` проверяются лимиты конкретного контейнера и память ноды.
В этом проекте у sidecars Grafana лимиты повышены до 256 МиБ; значения заданы
в `kubernetes/monitoring/values.yaml`.

## Не запускается port-forward

Лог: `.secrets/monitoring-port-forward.log`.
Проверяются доступ к API, состояние Prometheus и его Service:

```bash
kubectl --context=diploma -n monitoring get pods,svc
kubectl --context=diploma -n monitoring rollout status \
  statefulset/prometheus-monitoring-prometheus --timeout=300s
```

Если процесс проверки остановлен Ctrl+C, он завершает созданный port-forward.
Изменение локального порта само по себе не восстанавливает остановленную ВМ.

## SSH к worker 2 не проходит

Inventory направляет SSH к `10.20.10.12` через control plane. После изменения
Terraform outputs выполните `python3 scripts/make-inventory.py`.
Для публичного SSH к другим узлам проверяются текущий IP администратора и
правило `/32` в security group. После смены сети обновите параметры через
`prepare-vms.sh` и рассмотрите план изменения группы безопасности.

## Ошибка JSONDecodeError: Extra data при deploy

`kubectl create --dry-run=client -k ... -o json` может вернуть поток JSON-объектов.
`scripts/deploy-app.py` разбирает поток и формирует Kubernetes List.
Используйте текущий скрипт: возврат к одному `json.loads()` снова вызовет ошибку.

## Недоступна зона или внешний репозиторий

При создании worker 1 зона b вернула FailedPrecondition; его перенесли в e.
Worker 2 был перенесён из d в a после проверки внешней связности.
Текущие зоны, IP и subnet_key заданы в `terraform/main/compute.tf`.
Изменение зоны существующей ВМ может потребовать её замены и потери local PV;
план проверяется до применения.

## Ошибка Cloud Logging при создании функции

В рабочей конфигурации `log_options.disabled=true`. Группа логов не создаётся,
роль logging.writer для функции не требуется. Ручной dry-run возвращает
результат напрямую; сохранённых логов Cloud Logging для функции нет.
