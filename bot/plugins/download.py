import os
import asyncio
import aria2p
from time import time
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

# Initialize Aria2 client
aria2 = aria2p.Client(host="http://localhost", port=6800, secret="")

async def progress_message(sent_message, gid):
    """ Update progress message while downloading """
    while True:
        try:
            download = aria2.get_download(gid)
            if download.is_complete:
                await sent_message.edit("✅ **Download completed!**")
                return
            percent = (download.completed_length / download.total_length) * 100
            speed = humanbytes(download.download_speed) + "/s"
            remaining_time = (download.total_length - download.completed_length) / (download.download_speed + 1)
            time_left = f"{int(remaining_time // 60)} min {int(remaining_time % 60)} sec"

            progress_text = f"⬇ **Downloading:** `{download.name}`\n📥 **Progress:** {percent:.2f}%\n🚀 **Speed:** {speed}\n⏳ **ETA:** {time_left}"
            await sent_message.edit(progress_text)
        except Exception:
            pass
        await asyncio.sleep(5)

async def download_with_aria2(url, sent_message, filename=None):
    """ Start download using Aria2 """
    try:
        options = {"dir": DOWNLOAD_DIRECTORY}
        if filename:
            options["out"] = filename
        
        download = aria2.add_uris([url], options=options)
        asyncio.create_task(progress_message(sent_message, download.gid))
        download.wait_until_complete()
        
        file_path = os.path.join(DOWNLOAD_DIRECTORY, filename or download.name)
        return True, file_path
    except Exception as e:
        LOGGER.error(f"Aria2 Error: {e}")
        return False, None

@Client.on_message(
    filters.private
    & filters.incoming
    & filters.text
    & (filters.command(BotCommands.Download) | filters.regex("^(ht|f)tp*"))
)
async def _download(client, message):
    user_id = message.from_user.id

    if await is_banned(user_id):
        await message.reply_text("You are banned from using this bot.", quote=True)
        return

    if not await check_forcesub(client, message, user_id):
        return

    sent_message = await message.reply_text("🕵️ **Checking link...**", quote=True)
    link = message.text.strip()
    
    filename = None
    if "|" in link:
        link, filename = link.split("|")
        link = link.strip()
        filename = filename.strip()

    LOGGER.info(f"Download Request from {user_id}: {link}")

    # Fast download using Aria2
    result, file_path = await download_with_aria2(link, sent_message, filename)
    if result:
        await sent_message.edit(f"✅ **Download Complete:** `{os.path.basename(file_path)}`\n📁 Size: {humanbytes(os.path.getsize(file_path))}")
        
        msg = GoogleDrive(user_id).upload_file(file_path)
        await sent_message.edit(msg)

        LOGGER.info(f"Deleting: {file_path}")
        os.remove(file_path)
    else:
        await sent_message.edit("❌ **Download Failed!**")

@Client.on_message(
    filters.private
    & filters.incoming
    & (filters.document | filters.audio | filters.video | filters.photo)
)
async def _telegram_file(client, message):
    user_id = message.from_user.id

    if await is_banned(user_id):
        await message.reply_text("You are banned from using this bot.", quote=True)
        return

    if not await check_forcesub(client, message, user_id):
        return

    sent_message = await message.reply_text("🕵️ **Checking File...**", quote=True)
    
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

        msg = GoogleDrive(user_id).upload_file(file_path, file.mime_type)
        await sent_message.edit(msg)
    except RPCError:
        await sent_message.edit(Messages.WENT_WRONG)

    LOGGER.info(f"Deleting: {file_path}")
    os.remove(file_path)

@Client.on_message(
    filters.incoming
    & filters.private
    & filters.command(BotCommands.YtDl)
)
async def _ytdl(client, message):
    user_id = message.from_user.id

    if await is_banned(user_id):
        await message.reply_text("You are banned from using this bot.", quote=True)
        return

    if not await check_forcesub(client, message, user_id):
        return
    
    if len(message.command) > 1:
        sent_message = await message.reply_text("🕵️ **Checking Link...**", quote=True)
        link = message.command[1]

        LOGGER.info(f"YTDL:{user_id}: {link}")
        await sent_message.edit(Messages.DOWNLOADING.format(link))

        result, file_path = utube_dl(link)
        if result:
            await sent_message.edit(
                Messages.DOWNLOADED_SUCCESSFULLY.format(
                    os.path.basename(file_path), humanbytes(os.path.getsize(file_path))
                )
            )

            msg = GoogleDrive(user_id).upload_file(file_path)
            await sent_message.edit(msg)

            LOGGER.info(f"Deleting: {file_path}")
            os.remove(file_path)
        else:
            await sent_message.edit(Messages.DOWNLOAD_ERROR.format(file_path, link))
    else:
        await message.reply_text(Messages.PROVIDE_YTDL_LINK, quote=True)
