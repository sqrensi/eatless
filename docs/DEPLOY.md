# Полная инструкция: как вывести бота Мурлок на Linux-сервер

Пошагово от сервера до работающего бота.

---

## 1. Что нужно заранее

- **Сервер** с Linux (VPS: Timeweb, Selectel, Reg.ru, DigitalOcean, и т.п.). Достаточно 1 ядра, 512 MB RAM.
- **Токен бота** от [@BotFather](https://t.me/BotFather): команда `/newbot` → имя → username → скопировать токен.
- **Доступ по SSH** к серверу (логин и пароль или SSH-ключ).

---

## 2. Подключение к серверу

На своём компьютере открой терминал (PowerShell, CMD или Git Bash).

**Подключение по SSH:**

```bash
ssh root@IP_АДРЕС_СЕРВЕРА
```

Или, если создан отдельный пользователь:

```bash
ssh ubuntu@IP_АДРЕС_СЕРВЕРА
```

При первом входе подтверди отпечаток хоста (`yes`), введи пароль. После входа окажешься в консоли сервера.

### Если пишет «connection timeout» или «Connection timed out»

Подключение не доходит до сервера. Проверь по шагам:

**1. Верный ли IP и порт**

- IP должен быть **внешний (публичный)** сервера — его даёт хостинг в панели (VPS, облако). Не путай с внутренним IP (например 10.x.x.x).
- Порт по умолчанию — **22**. Если хостинг дал другой порт SSH, подключайся так:
  ```bash
  ssh -p НОМЕР_ПОРТА root@IP_АДРЕС_СЕРВЕРА
  ```

**2. Firewall у хостинга (правила / security group)**

Чаще всего порт 22 закрыт в панели хостинга:

- **Timeweb, Reg.ru, Selectel, RuVDS и т.п.** — в панели найди раздел «Firewall», «Сеть», «Группы безопасности» или «Правила».
- Добавь правило: **входящий (inbound)** трафик, порт **22** (или TCP 22), источник — «любой» (0.0.0.0/0) или твой IP. Сохрани.
- В облаках (AWS, DigitalOcean, Yandex Cloud и т.д.) это обычно **Security Groups** или **Firewall** — открой **inbound TCP 22**.

**3. Сервер вообще запущен**

В панели хостинга проверь: сервер в статусе «Running» / «Запущен». Если он выключен — включи и подожди 1–2 минуты.

**4. Твой интернет и firewall**

- Проверь, что интернет работает (сайты открываются).
- Корпоративная/учебная сеть или VPN иногда блокируют исходящий SSH (порт 22). Попробуй с другой сети (домашний Wi‑Fi, мобильный интернет с телефона).
- На своём ПК временно отключи антивирус/firewall и попробуй снова (только для проверки).

**5. Проверка доступности порта с твоего ПК**

На Windows (PowerShell):

```powershell
Test-NetConnection -ComputerName IP_АДРЕС_СЕРВЕРА -Port 22
```

Если `TcpTestSucceeded : False` — до порта 22 не доходишь (firewall у хостинга или у тебя, неверный IP, сервер выключен).

**6. Консоль в панели хостинга**

Если SSH с твоего ПК так и не подключается — зайди на сервер через **веб-консоль** (VNC, «Консоль», «Serial console») в панели хостинга. Там проверь, что запущен SSH-демон:

```bash
sudo systemctl status sshd
# или
sudo systemctl status ssh
```

Должно быть `active (running)`. Если нет — `sudo systemctl start ssh` (или `sshd`).

После того как откроешь порт 22 в firewall хостинга и убедишься в правильном IP, подключение по SSH обычно начинает работать.

---

## 3. Обновление системы и установка Python

Выполни на сервере:

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip git
```

Проверь версию Python (нужен 3.10 или выше):

```bash
python3 --version
```

Если версия старая (например 3.8), добавь репозиторий deadsnakes (Ubuntu) или установи Python вручную по инструкции для твоей ОС.

---

## 4. Пользователь для бота (рекомендуется)

Не запускать бота от `root`. Создай отдельного пользователя:

```bash
sudo adduser botrunner
```

Пароль задай и запомни (или оставь пустым, если не нужен вход по паролю). Остальные поля можно пропустить (Enter).

Дай права на sudo только если планируешь от него ставить пакеты (для минимального деплоя не обязательно):

```bash
sudo usermod -aG sudo botrunner
```

Переключись на этого пользователя:

```bash
sudo su - botrunner
```

Дальнейшие шаги — от `botrunner` (или от того пользователя, под которым будешь держать бота). Пусть домашний каталог будет `/home/botrunner`.

---

## 5. Загрузка проекта на сервер

### Вариант А: через Git (если проект на GitHub/GitLab)

От пользователя `botrunner` (или от своего):

```bash
cd ~
git clone https://github.com/ТВОЙ_ЛОГИН/ИМЯ_РЕПОЗИТОРИЯ.git bot
cd bot
```

Подставь свой URL репозитория. Папка с ботом окажется в `~/bot`.

### Вариант Б: копирование с компьютера (scp)

На **своём компьютере** (не на сервере), в папке с проектом:

```bash
scp -r c:\me\projects\kk botrunner@IP_СЕРВЕРА:~/
```

На **сервере**:

```bash
cd ~
mv kk bot
cd bot
```

---

## 6. Виртуальное окружение и зависимости

На сервере, в каталоге `~/bot`:

```bash
cd ~/bot
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Проверка:

```bash
python -c "import telegram; print('OK')"
```

Должно вывести `OK`. Выйти из venv можно командой `deactivate`.

---

## 7. Файл с токеном (.env)

В той же папке `~/bot` создай файл `.env`:

```bash
nano .env
```

Вставь одну строку (подставь свой токен от BotFather):

```
BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
```

Сохрани: `Ctrl+O`, Enter, затем `Ctrl+X`.

Проверь, что файл на месте и не попал в git:

```bash
cat .env
ls -la .env
```

Файл должен быть только у тебя на сервере, никому не показывай его и не заливай в репозиторий.

---

## 8. Проверка времени (часовой пояс)

Граница «не есть после 21:00» считается по **времени сервера**. Чтобы 21:00 совпадало с твоим городом, выставь часовой пояс. Например, Москва:

```bash
sudo timedatectl set-timezone Europe/Moscow
timedatectl
```

Другие примеры: `Europe/Kyiv`, `Asia/Almaty`, `Europe/Samara`. Список: `timedatectl list-timezones`.

Если не менять — будет использоваться UTC.

---

## 9. Тестовый запуск

Убедись, что бот вообще стартует:

```bash
cd ~/bot
source .venv/bin/activate
python main.py
```

В Telegram открой бота и нажми **Start**. Если бот отвечает — всё ок. Останови бота в терминале: `Ctrl+C`.

Для продакшена в `config.py` должно быть `TEST_FAST_TIMERS = False` (таймеры в минутах, а не в секундах).

---

## 10. Запуск через systemd (постоянно в фоне)

Чтобы бот работал после закрытия SSH и перезагрузки сервера.

### 10.1. Создать unit-файл

Создай файл сервиса (лучше от root или через sudo):

```bash
sudo nano /etc/systemd/system/murlok-bot.service
```

Вставь (путь и пользователя замени на свои):

```ini
[Unit]
Description=Telegram bot Murlok (eat less)
After=network.target

[Service]
Type=simple
User=botrunner
Group=botrunner
WorkingDirectory=/home/botrunner/bot
ExecStart=/home/botrunner/bot/.venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

- **User/Group** — пользователь, от которого запускается бот (например `botrunner` или `ubuntu`).
- **WorkingDirectory** — полный путь к папке с ботом (где лежит `main.py`).
- **ExecStart** — полный путь к `python` внутри `.venv` и `main.py`.

Сохрани: `Ctrl+O`, Enter, `Ctrl+X`.

### 10.2. Включить и запустить сервис

```bash
sudo systemctl daemon-reload
sudo systemctl enable murlok-bot
sudo systemctl start murlok-bot
```

### 10.3. Проверка

```bash
sudo systemctl status murlok-bot
```

Должно быть `active (running)` зелёным. Проверь бота в Telegram.

Логи в реальном времени:

```bash
sudo journalctl -u murlok-bot -f
```

Выход из логов: `Ctrl+C`.

### 10.4. Полезные команды

| Действие        | Команда |
|-----------------|--------|
| Остановить бота | `sudo systemctl stop murlok-bot` |
| Запустить снова | `sudo systemctl start murlok-bot` |
| Перезапустить   | `sudo systemctl restart murlok-bot` |
| Отключить автозапуск | `sudo systemctl disable murlok-bot` |

---

## 11. Обновление бота (после изменений в коде)

Если проект подтягиваешь через Git:

```bash
cd ~/bot
git pull
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart murlok-bot
```

Если копируешь файлы вручную — скопируй обновлённые файлы в `~/bot` и выполни:

```bash
sudo systemctl restart murlok-bot
```

---

## 12. Возможные проблемы

**Бот не отвечает в Telegram**
- Проверь: `sudo systemctl status murlok-bot` — сервис в состоянии `active (running)`?
- Логи: `sudo journalctl -u murlok-bot -n 50` — есть ли ошибки?
- Токен в `.env` правильный, без лишних пробелов и кавычек?

**Ошибка «Set BOT_TOKEN in .env»**
- Файл `.env` лежит в `~/bot` (в WorkingDirectory сервиса).
- Внутри одна строка вида: `BOT_TOKEN=токен` (без пробелов вокруг `=`).

**Граница 21:00 срабатывает не в то время**
- Выставь часовой пояс сервера (шаг 8): `sudo timedatectl set-timezone Europe/Moscow` (или свой город).

**После перезагрузки сервера бот не стартует**
- Проверь: `sudo systemctl is-enabled murlok-bot` — должно быть `enabled`.
- Если нет: `sudo systemctl enable murlok-bot`.

**Нет прав на папку / файлы**
- Владелец папки `~/bot` должен совпадать с `User` в unit-файле:
  ```bash
  sudo chown -R botrunner:botrunner /home/botrunner/bot
  ```

---

## Краткая шпаргалка (всё уже установлено)

```bash
cd ~/bot
source .venv/bin/activate
pip install -r requirements.txt   # после обновления кода
sudo systemctl restart murlok-bot
sudo journalctl -u murlok-bot -f  # логи
```

Готово: бот Мурлок работает на сервере и доступен в Telegram 24/7.
