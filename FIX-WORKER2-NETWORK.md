# Пересоздание worker-2 в ru-central1-a

Наблюдения: на всех узлах pkgs.k8s.io разрешается в 34.107.204.206.
Control plane и worker-1 получают HTTP 200. На worker-2 подключения к
pkgs.k8s.io:443 и api.ipify.org:443 завершаются тайм-аутом. После stop/start
его публичный адрес изменился с 158.160.145.170 на 158.160.145.129, но сбой
сохранился. Это не устанавливает точную причину и не доказывает сбой всей зоны.

Обходной вариант: пересоздать только worker-2 в ru-central1-a, где доступ
с control plane уже проверен. Новый внутренний адрес: 10.20.10.12.
Публичный адрес по-прежнему динамический. Ресурсы и прерываемость не меняются.
Диск старого worker-2 будет удалён; установка Kubernetes до него ещё не дошла.
Подсети a, d, e сохраняются; виртуальные машины размещаются в двух зонах a и e.
Для выбранного self-hosted варианта задания требуется минимум три ВМ;
размещение нод в трёх подсетях относится к альтернативному Managed Kubernetes.

Из корня репозитория:

```bash
terraform -chdir=terraform/main fmt
terraform -chdir=terraform/main validate
terraform -chdir=terraform/main plan
```

Ожидается замена только yandex_compute_instance.nodes["worker-2"]:
1 to add, 0 to change, 1 to destroy. Если план затрагивает другие ресурсы,
не применяйте его, пришлите вывод для проверки.

```bash
terraform -chdir=terraform/main apply
python3 scripts/make-inventory.py
cd ansible
ansible k8s-worker-2 -m wait_for_connection -a 'timeout=180'
ansible k8s-worker-2 -m command -a 'curl -4 -fLsS --connect-timeout 10 --max-time 30 -o /dev/null -w "%{http_code}\n" https://pkgs.k8s.io/core:/stable:/v1.37/deb/Release.key'
```

Если ответ 200:

```bash
ansible-playbook site.yml
```

Сохраните скриншот итогового PLAY RECAP. Для успешного завершения у всех
трёх узлов должны быть failed=0 и unreachable=0.
Если curl снова завершится ошибкой, передайте его вывод; повторять playbook
до восстановления связи не нужно.
