# Бот «Меньше есть»

Телеграм-бот для осознанного питания: чек-лист перед едой, секундомер приёма пищи, правило «подожди 10 минут» перед перекусом, учёт ккалорий и лимит в день.

## Запуск локально

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Токен бота задаётся в файле `.env`:

```
BOT_TOKEN=твой_токен_от_BotFather
```

## Запуск на выделенном сервере (Linux)

### 1. Подготовка сервера

- Сервер с Linux (Ubuntu/Debian и т.п.) и доступ по SSH.
- Установи Python 3.10+ (если нет):
  ```bash
  sudo apt update
  sudo apt install python3 python3-venv python3-pip
  ```

### 2. Загрузка проекта на сервер

Через Git (если проект в репозитории):

```bash
cd ~
git clone <url-репозитория> bot
cd bot
```

Или скопируй папку проекта на сервер (scp, rsync, SFTP):

```bash
scp -r c:\me\projects\kk user@IP_СЕРВЕРА:~/
# на сервере
mv kk bot && cd bot
```

### 3. Виртуальное окружение и зависимости

На сервере в каталоге проекта:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. Токен и настройки

Создай файл `.env` в корне проекта (там же, где `main.py`):

```bash
nano .env
```

Содержимое (подставь свой токен):

```
BOT_TOKEN=123456789:ABCdefGHI...
```

Для продакшена отключи тестовые таймеры: в `config.py` поставь `TEST_FAST_TIMERS = False`.

### 5. Запуск как фоновый процесс (systemd)

Бот будет работать постоянно и перезапускаться после сбоев и перезагрузки сервера.

1. Скопируй unit-файл и отредактируй пути и пользователя:

```bash
sudo cp deploy/kk-bot.service /etc/systemd/system/
sudo nano /etc/systemd/system/kk-bot.service
```

В файле замени:
- `User=kk` и `Group=kk` — на своего пользователя (например `User=ubuntu`);
- `/home/kk/bot` — на полный путь к папке с ботом (например `/home/ubuntu/bot`).

2. Включи и запусти сервис:

```bash
sudo systemctl daemon-reload
sudo systemctl enable kk-bot
sudo systemctl start kk-bot
```

3. Проверка и логи:

```bash
sudo systemctl status kk-bot
sudo journalctl -u kk-bot -f
```

Остановка: `sudo systemctl stop kk-bot`  
Перезапуск после правок: `sudo systemctl restart kk-bot`

### 6. Вариант без systemd (screen/tmux)

Если systemd недоступен:

```bash
screen -S kkbot
source .venv/bin/activate
python main.py
# Отключиться: Ctrl+A, затем D
# Подключиться снова: screen -r kkbot
```

Или с `tmux`: `tmux new -s kkbot`, затем те же команды; отключение: `Ctrl+B`, `D`; вход: `tmux attach -t kkbot`.

## Возможности

- **Собираюсь поесть** — чек-лист (вода, голод, маленькая тарелка), затем таймер 20 минут с напоминаниями в 7 и 15 минут; в конце вопрос «Остановился на 80%?» и запись приёма.
- **Хочу перекусить** — таймер 10 минут, затем «Всё ещё хочется?»; при «Нет» — запись в стрик.
- **Записать приём** — завтрак / обед / ужин / перекус без калорий.
- **Мой прогресс** — приёмы за сегодня, сколько раз переждал импульс, серия дней.
- **Настройки** — граница «не есть после» (время ЧЧ:ММ).

Данные хранятся в SQLite (`bot_data.db`).
