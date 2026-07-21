import discord
from discord.ui import View, Button
from typing import List, Dict

NUMBER_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

class SearchResultView(View):
    def __init__(self, ctx, results: List[Dict]):
        super().__init__(timeout=30)
        self.ctx = ctx
        self.results = results
        self.setup_buttons()

    async def button_callback(self, interaction: discord.Interaction):
        try:
            if not await self.interaction_check(interaction):
                return

            # Get the index from the button's custom_id
            index = int(interaction.data.get('custom_id', '0'))
            if 0 <= index < len(self.results):
                selected_result = self.results[index]

                # Disable all buttons
                for item in self.children:
                    item.disabled = True
                await interaction.message.edit(view=self)

                # Process the selected track
                await interaction.response.send_message(f"🎵 Добавляю трек: {selected_result['title']}")
                await self.ctx.invoke(self.ctx.bot.get_command("play"), query=selected_result["url"])
            else:
                await interaction.response.send_message("❌ Неверный выбор трека.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message("❌ Произошла ошибка при выборе трека.", ephemeral=True)

    def setup_buttons(self):
        # Ограничиваемся числом доступных эмодзи (до 10)
        for i, result in enumerate(self.results[:len(NUMBER_EMOJIS)]):
            # Create a button for each search result (по 5 кнопок в ряд)
            button = Button(
                style=discord.ButtonStyle.primary,
                emoji=NUMBER_EMOJIS[i],
                custom_id=str(i),
                row=i // 5
            )
            button.callback = self.button_callback
            self.add_item(button)

    def create_embed(self) -> discord.Embed:
        try:
            embed = discord.Embed(
                title="🎵 Выберите трек для воспроизведения",
                description="Нажмите на кнопку с номером, чтобы начать проигрывание:",
                color=discord.Color.blue()
            )

            if self.results:
                # Create a clean list of all results
                description = [embed.description, ""]  # Start with the initial description
                for i, result in enumerate(self.results[:len(NUMBER_EMOJIS)]):
                    title = result['title'][:70] + "..." if len(result['title']) > 70 else result['title']
                    emoji = NUMBER_EMOJIS[i]
                    description.append(
                        f"{emoji} **{title}**\n"
                        f"└ 📺 **{result['channel']}** ・ ⏱️ {result['duration']}\n"
                        "─────────────"
                    )

                embed.description = "\n".join(description)

            embed.set_footer(text="Бот автоматически подключится к голосовому каналу и начнет воспроизведение")

            return embed
        except Exception as e:
            # Fallback embed in case of errors
            embed = discord.Embed(
                title="🎵 Результаты поиска",
                description="Произошла ошибка при создании превью. Но вы все еще можете выбрать трек кнопками ниже.",
                color=discord.Color.red()
            )
            return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("❌ Это не ваша команда!", ephemeral=True)
            return False
        return True

    async def select_result(self, interaction: discord.Interaction, index: int):
        """Legacy method, now handled in button_callback"""
        pass

    async def show_search_results(self):
        embed = self.create_embed()
        return await self.ctx.send(embed=embed, view=self)
