import os
import time
from pyrogram import Client, filters
from bot.helpers.sql_helper import gDriveDB, idsDB
from bot.helpers.utils import CustomFilters, humanbytes
from bot.helpers.downloader import download_file, utube_dl
from bot.helpers.gdrive_utils import GoogleDrive
from bot import DOWNLOAD_DIRECTORY, LOGGER
from bot.config import Messages, BotCommands
from pyrogram.errors import FloodWait, RPCError
from bot.plugins.forcesub import check_forcesub
from bot.db.ban_sql import is_banned

def progress_callback(current, total):
    elapsed_time = time.time() - progress_callback.start_time
    speed = current / elapsed_time if elapsed_time > 0 else 0
    remaining_bytes = total - current
    eta = remaining_bytes / speed if speed > 0 else 0
    progress_msg = (
        f"**Progress:** {humanbytes(current)}/{humanbytes(total)}\n"
        f"**Speed:** {humanbytes(speed)}/s\n"
        f"**Remaining:** {humanbytes(remaining_bytes)}\n"
        f"**ETA:** {time.strftime('%H:%M:%S', time.gmtime(eta))}"
    )
    progress_callback.sent_message.edit(progress_msg)

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

    sent_message = await message.reply_text("🕵️**Checking link...**", quote=True)
    link = message.text.strip() if not message.command else message.command[1]
    filename = os.path.basename(link)
    dl_path = os.path.join(DOWNLOAD_DIRECTORY, filename)
    
    LOGGER.info(f"Download:{user_id}: {link}")
    await sent_message.edit(Messages.DOWNLOADING.format(link))
    
    progress_callback.start_time = time.time()
    progress_callback.sent_message = sent_message
    result, file_path = download_file(link, dl_path, progress_callback)
    
    if result:
        await sent_message.edit(
            Messages.DOWNLOADED_SUCCESSFULLY.format(
                os.path.basename(file_path),
                humanbytes(os.path.getsize(file_path))
            )
        )
        msg = GoogleDrive(user_id).upload_file(file_path, progress_callback)
        await sent_message.edit(msg)
        os.remove(file_path)
    else:
        await sent_message.edit(Messages.DOWNLOAD_ERROR.format(file_path, link))

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
    file = message.document or message.video or message.audio or message.photo
    if message.photo:
        file.mime_type = "images/png"
        file.file_name = f"IMG-{user_id}-{message.id}.png"
    await sent_message.edit(
        Messages.DOWNLOAD_TG_FILE.format(
            file.file_name, humanbytes(file.file_size), file.mime_type
        )
    )
    LOGGER.info(f"Download:{user_id}: {file.file_name}")
    try:
        progress_callback.start_time = time.time()
        progress_callback.sent_message = sent_message
        file_path = await message.download(file_name=DOWNLOAD_DIRECTORY, progress=progress_callback)
        await sent_message.edit(
            Messages.DOWNLOADED_SUCCESSFULLY.format(
                os.path.basename(file_path), humanbytes(os.path.getsize(file_path))
            )
        )
        msg = GoogleDrive(user_id).upload_file(file_path, progress_callback)
        await sent_message.edit(msg)
    except RPCError:
        await sent_message.edit(Messages.WENT_WRONG)
    LOGGER.info(f"Deleting: {file_path}")
    os.remove(file_path)

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
        LOGGER.info(f"YTDL:{user_id}: {link}")
        await sent_message.edit(Messages.DOWNLOADING.format(link))
        progress_callback.start_time = time.time()
        progress_callback.sent_message = sent_message
        result, file_path = utube_dl(link, progress_callback)
        if result:
            await sent_message.edit(
                Messages.DOWNLOADED_SUCCESSFULLY.format(
                    os.path.basename(file_path), humanbytes(os.path.getsize(file_path))
                )
            )
            msg = GoogleDrive(user_id).upload_file(file_path, progress_callback)
            await sent_message.edit(msg)
            os.remove(file_path)
        else:
            await sent_message.edit(Messages.DOWNLOAD_ERROR.format(file_path, link))
    else:
        await message.reply_text(Messages.PROVIDE_YTDL_LINK, quote=True)