# Руководство по развертыванию BeatBot в Selectel

## Предварительные требования

1. **Сервер в Selectel** с Ubuntu 20.04 или новее
2. **Telegram Bot Token** (получить у @BotFather)
3. **YouTube API Credentials** (файл client_secrets.json)
4. **Доступ к серверу** через SSH

## Пошаговое развертывание

### Шаг 1: Подключение к серверу

```bash
ssh root@your-server-ip
```

### Шаг 2: Настройка сервера

Запустите скрипт настройки:

```bash
chmod +x setup_server.sh
./setup_server.sh
```

Этот скрипт:
- Обновит систему
- Установит Python, ffmpeg, imagemagick
- Создаст пользователя botuser
- Настроит виртуальное окружение

### Шаг 3: Загрузка проекта

Есть несколько способов:

#### Вариант A: Через Git (рекомендуется)
```bash
sudo -u botuser bash -c '
cd ~/beatbot
git clone https://github.com/your-username/beatbot.git .
'
```

#### Вариант B: Через SCP
```bash
scp -r ./* root@your-server-ip:/home/botuser/beatbot/
```

### Шаг 4: Настройка переменных окружения

1. **Получите Telegram Bot Token:**
   - Напишите @BotFather в Telegram
   - Создайте нового бота командой `/newbot`
   - Скопируйте полученный токен

2. **Настройте YouTube API:**
   - Убедитесь, что файл `client_secrets.json` находится в корне проекта
   - Проверьте, что у вас есть доступ к YouTube Data API v3

3. **Установите переменные окружения:**

```bash
# Отредактируйте файл .env
sudo -u botuser bash -c '
cd ~/beatbot
cp .env.example .env
nano .env
'
```

Или установите переменную напрямую:

```bash
export TELEGRAM_BOT_TOKEN="your_actual_token_here"
```

### Шаг 5: Развертывание

```bash
chmod +x deploy.sh
./deploy.sh
```

### Шаг 6: Запуск бота

```bash
# Запуск сервиса
sudo systemctl start beatbot.service

# Проверка статуса
sudo systemctl status beatbot.service

# Просмотр логов
sudo journalctl -u beatbot.service -f
```

## Управление ботом

### Команды управления:

```bash
# Запуск
sudo systemctl start beatbot.service

# Остановка
sudo systemctl stop beatbot.service

# Перезапуск
sudo systemctl restart beatbot.service

# Статус
sudo systemctl status beatbot.service

# Просмотр логов
sudo journalctl -u beatbot.service -f

# Отключение автозапуска
sudo systemctl disable beatbot.service

# Включение автозапуска
sudo systemctl enable beatbot.service
```

### Обновление бота:

```bash
# Остановите бота
sudo systemctl stop beatbot.service

# Обновите код
sudo -u botuser bash -c '
cd ~/beatbot
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
'

# Запустите бота
sudo systemctl start beatbot.service
```

## Устранение неполадок

### 1. Бот не запускается

Проверьте логи:
```bash
sudo journalctl -u beatbot.service -n 50
```

### 2. Ошибки с YouTube API

Убедитесь, что:
- Файл `client_secrets.json` корректный
- YouTube Data API v3 включен в Google Cloud Console
- Учетная запись Google имеет права на загрузку видео

### 3. Проблемы с правами доступа

```bash
sudo chown -R botuser:botuser /home/botuser/beatbot/
sudo chmod -R 755 /home/botuser/beatbot/
```

### 4. Проблемы с зависимостями

```bash
sudo -u botuser bash -c '
cd ~/beatbot
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
'
```

## Безопасность

1. **Не публикуйте токены** в открытом доступе
2. **Используйте файрвол** для ограничения доступа
3. **Регулярно обновляйте** систему и зависимости
4. **Мониторьте логи** на предмет подозрительной активности

## Мониторинг

Для мониторинга работы бота используйте:

```bash
# Просмотр логов в реальном времени
sudo journalctl -u beatbot.service -f

# Проверка использования ресурсов
htop

# Проверка дискового пространства
df -h
```

## Контакты

При возникновении проблем:
1. Проверьте логи сервиса
2. Убедитесь в корректности всех токенов
3. Проверьте подключение к интернету
4. Убедитесь, что все зависимости установлены