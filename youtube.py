import os
import random
import shutil
import subprocess
import asyncio
import re
import pickle
from datetime import datetime, timedelta, timezone

from PIL import Image
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters
)

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# --- YouTube API config ---
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CLIENT_SECRETS_FILE = os.path.join(os.path.dirname(__file__), "client_secrets.json")
CREDENTIALS_PICKLE = "youtube_credentials.pkl"

# --- Bot config ---
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]  # <-- токен только из Render-секретов!
TMP_DIR = "temp_files"
if not os.path.exists(TMP_DIR):
    os.makedirs(TMP_DIR)

# --- Conversation states ---
WAITING_VIDEO_MODE, WAITING_CHOICE, WAITING_TEMPLATE_TITLE_INPUT, WAITING_TEMPLATE_DESCRIPTION, WAITING_TEMPLATE_TAGS, WAITING_FILES, WAITING_SCHEDULE, WAITING_AUTH_CODE = range(8)

user_data_store = {}

# --- YouTube auth ---
def get_authenticated_service():
    creds = None
    if os.path.exists(CREDENTIALS_PICKLE):
        with open(CREDENTIALS_PICKLE, "rb") as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
        creds = flow.run_local_server(port=0)
        with open(CREDENTIALS_PICKLE, "wb") as token:
            pickle.dump(creds, token)
    return build("youtube", "v3", credentials=creds)

def upload_video(youtube, video_file, title, description, tags, publish_at_utc_iso):
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "10"
        },
        "status": {
            "privacyStatus": "private",
            "publishAt": publish_at_utc_iso
        }
    }
    media = MediaFileUpload(video_file, chunksize=-1, resumable=True)
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media
    )
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Upload progress: {int(status.progress() * 100)}%")
    print("Upload complete.")
    return response

# --- Image processing ---
def process_image(input_path: str, output_path: str, mode="normal"):
    # mode: "normal" = 1920x1080, "shorts" = 1080x1920
    if mode == "shorts":
        base_width, base_height = 1080, 1920
    else:
        base_width, base_height = 1920, 1080
    with Image.open(input_path) as img:
        img_ratio = img.width / img.height
        base_ratio = base_width / base_height
        if img_ratio > base_ratio:
            new_width = base_width
            new_height = round(base_width / img_ratio)
        else:
            new_height = base_height
            new_width = round(base_height * img_ratio)
        img_resized = img.resize((new_width, new_height), Image.LANCZOS)
        background = Image.new('RGB', (base_width, base_height), (0, 0, 0))
        paste_x = (base_width - new_width) // 2
        paste_y = (base_height - new_height) // 2
        background.paste(img_resized, (paste_x, paste_y))
        background.save(output_path)

# --- Create video ---
def create_video(image_path: str, audio_path: str, output_path: str):
    command = [
        'ffmpeg',
        '-y',
        '-loop', '1',
        '-i', image_path,
        '-i', audio_path,
        '-c:v', 'libx264',
        '-c:a', 'aac',
        '-b:a', '192k',
        '-shortest',
        '-pix_fmt', 'yuv420p',
        output_path
    ]
    subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# --- Blocking video processing ---
def blocking_process_files(chat_id, mp3_files, jpg_files, video_mode):
    output_folder = os.path.join(TMP_DIR, f'{chat_id}_output')
    os.makedirs(output_folder, exist_ok=True)
    random.shuffle(jpg_files)
    videos_data = []
    for i, (mp3_path, jpg_path) in enumerate(zip(mp3_files, jpg_files), 1):
        processed_img_path = os.path.join(output_folder, f'proc_img_{i}.jpg')
        video_path = os.path.join(output_folder, f'video_{i}.mp4')
        process_image(jpg_path, processed_img_path, mode=video_mode)
        create_video(processed_img_path, mp3_path, video_path)
        videos_data.append({
            "video_path": video_path
        })
    return videos_data

