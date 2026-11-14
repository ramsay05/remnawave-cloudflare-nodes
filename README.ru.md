<p align="center">
  <img src="https://raw.githubusercontent.com/ramsay05/remnawave-cloudflare-nodes/master/.github/images/logo.webp" alt="remnawave-cloudflare-nodes" width="800px">
</p>

## remnawave-cloudflare-nodes

<p align="left">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.12-blue.svg" alt="Python 3.12"></a>
  <a href="https://opensource.org/licenses/GPL-3.0"><img src="https://img.shields.io/badge/license-GPLv3-green.svg" alt="License: GPL v3"></a>
</p>

[English](README.md) | Русский

> Настройки логирования, API и Telegram перенесены из `config.yml` в `.env`.
> См. [Гайд по миграции](docs/MIGRATION.md).

Сервис для автоматического управления DNS-записями Cloudflare в зависимости от состояния нод
Remnawave (https://docs.rw).

Форк [hteppl/remnawave-cloudflare-nodes](https://github.com/hteppl/remnawave-cloudflare-nodes) с исправлениями совместимости API и локальной сборкой Docker.

## Возможности

- **Мониторинг нод** - Отслеживание состояния нод через Remnawave API
- **Управление DNS** - Автоматическое добавление и удаление A-записей
- **Автоопределение зон** - Получение Zone ID по имени домена
- **Мультидоменность** - Поддержка нескольких доменов и зон
- **Telegram-уведомления** - Оповещения об изменении статуса нод, DNS и критических событиях
- **HTTP API** - Управление конфигурацией в реальном времени через защищенный REST API
- **Tailscale / Альтернативные адреса** - Маппинг публичных DNS IP на внутренние адреса нод (Tailscale, VPN, NAT)
- **Гибкая настройка** - Настраиваемые интервалы проверок
- **Docker** - Локальная сборка образа из кода форка через Docker Compose

## Требования

- **Remnawave Panel** с добавленными нодами
- **Remnawave API Token** - генерируется в настройках панели
- **Cloudflare** с настроенными DNS-зонами
- **Cloudflare API Token** - с правами Zone:DNS:Edit и Zone:Zone:Read

## Настройка

Ограничьте токен Cloudflare управляемыми зонами. `Zone:Zone:Read` нужен для
автоопределения Zone ID, а `Zone:DNS:Edit` — для чтения и изменения DNS-записей.

TTL и статус проксирования существующих A-записей синхронизируются в каждом цикле.
При `proxied: true` используется Auto TTL (`1` в API, сейчас 300 секунд).
Для DNS-only укажите Auto или 60–86400 секунд (30–59 доступны на Enterprise).
Подробности: [совместимость API и локальные тесты](docs/API-COMPATIBILITY.md).

Скопируйте [`.env.example`](.env.example) в `.env`:

```env
# Remnawave
REMNAWAVE_API_URL=https://panel.example.com
REMNAWAVE_API_KEY=remnawave_api_key

# Cloudflare (токен с правами Zone:DNS:Edit и Zone:Zone:Read для управляемых зон)
CLOUDFLARE_API_TOKEN=cloudflare_api_token

# API
API_ENABLED=false
API_TOKEN=  # Сгенерировать: openssl rand -hex 32
API_HOST=0.0.0.0
API_PORT=8741
API_DOCS=false

# Telegram-уведомления
TELEGRAM_ENABLED=false
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=123456789
TELEGRAM_TOPIC_ID=  # ID топика (для форумов, иначе оставить пустым)

# Фильтры уведомлений
TELEGRAM_NOTIFY_NODE_CHANGES=true
TELEGRAM_NOTIFY_DNS_CHANGES=true
TELEGRAM_NOTIFY_ERRORS=true
TELEGRAM_NOTIFY_CRITICAL=true
TELEGRAM_NOTIFY_API_CHANGES=true

# Язык уведомлений (en, ru)
LANGUAGE=ru
# Часовой пояс и формат времени
TIMEZONE=UTC
TIME_FORMAT="%d.%m.%Y %H:%M:%S"
# Уровень логов (DEBUG, INFO, WARNING, ERROR, CRITICAL)
LOG_LEVEL=INFO
```

Скопируйте [`config.example.yml`](config.example.yml) в `config.yml`:

```yaml
remnawave:
  check-interval: 30

domains:
  - domain: example1.com
    zones:
      - name: s1          # Создаёт s1.example1.com
        ttl: 60
        proxied: false
        ips:
          - 1.2.3.4
          - 5.6.7.8
      - name: "@"         # Создаёт корневую запись для example1.com
        ttl: 60
        proxied: false
        ips:
          - 1.2.3.4

  - domain: example2.com
    zones:
      - name: s2
        ttl: 60
        proxied: false
        ips:
          - 13.14.15.16
          - 17.18.19.20
```

### Корневые (apex) записи домена

Используйте `name: "@"`, чтобы создать A-запись для самого корневого домена (`example.com`), а не для поддомена:

```yaml
domains:
  - domain: example.com
    zones:
      - name: "@"       # A-запись для example.com
        ttl: 60
        proxied: false
        ips:
          - 1.2.3.4
      - name: sub       # A-запись для sub.example.com
        ttl: 60
        proxied: false
        ips:
          - 5.6.7.8
```

> **Важно:** При работе с apex-зонами через HTTP API необходимо URL-кодировать `@` как `%40` в пути запроса:
> ```
> PATCH /api/config/domains/example.com/zones/%40
> DELETE /api/config/domains/example.com/zones/%40
> ```

### Форматы нод

Зоны поддерживают два формата указания нод для мониторинга.

**`ips` — простой список IP**

```yaml
zones:
  - name: s1
    ttl: 60
    ips:
      - 1.2.3.4
      - 5.6.7.8
```

Каждый IP записывается в Cloudflare DNS и используется для поиска ноды в Remnawave.

**`nodes` — расширенный формат с отдельными адресами**

```yaml
zones:
  - name: s1
    ttl: 60
    nodes:
      - ip: 1.2.3.4
        address: 100.64.0.1  # Tailscale или внутренний адрес ноды в Remnawave
      - ip: 5.6.7.8
        address: 100.64.0.2
```

- `ip` — IP, записываемый в Cloudflare DNS.
- `address` — адрес ноды в Remnawave (`node.address`). Используется, если нода доступна через Tailscale, VPN или иной
  адрес, отличный от публичного IP. Если не указан, по умолчанию равен `ip`.

Оба формата можно смешивать внутри одной зоны и между разными зонами.

### Параметры

#### Переменные окружения (.env)

| Переменная                     | Описание                                         | По умолчанию        | Обязательно        |
|--------------------------------|--------------------------------------------------|---------------------|--------------------|
| `REMNAWAVE_API_URL`            | Адрес панели Remnawave                           | -                   | Да                 |
| `REMNAWAVE_API_KEY`            | API токен Remnawave                              | -                   | Да                 |
| `CLOUDFLARE_API_TOKEN`         | API токен Cloudflare (Zone:DNS:Edit и Zone:Zone:Read)                  | -                   | Да                 |
| `LOG_LEVEL`                    | Уровень логов (`DEBUG` `INFO` `WARNING` `ERROR`) | `INFO`              | Нет                |
| `API_ENABLED`                  | Включить HTTP API                                | `false`             | Нет                |
| `API_HOST`                     | Адрес привязки API-сервера                       | `0.0.0.0`           | Нет                |
| `API_PORT`                     | Порт API-сервера                                 | `8741`              | Нет                |
| `API_DOCS`                     | Swagger UI по адресу `/api/docs`                 | `false`             | Нет                |
| `API_TOKEN`                    | Токен API — строго 64 символа hex                | -                   | При включенном API |
| `TELEGRAM_ENABLED`             | Включить Telegram-уведомления                    | `false`             | Нет                |
| `TELEGRAM_BOT_TOKEN`           | Токен бота (@BotFather)                          | -                   | Нет                |
| `TELEGRAM_CHAT_ID`             | ID чата для уведомлений                          | -                   | Нет                |
| `TELEGRAM_TOPIC_ID`            | ID топика (для форумов)                          | -                   | Нет                |
| `TELEGRAM_NOTIFY_NODE_CHANGES` | Уведомления об изменении статуса нод             | `true`              | Нет                |
| `TELEGRAM_NOTIFY_DNS_CHANGES`  | Уведомления об изменениях DNS                    | `true`              | Нет                |
| `TELEGRAM_NOTIFY_ERRORS`       | Уведомления об ошибках                           | `true`              | Нет                |
| `TELEGRAM_NOTIFY_CRITICAL`     | Уведомление при падении всех нод                 | `true`              | Нет                |
| `TELEGRAM_NOTIFY_API_CHANGES`  | Уведомления об изменениях через HTTP API         | `true`              | Нет                |
| `LANGUAGE`                     | Язык уведомлений (`en`, `ru`)                    | `en`                | Нет                |
| `TIMEZONE`                     | Часовой пояс                                     | `UTC`               | Нет                |
| `TIME_FORMAT`                  | Формат времени                                   | `%d.%m.%Y %H:%M:%S` | Нет                |

#### config.yml

| Ключ                       | Описание                 | По умолчанию | Обязательно |
|----------------------------|--------------------------|--------------|-------------|
| `remnawave.check-interval` | Интервал проверки (сек)  | `30`         | Нет         |
| `domains`                  | Список доменов и DNS-зон | `[]`         | Да          |

## Установка

### Docker: локальная сборка на сервере (рекомендуется)

На Linux-сервере нужны Git, Docker Engine и плагин Docker Compose.
Проверьте команды `git --version`, `docker --version` и `docker compose version`.
Установка Docker: https://docs.docker.com/engine/install/.

1. Скачайте этот форк:

```bash
git clone https://github.com/ramsay05/remnawave-cloudflare-nodes.git
cd remnawave-cloudflare-nodes
```

2. Создайте файлы конфигурации до запуска Compose:

```bash
cp .env.example .env
cp config.example.yml config.yml
cp hosts.example.yml hosts.yml
nano .env
nano config.yml
nano hosts.yml
```

В `.env` заполните `REMNAWAVE_API_URL` — адрес панели без `/api`,
`REMNAWAVE_API_KEY` и `CLOUDFLARE_API_TOKEN`. Токену Cloudflare нужны права
**Zone / DNS / Edit** и **Zone / Zone / Read** для управляемых зон.
В `config.yml` замените домены и IP своими значениями по примерам выше.
Для прямого подключения к нодам оставьте `proxied: false`.

Синхронизация хостов по умолчанию выключена (`DISABLE_UNREACHABLE_HOSTS=false`).
Чтобы включить её, замените примеры UUID в `hosts.yml` реальными UUID нужных
хостов и установите `DISABLE_UNREACHABLE_HOSTS=true`. Отсутствующий или пустой
список означает управление **всеми хостами, адрес которых совпадает с управляемым DNS-именем**.
Файл `hosts.yml` должен существовать для монтирования в Compose даже при выключенной синхронизации.

3. Соберите образ и запустите контейнер:

```bash
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 -f
```

В готовом `docker-compose.yml` уже указаны `build: .` и
`image: remnawave-cloudflare-nodes:local`. Docker собирает приложение из кода
этой копии репозитория по включённому Dockerfile. Аккаунт Docker Hub и настройка
GitHub Actions не нужны; для первой сборки нужен доступ в Интернет для скачивания
базового образа Python и зависимостей. Выход из просмотра логов — Ctrl+C;
контейнер продолжит работать в фоне.

`.env`, `config.yml` и `hosts.yml` исключены из Git. Храните реальные токены и
конфигурацию на сервере. Файлы настроек и каталог `logs/` подключены как bind mounts
и сохраняются при пересоздании контейнера. HTTP API по умолчанию выключен;
готовый Compose не публикует порты на сервере.

### Обновление локальной Docker-установки

Выполните в каталоге скачанного репозитория:

```bash
git pull --ff-only
docker compose up -d --build
docker compose logs --tail=100
```

При обновлении не копируйте примеры поверх своих файлов настроек.
Одного `docker compose pull` недостаточно: локальный образ нужно пересобрать.
Если переходите с образа автора из Docker Hub, сначала остановите старую установку
командой `docker compose down` в её каталоге, затем перенесите её настройки
в эту копию репозитория. Для одних DNS-имён должен работать только один монитор.

Остановка этой установки:

```bash
docker compose down
```

### Запуск без Docker (Python 3.12+)

Скачайте форк и подготовьте все три файла настроек по инструкции выше, затем:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m src
```

На Windows создайте окружение командой `python -m venv .venv` и активируйте
в PowerShell: `.\.venv\Scripts\Activate.ps1`. Программа работает в текущем
терминале; автоматический перезапуск предусмотрен в рекомендованной установке через Compose.

## Принцип работы

1. **Запуск** - Сервис получает список нод из Remnawave и определяет Zone ID в Cloudflare

2. **Проверка состояния** - Нода считается рабочей, если:
    - `is_connected = true`
    - `is_disabled = false`

3. **Синхронизация DNS** - Для каждой зоны сопоставляет `address` каждой записи со статусом ноды, затем:
    - Добавляет A-записи для IP, чьи ноды работают
    - Удаляет A-записи для IP, чьи ноды недоступны

4. **Цикл** - Проверка повторяется каждые `check-interval` секунд

## Telegram-уведомления

Сервис отправляет уведомления о событиях в Telegram.

### Подключение

1. Создайте бота через [@BotFather](https://t.me/BotFather)
2. Узнайте свой chat ID через [@username_to_id_bot](https://t.me/username_to_id_bot)
3. Добавьте бота в чат
4. Настройте в `.env`:

```env
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=123456789
TELEGRAM_TOPIC_ID=              # Опционально: для форумов
LANGUAGE=ru                     # en, ru
```

### Типы уведомлений

| Событие            | Описание            | Пример                                                                          |
|--------------------|---------------------|---------------------------------------------------------------------------------|
| **Нода онлайн**    | Нода доступна       | ✅ Нода онлайн<br>node-1 (1.2.3.4) доступна.<br>📊 Ноды: 5/6 онлайн, 0 отключено |
| **Нода офлайн**    | Нода недоступна     | ❌ Нода офлайн<br>node-1 (1.2.3.4) недоступна.<br>Причина: disconnected          |
| **DNS добавлен**   | Добавлена A-запись  | 📝 DNS обновлен<br>Добавлен 1.2.3.4 → s1.example.com                            |
| **DNS удален**     | Удалена A-запись    | 🗑️ DNS удален<br>Удален 1.2.3.4 из s1.example.com                              |
| **Критическая**    | Все ноды недоступны | 🔴 КРИТИЧНО: Все ноды недоступны                                                |
| **Восстановление** | Ноды снова онлайн   | 🟢 Восстановление: Ноды снова онлайн                                            |
| **Запуск**         | Сервис запущен      | 🚀 Сервис запущен                                                               |
| **Остановка**      | Сервис остановлен   | 🛑 Сервис остановлен                                                            |

### Фильтрация уведомлений

```env
TELEGRAM_NOTIFY_NODE_CHANGES=true   # Статус нод
TELEGRAM_NOTIFY_DNS_CHANGES=true    # Изменения DNS
TELEGRAM_NOTIFY_ERRORS=true         # Ошибки
TELEGRAM_NOTIFY_CRITICAL=true       # Падение всех нод
TELEGRAM_NOTIFY_API_CHANGES=true    # Изменения через HTTP API
```

## HTTP API

Сервис включает опциональный REST API для управления конфигурацией в реальном времени.

Полная документация: **[docs/API.md](docs/API.md)**

### Быстрый старт

1. Сгенерируйте токен:

```bash
openssl rand -hex 32
```

2. Включите в `.env`:

```env
API_ENABLED=true
API_TOKEN=<сгенерированный токен>
API_HOST=0.0.0.0
API_PORT=8741
API_DOCS=false
```

### Reverse proxy

Примеры конфигурации для проброса API через reverse proxy:

- **Caddy** — [`docs/Caddyfile.example`](docs/Caddyfile.example)
- **Nginx** — [`docs/nginx.example.conf`](docs/nginx.example.conf)

Подключите reverse proxy к сети проекта, чтобы он мог обращаться к контейнеру по имени:

```yaml
networks:
  remnawave-cloudflare-nodes:
    external: true
```

### CLI

Внутри контейнера доступен интерактивный CLI для диагностики и управления конфигурацией:

```bash
docker exec -it remnawave-cloudflare-nodes cli
```

Навигация стрелками, выбор через Enter:

```
  remnawave-cloudflare-nodes

? Select action:
 ❯ Show config
   Validate config
   Reload config (hot)
   ──────────────────
   Exit
```

| Пункт               | Описание                                                       |
|---------------------|----------------------------------------------------------------|
| **Show config**     | Показать домены, зоны, ноды и настройки сервиса                |
| **Validate config** | Проверить `config.yml`, вывести ошибки или сводку              |
| **Reload config**   | Применить изменения из `config.yml` без перезапуска контейнера |

### Логи

```bash
# Docker
docker compose logs -f

# Ручная установка
# stdout + logs/app.log
```

## Миграция

Обновляетесь со старой версии? См. [Гайд по миграции](docs/MIGRATION.md).

## Лицензия

[GNU General Public License v3.0](LICENSE)
