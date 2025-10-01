import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import os
import random
import asyncio
from datetime import datetime, timedelta

# Dictionary Format: Level: (Rollen-ID, Benötigte Nachrichten)
LEVEL_ROLES = {
    5:  (1397962388828848188, 100),    # Level 5 - 100 Nachrichten
    10: (1397962411922686063, 250),    # Level 10 - 250 Nachrichten
    15: (1389702468086268097, 500),    # Level 15 - 500 Nachrichten  
    20: (1397962433833730109, 1000),   # Level 20 - 1000 Nachrichten
    25: (1275157817837359144, 2000),   # Level 25 - 2000 Nachrichten
}

XP_PER_MESSAGE = 15
XP_COOLDOWN = 60  # Sekunden zwischen XP-Vergabe

class LevelingSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = 'data/levels.db'
        self.xp_cooldown = {}
        
        if not os.path.exists('data'):
            os.makedirs('data')
            
        self.init_database()
        
    def init_database(self):
        """Initialize the SQLite database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_levels (
            user_id INTEGER PRIMARY KEY,
            guild_id INTEGER NOT NULL,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 0,
            messages INTEGER DEFAULT 0,
            last_message INTEGER,
            UNIQUE(user_id, guild_id)
        )
        ''')
        
        conn.commit()
        conn.close()

    def calculate_level(self, xp):
        """Calculate level from XP"""
        return int((xp / 100) ** 0.5)

    def calculate_xp_for_level(self, level):
        """Calculate XP needed for level"""
        return int(level * level * 100)

    async def add_xp(self, user_id: int, guild_id: int, xp_amount: int):
        """Add XP to user and check for level up"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        now = int(datetime.utcnow().timestamp())
        
        cursor.execute('''
            INSERT OR REPLACE INTO user_levels (user_id, guild_id, xp, messages, last_message)
            VALUES (
                ?,
                ?,
                COALESCE((SELECT xp FROM user_levels WHERE user_id = ? AND guild_id = ?) + ?, ?),
                COALESCE((SELECT messages FROM user_levels WHERE user_id = ? AND guild_id = ?) + 1, 1),
                ?
            )
        ''', (user_id, guild_id, user_id, guild_id, xp_amount, xp_amount, user_id, guild_id, now))
        
        cursor.execute('SELECT xp FROM user_levels WHERE user_id = ? AND guild_id = ?', 
                      (user_id, guild_id))
        total_xp = cursor.fetchone()[0]
        
        new_level = self.calculate_level(total_xp)
        
        cursor.execute('UPDATE user_levels SET level = ? WHERE user_id = ? AND guild_id = ?',
                      (new_level, user_id, guild_id))
        
        conn.commit()
        conn.close()
        
        return new_level

    @commands.Cog.listener()
    async def on_message(self, message):
        """Award XP for messages"""
        if message.author.bot or not message.guild:
            return
            
        user_id = message.author.id
        guild_id = message.guild.id
        
        # Check cooldown
        if user_id in self.xp_cooldown:
            last_msg = self.xp_cooldown[user_id]
            if datetime.utcnow() - last_msg < timedelta(seconds=XP_COOLDOWN):
                return
                
        self.xp_cooldown[user_id] = datetime.utcnow()
        
        # Add XP and check level up
        old_level = self.get_level(user_id, guild_id)
        new_level = await self.add_xp(user_id, guild_id, XP_PER_MESSAGE)
        
        if new_level > old_level:
            await self.handle_level_up(message.author, message.channel, new_level)

    def get_level(self, user_id: int, guild_id: int) -> int:
        """Get current level of user"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT level FROM user_levels WHERE user_id = ? AND guild_id = ?',
                      (user_id, guild_id))
        result = cursor.fetchone()
        
        conn.close()
        return result[0] if result else 0

    async def handle_level_up(self, member: discord.Member, channel: discord.TextChannel, new_level: int):
        """Handle level up event"""
        embed = discord.Embed(
            title="🎉 Level Up!",
            description=f"Glückwunsch {member.mention}!\nDu hast **Level {new_level}** erreicht!",
            color=discord.Color.green()
        )
        
        await channel.send(embed=embed)
        
        # Check for role rewards
        if new_level in LEVEL_ROLES:
            role_id, _ = LEVEL_ROLES[new_level]
            role = member.guild.get_role(role_id)
            if role and role not in member.roles:
                await member.add_roles(role)
                await channel.send(f"🏆 {member.mention} hat die Rolle {role.mention} freigeschaltet!")

    @app_commands.command(name="level", description="Zeige dein aktuelles Level")
    async def level_command(self, interaction: discord.Interaction):
        """Show current level stats"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT xp, level, messages FROM user_levels WHERE user_id = ? AND guild_id = ?',
                      (interaction.user.id, interaction.guild.id))
        result = cursor.fetchone()
        
        if not result:
            await interaction.response.send_message("Du hast noch keine XP gesammelt!", ephemeral=True)
            return
            
        xp, level, messages = result
        next_level = level + 1
        xp_needed = self.calculate_xp_for_level(next_level)
        
        progress = (xp - self.calculate_xp_for_level(level)) / (xp_needed - self.calculate_xp_for_level(level)) * 100
        
        embed = discord.Embed(
            title=f"Level Stats für {interaction.user.display_name}",
            color=discord.Color.blue()
        )
        
        embed.add_field(name="Level", value=str(level), inline=True)
        embed.add_field(name="XP", value=f"{xp:,}/{xp_needed:,}", inline=True)
        embed.add_field(name="Nachrichten", value=f"{messages:,}", inline=True)
        
        progress_bar = "▰" * int(progress/10) + "▱" * (10-int(progress/10))
        embed.add_field(name="Fortschritt", value=f"{progress_bar} ({progress:.1f}%)", inline=False)
        
        await interaction.response.send_message(embed=embed)
        
        conn.close()

    @app_commands.command(name="leaderboard", description="Zeige die Top 10 User")
    async def leaderboard_command(self, interaction: discord.Interaction):
        """Show XP leaderboard"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT user_id, xp, level, messages 
            FROM user_levels 
            WHERE guild_id = ? 
            ORDER BY xp DESC LIMIT 10
        ''', (interaction.guild.id,))
        
        top_users = cursor.fetchall()
        
        embed = discord.Embed(
            title="🏆 Level Leaderboard",
            color=discord.Color.gold()
        )
        
        for idx, (user_id, xp, level, messages) in enumerate(top_users, 1):
            member = interaction.guild.get_member(user_id)
            name = member.display_name if member else f"User {user_id}"
            
            embed.add_field(
                name=f"#{idx} {name}",
                value=f"Level: {level} | XP: {xp:,} | Nachrichten: {messages:,}",
                inline=False
            )
        
        await interaction.response.send_message(embed=embed)
        
        conn.close()

    @app_commands.command(name="xpinfo", description="Zeige XP-Anforderungen für verschiedene Level")
    async def xp_info(self, interaction: discord.Interaction):
        """Show XP requirements for different levels"""
        embed = discord.Embed(
            title="📊 Level-System: Übersicht",
            description="Hier siehst du die verschiedenen Level und ihre Anforderungen:",
            color=discord.Color.blue()
        )
        
        # Zeige Anforderungen für alle Level
        for level, (role_id, msg_count) in LEVEL_ROLES.items():
            xp_needed = self.calculate_xp_for_level(level)
            role = interaction.guild.get_role(role_id)
            role_text = f"{role.mention}" if role else "Rolle nicht gefunden"
            
            embed.add_field(
                name=f"Level {level}",
                value=f"🎯 **{xp_needed:,} XP**\n"
                      f"💬 **{msg_count}** Nachrichten\n"
                      f"🏆 Rolle: {role_text}",
                inline=True
            )
            
        embed.add_field(
            name="ℹ️ Info",
            value=f"Du erhältst **{XP_PER_MESSAGE} XP** pro Nachricht\n"
                  f"(Cooldown: {XP_COOLDOWN} Sekunden)",
            inline=False
        )
        
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(LevelingSystem(bot))

