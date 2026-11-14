# Video Scheduler — публикация видео в TikTok

Веб-кабинет + Telegram-бот для загрузки видео в TikTok через официальный
**Content Posting API**. Один Python-бэкенд: OAuth TikTok, загрузка видео,
статусы публикации, бот на aiogram.

> Демо-режим включается автоматически, если не заданы `TIKTOK_CLIENT_KEY` и
> `TIKTOK_CLIENT_SECRET`: все экраны работают, но видео никуда не отправляется.

## Что внутри

| Файл | Назначение |
|---|---|
| `app/main.py` | FastAPI: лендинг, кабинет, OAuth callback, API загрузки |
| `app/tiktok.py` | TikTok Login Kit + Content Posting API, chunked upload |
| `app/posting.py` | публикация, обновление токена, статусы, демо-режим |
| `app/bot.py` | Telegram-бот: видео → черновики/публикация |
| `app/storage.py` | SQLite: аккаунты, токены, посты, pending-загрузки |
| `site/` | лендинг и юридические страницы для GitHub Pages / ревью TikTok |
| `scripts/record_demo.py` | запись демо-видео и скриншотов через Playwright |
| `scripts/make_sample_video.py` | генерация тестового вертикального видео |
| `demo/` | готовое демо-видео и кадры |
| `docs/` | инструкция по заявке в TikTok и сценарий демо |

## Быстрый старт (демо)

```bash
cd /root/projects/tiktok-poster
python3 -m pip install --break-system-packages -r requirements.txt
DEMO_MODE=1 BASE_URL=http://127.0.0.1:8000 python3 run.py
```

Откройте `http://127.0.0.1:8000`, нажмите «Подключить TikTok» — откроется
демо-экран авторизации, затем кабинет. Загрузите `demo/sample.mp4`.

Тесты:

```bash
python3 -m unittest discover -s tests -v
```

## Реальный режим

1. Создайте приложение на <https://developers.tiktok.com/>.
2. Добавьте продукты **Login Kit** и **Content Posting API**.
3. В Login Kit укажите redirect URI:
   `https://ВАШ-ДОМЕН/auth/tiktok/callback` — символ в символ, как в `.env`.
4. Запросите scopes: `user.info.basic`, `video.upload`, `video.publish`.
5. Заполните `.env` (см. `.env.example`) и перезапустите:

```bash
BASE_URL=https://ВАШ-ДОМЕН \
TIKTOK_CLIENT_KEY=... \
TIKTOK_CLIENT_SECRET=... \
TIKTOK_REDIRECT_URI=https://ВАШ-ДОМЕН/auth/tiktok/callback \
TELEGRAM_BOT_TOKEN=... \
CONTACT_EMAIL=you@example.com \
SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_urlsafe(48))") \
DEMO_MODE=0 \
python3 run.py
```

Важно: пока приложение не прошло аудит TikTok, **прямая публикация**
(`mode=direct`) обычно недоступна — используйте черновики (`mode=inbox`).
Подробности и чек-лист: [`docs/TIKTOK_SUBMISSION_RU.md`](docs/TIKTOK_SUBMISSION_RU.md).

## Деплой на Render

В репозитории есть `render.yaml` и `Dockerfile`.

1. Запушьте репозиторий на GitHub.
2. Render → **New → Blueprint** → выберите репозиторий.
3. Заполните `BASE_URL`, `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`,
   `TIKTOK_REDIRECT_URI`, `TELEGRAM_BOT_TOKEN`, `CONTACT_EMAIL`.
4. Подключите диск (`/app/data`) — иначе SQLite и видео исчезнут при рестарте.
5. В TikTok Developer Portal укажите redirect URI с доменом Render.

Free-инстанс Render засыпает без трафика; для стабильной работы бота и OAuth
лучше платный инстанс или VPS с Docker.

Docker:

```bash
docker build -t video-scheduler .
docker run -p 8000:8000 --env-file .env -v "$PWD/data:/app/data" video-scheduler
```

## Telegram-бот

1. `@BotFather` → `/newbot` → токен.
2. Укажите `TELEGRAM_BOT_TOKEN` и публичный `BASE_URL` (бот даёт ссылку на OAuth).
3. Запустите `python3 run.py` — веб и бот работают в одном процессе.
4. В боте: `/start` → «Подключить TikTok» → отправьте видео с подписью →
   выберите «В черновики» или «Опубликовать».

Ограничение Telegram Bot API: бот может скачать файл только до **20 МБ**.
Большие видео загружайте через сайт.

## Демо-видео и кадры

```bash
python3 scripts/make_sample_video.py
python3 -m playwright install chromium
DEMO_MODE=1 BASE_URL=http://127.0.0.1:8000 python3 run.py
python3 scripts/record_demo.py --url http://127.0.0.1:8000
```

Результат: `demo/video/video-scheduler-demo.mp4` и `demo/frames/*.png`
(лендинг, экран авторизации, кабинет, загрузка, обработка, результат).

Для заявки в TikTok перезапишите видео **с реальными ключами**: тогда на шаге
авторизации будет настоящий `tiktok.com`, а не демо-экран. Сценарий и тайминги:
[`docs/DEMO_SCRIPT_RU.md`](docs/DEMO_SCRIPT_RU.md).

## API

| Метод | Путь | Описание |
|---|---|---|
| GET | `/auth/tiktok?tg=<id>` | старт OAuth, опционально привязка к Telegram |
| GET | `/auth/tiktok/callback` | обмен кода на токен |
| POST | `/api/upload` | `file`, `title`, `privacy_level`, `mode=inbox\|direct` |
| GET | `/api/posts/{id}` | статус публикации |
| POST | `/api/disconnect` | удалить аккаунт и токен |
| GET | `/healthz` | healthcheck |

## Ограничения и безопасность

- Токены хранятся в SQLite в открытом виде. Для продакшена добавьте шифрование
  (например, `cryptography.Fernet` с ключом из env) и бэкапы.
- Нет CSRF-токена на `/api/upload`: защита — `SameSite=Lax` cookie и проверка
  сессии. Для публичного сервиса добавьте CSRF-middleware.
- Видеофайлы удаляются после публикации не автоматически; настройте cron или
  добавьте очистку в `posting`.
- Приложение не аффилировано с TikTok. Соблюдайте их Developer Terms и
  Community Guidelines.

## Лицензия

Код проекта можно использовать свободно. Юридические тексты в `site/` — шаблон,
не юридическая консультация; проверьте их под свою юрисдикцию.
