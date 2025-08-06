# BeatBot - Telegram Bot для загрузки битов на YouTube

Этот бот позволяет загружать биты на YouTube через Telegram. Каждый пользователь авторизует свой собственный YouTube аккаунт. Учетные данные хранятся для каждого пользователя в локальной SQLite базе данных (`credentials.db`).

## 🚀 Быстрый старт в Selectel

### Автоматическое развертывание

1. **Подключитесь к серверу:**
   ```bash
   ssh root@your-server-ip
   ```

2. **Загрузите проект на сервер:**
   ```bash
   # Через Git
   git clone https://github.com/your-username/beatbot.git
   cd beatbot
   
   # Или через SCP
   scp -r ./* root@your-server-ip:/root/beatbot/
   ```

3. **Запустите быстрый старт:**
   ```bash
   chmod +x quick_start.sh
   ./quick_start.sh
   ```

### Ручное развертывание

См. подробное руководство в файле [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)

## 📋 Требования

- Python 3.8+
- ffmpeg
- imagemagick
- Telegram Bot Token
- YouTube API Credentials

## 🔧 Локальная разработка

1. **Установите зависимости:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Настройте переменные окружения:**
   ```bash
   cp .env.example .env
   # Отредактируйте .env файл
   ```

3. **Запустите бота:**
   ```bash
   python youtube.py
   ```

## 📖 Использование

1. Отправьте `/start` боту в Telegram
2. Выберите режим видео (обычное или Shorts)
3. Загрузите MP3 файлы и изображения
4. Настройте шаблон для YouTube
5. Выберите расписание публикаций

## 🛠️ Управление на сервере

```bash
# Запуск
sudo systemctl start beatbot.service

# Остановка
sudo systemctl stop beatbot.service

# Статус
sudo systemctl status beatbot.service

# Логи
sudo journalctl -u beatbot.service -f
```
