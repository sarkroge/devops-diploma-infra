# Grafana: OOMKilled вспомогательных контейнеров

Причина текущего сбоя: grafana-sc-dashboard и grafana-sc-datasources
перезапускаются с OOMKilled/exit=137 при лимите памяти 96Mi.
Основной контейнер grafana имеет restartCount=0. Неготовность вспомогательных
контейнеров исключает под из готовых endpoints Service, поэтому Traefik
может отвечать no available server.

Исправление в kubernetes/monitoring/values.yaml:

- grafana.sidecar.resources.requests.memory: 128Mi;
- grafana.sidecar.resources.limits.memory: 256Mi.

Эти значения применяются к каждому из двух вспомогательных контейнеров.
Потребность в памяти зарезервирована в requests; лимит остаётся ограниченным.
Фактическую достаточность новых значений нужно проверить после запуска.

После распаковки исправления из корня инфраструктурного проекта:

```bash
cd ~/netology/devops-diploma-infra

helm upgrade monitoring prometheus-community/kube-prometheus-stack \
  --version 92.17.0 \
  --kube-context diploma \
  --namespace monitoring \
  --values kubernetes/monitoring/values.yaml \
  --values .secrets/monitoring-runtime.values.json \
  --wait --timeout 10m

kubectl --context=diploma -n monitoring rollout status deployment/monitoring-grafana --timeout=300s
kubectl --context=diploma -n monitoring get pods -l app.kubernetes.io/name=grafana
curl -fsS --max-time 15 http://153.51.118.243/grafana/api/health
```

Ожидается новый под с 3/3 Ready и HTTP JSON с database=ok.
Deployment имеет стратегию Recreate, поэтому во время обновления возможна
краткая недоступность Grafana. Данные находятся в существующем PVC.
Пароль используется из существующего Secret grafana-admin.

Спустя 2–3 минуты повторите get pods: число перезапусков не должно расти.
Если проблема сохранилась, передайте вывод:

```bash
kubectl --context=diploma -n monitoring get pods -l app.kubernetes.io/name=grafana \
  -o 'jsonpath={range .items[*].status.containerStatuses[*]}{.name}{"\t restarts="}{.restartCount}{"\t reason="}{.lastState.terminated.reason}{"\n"}{end}'
```

После восстановления доступа откройте http://153.51.118.243/grafana/ и выполните:

```bash
python3 scripts/verify-monitoring.py
```

Рендер chart локально проверен: оба sidecar-контейнера получают новые
requests/limits, основной контейнер Grafana сохраняет прежние параметры,
а конфигурация ссылается на существующие Secret и PVC.
