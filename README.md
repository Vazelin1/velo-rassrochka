# Установка (Selectel + Telegram)
1. Telegram: в @BotFather команда /newbot, сохраните токен. Ваш числовой ID узнайте у @userinfobot.
2. Selectel: создайте облачный сервер Ubuntu 24.04 (1 vCPU, 1-2 ГБ), запишите его IP. У регистратора домена создайте запись A: ваш (под)домен -> IP сервера.
3. Подключитесь: `ssh root@IP`. Установите Docker: `curl -fsSL https://get.docker.com | sh`
4. Загрузите папку проекта на сервер (с вашего компьютера: `scp -r velo root@IP:/root/`), затем `cd /root/velo`.
5. `cp .env.example .env`, откройте `nano .env` и впишите токен, ID и домен (без https://).
6. `docker compose up -d --build`. Через минуту адрес https://ВАШ_ДОМЕН должен отвечать.
7. @BotFather: /mybots, ваш бот, Bot Settings, Menu Button, Configure menu button, укажите https://ВАШ_ДОМЕН. Откройте бота в Telegram и нажмите кнопку меню.
Копии базы: каждую ночь в 03:00 (МСК) файл `velo-….json` приходит владельцу в чат с ботом (напишите боту /start, чтобы он мог писать вам), плюс 30 копий лежат в `data/backups`. Кнопки «Отправить копию в Telegram сейчас» и «Восстановить из файла копии» находятся в приложении: Настройки, раздел «Резервная копия». Перед каждым восстановлением сервер сохраняет текущую базу в `data/backups/pre-restore-….db`.
Сменить владельца: `nano .env`, поменять OWNER_ID, `docker compose up -d`.
Логи: `docker compose logs app`. Обновить: заменить файлы и `docker compose up -d --build`.
