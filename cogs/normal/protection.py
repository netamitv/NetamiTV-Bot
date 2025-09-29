import discord
from discord import app_commands
from discord.ext import commands
import datetime
from collections import defaultdict

class Protection(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.anti_nuke = defaultdict(lambda: {'actions': 0, 'last_reset': datetime.datetime.now()})
        self.raid_protection = {
            'enabled': False,
            'account_age': 7,
            'join_threshold': 10,
            'join_window': 10
        }
        self.recent_joins = []
        self.invite_tracker = defaultdict(dict)

    @app_commands.command(name="antinuke", description="Configure anti-nuke settings")
    async def antinuke(self, interaction: discord.Interaction, action: str):
        if not self.bot.is_authorized(interaction.user.id):
            return await interaction.response.send_message("❌ Du hast nicht die Berechtigung, diesen Befehl zu nutzen.", ephemeral=True)
        
        if action.lower() == "enable":
            self.anti_nuke[interaction.guild.id]['enabled'] = True
            await interaction.response.send_message("Anti-nuke protection enabled!")
        elif action.lower() == "disable":
            self.anti_nuke[interaction.guild.id]['enabled'] = False
            await interaction.response.send_message("Anti-nuke protection disabled!")

    @app_commands.command(name="raidprotection", description="Configure raid protection")
    async def raidprotection(self, interaction: discord.Interaction, action: str, value: int = None):
        if not self.bot.is_authorized(interaction.user.id):
            return await interaction.response.send_message("❌ Du hast nicht die Berechtigung, diesen Befehl zu nutzen.", ephemeral=True)
        
        if action.lower() == "enable":
            self.raid_protection['enabled'] = True
            await interaction.response.send_message("Raid protection enabled!")
        elif action.lower() == "disable":
            self.raid_protection['enabled'] = False
            await interaction.response.send_message("Raid protection disabled!")
        elif action.lower() in ["age", "threshold", "window"] and value is not None:
            if action.lower() == "age":
                self.raid_protection['account_age'] = value
            elif action.lower() == "threshold":
                self.raid_protection['join_threshold'] = value
            elif action.lower() == "window":
                self.raid_protection['join_window'] = value
            await interaction.response.send_message(f"Raid protection {action} set to {value}")

    @app_commands.command(name="securitystatus", description="Check server security settings")
    async def securitystatus(self, interaction: discord.Interaction):
        if not self.bot.is_authorized(interaction.user.id):
            return await interaction.response.send_message("❌ Du hast nicht die Berechtigung, diesen Befehl zu nutzen.", ephemeral=True)
        
        embed = discord.Embed(
            title="Security Status",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="Anti-Nuke",
            value=f"Enabled: {self.anti_nuke[interaction.guild.id].get('enabled', False)}\n"
                  f"Recent Actions: {self.anti_nuke[interaction.guild.id]['actions']}",
            inline=False
        )
        
        embed.add_field(
            name="Raid Protection",
            value=f"Enabled: {self.raid_protection['enabled']}\n"
                  f"Min Account Age: {self.raid_protection['account_age']} days\n"
                  f"Join Threshold: {self.raid_protection['join_threshold']} joins\n"
                  f"Time Window: {self.raid_protection['join_window']} minutes",
            inline=False
        )
        
        await interaction.response.send_message(embed=embed)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if self.raid_protection['enabled']:
            account_age = (datetime.datetime.now() - member.created_at).days
            if account_age < self.raid_protection['account_age']:
                await member.kick(reason=f"Anti-Raid: Account too new ({account_age} days old)")
                return

            # Track recent joins
            self.recent_joins.append(datetime.datetime.now())
            self.recent_joins = [j for j in self.recent_joins 
                               if (datetime.datetime.now() - j).seconds < self.raid_protection['join_window'] * 60]

            if len(self.recent_joins) > self.raid_protection['join_threshold']:
                await member.guild.default_role.edit(permissions=discord.Permissions.none())
                log_channel = member.guild.system_channel
                if log_channel:
                    await log_channel.send("⚠️ Raid detected! Server locked down!")

        if hasattr(self.bot, 'invite_log_channel'):
            invites = await member.guild.invites()
            for invite in invites:
                if invite.code in self.invite_tracker[member.guild.id]:
                    if invite.uses > self.invite_tracker[member.guild.id][invite.code]:
                        log_channel = member.guild.get_channel(self.bot.invite_log_channel)
                        if log_channel:
                            embed = discord.Embed(title="Member Joined", color=discord.Color.green())
                            embed.add_field(name="Member", value=f"{member.mention} ({member.id})")
                            embed.add_field(name="Invited by", value=f"{invite.inviter.mention}")
                            embed.add_field(name="Invite Code", value=invite.code)
                            embed.add_field(name="Total Uses", value=f"{invite.uses}")
                            await log_channel.send(embed=embed)
                        break

async def setup(bot):
    await bot.add_cog(Protection(bot))
