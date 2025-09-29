import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import logging

logger = logging.getLogger(__name__)

class TempChannel(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._rate_limit_cooldown = {}  # User cooldowns

    def is_rate_limited(self, user_id: int) -> bool:
        """Check if user is on cooldown"""
        import time
        now = time.time()
        if user_id in self._rate_limit_cooldown:
            if now < self._rate_limit_cooldown[user_id]:
                return True
        return False

    def set_user_cooldown(self, user_id: int, seconds: int = 30):
        """Set user cooldown"""
        import time
        self._rate_limit_cooldown[user_id] = time.time() + seconds

    @app_commands.command(name="tempchannel", description="Create a temporary channel in a category with 2-hour slowmode")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.describe(
        category="The category to create the channel in",
        name="The name for the new channel"
    )
    async def tempchannel(
        self,
        interaction: discord.Interaction,
        category: discord.CategoryChannel,
        name: str
    ):
        # Authorization check
        if not self.bot.is_authorized(interaction.user.id):
            return await interaction.response.send_message("❌ Du hast nicht die Berechtigung, diesen Befehl zu nutzen.", ephemeral=True)
        
        # Rate limit check
        if self.is_rate_limited(interaction.user.id):
            return await interaction.response.send_message("⏰ Du musst noch warten, bevor du diesen Befehl erneut verwenden kannst.", ephemeral=True)

        try:
            # SINGLE defer - no multiple responses
            await interaction.response.defer(ephemeral=True)
            
            # Set cooldown immediately
            self.set_user_cooldown(interaction.user.id, 30)
            
            # Create channel with ALL settings in ONE call
            overwrites = category.overwrites  # Use category permissions
            
            new_channel = await interaction.guild.create_text_channel(
                name=name,
                category=category,
                overwrites=overwrites,  # Set permissions immediately
                slowmode_delay=7200,    # Set slowmode immediately
                reason=f"Temporary channel created by {interaction.user}"
            )
            
            # SINGLE response only
            embed = discord.Embed(
                title="✅ Temporärer Channel Erstellt", 
                description=f"Channel {new_channel.mention} wurde in **{category.name}** mit 2h Slowmode erstellt",
                color=discord.Color.green()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except discord.HTTPException as e:
            if e.status == 429:
                await interaction.followup.send("⚠️ Bot ist rate-limited. Versuche es in 5 Minuten erneut.", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ Fehler: {str(e)[:100]}", ephemeral=True)
        except Exception as e:
            logger.error(f"TempChannel error: {e}")
            await interaction.followup.send("❌ Ein unerwarteter Fehler ist aufgetreten.", ephemeral=True)

    @app_commands.command(name="delete", description="Delete the current channel")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def delete_channel(self, interaction: discord.Interaction):
        if not self.bot.is_authorized(interaction.user.id):
            return await interaction.response.send_message("❌ Du hast nicht die Berechtigung, diesen Befehl zu nutzen.", ephemeral=True)
        
        # Rate limit check
        if self.is_rate_limited(interaction.user.id):
            return await interaction.response.send_message("⏰ Du musst noch warten, bevor du diesen Befehl erneut verwenden kannst.", ephemeral=True)

        try:
            await interaction.response.send_message(f"🗑️ Channel wird in 3 Sekunden gelöscht...", ephemeral=True)
            self.set_user_cooldown(interaction.user.id, 60)  # Longer cooldown for delete
            
            await asyncio.sleep(3)
            await interaction.channel.delete(reason=f"Deleted by {interaction.user}")
            
        except discord.HTTPException as e:
            if e.status == 429:
                await interaction.edit_original_response(content="⚠️ Bot ist rate-limited. Versuche es später erneut.")
            else:
                await interaction.edit_original_response(content=f"❌ Fehler beim Löschen: {str(e)[:100]}")
        except Exception as e:
            logger.error(f"Delete channel error: {e}")
            try:
                await interaction.edit_original_response(content="❌ Fehler beim Löschen des Channels.")
            except:
                pass  # Channel might already be deleted

async def setup(bot):
    await bot.add_cog(TempChannel(bot))