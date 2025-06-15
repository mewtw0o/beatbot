import os
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2

TOKEN = "8058145836:AAGbVp_NbQMYj8ikNjawFXWOz7W8kuSdUmw"
TMP_DIR = "temp_files"
os.makedirs(TMP_DIR, exist_ok=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Пришли мне аудиосообщение (MP3), и я скажу название трека из метаданных."
    )

async def receive_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    audio = update.message.audio
    if not audio:
        await update.message.reply_text("Пожалуйста, отправьте аудиосообщение.")
        return

    chat_id = update.effective_chat.id
    folder = os.path.join(TMP_DIR, str(chat_id))
    os.makedirs(folder, exist_ok=True)

    filename = f"{audio.file_unique_id}.mp3"
    file_path = os.path.join(folder, filename)

    file = await audio.get_file()
    await file.download_to_drive(file_path)

    # Попытка получить название из ID3 тегов
    title = None
    try:
        tags = ID3(file_path)
        title_tag = tags.get("TIT2")
        if title_tag:
            title = title_tag.text[0]
    except Exception:
        pass

    if not title:
        # fallback на имя файла без расширения
        title = os.path.splitext(filename)[0]

    await update.message.reply_text(f"Название трека: {title}")

def main():
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.AUDIO, receive_audio))

    print("Бот запущен...")
    application.run_polling()

if __name__ == "__main__":
    main()
