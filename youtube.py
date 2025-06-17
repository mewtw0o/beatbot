import os
import random
import shutil
import subprocess
import asyncio
import re
import pickle
import zipfile
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
CLIENT_SECRETS_FILE = "client_secrets.json"
CREDENTIALS_PICKLE = "youtube_credentials.pkl"

# --- Bot config ---
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]  # <-- токен только из Render-секретов!
TMP_DIR = "temp_files"
if not os.path.exists(TMP_DIR):
    os.makedirs(TMP_DIR)

# --- Conversation states ---
WAITING_ARCHIVE_CHOICE, WAITING_CHOICE, WAITING_TEMPLATE_TITLE_INPUT, WAITING_TEMPLATE_DESCRIPTION, WAITING_TEMPLATE_TAGS, WAITING_FILES, WAITING_SCHEDULE = range(7)

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

# --- Beat filename parser ---
def parse_beat_metadata_perfect(filename):
    import re
    import os

    name = os.path.splitext(filename)[0].strip()
    title = None
    if '-' in name:
        *before, after = name.split('-')
        title = after.strip()
        before = ' '.join(before).strip()
    else:
        before = name

    parts = before.split()
    bpm = None
    key = None
    nicks = []
    authors = []

    bpm_pat = re.compile(r'^(\d{2,3})\s?BPM$', re.IGNORECASE)
    key_pat = re.compile(r'^([A-Ga-g][#b]?)(maj|min|MAJ|MIN|m|M)?(?:\s*-?\d{1,3}(cent)?)?$', re.IGNORECASE)

    i = 0
    while i < len(parts):
        part = parts[i]
        if part.startswith('@'):
            nicks.append(part)
        elif bpm_pat.match(part):
            bpm = bpm_pat.match(part).group(1)
        elif re.match(r'^\d{2,3}$', part):
            if i+1 < len(parts) and parts[i+1].lower().startswith('bpm'):
                bpm = part
                i += 1
            else:
                bpm = part
        elif key_pat.match(part):
            key_block = [part]
            j = i+1
            while j < len(parts) and (parts[j].lower() in ['maj', 'min', 'm'] or 'cent' in parts[j].lower() or parts[j].startswith('-')):
                key_block.append(parts[j])
                j += 1
            key = ' '.join(key_block)
            i = j - 1
        i += 1

    if not title:
        for idx, part in enumerate(parts):
            if not part.startswith('@') and not bpm_pat.match(part) and not re.match(r'^\d{2,3}$', part) and not key_pat.match(part):
                title = part
                break

    skip_list = {title, bpm, key}
    for part in parts:
        if (part not in skip_list and not part.startswith('@')
            and not bpm_pat.match(part) and not re.match(r'^\d{2,3}$', part)
            and not key_pat.match(part) and len(part) > 1):
            authors.append(part)
    authors.extend(nicks)

    return {
        "title": title or "",
        "bpm": bpm or "",
        "key": key or "",
        "authors": [a for a in authors if len(a) > 1]
    }

# --- Image processing ---
def process_image(input_path: str, output_path: str):
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

# --- Blocking video processing for archive ---
def blocking_process_files_archive(chat_id, archive_path):
    output_folder = os.path.join(TMP_DIR, f'{chat_id}_output')
    os.makedirs(output_folder, exist_ok=True)
    mp3_files = []
    jpg_files = []
    # Распаковать архив
    with zipfile.ZipFile(archive_path, 'r') as zip_ref:
        zip_ref.extractall(output_folder)
    # Найти все mp3 и картинки
    for root, dirs, files in os.walk(output_folder):
        for f in files:
            ext = f.lower().split('.')[-1]
            full_path = os.path.join(root, f)
            if ext == "mp3":
                mp3_files.append(full_path)
            elif ext in ("jpg", "jpeg", "png"):
                jpg_files.append(full_path)
    mp3_files.sort()
    jpg_files.sort()
    random.shuffle(jpg_files)
    videos_data = []
    for i, (mp3_path, jpg_path) in enumerate(zip(mp3_files, jpg_files), 1):
        processed_img_path = os.path.join(output_folder, f'proc_img_{i}.jpg')
        video_path = os.path.join(output_folder, f'video_{i}.mp4')
        process_image(jpg_path, processed_img_path)
        create_video(processed_img_path, mp3_path, video_path)
        beat_metadata = parse_beat_metadata_perfect(os.path.basename(mp3_path))
        videos_data.append({
            "video_path": video_path,
            "beat_metadata": beat_metadata
        })
    return videos_data

