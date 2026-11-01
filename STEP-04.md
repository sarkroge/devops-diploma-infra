# Шаг 4: Kubernetes через Ansible

Предполагается, что три ВМ уже созданы, Terraform показывает `No changes`, а
локальные `.secrets/terraform-key.json` и `.secrets/diploma-ssh` сохранены.
ВМ используют зоны `a`, `e`, `d` после исправления недоступности зоны `b`.

## Результат этапа

- Kubernetes 1.37.2: один control plane и два worker.
- containerd.io 2.4.2-3 для Ubuntu 24.04, systemd cgroups и CRI.
- Flannel v0.28.10: сеть pod `10.244.0.0/16`; сеть Service `10.96.0.0/12`.
- Взаимодействие нод и join через внутренние адреса Yandex VPC.
- Доступ с Mac через публичный статический IP control plane, TLS с проверкой CA.
- Контекст `diploma` в `~/.kube/config`; существующие контексты сохраняются.

Точные пакеты и сетевые диапазоны заданы в `ansible/group_vars/all.yml`.
Приложение, ingress и мониторинг устанавливаются следующими этапами.

## Что находится в архиве

- `ansible/site.yml` — четыре play: подготовка нод, control plane, workers, проверка.
- Роли `node`, `control_plane`, `worker`, `verify`.
- `scripts/make-inventory.py` — inventory из `terraform output -json nodes`.
- `scripts/install-kubeconfig.py` — настройка внешнего API и слияние kubeconfig.

Роли используют только `ansible.builtin`; дополнительные коллекции не нужны.
Локальные скрипты используют Python standard library, Terraform CLI и kubectl.
Секретные ключи и полученный kubeconfig в архив не включены.

## Запуск с Mac

Распакуйте архив в существующий проект:

```bash
unzip ~/Downloads/devops-diploma-infra-step04.zip -d ~/netology
cd ~/netology/devops-diploma-infra
python3 scripts/make-inventory.py
cd ansible
ansible all -m ping
```

Inventory записывается в `.secrets/ansible-inventory.json`; путь закрыт исходным
`.gitignore`. Нужны рабочие backend credentials из шага 2. В новом терминале
повторите экспорты из `STEP-02.md`, не создавая повторно ключ сервисного аккаунта.

У всех трёх узлов должен быть результат `pong`. Ansible использует стандартную
проверку SSH host keys: новые ключи принимаются при первом соединении
(`accept-new`), изменившиеся ключи вызывают ошибку. При неожиданной смене
отпечатка разберитесь с причиной до удаления записи из known_hosts.

Если SSH зависает, проверьте запущенность ВМ, текущий внешний IP администратора
и правило SSH/22 из шага 3. После смены IP обновите входные данные скриптом
`prepare-vms.sh` и примените план группы безопасности. После перезапуска worker-2
обновите state через `terraform apply -refresh-only` и пересоздайте inventory:
его публичный IP динамический.

После успешного ping:

```bash
ansible-playbook site.yml --syntax-check
ansible-playbook site.yml
```

На доле CPU 20% установка может занимать заметное время. Playbook ожидает
готовность SSH и cloud-init, устанавливает зависимости и пакеты, готовит runtime,
инициализирует control plane, устанавливает Flannel и присоединяет workers.

Результат установки проверяется ожиданием трёх Ready-нод, rollout Flannel и
CoreDNS. В успешном `PLAY RECAP` у всех узлов должны быть `failed=0`, `unreachable=0`.

## Kubeconfig на Mac

После успешного playbook вернитесь в корень проекта:

```bash
cd ..
python3 scripts/install-kubeconfig.py
export KUBECONFIG="$HOME/.kube/config"
kubectl config current-context
kubectl get nodes -o wide
kubectl get pods --all-namespaces
```

Скрипт сначала создаёт отдельный конфиг в `.secrets/kubeconfig-diploma` и проверяет
доступ к `/readyz`. Затем объединяет новый контекст с существующими в
`~/.kube/config`; прежний default-файл при изменении копируется в защищённый
backup в `.secrets`. Копирование credentials в терминал не требуется.

Ожидается контекст `diploma`, три ноды `Ready` и системные pod без ошибок.
Worker-1 будет иметь внутренний адрес `10.20.40.10`, worker-2 — `10.20.30.10`.
После установки Kubernetes колонка EXTERNAL-IP у нод может быть пустой: этот
self-hosted кластер не использует cloud-controller-manager, а доступ к API
обеспечивается адресом из kubeconfig и настройками VPC.

## Скриншоты для отчёта

1. `ansible all -m ping`: три успешных ответа.
2. Окончание playbook с `PLAY RECAP`, `failed=0` и `unreachable=0`.
3. `kubectl get nodes -o wide`: три Ready-ноды.
4. `kubectl get pods --all-namespaces`: системные pod в рабочем состоянии.

Не выводите содержимое admin kubeconfig или приватных ключей для скриншотов.
Задачи с bootstrap-токенами и kubeconfig скрывают содержимое через `no_log`.

## Повторный запуск и диагностика

Наличие `admin.conf` предотвращает повторный `kubeadm init`, а `kubelet.conf` —
повторный join уже настроенного worker. Это не сценарий автоматического
обновления версии Kubernetes: для upgrade нужен отдельный порядок действий.
При частично неудачной инициализации сохранившиеся файлы и конкретную ошибку
нужно разобрать до ручного reset; playbook не выполняет reset автоматически.

Для начальной диагностики доступны:

```bash
ansible all -b -m command -a 'systemctl is-active containerd'
ansible all -b -m command -a 'journalctl -u kubelet -n 50 --no-pager'
ansible all -b -m command -a 'crictl ps -a'
```

Если ошибка скачивания пакета или образа, пришлите точный URL и текст ошибки:
доступ к GitHub, pkgs.k8s.io, Docker apt и registry проверяется из облачных ВМ
во время установки. Номера версий не заменяются на `latest` автоматически.

## Остановка стенда

После работы из корня проекта:

```bash
bash scripts/nodes.sh stop
```

Для продолжения используйте порядок запуска и обновления outputs из `STEP-03.md`.

## Верификация артефакта

Локально проверены синтаксис Python и YAML/Jinja-шаблоны, а также Ansible
`--syntax-check`. Подключение к ВМ, загрузка пакетов и работоспособность
развёрнутого кластера должны быть проверены фактическим запуском у пользователя.

## Документация

- https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/install-kubeadm/
- https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/create-cluster-kubeadm/
- https://kubernetes.io/docs/setup/production-environment/container-runtimes/
- https://kubernetes.io/docs/reference/config-api/kubeadm-config.v1beta4/
- https://github.com/kubernetes/kubernetes/releases/tag/v1.37.2
- https://github.com/flannel-io/flannel/releases/tag/v0.28.10
- https://download.docker.com/linux/ubuntu/dists/noble/pool/stable/amd64/
