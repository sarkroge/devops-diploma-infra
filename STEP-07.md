# Шаг 7. Мониторинг Kubernetes и Grafana

Устанавливаем kube-prometheus-stack 92.17.0 из официального репозитория
prometheus-community. Chart собирает компоненты проекта kube-prometheus:
Prometheus Operator, Prometheus, Grafana, Alertmanager, kube-state-metrics
и node-exporter. Версия оператора в этом chart — v0.94.2.

Grafana будет доступна по http://153.51.118.243/grafana/ через существующий
Traefik и HTTP-порт 80. Фактический IP скрипт берёт из Terraform output web_ip.
Приложение остаётся доступным по корневому пути /.

## Размещение и хранение

Тяжёлые компоненты размещаются на worker-2 с 4 ГБ RAM. Node exporter работает
на всех трёх узлах, включая control plane. Контроллеры получают requests/limits.
Namespace monitoring допускает доступ node exporter к ресурсам хоста.

На worker-2 создаются локальные PV с каталогами /var/lib/diploma-monitoring:

| Данные | PV | Заявленная ёмкость |
| --- | --- | --- |
| Prometheus | diploma-prometheus | 2 GiB |
| Grafana | diploma-grafana | 512 MiB |
| Alertmanager | diploma-alertmanager | 128 MiB |

Это каталоги на существующем загрузочном диске ВМ, а не отдельные облачные диски.
Ёмкости PV не создают файловые квоты. Prometheus ограничен retention=24h
и retentionSize=512MB; предел TSDB не включает все временные данные и WAL.
Перед первой установкой проверяется наличие минимум 3 GiB свободного места.
Если места меньше, скрипт остановится: передайте его вывод для корректировки.

Local PV сохраняет данные при пересоздании пода и остановке/запуске той же ВМ.
При пересоздании самой ВМ Terraform удаляет её загрузочный диск вместе с данными.
Retain у PV не является резервной копией. Для дипломного стенда это компромисс
по стоимости; дашборды и конфигурация восстанавливаются из репозитория.

## Установка

После распаковки архива выполняйте из корня инфраструктурного проекта:

```bash
cd ~/netology/devops-diploma-infra
export KUBECONFIG="$HOME/.kube/config"
python3 scripts/install-monitoring.py
```

Скрипт выполняет следующие действия:

1. Проверяет context diploma и доступность Kubernetes API.
2. Через ansible/monitoring-storage.yml проверяет место на worker-2 и создаёт
   каталоги с UID/GID Prometheus, Alertmanager и Grafana.
3. Создаёт namespace, StorageClass, локальные PV и PVC Grafana.
4. Создаёт случайный пароль Grafana, сохраняет его в Secret grafana-admin
   и в локальном gitignored файле .secrets/grafana-admin-password (права 0600).
   При повторном запуске используется существующий Secret.
5. Устанавливает закреплённую версию chart с kubernetes/monitoring/values.yaml.
   Runtime root_url Grafana записывается в .secrets/monitoring-runtime.values.json.
6. Ожидает готовности StatefulSet Prometheus и Alertmanager.
7. Добавляет дашборд «Дипломный проект / Обзор кластера» и Ingress Grafana.
8. Проверяет метрики через временный локальный port-forward и завершает его.

Установка может занять несколько минут из-за скачивания образов и создания CRD.
Новые облачные ресурсы Terraform на этом шаге не создаются.
Если установка завершилась ошибкой, передайте её вывод, не удаляя namespace/PV.

## Ожидаемые результаты

Проверочный скрипт выводит:

```text
Ready nodes: 3
Node exporters: 3
Available application replicas: 2
Healthy scrape targets: N/N
Monitoring verification passed.
```

Количество targets зависит от конфигурации chart. При нездоровых targets
выводятся job, instance и причина; передайте эти строки для диагностики.
Проверку можно повторить отдельно:

```bash
python3 scripts/verify-monitoring.py
kubectl --context=diploma -n monitoring get pods,pvc,ingress -o wide
```

Все три PVC должны быть Bound. У Prometheus и Alertmanager обычно два
контейнера в поде: основной процесс и config reloader. Это ожидаемо.

## Вход в Grafana

Логин: admin. Скопируйте пароль в буфер обмена Mac:

```bash
pbcopy < .secrets/grafana-admin-password
WEB_IP="$(terraform -chdir=terraform/main output -raw web_ip)"
open "http://$WEB_IP/grafana/"
```

Пароль не выводится в терминал и не включается в архив/репозиторий.
Откройте Dashboards и найдите «Дипломный проект / Обзор кластера».
Там показаны Ready-узлы, доступные реплики приложения, CPU и память узлов.
Также установлены стандартные дашборды Kubernetes / Compute Resources.
После первой установки дайте Prometheus около 1–2 минут на сбор первых данных.

В Alertmanager маршруты и правила устанавливаются вместе со стеком.
Отправка уведомлений в почту или мессенджер в этом шаге не настраивается.
Интерфейсы Prometheus и Alertmanager доступны внутри кластера; для локальной
диагностики можно использовать kubectl port-forward.

## Скриншоты для отчёта

1. get pods,pvc,ingress: компоненты Running, PVC Bound.
2. Окончание проверки с Ready nodes=3, Node exporters=3 и replicas=2.
3. Дашборд Grafana с данными; в адресной строке виден /grafana/.
4. Один стандартный Kubernetes-дашборд с графиками CPU/памяти.

## Проверка перед выдачей

Chart скачан из официального Helm-репозитория, checksum сверена с index.yaml.
Проверены рендер Helm для Kubernetes 1.37.2, ссылки на Secret и PVC, имя/порт
Service Grafana, subpath root_url, placement, retention и параметры томов.
Проверены синтаксис Ansible/Python/YAML и JSON дашборда. Фактическую готовность
подов, сбор метрик и HTTP-доступ проверяют команды на вашем стенде.

Документация:

- https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack
- https://github.com/prometheus-operator/kube-prometheus
- https://grafana.com/docs/grafana/latest/setup-grafana/configure-grafana/
- https://kubernetes.io/docs/concepts/storage/volumes/#local
