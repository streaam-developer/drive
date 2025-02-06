import os
import time
import asyncio
import aiohttp
from tqdm import tqdm
from pyrogram import Client, filters
from bot.helpers.sql_helper import gDriveDB, idsDB
from bot.helpers.utils import CustomFilters, humanbytes
from bot.helpers.downloader import utube_dl
from bot.helpers.gdrive_utils import GoogleDrive
from bot import DOWNLOAD_DIRECTORY, LOGGER
from bot.config import Messages, BotCommands
from pyrogram.errors import FloodWait, RPCError
from bot.plugins.forcesub import check_forcesub
from bot.db.ban_sql import is_banned

# Task queue for each user
user_tasks = {}

async def download_file_with_progress(url, destination, sent_message):
    import os

    # Ensure the download directory exists
    os.makedirs(destination, exist_ok=True)

    # Extract a filename from the URL or generate one if missing
    filename = os.path.basename(url) if "." in os.path.basename(url) else f"downloaded_file.mp4"
    destination_file = os.path.join(destination, filename)

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            total_size = int(response.headers.get('content-length', 0))
            block_size = 1024  # 1 KB
            progress = tqdm(total=total_size, unit='B', unit_scale=True, desc=filename)

            with open(destination_file, 'wb') as f:
                start_time = time.time()
                while True:
                    chunk = await response.content.read(block_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    progress.update(len(chunk))
                    elapsed_time = time.time() - start_time
                    download_speed = progress.n / elapsed_time if elapsed_time > 0 else 0
                    progress.set_postfix(speed=f"{humanbytes(download_speed)}/s", 
                                        remaining=f"{humanbytes(total_size - progress.n)}")
                    # Update progress in Telegram
                    await sent_message.edit(
                        Messages.DOWNLOADING.format(
                            filename,
                            humanbytes(progress.n),
                            humanbytes(total_size),
                            f"{humanbytes(download_speed)}/s",
                            f"{humanbytes(total_size - progress.n)} remaining"
                        )
                    )
            progress.close()

    return True, destination_file

async def upload_file_with_progress(file_path, mime_type, sent_message, user_id):
    total_size = os.path.getsize(file_path)
    progress = tqdm(total=total_size, unit='B', unit_scale=True, desc=os.path.basename(file_path))
    start_time = time.time()
    
    def callback(uploaded_bytes):
        progress.update(uploaded_bytes - progress.n)
        elapsed_time = time.time() - start_time
        upload_speed = progress.n / elapsed_time if elapsed_time > 0 else 0
        progress.set_postfix(speed=f"{humanbytes(upload_speed)}/s", 
                            remaining=f"{humanbytes(total_size - progress.n)}")
        # Update progress in Telegram
        asyncio.create_task(sent_message.edit(
            Messages.UPLOADING.format(
                os.path.basename(file_path),
                humanbytes(progress.n),
                humanbytes(total_size),
                f"{humanbytes(upload_speed)}/s",
                f"{humanbytes(total_size - progress.n)} remaining"
            )
        ))
    
    msg = GoogleDrive(user_id).upload_file(file_path, mime_type, callback)
    progress.close()
    return msg

async def process_user_queue(user_id, client, sent_message, task):
    if user_id not in user_tasks:
        user_tasks[user_id] = asyncio.Queue()
    
    await user_tasks[user_id].put(task)
    
    while not user_tasks[user_id].empty():
        current_task = await user_tasks[user_id].get()
        await current_task(client, sent_message)
        user_tasks[user_id].task_done()

@Client.on_message(
    filters.private
    & filters.incoming
    & filters.text
    & (filters.command(BotCommands.Download) | filters.regex("^(ht|f)tp*"))
    & CustomFilters.auth_users
)
async def _download(client, message):
    user_id = message.from_user.id

    if await is_banned(user_id):
        await message.reply_text("You are banned from using this bot.", quote=True)
        return

    if not await check_forcesub(client, message, user_id):
        return

    if not message.media:
        sent_message = await message.reply_text("🕵️**Checking link...**", quote=True)
        if message.command:
            link = message.command[1]
        else:
            link = message.text

        async def download_task(client, sent_message):
            if "drive.google.com" in link:
                await sent_message.edit(Messages.CLONING.format(link))
                LOGGER.info(f"Copy:{user_id}: {link}")
                msg = GoogleDrive(user_id).clone(link)
                await sent_message.edit(msg)
            else:
                if "|" in link:
                    link, filename = link.split("|")
                    link = link.strip()
                    filename.strip()
                    dl_path = os.path.join(f"{DOWNLOAD_DIRECTORY}/{filename}")
                else:
                    link = link.strip()
                    filename = os.path.basename(link)
                    dl_path = DOWNLOAD_DIRECTORY
                LOGGER.info(f"Download:{user_id}: {link}")
                await sent_message.edit(Messages.DOWNLOADING.format(link))
                result, file_path = await download_file_with_progress(link, dl_path, sent_message)
                if result == True:
                    await sent_message.edit(
                        Messages.DOWNLOADED_SUCCESSFULLY.format(
                            os.path.basename(file_path),
                            humanbytes(os.path.getsize(file_path)),
                        )
                    )
                    msg = await upload_file_with_progress(file_path, None, sent_message, user_id)
                    await sent_message.edit(msg)
                    LOGGER.info(f"Deleteing: {file_path}")
                    os.remove(file_path)
                else:
                    await sent_message.edit(Messages.DOWNLOAD_ERROR.format(file_path, link))

        await process_user_queue(user_id, client, sent_message, download_task)

@Client.on_message(
    filters.private
    & filters.incoming
    & (filters.document | filters.audio | filters.video | filters.photo)
    & CustomFilters.auth_users
)
async def _telegram_file(client, message):
    user_id = message.from_user.id

    if await is_banned(user_id):
        await message.reply_text("You are banned from using this bot.", quote=True)
        return

    if not await check_forcesub(client, message, user_id):
        return

    sent_message = await message.reply_text("🕵️**Checking File...**", quote=True)
    if message.document:
        file = message.document
    elif message.video:
        file = message.video
    elif message.audio:
        file = message.audio
    elif message.photo:
        file = message.photo
        file.mime_type = "images/png"
        file.file_name = f"IMG-{user_id}-{message.id}.png"

    async def upload_task(client, sent_message):
        await sent_message.edit(
            Messages.DOWNLOAD_TG_FILE.format(
                file.file_name, humanbytes(file.file_size), file.mime_type
            )
        )
        LOGGER.info(f"Download:{user_id}: {file.file_name}")
        try:
            file_path = await message.download(file_name=DOWNLOAD_DIRECTORY)
            await sent_message.edit(
                Messages.DOWNLOADED_SUCCESSFULLY.format(
                    os.path.basename(file_path), humanbytes(os.path.getsize(file_path))
                )
            )
            msg = await upload_file_with_progress(file_path, file.mime_type, sent_message, user_id)
            await sent_message.edit(msg)
        except RPCError:
            await sent_message.edit(Messages.WENT_WRONG)
        LOGGER.info(f"Deleteing: {file_path}")
        os.remove(file_path)

    await process_user_queue(user_id, client, sent_message, upload_task)

@Client.on_message(
    filters.incoming
    & filters.private
    & filters.command(BotCommands.YtDl)
    & CustomFilters.auth_users
)
async def _ytdl(client, message):
    user_id = message.from_user.id

    if await is_banned(user_id):
        await message.reply_text("You are banned from using this bot.", quote=True)
        return

    if not await check_forcesub(client, message, user_id):
        return

    if len(message.command) > 1:
        sent_message = await message.reply_text("🕵️**Checking Link...**", quote=True)
        link = message.command[1]

        async def ytdl_task(client, sent_message):
            LOGGER.info(f"YTDL:{user_id}: {link}")
            await sent_message.edit(Messages.DOWNLOADING.format(link))
            result, file_path = await download_file_with_progress(link, DOWNLOAD_DIRECTORY, sent_message)
            if result:
                await sent_message.edit(
                    Messages.DOWNLOADED_SUCCESSFULLY.format(
                        os.path.basename(file_path), humanbytes(os.path.getsize(file_path))
                    )
                )
                msg = await upload_file_with_progress(file_path, None, sent_message, user_id)
                await sent_message.edit(msg)
                LOGGER.info(f"Deleteing: {file_path}")
                os.remove(file_path)
            else:
                await sent_message.edit(Messages.DOWNLOAD_ERROR.format(file_path, link))

        await process_user_queue(user_id, client, sent_message, ytdl_task)
    else:
        await message.reply_text(Messages.PROVIDE_YTDL_LINK, quote=True)
