# Telegram-киногид

Бот на Python 3.11+, aiogram 3, Neon PostgreSQL и Google Gemini. При запуске он создает таблицы и заполняет пустой каталог записями из тестового набора. Gemini выбирает названия только из каталога; ссылки формируются ботом по данным базы.

## Переменные окружения

Скопируйте `.env.example` в `.env` и заполните:

- `BOT_TOKEN` — токен Telegram-бота от BotFather.
- `GEMINI_API_KEY` — ключ Google AI Studio.
- `DATABASE_URL` — строка подключения Neon с `sslmode=require`.

Не добавляйте `.env` в Git и не публикуйте секреты.

## Локальный запуск

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python bot.py
```

При первом запуске бот подключится к Neon, создаст `catalog`, `users` и `recommendation_history`, а затем добавит тестовые записи, если `catalog` пуст.

## GitHub

Создайте пустой репозиторий на GitHub, затем выполните в папке проекта:

```powershell
git init
git add bot.py requirements.txt Dockerfile .gitignore README.md .env.example
git commit -m "Add Telegram recommendation bot"
git branch -M main
git remote add origin https://github.com/USERNAME/REPOSITORY.git
git push -u origin main
```

Перед `git add` проверьте, что `.env` не добавлен в индекс.

## Деплой

Можно использовать Render как Background Worker, Railway как сервис или VPS с Docker. Подключите GitHub-репозиторий либо соберите образ из `Dockerfile` и задайте `BOT_TOKEN`, `GEMINI_API_KEY` и `DATABASE_URL` в настройках окружения хостинга. Команда запуска контейнера: `python bot.py`. Для VPS можно собрать образ командой `docker build -t telegram-kinogid .` и запустить его с этими переменными окружения. Не помещайте секреты в Dockerfile или репозиторий.