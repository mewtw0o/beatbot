#!/bin/bash

# Скрипт развертывания BeatBot на сервере Selectel

echo "=== Развертывание BeatBot ==="

# Проверяем, что мы в правильной директории
if [ ! -f "youtube.py" ]; then
    echo "Ошибка: Файл youtube.py не найден. Убедитесь, что вы в корневой директории проекта."
    exit 1
fi

# Копируем файлы в домашнюю директорию botuser
echo "Копируем файлы проекта..."
sudo cp -r . /home/botuser/beatbot/
sudo chown -R botuser:botuser /home/botuser/beatbot/

# Переключаемся на пользователя botuser
sudo -u botuser bash -c '
cd /home/botuser/beatbot

# Активируем виртуальное окружение
source venv/bin/activate

# Устанавливаем зависимости
pip install -r requirements.txt

# Создаем директории если их нет
mkdir -p temp_files
chmod 755 temp_files

# Проверяем наличие токена
if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    echo "ВНИМАНИЕ: TELEGRAM_BOT_TOKEN не установлен!"
    echo "Установите переменную окружения TELEGRAM_BOT_TOKEN"
fi
'

# Копируем systemd сервис
echo "Настраиваем systemd сервис..."
sudo cp beatbot.service /etc/systemd/system/

# Перезагружаем systemd
sudo systemctl daemon-reload

# Включаем автозапуск
sudo systemctl enable beatbot.service

echo "=== Развертывание завершено ==="
echo ""
echo "Для запуска бота выполните:"
echo "sudo systemctl start beatbot.service"
echo ""
echo "Для проверки статуса:"
echo "sudo systemctl status beatbot.service"
echo ""
echo "Для просмотра логов:"
echo "sudo journalctl -u beatbot.service -f"