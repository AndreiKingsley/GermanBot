import discord
from discord.ext import commands
from discord.ui import View, Button
from discord import ButtonStyle
import yt_dlp
import asyncio
import os
import re
import time
from googleapiclient.discovery import build

from _token import TOKEN, YOUTUBE_API_KEY  # Храни API-ключ в _token.py

# Global variables
current_view = None

class MusicPlayerView(View):
    def __init__(self, ctx, title: str, duration: int = None, thumbnail_url: str = None):
        super().__init__(timeout=None)
        self.ctx = ctx
        self.title = title
        self.duration = duration
        self.thumbnail_url = thumbnail_url
        self.start_time = time.time()
        self.message = None
        self.update_task = None
        self.is_playing = True
        self.is_paused = False
        self.volume = 1.0  # Default volume
        self.loop = False  # Track repeat
        self.pause_time = None
        self.guild_id = ctx.guild.id

    async def start_updates(self):
        self.update_task = asyncio.create_task(self.update_progress())

    async def update_progress(self):
        try:
            while self.is_playing:
                await self.update_message()
                await asyncio.sleep(5)  # Update every 5 seconds
        except Exception as e:
            print(f"Error in progress update: {e}")

    def create_progress_bar(self):
        try:
            if self.is_paused and self.pause_time:
                elapsed = int(self.pause_time - self.start_time)
            else:
                elapsed = int(time.time() - self.start_time)

            if self.duration:
                progress = min(elapsed / self.duration, 1.0)
                duration_str = f"{int(self.duration/60):02d}:{int(self.duration%60):02d}"
            else:
                progress = 0
                duration_str = "--:--"

            bar_length = 16
            filled_length = int(bar_length * progress)

            # Создаем стильный индикатор прогресса
            if filled_length == 0:
                bar = "○" + "─" * (bar_length - 1)
            elif filled_length == bar_length:
                bar = "━" * (bar_length - 1) + "⬤"
            else:
                bar = "━" * (filled_length - 1) + "⬤" + "─" * (bar_length - filled_length)

            minutes, seconds = divmod(elapsed, 60)
            time_str = f"{int(minutes):02d}:{int(seconds):02d}"

            # Добавляем оставшееся время
            if self.duration:
                remaining = max(0, self.duration - elapsed)
                r_minutes, r_seconds = divmod(remaining, 60)
                remaining_str = f"-{int(r_minutes):02d}:{int(r_seconds):02d}"
            else:
                remaining_str = "∞"

            return f"`{time_str}` `{bar}` `{remaining_str}`"
        except Exception as e:
            print(f"Error in progress bar: {e}")
            return "`──────────────────`"

    async def update_message(self):
        if self.message:
            try:
                # Выбираем цвет в зависимости от состояния
                if self.is_paused:
                    color = discord.Color.orange()
                elif self.loop:
                    color = discord.Color.green()
                else:
                    color = discord.Color.blue()

                # Создаем основной эмбед
                embed = discord.Embed(color=color, timestamp=discord.utils.utcnow())

                # Форматируем название с URL если возможно
                title_text = f"**[{self.title}]({self.ctx.message.jump_url})**" if hasattr(self.ctx, 'message') else f"**{self.title}**"

                # Добавляем название трека с прогресс баром
                progress_bar = self.create_progress_bar()
                description_parts = [
                    title_text,
                    "",  # Пустая строка для отступа
                    progress_bar
                ]

                # Добавляем информацию о следующем треке если есть
                if self.guild_id in song_queue and len(song_queue[self.guild_id]) > 1:
                    next_track = song_queue[self.guild_id][1][1]  # [1] for next track, [0] is current
                    description_parts.extend([
                        "",  # Пустая строка для отступа
                        "─" * 20,  # Разделитель
                        f"⏩ **Следующий трек**\n`→` {next_track}"
                    ])

                embed.description = "\n".join(description_parts)

                # Добавляем информацию о плеере
                embed.set_author(
                    name="Музыкальный плеер",
                    icon_url=self.ctx.guild.me.display_avatar.url
                )

                if self.thumbnail_url:
                    embed.set_thumbnail(url=self.thumbnail_url)

                # Добавляем статус воспроизведения
                status_parts = []
                if self.loop:
                    status_parts.append("🔁 Повтор включен")
                status_parts.append("⏸️ На паузе" if self.is_paused else "▶️ Проигрывается")
                status_text = " • ".join(status_parts)
                embed.add_field(
                    name="🎵 Статус",
                    value=status_text,
                    inline=True
                )

                # Информация о громкости
                volume_percentage = int(self.volume * 100)
                volume_bar = self.create_volume_bar()
                volume_info = [
                    self.get_volume_icon(),
                    f"`{volume_bar}`",
                    f"**{volume_percentage}%**"
                ]
                embed.add_field(
                    name="🔊 Громкость",
                    value=" ".join(volume_info),
                    inline=True
                )

                # Пустое поле для выравнивания
                embed.add_field(name="⠀", value="⠀", inline=True)

                # Добавляем информацию об очереди
                if self.guild_id in song_queue and len(song_queue[self.guild_id]) > 1:  # > 1 because first track is current
                    queue_list = []
                    total_tracks = len(song_queue[self.guild_id])

                    # Показываем следующие 3 трека
                    for i in range(1, min(4, total_tracks)):  # Start from 1 to skip current track
                        next_title = song_queue[self.guild_id][i][1]
                        queue_list.append(f"`{i}.` {next_title}")

                    if total_tracks > 4:
                        remaining = total_tracks - 4
                        tracks_word = 'трек' if remaining == 1 else 'трека' if 1 < remaining < 5 else 'треков'
                        queue_list.append(f"\n`─────`\nИ ещё **{remaining}** {tracks_word} в очереди")

                    if queue_list:
                        embed.add_field(
                            name="📑 В очереди",
                            value="\n".join(queue_list),
                            inline=False
                        )

                # Собираем информацию для footer
                footer_parts = []

                # Добавляем длительность
                if self.duration:
                    minutes, seconds = divmod(self.duration, 60)
                    duration_str = f"{int(minutes)}:{int(seconds):02d}"
                    footer_parts.append(f"⏱️ {duration_str}")

                # Добавляем статус очереди
                total_tracks = len(song_queue.get(self.guild_id, []))
                if total_tracks > 1:  # > 1 because first track is current
                    tracks_word = 'трек' if total_tracks == 2 else 'трека' if 2 < total_tracks < 5 else 'треков'
                    footer_parts.append(f"📑 {total_tracks - 1} {tracks_word} в очереди")
                else:
                    footer_parts.append("📑 Очередь пуста")

                # Добавляем статус повтора
                if self.loop:
                    footer_parts.append("🔁 Повтор включен")

                # Добавляем время обновления
                footer_parts.append("🔄 Обновлено")
                embed.set_footer(text=" • ".join(footer_parts))

                await self.message.edit(embed=embed, view=self)

            except Exception as e:
                print(f"Error updating message: {e}")

    @discord.ui.button(emoji="⏸️", style=ButtonStyle.gray)
    async def pause_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.voice and interaction.user.voice.channel == self.ctx.voice_client.channel:
            if self.ctx.voice_client.is_playing():
                self.ctx.voice_client.pause()
                button.emoji = "▶️"
                self.is_paused = True
                self.pause_time = time.time()
            else:
                self.ctx.voice_client.resume()
                button.emoji = "⏸️"
                self.is_paused = False
                if self.pause_time:
                    self.start_time += (time.time() - self.pause_time)
                    self.pause_time = None
            await self.update_message()
            await interaction.response.defer()
        else:
            await interaction.response.send_message("Вы должны быть в том же голосовом канале!", ephemeral=True)

    @discord.ui.button(emoji="⏭️", style=ButtonStyle.gray)
    async def skip_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.voice and interaction.user.voice.channel == self.ctx.voice_client.channel:
            self.ctx.voice_client.stop()
            await interaction.response.send_message("⏭️ Пропускаю трек...", ephemeral=True)
        else:
            await interaction.response.send_message("Вы должны быть в том же голосовом канале!", ephemeral=True)

    def get_volume_icon(self):
        if self.volume >= 0.75:
            return "🔊"
        elif self.volume >= 0.4:
            return "🔉"
        elif self.volume > 0:
            return "🔈"
        else:
            return "🔇"

    def create_volume_bar(self):
        bar_length = 10
        filled = int(self.volume * bar_length)
        if filled == 0 and self.volume > 0:
            filled = 1
        empty = bar_length - filled
        return "█" * filled + "░" * empty

    @discord.ui.button(emoji="🔊", style=ButtonStyle.gray)
    async def volume_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.voice and interaction.user.voice.channel == self.ctx.voice_client.channel:
            # Циклическое изменение громкости: 100% -> 75% -> 50% -> 25% -> 0% -> 100%
            if self.volume >= 0.9:  # 100% -> 75%
                self.volume = 0.75
            elif self.volume >= 0.7:  # 75% -> 50%
                self.volume = 0.5
            elif self.volume >= 0.4:  # 50% -> 25%
                self.volume = 0.25
            elif self.volume >= 0.2:  # 25% -> 0%
                self.volume = 0.0
            else:  # 0% -> 100%
                self.volume = 1.0

            button.emoji = self.get_volume_icon()

            if hasattr(self.ctx.voice_client, 'source') and self.ctx.voice_client.source:
                self.ctx.voice_client.source.volume = self.volume

            # Показываем текущую громкость с визуальным индикатором
            volume_percentage = int(self.volume * 100)
            volume_bar = self.create_volume_bar()
            await interaction.response.send_message(
                f"{self.get_volume_icon()} Громкость: **{volume_percentage}%**\n`{volume_bar}`",
                ephemeral=True
            )
            await self.update_message()
        else:
            await interaction.response.send_message(
                "Вы должны быть в том же голосовом канале!",
                ephemeral=True
            )

    @discord.ui.button(emoji="🔁", style=ButtonStyle.gray)
    async def loop_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.voice and interaction.user.voice.channel == self.ctx.voice_client.channel:
            self.loop = not self.loop
            button.style = ButtonStyle.green if self.loop else ButtonStyle.gray
            await self.update_message()
            await interaction.response.defer()
        else:
            await interaction.response.send_message("Вы должны быть в том же голосовом канале!", ephemeral=True)

    def stop_updates(self):
        self.is_playing = False
        if self.update_task:
            self.update_task.cancel()

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
    global current_view
    if current_view and not current_view.loop:
        current_view.stop_updates()
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

        # Используем существующий экземпляр для полного извлечения информации
        info = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: download_audio.ydl.extract_info(url, download=False)
        )

        if not info:
            raise Exception("Не удалось получить информацию о треке")

        title = info.get('title', 'Неизвестный трек')
        duration = info.get('duration')
        stream_url = info.get('url')
        thumbnail_url = info.get('thumbnail')

        if not stream_url and 'formats' in info:
            # Выбираем лучший аудио формат
            formats = [f for f in info['formats'] if f.get('acodec') != 'none']
            if formats:
                stream_url = formats[0]['url']

        if not stream_url:
            raise Exception("Не найдены форматы для воспроизведения")

        return stream_url, title, duration, thumbnail_url
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
            stream_url, title, duration, thumbnail_url = await download_audio(next_url, guild_id)
            preloaded_tracks[guild_id] = {
                'url': next_url,
                'title': title,
                'stream_url': stream_url,
                'duration': duration,
                'thumbnail_url': thumbnail_url
            }
        except Exception as e:
            print(f"Ошибка при предзагрузке: {str(e)}")

