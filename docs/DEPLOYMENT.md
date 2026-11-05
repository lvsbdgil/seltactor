# Развёртывание на myserver

Домен: https://seltavir.alexanderlych.ru
Каталог приложения: `/home/admin/seltavir`.

Два контейнера в отдельном Compose-проекте `seltavir`:

- `seltavir-web`: Caddy 2, раздаёт только собранный `dist`, проксирует `/api/*` в API.
- `seltavir-api`: Python, FastAPI, FFmpeg и официальный SDK OpenAI. Один worker сохраняет согласованность сессий и очереди в памяти.

Оба подключены к существующей внешней сети `proxy`, порты приложения на хост не публикуются. Существующий `caddy-gateway` завершает TLS и направляет только новый домен в `seltavir-web:80`. Конфигурация добавляемого сайта: `deploy/Caddyfile.gateway`. Остальные сайты и контейнеры не пересоздаются.

На сервере использован уже существующий ARM64-образ `tiangolo/uvicorn-gunicorn-fastapi:python3.11-slim`, поскольку DNS `auth.docker.io` был недоступен. Версии Python-зависимостей устанавливаются из `backend/requirements.lock`, запуск явно задан через один Uvicorn worker, стандартные скрипты Gunicorn базового образа не используются. Базовый образ переопределяется build-аргументом `BASE_IMAGE`.

## Конфигурация

`/home/admin/seltavir/.env.production`, права `600`: `OPENAI_API_KEY`, `OPENAI_MODEL`, `ADMIN_USERNAME`, `ADMIN_PASSWORD_HASH`. Сам пароль и исходный файл ключа на сервер сайта не копируются. Образы и репозиторий не содержат секретов.

Compose задаёт `COOKIE_SECURE=true` и `ALLOWED_ORIGINS=https://seltavir.alexanderlych.ru`. Разрешение источника проверяется при входе и изменяющих API-запросах. Используются прежние локальные данные администратора.

## Обновление

Из полной рабочей копии проекта:

```bash
npm ci
npm run build
docker compose -f deploy/compose.yaml build --pull=false
docker compose -f deploy/compose.yaml up -d --no-build
```

При передаче собранного приложения копируются только `dist`, `deploy`, `.dockerignore`, Python-модули backend и lock-файл. Не копировать `key`, `.env`, `admin-credentials.txt`, `.venv` и `node_modules`. На сервере не требуется Node.js для запуска готовой сборки.

## Проверка и перезапуск

```bash
cd /home/admin/seltavir
docker compose -f deploy/compose.yaml ps
docker compose -f deploy/compose.yaml restart api
curl -fsS https://seltavir.alexanderlych.ru/api/health
```

Не используйте команды остановки общих Docker-сервисов или других Compose-проектов. Перезапуск API сбрасывает администраторские сессии и историю заданий.

Реальные вызовы OpenAI зависят от доступного баланса API-проекта. Последняя локальная проверка ключа вернула `credit_balance_exhausted`; демопримеры и авторизация работают независимо от этого ограничения.
