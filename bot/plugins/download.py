import os
import asyncio
import aiofiles
from time import time
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

async def broadcast_stats(client, user_id, message):
    stats_msg = f"📊 Process Stats: User {user_id} | {message}"
    for chat in await client.get_chat_members(client.me.id):
        try:
            await client.send_message(chat.user.id, stats_msg)
        except Exception as e:
            LOGGER.error(f"Failed to send stats to {chat.user.id}: {e}")

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
    link = message.text if not message.command else message.command[1]

    if "drive.google.com" in link:
        await sent_message.edit(Messages.CLONING.format(link))
        LOGGER.info(f"Copy:{user_id}: {link}")
        msg = GoogleDrive(user_id).clone(link)
        await sent_message.edit(msg)
    else:
        filename = os.path.basename(link.split("|")[0].strip())
        dl_path = os.path.join(DOWNLOAD_DIRECTORY, filename)
        
        LOGGER.info(f"Download:{user_id}: {link}")
        await sent_message.edit(Messages.DOWNLOADING.format(link))
        start_time = time()
        result, file_path = await asyncio.to_thread(download_file, link, dl_path)
        if result:
            elapsed_time = time() - start_time
            await sent_message.edit(
                Messages.DOWNLOADED_SUCCESSFULLY.format(
                    os.path.basename(file_path), humanbytes(os.path.getsize(file_path))
                )
            )
            msg = GoogleDrive(user_id).upload_file(file_path)
            await sent_message.edit(msg)
            os.remove(file_path)
            await broadcast_stats(client, user_id, f"Downloaded {filename} in {elapsed_time:.2f}s")
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
    
    await sent_message.edit(
        Messages.DOWNLOAD_TG_FILE.format(file.file_name, humanbytes(file.file_size), file.mime_type)
    )
    try:
        start_time = time()
        file_path = await message.download(file_name=DOWNLOAD_DIRECTORY)
        elapsed_time = time() - start_time
        
        await sent_message.edit(
            Messages.DOWNLOADED_SUCCESSFULLY.format(os.path.basename(file_path), humanbytes(os.path.getsize(file_path)))
        )
        msg = GoogleDrive(user_id).upload_file(file_path, file.mime_type)
        await sent_message.edit(msg)
        os.remove(file_path)
        await broadcast_stats(client, user_id, f"Uploaded {file.file_name} in {elapsed_time:.2f}s")
    except RPCError:
        await sent_message.edit(Messages.WENT_WRONG)

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
        start_time = time()
        result, file_path = await asyncio.to_thread(utube_dl, link)
        
        if result:
            elapsed_time = time() - start_time
            await sent_message.edit(
                Messages.DOWNLOADED_SUCCESSFULLY.format(os.path.basename(file_path), humanbytes(os.path.getsize(file_path)))
            )
            msg = GoogleDrive(user_id).upload_file(file_path)
            await sent_message.edit(msg)
            os.remove(file_path)
            await broadcast_stats(client, user_id, f"Downloaded {file_path} in {elapsed_time:.2f}s")
        else:
            await sent_message.edit(Messages.DOWNLOAD_ERROR.format(file_path, link))
    else:
        await message.reply_text(Messages.PROVIDE_YTDL_LINK, quote=True)
