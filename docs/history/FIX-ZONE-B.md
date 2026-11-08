# Исправление недоступности ru-central1-b

Первоначальный `apply` создал control-plane и worker-2, обе записи статических IP
и три группы безопасности. Создание worker-1 завершилось ошибкой
`Zone ru-central1-b is not available`. Успешные операции сохранены в удалённом
state. Продолжаем работу с этим состоянием.

## Изменение

- Для worker-1 выбирается `ru-central1-e`, подсеть `10.20.40.0/24`, IP `10.20.40.10`.
- Пустая подсеть `b` удаляется; добавляется подсеть `e` с отдельным диапазоном,
  чтобы создание новой подсети не конфликтовало с существующим CIDR.
- Статический адрес worker-1 заменяется на адрес зоны `e`; прежний адрес ещё
  не использовался созданной ВМ.
- Control-plane в `a` и worker-2 в `d` сохраняют прежнюю конфигурацию.

Платформа и ресурсы worker-1 прежние: `standard-v3`, 2 vCPU, 20%, 2 ГиБ RAM,
прерываемая ВМ, HDD 10 ГиБ. Меняется размещение, расчёт тарифа сохраняется.

## Применение

```bash
unzip -o ~/Downloads/devops-diploma-zone-fix.zip -d ~/netology
cd ~/netology/devops-diploma-infra
terraform -chdir=terraform/main fmt
terraform -chdir=terraform/main validate
terraform -chdir=terraform/main plan
```

При указанном частичном состоянии ожидается:

```text
Plan: 3 to add, 0 to change, 2 to destroy.
```

Создание: подсеть `e`, новый статический IP worker-1 и сама ВМ worker-1.
Удаление: пустая подсеть `b` и неиспользованный статический IP worker-1 в `b`.
Control-plane и worker-2 не должны быть отмечены на изменение или замену.
Если набор изменений другой, разберите план до применения.

```bash
terraform -chdir=terraform/main apply
```

Проверьте план, подтвердите `yes`, затем:

```bash
terraform -chdir=terraform/main output ssh_commands
terraform -chdir=terraform/main plan
```

Повторный план после успешного apply должен показать `No changes`.

Состояние после частичного apply — штатная ситуация Terraform: повторное
применение достраивает отсутствующие ресурсы. Общий `destroy` и удаление state
для этого исправления не нужны.

При новой ошибке создания сохраните её точный текст: доступность зоны и наличие
свободных ресурсов окончательно проверяются облачным API при создании.

## Источники

- https://status.yandex.cloud/ru/incidents/2092
- https://yandex.cloud/en/docs/compute/concepts/vm-platforms
