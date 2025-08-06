#!/bin/bash

# Быстрый старт для развертывания BeatBot в Selectel

echo "🚀 Быстрый старт BeatBot в Selectel"
echo "======================================"

# Проверяем наличие необходимых файлов
if [ ! -f "youtube.py" ]; then
    echo "❌ Ошибка: Файл youtube.py не найден"
    exit 1
fi

if [ ! -f "client_secrets.json" ]; then
    echo "❌ Ошибка: Файл client_secrets.json не найден"
    exit 1
fi

# Запрашиваем токен бота
echo ""
echo "📱 Введите ваш Telegram Bot Token (получите у @BotFather):"
read -s TELEGRAM_TOKEN

if [ -z "$TELEGRAM_TOKEN" ]; then
    echo "❌ Токен не может быть пустым"
    exit 1
fi

echo ""
echo "🔧 Начинаем настройку сервера..."

# Запускаем настройку сервера
chmod +x setup_server.sh
./setup_server.sh

echo ""
echo "📦 Копируем файлы проекта..."

# Копируем файлы
sudo cp -r . /home/botuser/beatbot/
sudo chown -R botuser:botuser /home/botuser/beatbot/

# Настраиваем виртуальное окружение
sudo -u botuser bash -c '
cd /home/botuser/beatbot
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
mkdir -p temp_files
chmod 755 temp_files
'

# Обновляем systemd сервис с токеном
sudo sed -i "s/your_telegram_bot_token_here/$TELEGRAM_TOKEN/g" beatbot.service

# Копируем и настраиваем сервис
sudo cp beatbot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable beatbot.service

echo ""
echo "🎯 Запускаем бота..."

# Запускаем бота
sudo systemctl start beatbot.service

# Проверяем статус
sleep 3
STATUS=$(sudo systemctl is-active beatbot.service)

if [ "$STATUS" = "active" ]; then
    echo "✅ Бот успешно запущен!"
    echo ""
    echo "📊 Статус сервиса:"
    sudo systemctl status beatbot.service --no-pager -l
    echo ""
    echo "📝 Для просмотра логов используйте:"
    echo "sudo journalctl -u beatbot.service -f"
    echo ""
    echo "🛠️ Команды управления:"
    echo "sudo systemctl start beatbot.service   # Запуск"
    echo "sudo systemctl stop beatbot.service    # Остановка"
    echo "sudo systemctl restart beatbot.service # Перезапуск"
    echo "sudo systemctl status beatbot.service  # Статус"
else
    echo "❌ Ошибка запуска бота"
    echo "Проверьте логи:"
    sudo journalctl -u beatbot.service -n 20
fi