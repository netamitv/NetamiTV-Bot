import discord
from discord.ext import commands

class ScreeningRole(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        GUILD_ID = 556552682865688603  # Your server ID here
        ROLE_ID = 1275157817837359144  # Your role ID here
        
        # Check if correct server and member completed screening
        if after.guild.id == GUILD_ID and before.pending and not after.pending:
            role = after.guild.get_role(ROLE_ID)
            if role:
                try:
                    await after.add_roles(role)
                except discord.HTTPException:
                    pass

async def setup(bot):
    await bot.add_cog(ScreeningRole(bot))