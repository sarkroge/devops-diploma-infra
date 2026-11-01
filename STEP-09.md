# Шаг 9. Terraform через GitHub Actions

Архив добавляет workflow, зеркало для CI, подготовку Secrets и обновлённый README.
Конфигурации существующих ресурсов Terraform в этом шаге не меняются.

## 1. Распаковать и подготовить lock-файлы

```bash
unzip -o ~/Downloads/devops-diploma-infra-step09.zip -d ~/netology
cd ~/netology/devops-diploma-infra

terraform fmt -recursive terraform
terraform -chdir=terraform/bootstrap providers lock \
  -net-mirror=https://terraform-mirror.yandexcloud.net \
  -platform=darwin_arm64 -platform=linux_amd64 yandex-cloud/yandex
terraform -chdir=terraform/main providers lock \
  -net-mirror=https://terraform-mirror.yandexcloud.net \
  -platform=darwin_arm64 -platform=linux_amd64 yandex-cloud/yandex

python3 scripts/prepare-terraform-ci.py
```

Команды providers lock не применяют инфраструктуру: дополняют существующие
`.terraform.lock.hcl` checksum для Mac и Linux. Оба lock-файла сохраняются в Git.
CI использует `init -lockfile=readonly`.

Скрипт использует существующий `.secrets/terraform-key.json`, outputs локального
bootstrap и `terraform/main/local.auto.tfvars.json`. Ключи повторно не создаются.
SSH public key и admin CIDR берутся из текущей конфигурации, а не из IP runner.
Cloud/folder IDs берутся из local.auto.tfvars.json или TF_VAR_*, затем из yc при
отсутствии. Если ранее использовались дополнительные -var/-var-file, сначала
перенесите эти значения в local.auto.tfvars.json, чтобы CI совпадал с локальным
запуском.

Ожидаются четыре сообщения `Prepared GitHub Secret` и имя бакета. Значения ключей
скрипт не печатает. При ошибке остановитесь и пришлите её текст без credentials.

## 2. Создать репозиторий инфраструктуры

На GitHub создайте **пустой Public** репозиторий `sarkroge/devops-diploma-infra`.
Не добавляйте README, .gitignore или license через интерфейс: они уже есть
локально. Если такой репозиторий уже создан, используйте его и проверьте origin.

## 3. GitHub Secrets и Variable

В новом репозитории: Settings → Secrets and variables → Actions.
Добавьте четыре Repository secrets. Для каждого выполните команду из таблицы,
затем вставьте содержимое буфера в поле Value.

| Имя Secret | Команда копирования из корня infra |
| --- | --- |
| `TF_SA_JSON_CREDENTIALS` | `pbcopy < .secrets/terraform-ci/TF_SA_JSON_CREDENTIALS` |
| `AWS_ACCESS_KEY_ID` | `pbcopy < .secrets/terraform-ci/AWS_ACCESS_KEY_ID` |
| `AWS_SECRET_ACCESS_KEY` | `pbcopy < .secrets/terraform-ci/AWS_SECRET_ACCESS_KEY` |
| `TF_INPUTS_JSON` | `pbcopy < .secrets/terraform-ci/TF_INPUTS_JSON` |

На вкладке Variables добавьте Repository variable:

| Имя | Значение текущего стенда |
| --- | --- |
| `TF_STATE_BUCKET` | `sarkroge-diploma-state-b1g90k05go90aj6v84m2` |

Это настройки репозитория инфраструктуры; Secrets приложения автоматически сюда
не переносятся. Приватный SSH-ключ и kubeconfig CI Terraform не нужны.
Значения Secrets не включайте в скриншоты или README.

## 4. Сохранить и отправить в Git

Во время CI не запускайте локальный apply/destroy или операции state:
concurrency ограничивает только workflow в этом репозитории. Распределённой
блокировки между CI и Mac нет.

Из корня infra:

```bash
git status --short
git branch --show-current
git remote -v
```

Если Git ещё не инициализирован: `git init -b main`. Если текущая ветка master,
переименуйте её `git branch -m main`. Для другой существующей ветки сначала
разберите её изменения; не применяйте git reset --hard.

Добавьте конфигурации (.gitignore исключает credentials/state):

```bash
git add .gitignore README.md terraform ansible kubernetes scripts ci .github patches
git add -- '*.md'
python3 scripts/check-git-files.py
git diff --cached --stat
```

Проверка должна завершиться `Git index: no Terraform state...`.
Если найден файл, не публикуйте его: уберите путь из индекса
`git rm --cached -- путь` (не удаляя локальную копию), проверьте снова.
Это проверка текущего индекса, а не аудит истории старого репозитория.
Не используйте git add -f. Если ключи попали в предыдущие коммиты, остановитесь
до публикации и разберите историю.

Если origin отсутствует, добавьте его:

```bash
git remote add origin https://github.com/sarkroge/devops-diploma-infra.git
```

Если он уже существует, проверьте, что URL указывает на этот репозиторий.
Затем:

```bash
git commit -m "Add infrastructure, Kubernetes, monitoring and Terraform pipeline"
git push -u origin main
```

## 5. Проверка pipeline и скриншоты

Actions → Terraform infrastructure → первый запуск. Ожидаются зелёные задачи:

1. validate: fmt, init без backend и validate обеих конфигураций.
2. apply: существующий S3 backend, plan, применение сохранённого плана,
   повторный plan с No changes.

При совпадении конфигурации и state первый apply покажет 0 added / 0 changed /
0 destroyed — это корректно. Bootstrap в Actions не применяется. Plan сохраняется
только в рабочем каталоге runner, не как artifact.

Сохраните скриншот успешного запуска, раскрытого Apply saved plan и
Confirm infrastructure matches configuration. Длинный refresh-вывод не нужен.

Чтобы проверить следующий коммит без изменения облачных ресурсов, после
завершения первого запуска:

```bash
git commit --allow-empty -m "Verify Terraform pipeline on main push"
git push origin main
```

Должен появиться второй успешный запуск. queue: max сохраняет несколько
ожидающих запусков в очереди (до лимита GitHub), cancel-in-progress: false
сохраняет уже выполняющийся apply. Pull request запускает только проверки.

При красном статусе пришлите название шага и конец лога. Не удаляйте state
и не запускайте destroy для исправления ошибки CI.

## Проверка подготовки

Workflow проверен локально. queue: max сверён с актуальной документацией GitHub;
actionlint 1.7.12 ещё не знает этот ключ, остальной workflow проверен линтером.
Terraform init с Linux-провайдером выполнен. Полный validate в среде подготовки
ограничен запретом локальных Unix sockets для плагина; его выполняет CI.
Облачный apply и корректность GitHub Secrets подтверждаются реальным запуском.

## Документация

- https://yandex.cloud/en/docs/terraform/quickstart
- https://developer.hashicorp.com/terraform/cli/commands/providers/lock
- https://developer.hashicorp.com/terraform/language/backend/s3
- https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency
- https://github.com/hashicorp/setup-terraform
