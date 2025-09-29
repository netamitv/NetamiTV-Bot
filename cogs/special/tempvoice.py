import discord
from discord import app_commands
from discord.ext import commands, tasks
import json
import os
import datetime

class TempVoice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.temp_channels = {}
        self.setup_channels = {}
        self.user_cooldowns = {}
        self.dm_sent_users = set()
        
        if not os.path.exists('temp_voice.json'):
            default_data = {
                'setup_channels': {},
                'temp_channels': {},
                'user_cooldowns': {},
                'dm_sent_users': []
            }
            with open('temp_voice.json', 'w') as f:
                json.dump(default_data, f, indent=4)
    
        self.load_channels()
        self.check_empty_channels.start()

    def load_channels(self):
        try:
            with open('temp_voice.json', 'r') as f:
                content = f.read().strip()
                if not content:
                    self._create_default_data()
                    return
                
                data = json.loads(content)
                self.setup_channels = {int(k): int(v) for k, v in data.get('setup_channels', {}).items()}
                self.temp_channels = {int(k): int(v) for k, v in data.get('temp_channels', {}).items()}
                self.user_cooldowns = data.get('user_cooldowns', {})
                self.dm_sent_users = set(data.get('dm_sent_users', []))
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Error loading temp_voice.json: {e}")
            self._create_default_data()
    
    def _create_default_data(self):
        self.setup_channels = {}
        self.temp_channels = {}
        self.user_cooldowns = {}
        self.dm_sent_users = set()
        self.save_channels()
            
    def save_channels(self):
        data = {
            'setup_channels': self.setup_channels,
            'temp_channels': self.temp_channels,
            'user_cooldowns': self.user_cooldowns,
            'dm_sent_users': list(self.dm_sent_users)
        }
        with open('temp_voice.json', 'w') as f:
            json.dump(data, f, indent=4)

    @tasks.loop(seconds=10)
    async def check_empty_channels(self):
        for guild in self.bot.guilds:
            for vc in guild.voice_channels:
                if vc.id in self.setup_channels:
                    continue
                if len(vc.members) == 0 and vc.id in self.temp_channels:
                    audit_logger = self.bot.get_cog("AuditLogger")
                    if audit_logger:
                        user_id = self.temp_channels[vc.id]
                        user = self.bot.get_user(user_id)
                        username = user.name if user else "Unknown User"
                        audit_logger.log_temp_channel_deleted(user_id, username, vc.name, vc.guild.id)
                    
                    await vc.delete()
                    del self.temp_channels[vc.id]
                    self.save_channels()

    @commands.command(name="tempvoice")
    async def tempvoice_prefix(self, ctx, category: discord.CategoryChannel = None):
        if not self.bot.is_authorized(ctx.author.id):
            return await ctx.send("❌ Du hast nicht die Berechtigung, diesen Befehl zu nutzen.")
        
        if not category:
            embed = discord.Embed(
                title="Temporary Voice Setup Guide",
                description="> Here's how to set up temporary voice channels:\n\n"
                           "> 1. Right-click on a category where you want temp channels\n"
                           "> 2. Copy the category ID (Developer Mode must be enabled)\n"
                           "> 3. Use `!tempvoice <category-id>`\n\n"
                           "> Example: `!tempvoice 123456789`",
                color=discord.Color.blue()
            )
            return await ctx.send(embed=embed)

        join_channel = await ctx.guild.create_voice_channel(
            name="➕ Create Voice Channel",
            category=category
        )
        self.setup_channels[join_channel.id] = category.id
        self.save_channels()
        
        embed = discord.Embed(
            title="✅ Temporary Voice Setup Complete!",
            description="> System is ready!\n\n"
                       f"> 📌 Join {join_channel.mention} to create your own voice channel\n"
                       "> 🔧 Channel creator gets full control\n"
                       "> 🗑️ Channel auto-deletes when empty",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)

    @app_commands.command(name="tempvoice")
    @app_commands.describe(category="Select the category for temporary voice channels")
    async def tempvoice_slash(self, interaction: discord.Interaction, category: discord.CategoryChannel):
        if not self.bot.is_authorized(interaction.user.id):
            return await interaction.response.send_message("❌ Du hast nicht die Berechtigung, diesen Befehl zu nutzen.", ephemeral=True)
        
        join_channel = await interaction.guild.create_voice_channel(
            name="➕ Create Voice Channel",
            category=category
        )
        self.setup_channels[join_channel.id] = category.id
        self.save_channels()
        
        embed = discord.Embed(
            title="✅ Temporary Voice Setup Complete!",
            description="> System is ready!\n\n"
                       f"> 📌 Join {join_channel.mention} to create your own voice channel\n"
                       "> 🔧 Channel creator gets full control\n"
                       "> 🗑️ Channel auto-deletes when empty",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="removecooldown")
    @app_commands.describe(user="User to remove cooldown from")
    async def removecooldown(self, interaction: discord.Interaction, user: discord.Member):
        if not self.bot.is_authorized(interaction.user.id):
            return await interaction.response.send_message("❌ Du hast nicht die Berechtigung, diesen Befehl zu nutzen.", ephemeral=True)

        if str(user.id) in self.user_cooldowns:
            del self.user_cooldowns[str(user.id)]
            self.save_channels()
            await interaction.response.send_message(f"> ✅ Removed cooldown for {user.mention}!", ephemeral=True)
        else:
            await interaction.response.send_message(f"> ❌ {user.mention} has no active cooldown!", ephemeral=True)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if after.channel and after.channel.id in self.setup_channels:
            current_time = datetime.datetime.now().timestamp()
            last_creation = float(self.user_cooldowns.get(str(member.id), 0))

            if current_time - last_creation < 300:
                remaining = int(300 - (current_time - last_creation))
                try:
                    embed = discord.Embed(
                        title="⏰ Cooldown Active",
                        description=f"> Please wait {remaining} seconds before creating another channel!\n"
                                  f"> Or ask an admin to remove your cooldown.",
                        color=discord.Color.red()
                    )
                    await member.send(embed=embed)
                except:
                    pass
                await member.move_to(None)
                return

            category = self.bot.get_channel(self.setup_channels[after.channel.id])
            temp_channel = await member.guild.create_voice_channel(
                name=f"✏️ {member.name}'s Channel",
                category=category
            )
            await member.move_to(temp_channel)
            self.temp_channels[temp_channel.id] = member.id
            
            self.user_cooldowns[str(member.id)] = current_time
            self.save_channels()
            
            audit_logger = self.bot.get_cog("AuditLogger")
            if audit_logger:
                audit_logger.log_temp_channel_created(member, temp_channel)
            
            await temp_channel.set_permissions(member, 
                manage_channels=True,
                manage_permissions=True,
                connect=True,
                speak=True,
                move_members=True,
                priority_speaker=True
            )

            if member.id not in self.dm_sent_users:
                try:
                    embed = discord.Embed(
                        title="🎮 Your Voice Channel",
                        description="> Your temporary voice channel has been created!\n\n"
                                   "> You can:\n"
                                   "> ✏️ Rename the channel\n"
                                   "> 👥 Manage user permissions\n"
                                   "> 🔒 Lock/unlock the channel\n"
                                   "> 🔄 Move users\n\n"
                                   "> Channel will auto-delete when empty.",
                        color=discord.Color.blue()
                    )
                    await member.send(embed=embed)
                    self.dm_sent_users.add(member.id)
                    self.save_channels()
                except:
                    pass

        if before.channel and before.channel.id in self.temp_channels:
            if len(before.channel.members) == 0:
                audit_logger = self.bot.get_cog("AuditLogger")
                if audit_logger:
                    user_id = self.temp_channels[before.channel.id]
                    user = self.bot.get_user(user_id)
                    username = user.name if user else "Unknown User"
                    audit_logger.log_temp_channel_deleted(user_id, username, before.channel.name, before.channel.guild.id)
                
                await before.channel.delete()
                del self.temp_channels[before.channel.id]
                self.save_channels()

    def cog_unload(self):
        self.check_empty_channels.cancel()

async def setup(bot):
    await bot.add_cog(TempVoice(bot))