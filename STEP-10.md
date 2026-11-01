# Шаг 10. Оформление сдачи

В архиве: README-REVIEW.md для преподавателя, восемь ранее предоставленных
скриншотов и небольшой patch основного README. Ресурсы и workflow не меняются.

## Применить документацию

Дождитесь завершения текущего Terraform pipeline. Скачайте архив и выполните:

```bash
unzip -o ~/Downloads/devops-diploma-infra-step10.zip -d ~/netology
cd ~/netology/devops-diploma-infra

git pull --ff-only &&
git apply --check patches/final-readme.patch &&
git apply patches/final-readme.patch
```

Если проверка patch завершилась ошибкой, остановитесь и пришлите её текст:
не заменяйте README целиком. Patch рассчитан на опубликованный README от первого
успешного запуска Terraform. Сами новые документы и скриншоты распаковка добавляет
отдельными файлами.

После успешного применения:

```bash
git add README.md README-REVIEW.md STEP-10.md docs/evidence patches/final-readme.patch &&
python3 scripts/check-git-files.py &&
git commit -m "Document completed diploma and add verification screenshots" &&
git push origin main
```

Этот push также запустит Terraform workflow: второй успешный запуск подтвердит
автоматический запуск на следующем коммите. Отдельный пустой коммит не требуется.

## Финальная проверка работающего стенда

```bash
export KUBECONFIG="$HOME/.kube/config"
kubectl --context=diploma get nodes -o wide
kubectl --context=diploma get pods --all-namespaces
python3 scripts/verify-monitoring.py
curl -fsS http://153.51.118.243/healthz
curl -fsS http://153.51.118.243/version.json
```

Ожидаются три Ready-узла, рабочие pod без Pending/CrashLoopBackOff,
успешная проверка мониторинга, healthz ok и версия v1.0.1.
Откройте приложение и Grafana в браузере. При желании добавьте актуальный
скриншот страницы v1.0.1 в docs/evidence: приложенный v1.0.0 является исторической
первичной проверкой; обновление подтверждено скриншотом CD.

## Что отправить преподавателю

Главная ссылка:
https://github.com/sarkroge/devops-diploma-infra/blob/main/README-REVIEW.md

В форме сдачи отдельно укажите:

- репозиторий приложения: https://github.com/sarkroge/devops-diploma-app
- приложение: http://153.51.118.243/
- Grafana: http://153.51.118.243/grafana/
- логин Grafana: admin; пароль — в закрытом поле формы, не в публичном Git.

Для копирования пароля на Mac:

```bash
pbcopy < .secrets/grafana-admin-password
```

Сам пароль и kubeconfig в переписку со скриншотами не отправляются.

## Что ещё относится к демонстрации

Успешные pipeline и скриншоты не доказывают выполнение полного цикла
terraform destroy/apply. Такой цикл текущего стенда отдельно не фиксировался.
Конфигурации и порядок повторной установки подготовлены; перед демонстрацией
нужно согласовать время, сохранить нужные данные и дождаться окончания CI.
Удаление ВМ уничтожает local PV мониторинга. Этот шаг не запускает destroy.

После подтверждения второго pipeline и финальной проверки сдаётся ссылка
на README-REVIEW.md с данными доступа. При остановленных ВМ приложение и Grafana
недоступны: на время проверки оставьте стенд запущенным в пределах бюджета
или согласуйте время запуска с преподавателем.
