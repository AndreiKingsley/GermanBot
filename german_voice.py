import asyncio

import discord
from discord import FFmpegPCMAudio
from discord.ext import commands

from _token import TOKEN

# Инициализация бота
intents = discord.Intents.default()
intents.voice_states = True
intents.guilds = True
intents.members = True
intents.messages = True
bot = commands.Bot(command_prefix="!", intents=intents)

voice_clients = {}


def play_audio(vc, file_path, guild_id):
    def after_playback(error):
        if guild_id in voice_clients:
            asyncio.run_coroutine_threadsafe(voice_clients[guild_id].disconnect(), bot.loop)
            del voice_clients[guild_id]

    source = FFmpegPCMAudio(file_path)
    vc.play(source, after=after_playback)


@bot.event
async def on_voice_state_update(member, before, after):
    if after.channel and not before.channel:  # Пользователь зашел в канал
        channel = after.channel
        if member != bot.user:
            if channel.guild.id not in voice_clients:
                vc = await channel.connect()
                voice_clients[channel.guild.id] = vc
            else:
                vc = voice_clients[channel.guild.id]
            play_audio(vc, "welcome.mp3", channel.guild.id)


@bot.command()
async def join(ctx):
    if ctx.author.voice:
        channel = ctx.author.voice.channel
        if ctx.guild.id not in voice_clients:
            vc = await channel.connect()
            voice_clients[ctx.guild.id] = vc
        await ctx.send("Подключился к голосовому каналу!")
    else:
        await ctx.send("Ты должен быть в голосовом канале!")


@bot.command()
async def leave(ctx):
    if ctx.guild.id in voice_clients:
        await voice_clients[ctx.guild.id].disconnect()
        del voice_clients[ctx.guild.id]
        await ctx.send("Отключился от голосового канала!")


if __name__ == "__main__":
    bot.run(TOKEN)
