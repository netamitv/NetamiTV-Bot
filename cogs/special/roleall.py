import discord
from discord import app_commands
from discord.ext import commands
import asyncio

class RoleAll(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="roleall")
    @app_commands.describe(role="Select the role to give to everyone")
    @app_commands.default_permissions(administrator=True)
    async def roleall(self, interaction: discord.Interaction, role: discord.Role):
        """Give a role to all members"""
        # First confirmation message
        embed = discord.Embed(
            title="⚠️ Role Mass Add Confirmation",
            description=f"Are you sure you want to add the role {role.mention} to **ALL** members?\n\n"
                       f"Total members: {len(interaction.guild.members)}\n"
                       f"This action cannot be undone!",
            color=discord.Color.yellow()
        )
        
        # Create buttons
        class ConfirmButtons(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=30)
                
            @discord.ui.button(label="Yes", style=discord.ButtonStyle.green)
            async def confirm(self, button_interaction: discord.Interaction, button: discord.ui.Button):
                await button_interaction.response.defer()
                progress_msg = await interaction.channel.send(f"Adding {role.name} to all members... 0%")
                
                total_members = len(interaction.guild.members)
                processed = 0
                
                for member in interaction.guild.members:
                    if role not in member.roles:
                        try:
                            await member.add_roles(role)
                            processed += 1
                            if processed % 10 == 0:
                                progress = (processed / total_members) * 100
                                await progress_msg.edit(content=f"Adding {role.name} to all members... {progress:.1f}%")
                            await asyncio.sleep(1.5)
                        except discord.Forbidden:
                            continue
                
                await progress_msg.edit(content=f"✅ Successfully added {role.name} to {processed} members!")
                self.stop()
                
            @discord.ui.button(label="No", style=discord.ButtonStyle.red)
            async def cancel(self, button_interaction: discord.Interaction, button: discord.ui.Button):
                await button_interaction.response.send_message("❌ Role mass add cancelled.", ephemeral=True)
                self.stop()

        await interaction.response.send_message(embed=embed, view=ConfirmButtons())

async def setup(bot):
    await bot.add_cog(RoleAll(bot))
