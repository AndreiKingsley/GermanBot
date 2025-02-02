import discord
from discord.ext import commands
import yt_dlp
import asyncio
import os
import re
import sqlite3
from googleapiclient.discovery import build

from _token import TOKEN, YOUTUBE_API_KEY  # Храни API-ключ в _token.py

# Инициализация бота
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Очередь песен (словарь для каждого сервера)
song_queue = {}

# Подключение к YouTube API
youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

# Подключение к SQLite
def init_db():
    """Инициализация базы данных SQLite"""
    conn = sqlite3.connect("music_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS downloaded_tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE,
            title TEXT,
            file_path TEXT
        )
    """)
    conn.commit()
    return conn

db_conn = init_db()

# Проверка, является ли ссылка плейлистом
def is_playlist(url):
    return "playlist?list=" in url or "&list=" in url

# Функция загрузки аудио
async def download_audio(url, guild_id):
    """Скачивает аудиофайл перед воспроизведением"""
    # Проверяем, есть ли трек в базе данных
    cursor = db_conn.cursor()
    cursor.execute("SELECT file_path FROM downloaded_tracks WHERE url = ?", (url,))
    result = cursor.fetchone()

    if result:
        # Если трек уже скачан, возвращаем путь к файлу
        file_path = result[0]
        title = cursor.execute("SELECT title FROM downloaded_tracks WHERE url = ?", (url,)).fetchone()[0]
        return file_path, title

    # Если трек не скачан, скачиваем его
    ydl_opts = {
        "format": "bestaudio/best",
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
        "outtmpl": f"downloads/{guild_id}/%(title)s.%(ext)s",
        "quiet": True,
    }

    os.makedirs(f"downloads/{guild_id}", exist_ok=True)

    loop = asyncio.get_running_loop()
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))
        filename = ydl.prepare_filename(info).replace(".webm", ".mp3").replace(".m4a", ".mp3")
        title = info["title"]

    # Сохраняем информацию о треке в базу данных
    cursor.execute("INSERT INTO downloaded_tracks (url, title, file_path) VALUES (?, ?, ?)", (url, title, filename))
    db_conn.commit()

    return filename, title

# Функция воспроизведения следующего трека
async def play_next(ctx):
    """Воспроизводит следующий трек, загружая его перед стартом"""
    guild_id = ctx.guild.id
    if guild_id in song_queue and song_queue[guild_id]:
        url, title = song_queue[guild_id].pop(0)

        await ctx.send(f"⬇ Загружаю: {title}...")
        filename, _ = await download_audio(url, guild_id)

        source = discord.FFmpegPCMAudio(filename, executable="ffmpeg", options="-loglevel quiet -ar 48000")

        ctx.voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop))
        await ctx.send(f"🎵 Сейчас играет: {title}")
    else:
        await ctx.send("🎵 Очередь пуста, ожидаю новые треки...")

# Подключение к голосовому каналу
async def ensure_voice(ctx):
    if ctx.author.voice:
        if ctx.voice_client is None:
            await ctx.author.voice.channel.connect()
    else:
        await ctx.send("Вы должны быть в голосовом канале!")
        return False
    return True

# Функция поиска видео на YouTube
def search_youtube(query):
    search_response = youtube.search().list(
        q=query,
        part="snippet",
        maxResults=5,
        type="video",
        safeSearch="none",
    ).execute()

    results = []
    for item in search_response["items"]:
        video_id = item["id"]["videoId"]
        title = item["snippet"]["title"]
        results.append((title, f"https://www.youtube.com/watch?v={video_id}"))

    return results

# Функция обработки одиночного трека
async def process_play(ctx, url):
    """Добавляет трек в очередь и загружает его"""
    guild_id = ctx.guild.id
    if guild_id not in song_queue:
        song_queue[guild_id] = []

    ydl_opts = {"quiet": True, "noplaylist": True, "extract_flat": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        title = info["title"]

    song_queue[guild_id].append((url, title))
    await ctx.send(f"✅ Добавлено в очередь: {title}")

    if not ctx.voice_client.is_playing():
        await play_next(ctx)

# Функция обработки плейлиста
async def process_playlist(ctx, url):
    """Обрабатывает скачивание и добавление плейлиста в очередь"""
    guild_id = ctx.guild.id
    if guild_id not in song_queue:
        song_queue[guild_id] = []

    await ctx.send("📜 Загружаю плейлист, подождите...")

    ydl_opts = {"quiet": True, "extract_flat": True, "playlistend": 20}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    for entry in info["entries"]:
        if "url" in entry:
            song_queue[guild_id].append((entry["url"], entry["title"]))

    await ctx.send(f"📥 Добавлено {len(info['entries'])} треков из плейлиста.")

    if not ctx.voice_client.is_playing():
        await play_next(ctx)

# Команды
@bot.command(name="play", aliases=["p"], help="Добавляет трек или плейлист в очередь. Пример: !play <запрос/ссылка>")
async def play(ctx, *, query: str):
    """Добавляет в очередь видео или плейлист"""
    if not await ensure_voice(ctx):
        return

    youtube_url_regex = re.compile(r"(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+")
    if not youtube_url_regex.match(query):
        results = search_youtube(query)
        if not results:
            await ctx.send("❌ Ничего не найдено на YouTube.")
            return

        # Создаем кнопки для выбора трека
        view = discord.ui.View(timeout=30)
        for i, (title, link) in enumerate(results):
            button = discord.ui.Button(label=f"{i+1}. {title[:40]}", style=discord.ButtonStyle.primary, custom_id=link)

            async def callback(interaction):
                await interaction.response.defer()
                await process_play(ctx, interaction.data["custom_id"])

            button.callback = callback
            view.add_item(button)

        await ctx.send("🔎 Выберите один из найденных треков:", view=view)
        return

    if is_playlist(query):
        await process_playlist(ctx, query)
    else:
        await process_play(ctx, query)

@bot.command(name="skip", aliases=["s"], help="Пропускает текущий трек.")
async def skip(ctx):
    """Пропускает текущий трек"""
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send("⏭ Пропускаю трек...")

@bot.command(name="queue", aliases=["q"], help="Показывает текущую очередь треков.")
async def queue(ctx):
    """Показывает очередь треков"""
    guild_id = ctx.guild.id
    if guild_id in song_queue and song_queue[guild_id]:
        queue_list = "\n".join([f"{i+1}. {title}" for i, (_, title) in enumerate(song_queue[guild_id])])
        await ctx.send(f"📜 Очередь:\n{queue_list}")
    else:
        await ctx.send("📭 Очередь пуста!")

@bot.command(name="pause", help="Ставит воспроизведение на паузу.")
async def pause(ctx):
    """Ставит текущий трек на паузу"""
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send("⏸ Музыка на паузе!")

@bot.command(name="resume", help="Возобновляет воспроизведение.")
async def resume(ctx):
    """Возобновляет воспроизведение"""
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send("▶ Продолжаю воспроизведение!")

@bot.command(name="stop", help="Останавливает воспроизведение и очищает очередь.")
async def stop(ctx):
    """Останавливает воспроизведение и очищает очередь"""
    if ctx.voice_client:
        ctx.voice_client.stop()
        song_queue[ctx.guild.id] = []
        await ctx.send("⏹ Воспроизведение остановлено и очередь очищена!")

@bot.command(name="remove", help="Удаляет трек из очереди по его номеру. Пример: !remove <номер>")
async def remove(ctx, index: int):
    """Удаляет трек из очереди по его номеру"""
    guild_id = ctx.guild.id
    if 0 < index <= len(song_queue[guild_id]):
        removed_song = song_queue[guild_id].pop(index - 1)
        await ctx.send(f"🗑 Удалено: {removed_song[1]}")

@bot.command(name="clear", help="Очищает очередь треков.")
async def clear(ctx):
    """Очищает очередь треков"""
    guild_id = ctx.guild.id
    if guild_id in song_queue:
        song_queue[guild_id] = []
        await ctx.send("🧹 Очередь очищена!")
    else:
        await ctx.send("📭 Очередь уже пуста!")

if __name__ == '__main__':
    bot.run(TOKEN)