async def play_next(ctx):
    """Воспроизводит следующий трек, используя предзагрузку"""
    global current_view
    guild_id = ctx.guild.id

    if guild_id not in song_queue or not song_queue[guild_id]:
        await ctx.send("🎵 Очередь пуста, ожидаю новые треки...")
        return

    # Получаем следующий трек
    if current_view and current_view.loop:
        url, title = song_queue[guild_id][0]  # Don't pop when looping
    else:
        url, title = song_queue[guild_id].pop(0)

    try:
        # Проверяем, есть ли предзагруженный трек
        if guild_id in preloaded_tracks and preloaded_tracks[guild_id]['url'] == url:
            stream_url = preloaded_tracks[guild_id]['stream_url']
            title = preloaded_tracks[guild_id]['title']
            duration = preloaded_tracks[guild_id]['duration']
            thumbnail_url = preloaded_tracks[guild_id]['thumbnail_url']
            del preloaded_tracks[guild_id]
        else:
            stream_url, title, duration, thumbnail_url = await download_audio(url, guild_id)

        ffmpeg_options = {
            'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin',
            'options': '-vn -filter:a volume=1.0'
        }
        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(stream_url, **ffmpeg_options),
            volume=1.0
        )

        # Создаем новый view для трека
        view = MusicPlayerView(ctx, title, duration, thumbnail_url)

        # Создаем embed с информацией о треке
        embed = discord.Embed(
            title="🎵 Сейчас играет",
            description=f"**{title}**",
            color=discord.Color.blue()
        )

        if thumbnail_url:
            embed.set_thumbnail(url=thumbnail_url)

        # Добавляем информацию о прогрессе
        embed.add_field(name="Прогресс", value=view.create_progress_bar(), inline=False)

        # Добавляем информацию об очереди
        if len(song_queue[guild_id]) > 0:
            next_song = song_queue[guild_id][0][1]  # Получаем название следующего трека
            queue_info = f"Следующий: **{next_song}**"
            if len(song_queue[guild_id]) > 1:
                queue_info += f"\nВ очереди: **{len(song_queue[guild_id]) - 1}** треков"
            embed.add_field(name="Очередь", value=queue_info, inline=False)

        # Отправляем сообщение с view и сохраняем его
        view.message = await ctx.send(embed=embed, view=view)

        # Запускаем обновление прогресса
        await view.start_updates()

        # Сохраняем текущий view
        if current_view:
            current_view.stop_updates()
        current_view = view

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