# --- Blocking video processing for manual mode ---
def blocking_process_files_manual(chat_id, mp3_files, jpg_files):
    output_folder = os.path.join(TMP_DIR, f'{chat_id}_output')
    os.makedirs(output_folder, exist_ok=True)
    random.shuffle(jpg_files)
    videos_data = []
    for i, (mp3_path, jpg_path) in enumerate(zip(mp3_files, jpg_files), 1):
        processed_img_path = os.path.join(output_folder, f'proc_img_{i}.jpg')
        video_path = os.path.join(output_folder, f'video_{i}.mp4')
        process_image(jpg_path, processed_img_path)
        create_video(processed_img_path, mp3_path, video_path)
        videos_data.append({
            "video_path": video_path,
            "beat_name": os.path.splitext(os.path.basename(mp3_path))[0]
        })
    return videos_data

# --- Telegram Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_data_store.setdefault(chat_id, {})
    keyboard = [
        ["Архивом (рекомендуется)"],
        ["По отдельности (без автопарсинга)"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text(
        "Как хотите загружать файлы?\n\n"
        "Архивом (zip/rar) — бот сам распарсит BPM, Key, название, авторов из названия файлов!\n"
        "По отдельности — вручную, парсинга не будет.",
        reply_markup=reply_markup
    )
    return WAITING_ARCHIVE_CHOICE

async def archive_choice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text.strip().lower()
    if "архив" in text:
        user_data_store[chat_id]["use_archive"] = True
        await update.message.reply_text("Отправьте архив с файлами (mp3 и картинки). После загрузки нажмите /process")
        user_data_store[chat_id]["archives"] = []
        return WAITING_FILES
    else:
        user_data_store[chat_id]["use_archive"] = False
        await update.message.reply_text(
            "Загружайте mp3 и картинки по отдельности. После загрузки всех файлов нажмите /process"
        )
        user_data_store[chat_id]["mp3_files"] = []
        user_data_store[chat_id]["jpg_files"] = []
        return WAITING_FILES

async def receive_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in user_data_store:
        await update.message.reply_text("Пожалуйста, используйте /start для начала.")
        return WAITING_ARCHIVE_CHOICE

    use_archive = user_data_store[chat_id].get("use_archive")
    message = update.message

    if use_archive:
        # Только архивы .zip
        if message.document and message.document.file_name.lower().endswith(".zip"):
            file = await message.document.get_file()
            folder = os.path.join(TMP_DIR, f"{chat_id}_archive")
            os.makedirs(folder, exist_ok=True)
            safe_name = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', message.document.file_name)
            file_path = os.path.join(folder, safe_name)
            await file.download_to_drive(file_path)
            user_data_store[chat_id]["archives"].append(file_path)
            await update.message.reply_text(f"Архив '{message.document.file_name}' загружен.")
            return WAITING_FILES
        else:
            await update.message.reply_text("Пожалуйста, отправьте архив .zip.")
            return WAITING_FILES

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
        ext = os.path.splitext(message.document.file_name)[1]
        safe_name = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', message.document.file_name)
        file_path = os.path.join(folder, safe_name)
        await file.download_to_drive(file_path)
        user_data_store[chat_id]["jpg_files"].append(file_path)
        await update.message.reply_text(f"Изображение '{message.document.file_name}' загружено.")
        return WAITING_FILES

<<<<<<< codex/приветствие
    await update.message.reply_text("Пожалуйста, загружайте только MP3 и JPG/JPEG/PNG файлы.")
    return WAITING_FILES

def parse_beat_metadata_perfect(filename):
    import re
    import os

    name = os.path.splitext(filename)[0].strip()
    title = None
    if '-' in name:
        *before, after = name.split('-')
        title = after.strip()
        before = ' '.join(before).strip()
    else:
        before = name

    parts = before.split()
    bpm = None
    key = None
    nicks = []
    authors = []

    bpm_pat = re.compile(r'^(\d{2,3})\s?BPM$', re.IGNORECASE)
    key_pat = re.compile(r'^([A-Ga-g][#b]?)(maj|min|MAJ|MIN|m|M)?(?:\s*-?\d{1,3}(cent)?)?$', re.IGNORECASE)

    i = 0
    while i < len(parts):
        part = parts[i]
        if part.startswith('@'):
            nicks.append(part)
        elif bpm_pat.match(part):
            bpm = bpm_pat.match(part).group(1)
        elif re.match(r'^\d{2,3}$', part):
            if i+1 < len(parts) and parts[i+1].lower().startswith('bpm'):
                bpm = part
                i += 1
            else:
                bpm = part
        elif key_pat.match(part):
            key_block = [part]
            j = i+1
            while j < len(parts) and (parts[j].lower() in ['maj', 'min', 'm'] or 'cent' in parts[j].lower() or parts[j].startswith('-')):
                key_block.append(parts[j])
                j += 1
            key = ' '.join(key_block)
            i = j - 1
        i += 1

    if not title:
        for idx, part in enumerate(parts):
            if not part.startswith('@') and not bpm_pat.match(part) and not re.match(r'^\d{2,3}$', part) and not key_pat.match(part):
                title = part
                break

    skip_list = {title, bpm, key}
    for part in parts:
        if (part not in skip_list and not part.startswith('@')
            and not bpm_pat.match(part) and not re.match(r'^\d{2,3}$', part)
            and not key_pat.match(part) and len(part) > 1):
            authors.append(part)
    authors.extend(nicks)

    return {
        "title": title or "",
        "bpm": bpm or "",
        "key": key or "",
        "authors": [a for a in authors if len(a) > 1]
    }

async def process_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
=======
    await update.message.reply_text("Пожалуйста, загружайте только MP3, JPG/JPEG/PNG или архивы .zip.")
    return WAITING_FILES

async def process_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
>>>>>>> main
    chat_id = update.effective_chat.id
    if chat_id not in user_data_store:
        await update.message.reply_text("Нет загруженных файлов. Используйте /start для начала.")
        return WAITING_FILES

    use_archive = user_data_store[chat_id].get("use_archive")
    videos_data = []

    if use_archive:
        archives = user_data_store[chat_id].get("archives", [])
        if not archives:
            await update.message.reply_text("Нет загруженных архивов. Отправьте архив .zip и нажмите /process.")
            return WAITING_FILES
        await update.message.reply_text(f"Начинаю обработку файлов из архива...")
        loop = asyncio.get_running_loop()
        videos_data = await loop.run_in_executor(None, blocking_process_files_archive, chat_id, archives[0])
        user_data_store[chat_id]["videos_data"] = videos_data
    else:
        mp3_files = user_data_store[chat_id].get("mp3_files", [])
        jpg_files = user_data_store[chat_id].get("jpg_files", [])
        if len(mp3_files) == 0 or len(jpg_files) == 0:
            await update.message.reply_text("Нет загруженных MP3 или JPG файлов.")
            return WAITING_FILES
        if len(mp3_files) != len(jpg_files):
            await update.message.reply_text(f"Количество MP3 ({len(mp3_files)}) и JPG ({len(jpg_files)}) не совпадает.")
            return WAITING_FILES
        await update.message.reply_text(f"Начинаю обработку {len(mp3_files)} видео...")
        loop = asyncio.get_running_loop()
        videos_data = await loop.run_in_executor(None, blocking_process_files_manual, chat_id, mp3_files, jpg_files)
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
    chat_id = update.message.chat_id if hasattr(update.message, 'chat_id') else update.effective_chat.id
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
    use_archive = user_data_store[chat_id].get("use_archive")

<<<<<<< codex/приветствие
    for i, (video, publish_date) in enumerate(zip(videos_data, publish_dates), 1):
        beat_metadata = parse_beat_metadata_perfect(os.path.basename(video["video_path"]).replace('.mp4', '.mp3'))

        beat_title = beat_metadata["title"].strip()
        bpm = beat_metadata["bpm"]
        key = beat_metadata["key"]
        authors = ', '.join(beat_metadata["authors"]) if beat_metadata["authors"] else "unknown"

        yt_title = f'free nettspend x osama type beat "{beat_title}"'
        key_line = f"KEY: {key}," if key else ""
        bpm_line = f"BPM {bpm}," if bpm else ""
        prod_line = f"FOR SC MUST CREDIT: {authors}"
        yt_desc = f"{key_line} {bpm_line} {prod_line}".strip().replace(" ,", ",").replace("  ", " ")

        if template:
            yt_title = f'{template["title"]} "{beat_title}"'
            yt_desc = template["description"]
            tags = template["tags"]
        else:
            tags = ["beat", "hiphop", "rap", beat_title.lower()]

        await update.message.reply_text(f"Загружаю видео {i} на YouTube с публикацией {publish_date}...")
        upload_video(youtube, video["video_path"], yt_title, yt_desc, tags, publish_date)

        with open(video["video_path"], "rb") as video_file:
            await update.message.reply_video(video_file, caption=f"Видео {i} из {len(videos_data)}")
=======
    for i, (video, publish_date) in enumerate(zip(videos_data, publish_dates), 1):
        if use_archive:
            beat_metadata = video["beat_metadata"]
            beat_title = beat_metadata["title"].strip()
            bpm = beat_metadata["bpm"]
            key = beat_metadata["key"]
            authors = ', '.join(beat_metadata["authors"]) if beat_metadata["authors"] else "unknown"
        else:
            beat_title = video.get("beat_name", "Unknown").strip()
            bpm = ""
            key = ""
            authors = ""

        yt_title = f'free nettspend x osama type beat "{beat_title}"'
        key_line = f"KEY: {key}," if key else ""
        bpm_line = f"BPM {bpm}," if bpm else ""
        prod_line = f"FOR SC MUST CREDIT: {authors}" if authors else ""
        yt_desc = f"{key_line} {bpm_line} {prod_line}".strip().replace(" ,", ",").replace("  ", " ")

        if template:
            yt_title = f'{template["title"]} "{beat_title}"'
            yt_desc = template["description"]
            tags = template["tags"]
        else:
            tags = ["beat", "hiphop", "rap", beat_title.lower()]

        await update.message.reply_text(f"Загружаю видео {i} на YouTube с публикацией {publish_date}...")
        upload_video(youtube, video["video_path"], yt_title, yt_desc, tags, publish_date)

        with open(video["video_path"], "rb") as video_file:
            await update.message.reply_video(video_file, caption=f"Видео {i} из {len(videos_data)}")
>>>>>>> main

    # Очистка
    shutil.rmtree(os.path.join(TMP_DIR, f"{chat_id}_mp3"), ignore_errors=True)
    shutil.rmtree(os.path.join(TMP_DIR, f"{chat_id}_jpg"), ignore_errors=True)
    shutil.rmtree(os.path.join(TMP_DIR, f"{chat_id}_output"), ignore_errors=True)
    shutil.rmtree(os.path.join(TMP_DIR, f"{chat_id}_archive"), ignore_errors=True)

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
            WAITING_ARCHIVE_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, archive_choice_handler)],
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
