#!/bin/bash

# Скрипт для настройки сервера в Selectel
echo "Начинаем настройку сервера для Telegram бота..."

# Обновляем систему
sudo apt update && sudo apt upgrade -y

# Устанавливаем Python и pip
sudo apt install -y python3 python3-pip python3-venv

# Устанавливаем системные зависимости для работы с видео и изображениями
sudo apt install -y ffmpeg imagemagick

# Устанавливаем git для клонирования репозитория
sudo apt install -y git

# Создаем пользователя для бота
sudo useradd -m -s /bin/bash botuser
sudo usermod -aG sudo botuser

# Переключаемся на пользователя бота
sudo -u botuser bash -c '
# Создаем рабочую директорию
mkdir -p ~/beatbot
cd ~/beatbot

# Клонируем репозиторий (замените на ваш URL)
# git clone https://github.com/your-username/beatbot.git .

# Создаем виртуальное окружение
python3 -m venv venv
source venv/bin/activate

# Устанавливаем зависимости
pip install --upgrade pip
pip install -r requirements.txt

# Создаем директории для временных файлов
mkdir -p temp_files

# Устанавливаем права на директории
chmod 755 temp_files
'

echo "Настройка сервера завершена!"
echo "Теперь нужно настроить переменные окружения и запустить бота"