# --- Telegram Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_data_store.setdefault(chat_id, {})
    keyboard = [
        ["YouTube Shorts (вертикальное 9:16)"],
        ["Обычный YouTube (горизонтальное 16:9)"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text(
        "В каком формате делать видео?\n\n"
        "— YouTube Shorts (вертикальное 9:16)\n"
        "— Обычный YouTube (горизонтальное 16:9)",
        reply_markup=reply_markup
    )
    return WAITING_VIDEO_MODE

async def video_mode_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text.strip().lower()
    if "short" in text:
        user_data_store[chat_id]["video_mode"] = "shorts"
    else:
        user_data_store[chat_id]["video_mode"] = "normal"
    keyboard = [
        ["Создать шаблон для всех видео"],
        ["Загружать видео без шаблона"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text(
        "Выберите, что вы хотите сделать:\n"
        "— Создать шаблон (название, описание, теги) для всех загружаемых видео\n"
        "— Или загружать видео с заполнением данных вручную",
        reply_markup=reply_markup
    )
    return WAITING_CHOICE

async def choice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text.strip().lower()
    if text == "создать шаблон для всех видео":
        await update.message.reply_text(
            "Введите желаемое название видео (пример: (free) nettspend x osamason type beat):",
            reply_markup=ReplyKeyboardRemove()
        )
        return WAITING_TEMPLATE_TITLE_INPUT
    elif text == "загружать видео без шаблона":
        user_data_store[chat_id]["template"] = None
        await update.message.reply_text(
            "Хорошо, загружайте MP3 и картинки.\n"
            "После загрузки всех файлов нажмите /process",
            reply_markup=ReplyKeyboardMarkup([["/process"]], resize_keyboard=True, one_time_keyboard=True)
        )
        user_data_store[chat_id]["mp3_files"] = []
        user_data_store[chat_id]["jpg_files"] = []
        return WAITING_FILES
    else:
        await update.message.reply_text("Пожалуйста, выберите опцию из клавиатуры.")
        return WAITING_CHOICE

async def receive_template_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_data_store[chat_id]["template"] = {}
    user_data_store[chat_id]["template"]["title"] = update.message.text.strip()
    await update.message.reply_text("Введите описание всех последующих видео:")
    return WAITING_TEMPLATE_DESCRIPTION

async def receive_template_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_data_store[chat_id]["template"]["description"] = update.message.text.strip()
    await update.message.reply_text("Введите теги через запятую (пример: beat, hiphop, rap):")
    return WAITING_TEMPLATE_TAGS

async def receive_template_tags(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    raw_tags = update.message.text.strip()
    tags = [tag.strip() for tag in raw_tags.split(",") if tag.strip()]
    user_data_store[chat_id]["template"]["tags"] = tags
    await update.message.reply_text(
        "Шаблон сохранён! Теперь загружайте MP3 и картинки.\n"
        "После загрузки всех файлов нажмите /process",
        reply_markup=ReplyKeyboardMarkup([["/process"]], resize_keyboard=True, one_time_keyboard=True)
    )
    user_data_store[chat_id]["mp3_files"] = []
    user_data_store[chat_id]["jpg_files"] = []
    return WAITING_FILES

async def receive_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in user_data_store:
        await update.message.reply_text("Пожалуйста, используйте /start для начала.")
        return WAITING_CHOICE

    message = update.message

    # mp3 как document
    if message.document and message.document.file_name.lower().endswith(".mp3"):
        file = await message.document.get_file()
        folder = os.path.join(TMP_DIR, f"{chat_id}_mp3")
        os.makedirs(folder, exist_ok=True)
        safe_name = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', message.document.file_name)
        file_path = os.path.join(folder, safe_name)
        await file.download_to_drive(file_path)
        user_data_store[chat_id]["mp3_files"].append(file_path)
        await update.message.reply_text(f"MP3 файл '{message.document.file_name}' загружен.")
        return WAITING_FILES

    # mp3 как audio
    if message.audio and message.audio.mime_type == "audio/mpeg":
        file = await message.audio.get_file()
        folder = os.path.join(TMP_DIR, f"{chat_id}_mp3")
        os.makedirs(folder, exist_ok=True)
        safe_name = f"{message.audio.file_unique_id}.mp3"
        file_path = os.path.join(folder, safe_name)
        await file.download_to_drive(file_path)
        user_data_store[chat_id]["mp3_files"].append(file_path)
        await update.message.reply_text(f"MP3 аудио загружено.")
        return WAITING_FILES

    # картинки
    if message.document and message.document.file_name.lower().endswith((".jpg", ".jpeg", ".png")):
        file = await message.document.get_file()
        folder = os.path.join(TMP_DIR, f"{chat_id}_jpg")
        os.makedirs(folder, exist_ok=True)
        safe_name = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', message.document.file_name)
        file_path = os.path.join(folder, safe_name)
        await file.download_to_drive(file_path)
        user_data_store[chat_id]["jpg_files"].append(file_path)
        await update.message.reply_text(f"Изображение '{message.document.file_name}' загружено.")
        return WAITING_FILES

    await update.message.reply_text("Пожалуйста, загружайте только MP3 и JPG/JPEG/PNG файлы.")
    return WAITING_FILES

async def process_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in user_data_store:
        await update.message.reply_text("Нет загруженных файлов. Используйте /start для начала.")
        return WAITING_FILES

    mp3_files = user_data_store[chat_id].get("mp3_files", [])
    jpg_files = user_data_store[chat_id].get("jpg_files", [])
    template = user_data_store[chat_id].get("template")
    video_mode = user_data_store[chat_id].get("video_mode", "normal")

    if len(mp3_files) == 0 or len(jpg_files) == 0:
        await update.message.reply_text("Нет загруженных MP3 или JPG файлов.")
        return WAITING_FILES
    if len(mp3_files) != len(jpg_files):
        await update.message.reply_text(f"Количество MP3 ({len(mp3_files)}) и JPG ({len(jpg_files)}) не совпадает.")
        return WAITING_FILES

    await update.message.reply_text(f"Начинаю обработку {len(mp3_files)} видео...")
    loop = asyncio.get_running_loop()
    videos_data = await loop.run_in_executor(None, blocking_process_files, chat_id, mp3_files, jpg_files, video_mode)
    user_data_store[chat_id]["videos_data"] = videos_data

    keyboard = [["/daily", "/every_other_day", "/weekly"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text(
        "Обработка завершена! Выберите периодичность публикаций командой:\n"
        "/daily — ежедневно\n"
        "/every_other_day — через день\n"
        "/weekly — еженедельно",
        reply_markup=reply_markup,
    )
    return WAITING_SCHEDULE

async def set_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    cmd = update.message.text.lower()
    mapping = {
        "/daily": 1,
        "/every_other_day": 2,
        "/weekly": 7
    }
    interval_days = mapping.get(cmd)
    if not interval_days:
        await update.message.reply_text("Неизвестная команда расписания.")
        return WAITING_SCHEDULE

    videos_data = user_data_store.get(chat_id, {}).get("videos_data")
    if not videos_data:
        await update.message.reply_text("Нет видео для загрузки. Сначала обработайте файлы командой /process.")
        return WAITING_SCHEDULE

    youtube = get_authenticated_service()
    start_date = datetime.now(timezone.utc).replace(hour=21, minute=0, second=0, microsecond=0) + timedelta(days=1)
    publish_dates = [ (start_date + timedelta(days=interval_days * i)).isoformat() for i in range(len(videos_data))]

    await update.message.reply_text(f"Начинаю загрузку {len(videos_data)} видео на YouTube с периодичностью каждые {interval_days} дней...")

    template = user_data_store[chat_id].get("template")

    for i, (video, publish_date) in enumerate(zip(videos_data, publish_dates), 1):
        if template:
            title = template["title"]
            description = template["description"]
            tags = template["tags"]
        else:
            title = ""
            description = "Подписывайтесь и слушайте больше битов!"
            tags = ["beat", "hiphop", "rap"]

        await update.message.reply_text(f"Загружаю видео {i} на YouTube с публикацией {publish_date}...")
        upload_video(youtube, video["video_path"], title, description, tags, publish_date)

        with open(video["video_path"], "rb") as video_file:
            await update.message.reply_video(video_file, caption=f"Видео {i} из {len(videos_data)}")

    # Очистка
    shutil.rmtree(os.path.join(TMP_DIR, f"{chat_id}_mp3"), ignore_errors=True)
    shutil.rmtree(os.path.join(TMP_DIR, f"{chat_id}_jpg"), ignore_errors=True)
    shutil.rmtree(os.path.join(TMP_DIR, f"{chat_id}_output"), ignore_errors=True)

    user_data_store.pop(chat_id, None)
    await update.message.reply_text("Все видео загружены и запланированы на публикацию!")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_data_store.pop(chat_id, None)
    await update.message.reply_text("Операция отменена. Чтобы начать заново, используйте /start.")
    return ConversationHandler.END

def main():
    application = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAITING_VIDEO_MODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, video_mode_handler)],
            WAITING_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, choice_handler)],
            WAITING_TEMPLATE_TITLE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_template_title)],
            WAITING_TEMPLATE_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_template_description)],
            WAITING_TEMPLATE_TAGS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_template_tags)],
            WAITING_FILES: [
                MessageHandler(filters.Document.ALL | filters.AUDIO, receive_file),
                CommandHandler("process", process_files),
                CommandHandler("cancel", cancel)
            ],
            WAITING_SCHEDULE: [
                CommandHandler("daily", set_schedule),
                CommandHandler("every_other_day", set_schedule),
                CommandHandler("weekly", set_schedule),
                CommandHandler("cancel", cancel)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    application.add_handler(conv_handler)

    print("Бот запущен...")
    application.run_polling()

if __name__ == "__main__":
    main()
