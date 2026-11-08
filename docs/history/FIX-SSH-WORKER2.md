# SSH к worker-2 через control plane

Проверка показала, что все три ВМ работают, а SSH к `10.20.30.10` через control
plane успешно возвращает `k8s-worker-2`. Для Ansible закреплён тот же маршрут.

Обновлён `scripts/make-inventory.py`: worker-2 использует внутренний адрес и
ProxyCommand через публичный адрес control plane из Terraform outputs.
Пути SSH-ключа экранируются, включая пути с пробелами. Приватный ключ остаётся
на Mac; на control plane ничего копировать не требуется.

Из любой папки:

```bash
unzip -o ~/Downloads/devops-diploma-ssh-fix.zip -d ~/netology
cd ~/netology/devops-diploma-infra
python3 scripts/make-inventory.py
cd ansible
ansible all -m ping
```

После трёх успешных `pong`:

```bash
ansible-playbook site.yml --syntax-check
ansible-playbook site.yml
```

Продолжение установки kubeconfig описано в `STEP-04.md`.
Изменение inventory не требует `terraform apply` и не пересоздаёт ВМ.
