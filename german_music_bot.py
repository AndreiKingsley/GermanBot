import discord
from discord.ext import commands
import yt_dlp
import asyncio
import os
import re
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

# Проверка, является ли ссылка плейлистом
def is_playlist(url):
    return "playlist?list=" in url or "&list=" in url

# Функция загрузки аудио
async def download_audio(url, guild_id):
    """Получает аудио-стрим и информацию о треке"""
    ydl_opts = {
        'format': '251/250/249/bestaudio[ext=webm][acodec=opus]/bestaudio[acodec=opus]/bestaudio',  # Prefer Opus, fallback to best available
        'quiet': True,
        'no_warnings': True,
        'extract_flat': 'in_playlist',
        'skip_download': True,
        'force_generic_extractor': False,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'logtostderr': False,
        'no_color': True
    }

    try:
        # Создаем единый экземпляр YoutubeDL для повторного использования
        if not hasattr(download_audio, 'ydl'):
            download_audio.ydl = yt_dlp.YoutubeDL(ydl_opts)

        # Используем существующий экземпляр
        info = await asyncio.get_event_loop().run_in_executor(
            None, 
            lambda: download_audio.ydl.extract_info(url, download=False, process=False)
        )

        if not info:
            raise Exception("Не удалось получить информацию о треке")

        # Если нужна дополнительная обработка
        if info.get('_type') == 'url' or not info.get('url'):
            info = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: download_audio.ydl.extract_info(url, download=False)
            )

        title = info.get('title', 'Неизвестный трек')
        stream_url = info.get('url')

        if not stream_url and 'formats' in info:
            # Выбираем лучший аудио формат
            formats = [f for f in info['formats'] if f.get('acodec') != 'none']
            if formats:
                stream_url = formats[0]['url']

        if not stream_url:
            raise Exception("Не найдены форматы для воспроизведения")

        return stream_url, title
    except Exception as e:
        print(f"Ошибка при получении аудио: {str(e)}")
        raise

# Функция воспроизведения следующего трека
# Хранилище предзагруженных треков
preloaded_tracks = {}

async def preload_next_track(ctx, guild_id):
    """Предзагружает следующий трек из очереди"""
    if guild_id in song_queue and len(song_queue[guild_id]) > 0:
        next_url, next_title = song_queue[guild_id][0]
        try:
            stream_url, _ = await download_audio(next_url, guild_id)
            preloaded_tracks[guild_id] = {
                'url': next_url,
                'title': next_title,
                'stream_url': stream_url
            }
        except Exception as e:
            print(f"Ошибка при предзагрузке: {str(e)}")

async def play_next(ctx):
    """Воспроизводит следующий трек, используя предзагрузку"""
    guild_id = ctx.guild.id

    if guild_id not in song_queue or not song_queue[guild_id]:
        await ctx.send("🎵 Очередь пуста, ожидаю новые треки...")
        return

    # Получаем следующий трек
    url, title = song_queue[guild_id].pop(0)

    try:
        # Проверяем, есть ли предзагруженный трек
        if guild_id in preloaded_tracks and preloaded_tracks[guild_id]['url'] == url:
            await ctx.send(f"▶️ Воспроизведение: {title}")
            stream_url = preloaded_tracks[guild_id]['stream_url']
            del preloaded_tracks[guild_id]
        else:
            await ctx.send(f"🎵 Подготовка трека: {title}")
            stream_url, _ = await download_audio(url, guild_id)

        ffmpeg_options = {
            'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin',
            'options': '-vn'
        }
        source = discord.FFmpegPCMAudio(stream_url, **ffmpeg_options)

        # Начинаем воспроизведение
        ctx.voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop))

        # Предзагружаем следующий трек
        asyncio.create_task(preload_next_track(ctx, guild_id))

    except Exception as e:
        await ctx.send(f"❌ Ошибка при воспроизведении: {str(e)}")
        # В случае ошибки пытаемся воспроизвести следующий трек
        asyncio.create_task(play_next(ctx))

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

    try:
        # Используем существующий экземпляр YoutubeDL для быстрого получения информации
        if not hasattr(download_audio, 'ydl'):
            ydl_opts = {
                'quiet': True,
                'noplaylist': True,
                'extract_flat': True,
                'no_warnings': True
            }
            download_audio.ydl = yt_dlp.YoutubeDL(ydl_opts)

        info = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: download_audio.ydl.extract_info(url, download=False, process=False)
        )

        if not info:
            await ctx.send("❌ Не удалось получить информацию о треке")
            return

        title = info.get('title', 'Неизвестный трек')
        song_queue[guild_id].append((url, title))
        await ctx.send(f"✅ Добавлено в очередь: {title}")

        # Если это единственный трек в очереди, начинаем воспроизведение
        if len(song_queue[guild_id]) == 1 and not ctx.voice_client.is_playing():
            await play_next(ctx)
        # Если это второй трек, запускаем предзагрузку
        elif len(song_queue[guild_id]) == 1:
            asyncio.create_task(preload_next_track(ctx, guild_id))

    except Exception as e:
        await ctx.send(f"❌ Ошибка при добавлении трека: {str(e)}")

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
