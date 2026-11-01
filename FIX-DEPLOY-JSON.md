# Исправление JSONDecodeError: Extra data

Traefik и imagePullSecret уже установлены успешно. Команда kubectl create
с --dry-run=client -k и -o json может вывести несколько JSON-объектов подряд.
Первоначальный скрипт ожидал один JSON List, поэтому завершился до применения
манифестов приложения.

Обновлённый scripts/deploy-app.py последовательно разбирает JSON-объекты
и собирает их в один Kubernetes List. Также поддерживаются вывод List
и одиночный ресурс. Некорректный или пустой вывод останавливает деплой
до kubectl apply.

После распаковки исправления выполните из корня инфраструктурного проекта:

```bash
cd ~/netology/devops-diploma-infra
python3 scripts/deploy-app.py v1.0.0

WEB_IP="$(terraform -chdir=terraform/main output -raw web_ip)"
curl -fsS --max-time 15 "http://$WEB_IP/healthz"
curl -fsS --max-time 15 "http://$WEB_IP/version.json"
open "http://$WEB_IP/"
```

Ожидается успешный rollout двух реплик и версия v1.0.0.
Повторять Terraform apply, создание ключа/Secret и установку Traefik
для исправления этой ошибки не требуется.

Локально проверены поток нескольких JSON-объектов, List, одиночный ресурс,
отклонение пустого/повреждённого вывода и подстановка образа из Terraform
в итоговый manifest на пути к kubectl apply. Работоспособность подов и HTTP
проверяется указанными командами в вашем кластере.
