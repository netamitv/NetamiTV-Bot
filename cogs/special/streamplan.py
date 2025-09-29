import discord
from discord import app_commands
from discord.ext import commands

class StreamPlan(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.embed_handler = None

    async def cog_load(self):
        self.embed_handler = self.bot.get_cog('EmbedHandler')

    @app_commands.command(name="streamplan", description="Zeigt Netamis Streaming-Zeitplan")
    async def streamplan(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🎮 Netamis Streaming-Zeitplan",
            description="Sei dabei, wenn ich live auf Twitch streame um 17:00 Uhr!\nÄnderungen werden immer vorher angekündigt.",
            color=0x6441a5  # Twitch Lila
        )
        
        # Streaming-Tage
        embed.add_field(
            name="📅 Regelmäßige Stream-Tage",
            value="• Dienstag: 17:00 Uhr\n• Mittwoch: 17:00 Uhr\n• Freitag: 17:00 Uhr\n• Samstag: 17:00 Uhr",
            inline=False
        )
        
        # Twitch-Link
        embed.add_field(
            name="🎯 Wo ihr mich findet",
            value="[Live auf Twitch dabei sein](https://www.twitch.tv/netami_tv)",
            inline=False
        )
        
        # Twitch Logo als Thumbnail
        embed.set_thumbnail(url="https://cdn3.iconfinder.com/data/icons/social-messaging-ui-color-shapes-2-free/128/social-twitch-circle-512.png")
        
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(StreamPlan(bot))
