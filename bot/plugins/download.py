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

async def send_progress(sent_message, file_name, downloaded, total_size, start_time):
    percent = (downloaded / total_size) * 100
    elapsed_time = time() - start_time
    speed = downloaded / elapsed_time if elapsed_time > 0 else 0
    remaining_time = (total_size - downloaded) / speed if speed > 0 else 0
    progress_msg = (f"📥 Downloading {file_name}\n"
                    f"Progress: {humanbytes(downloaded)}/{humanbytes(total_size)} ({percent:.2f}%)\n"
                    f"Speed: {humanbytes(speed)}/s\n"
                    f"ETA: {remaining_time:.2f}s")
    await sent_message.edit(progress_msg)

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
        
        result, file_path, total_size = await asyncio.to_thread(download_file, link, dl_path, send_progress, sent_message, filename, start_time)
        
        if result:
            elapsed_time = time() - start_time
            await sent_message.edit(
                Messages.DOWNLOADED_SUCCESSFULLY.format(
                    os.path.basename(file_path), humanbytes(os.path.getsize(file_path))
                )
            )
            upload_start = time()
            msg = await asyncio.to_thread(GoogleDrive(user_id).upload_file, file_path)
            upload_time = time() - upload_start
            await sent_message.edit(msg + f"\n🚀 Upload Speed: {humanbytes(os.path.getsize(file_path)/upload_time)}/s")
            os.remove(file_path)
            await broadcast_stats(client, user_id, f"Downloaded {filename} in {elapsed_time:.2f}s and uploaded in {upload_time:.2f}s")
        else:
            await sent_message.edit(Messages.DOWNLOAD_ERROR.format(file_path, link))

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
            msg = await asyncio.to_thread(GoogleDrive(user_id).upload_file, file_path)
            upload_time = time() - start_time
            await sent_message.edit(msg + f"\n🚀 Upload Speed: {humanbytes(os.path.getsize(file_path)/upload_time)}/s")
            os.remove(file_path)
            await broadcast_stats(client, user_id, f"Downloaded {file_path} in {elapsed_time:.2f}s and uploaded in {upload_time:.2f}s")
        else:
            await sent_message.edit(Messages.DOWNLOAD_ERROR.format(file_path, link))
    else:
        await message.reply_text(Messages.PROVIDE_YTDL_LINK, quote=True)
