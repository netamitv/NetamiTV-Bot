import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import os
import datetime
import asyncio
from typing import Optional, Dict, Any

# ====== KONFIGURATION - HIER DEINE IDs EINTRAGEN ======
REVIEW_CHANNEL_ID = 1397962388828848188      # Channel wo Admins reviewen
APPROVED_CHANNEL_ID = 1397962411922686063    # Channel wo genehmigte Bilder gepostet werden  
ADMIN_ROLE_ID = 1389702468086268097          # Role ID die approve/decline kann
UPLOAD_CHANNEL_ID = 1397962433833730109      # Channel wo /review verwendet werden darf
USER_ROLE_ID = 1275157817837359144           # Role ID die /review verwenden darf

class ReviewSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = 'data/review_system.db'
        
        if not os.path.exists('data'):
            os.makedirs('data')

        self.init_database()
        
        self.review_channel_id = REVIEW_CHANNEL_ID
        self.approved_channel_id = APPROVED_CHANNEL_ID  
        self.admin_role_id = ADMIN_ROLE_ID
        self.upload_channel_id = UPLOAD_CHANNEL_ID
        self.user_role_id = USER_ROLE_ID
        
        self._channel_cache = {}
        self._user_cache = {}
        self._last_request_time = 0
        self._request_delay = 0.1

    def init_database(self):
        """Initialize the SQLite database with required tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            file_url TEXT NOT NULL,
            filename TEXT NOT NULL,
            message_id INTEGER,
            guild_id INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            submitted_at INTEGER NOT NULL,
            reviewed_by INTEGER,
            reviewed_at INTEGER
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_usage (
            user_id INTEGER PRIMARY KEY,
            guild_id INTEGER NOT NULL,
            used_at INTEGER NOT NULL,
            unlisted_by INTEGER,
            unlisted_at INTEGER
        )
        ''')
        

        
        conn.commit()
        conn.close()

    async def _rate_limit_delay(self):
        """Anti-Rate-Limit: Delay zwischen API requests"""
        current_time = datetime.datetime.now().timestamp()
        time_diff = current_time - self._last_request_time
        
        if time_diff < self._request_delay:
            await asyncio.sleep(self._request_delay - time_diff)
        
        self._last_request_time = datetime.datetime.now().timestamp()

    async def get_channel_cached(self, channel_id: int):
        """Anti-Rate-Limit: Channel aus Cache oder sofort holen"""
        if channel_id in self._channel_cache:
            return self._channel_cache[channel_id]
        
        channel = self.bot.get_channel(channel_id)
        if channel:
            self._channel_cache[channel_id] = channel
        return channel

    async def get_user_cached(self, user_id: int):
        """Anti-Rate-Limit: User aus Cache oder API holen"""
        if user_id in self._user_cache:
            return self._user_cache[user_id]
        
        user = self.bot.get_user(user_id)
        if not user:
            try:
                user = await self.bot.fetch_user(user_id)
            except:
                pass
        
        if user:
            self._user_cache[user_id] = user
        return user

    def is_admin(self, user: discord.Member) -> bool:
        """Check if user has admin permissions"""
        return any(role.id == self.admin_role_id for role in user.roles) or user.guild_permissions.administrator

    def can_use_review(self, user: discord.Member) -> bool:
        """Check if user can use /review command"""
        return any(role.id == self.user_role_id for role in user.roles) or self.is_admin(user)

    def has_used_review(self, user_id: int, guild_id: int) -> bool:
        """Check if user has already used /review (one-time-use system)"""
        if self.is_admin_by_id(user_id):
            return False
            
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM user_usage WHERE user_id = ? AND guild_id = ?", (user_id, guild_id))
        result = cursor.fetchone()
        conn.close()
        return result is not None

    def is_admin_by_id(self, user_id: int) -> bool:
        """Check if user ID belongs to an admin (helper method)"""
        return False

    def mark_user_as_used(self, user_id: int, guild_id: int):
        """Mark user as having used /review"""
        now = int(datetime.datetime.utcnow().timestamp())
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO user_usage (user_id, guild_id, used_at)
            VALUES (?, ?, ?)
        ''', (user_id, guild_id, now))
        conn.commit()
        conn.close()

    def unlist_user(self, user_id: int, guild_id: int, admin_id: int):
        """Allow user to use /review again (admin only)"""
        now = int(datetime.datetime.utcnow().timestamp())
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE user_usage 
            SET unlisted_by = ?, unlisted_at = ?
            WHERE user_id = ? AND guild_id = ?
        ''', (admin_id, now, user_id, guild_id))
        
        if cursor.rowcount == 0:
            cursor.execute('''
                INSERT INTO user_usage (user_id, guild_id, used_at, unlisted_by, unlisted_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, guild_id, 0, admin_id, now))
        
        conn.commit()
        conn.close()

    def is_user_unlisted(self, user_id: int, guild_id: int) -> bool:
        """Check if user has been unlisted by an admin"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT unlisted_at, used_at FROM user_usage 
            WHERE user_id = ? AND guild_id = ? AND unlisted_by IS NOT NULL
        ''', (user_id, guild_id))
        result = cursor.fetchone()
        conn.close()
        
        if not result:
            return False
        
        unlisted_at, used_at = result
        return unlisted_at > used_at

    async def record_submission(self, user_id: int, username: str, file_url: str, 
                               filename: str, guild_id: int, message_id: int = None) -> int:
        """Record a new submission in the database"""
        now = int(datetime.datetime.utcnow().timestamp())
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO submissions (user_id, username, file_url, filename, message_id, guild_id, submitted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, username, file_url, filename, message_id, guild_id, now))
        
        submission_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return submission_id

    async def update_submission_status(self, message_id: int, status: str, reviewer_id: int):
        """Update submission status"""
        now = int(datetime.datetime.utcnow().timestamp())
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE submissions 
            SET status = ?, reviewed_by = ?, reviewed_at = ?
            WHERE message_id = ?
        ''', (status, reviewer_id, now, message_id))
        conn.commit()
        conn.close()

    def get_submission_by_message(self, message_id: int) -> Optional[Dict[str, Any]]:
        """Get submission by message ID"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM submissions WHERE message_id = ?", (message_id,))
        result = cursor.fetchone()
        
        conn.close()
        return dict(result) if result else None

    def get_review_stats(self, guild_id: int) -> Dict[str, int]:
        """Get review statistics"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        stats = {}
        
        cursor.execute("SELECT COUNT(*) FROM submissions WHERE guild_id = ? AND status = 'pending'", (guild_id,))
        stats['pending'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM submissions WHERE guild_id = ? AND status = 'approved'", (guild_id,))
        stats['approved'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM submissions WHERE guild_id = ? AND status = 'declined'", (guild_id,))
        stats['declined'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM submissions WHERE guild_id = ?", (guild_id,))
        stats['total'] = cursor.fetchone()[0]
        
        conn.close()
        return stats

    @app_commands.command(name="review", description="Sende eine Datei zur Überprüfung")
    @app_commands.describe(file="Die Datei, die überprüft werden soll")
    async def review_command(self, interaction: discord.Interaction, file: discord.Attachment):
        """Submit a file for review"""

        if interaction.channel.id != self.upload_channel_id:
            return await interaction.response.send_message(
                f"❌ Dieser Command kann nur in <#{self.upload_channel_id}> verwendet werden!",
                ephemeral=True
            )
        
        if not self.can_use_review(interaction.user):
            return await interaction.response.send_message(
                "❌ Du hast keine Berechtigung, diesen Command zu verwenden!",
                ephemeral=True
            )
        
        if not self.is_admin(interaction.user):
            if self.has_used_review(interaction.user.id, interaction.guild.id) and not self.is_user_unlisted(interaction.user.id, interaction.guild.id):
                return await interaction.response.send_message(
                    "❌ Du hast bereits einmal `/review` verwendet! Nur Admins können dich wieder freischalten.",
                    ephemeral=True
                )
        
        if not file.content_type or not file.content_type.startswith('image/'):
            return await interaction.response.send_message(
                "❌ Bitte nur Bilddateien hochladen!", 
                ephemeral=True
            )
        
        if file.size > 8 * 1024 * 1024:
            return await interaction.response.send_message(
                "❌ Datei ist zu groß! Maximum: 8MB", 
                ephemeral=True
            )
        
        await interaction.response.send_message(
            "✅ Deine Datei wird zur Überprüfung eingereicht...", 
            ephemeral=True
        )
        
        asyncio.create_task(self._process_review_submission(
            interaction.user, file, interaction.guild.id, interaction.channel
        ))

    async def _process_review_submission(self, user, file, guild_id, channel):
        """Background task to process review submission"""
        try:
            review_channel = await self.get_channel_cached(self.review_channel_id)
            if not review_channel:
                return
            
            embed = discord.Embed(
                title="📋 Neue Einreichung zur Überprüfung",
                color=discord.Color.orange(),
                timestamp=datetime.datetime.utcnow()
            )
            embed.add_field(name="👤 Von", value=f"{user.mention} ({user.name})", inline=True)
            embed.add_field(name="📁 Dateiname", value=file.filename, inline=True)
            embed.add_field(name="📏 Dateigröße", value=f"{file.size/1024:.1f} KB", inline=True)
            embed.set_image(url=file.url)
            embed.set_footer(text="Klicke auf ✅ zum Genehmigen oder ❌ zum Ablehnen")
            
            review_message = await review_channel.send(embed=embed)
            
            await review_message.add_reaction("✅")
            await review_message.add_reaction("❌")
            
            submission_id = await self.record_submission(
                user.id,
                str(user),
                file.url,
                file.filename,
                guild_id,
                review_message.id
            )
            
            if not any(role.id == self.admin_role_id for role in user.roles):
                self.mark_user_as_used(user.id, guild_id)
            
        except Exception as e:
            print(f"Error processing review submission: {e}")
            pass



    @app_commands.command(name="review_stats", description="Review-Statistiken anzeigen (Nur für Admins)")
    async def review_stats(self, interaction: discord.Interaction):
        """Show review statistics"""
        
        if not self.is_admin(interaction.user):
            return await interaction.response.send_message(
                "❌ Du hast keine Berechtigung für diesen Befehl!", 
                ephemeral=True
            )
        
        stats = self.get_review_stats(interaction.guild.id)
        
        embed = discord.Embed(
            title="📊 Review-Statistiken",
            color=discord.Color.blue()
        )
        embed.add_field(name="⏳ Wartend", value=str(stats['pending']), inline=True)
        embed.add_field(name="✅ Genehmigt", value=str(stats['approved']), inline=True)
        embed.add_field(name="❌ Abgelehnt", value=str(stats['declined']), inline=True)
        embed.add_field(name="📊 Gesamt", value=str(stats['total']), inline=True)
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="unlistreview", description="User wieder für /review freischalten (Nur für Admins)")
    @app_commands.describe(user="Der User der wieder /review verwenden darf")
    async def unlist_review(self, interaction: discord.Interaction, user: discord.Member):
        """Allow a user to use /review again"""
        
        if not self.is_admin(interaction.user):
            return await interaction.response.send_message(
                "❌ Du hast keine Berechtigung für diesen Befehl!", 
                ephemeral=True
            )
        
        self.unlist_user(user.id, interaction.guild.id, interaction.user.id)
        
        embed = discord.Embed(
            title="✅ User freigeschaltet!",
            color=discord.Color.green()
        )
        embed.add_field(name="👤 User", value=user.mention, inline=True)
        embed.add_field(name="👨‍💼 Freigeschaltet von", value=interaction.user.mention, inline=True)
        embed.add_field(name="📝 Info", value="Kann jetzt wieder `/review` verwenden", inline=False)
        
        await interaction.response.send_message(embed=embed)

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        """Handle review decisions via reactions"""
        
        if user.bot:
            return
        
        if not self.review_channel_id or reaction.message.channel.id != self.review_channel_id:
            return
        
        if not isinstance(user, discord.Member) or not self.is_admin(user):
            return
        
        submission = self.get_submission_by_message(reaction.message.id)
        if not submission or submission['status'] != 'pending':
            return
        
        if str(reaction.emoji) == "✅":
            await self.handle_approval(reaction.message, submission, user)
        elif str(reaction.emoji) == "❌":
            await self.handle_decline(reaction.message, submission, user)

    async def handle_approval(self, message: discord.Message, submission: Dict[str, Any], reviewer: discord.Member):
        """Handle approval of a submission"""
        
        await self.update_submission_status(message.id, 'approved', reviewer.id)
        
        if self.approved_channel_id:
            approved_channel = await self.get_channel_cached(self.approved_channel_id)
            if approved_channel:
                approved_embed = discord.Embed(
                    title="✅ Genehmigtes Bild",
                    color=discord.Color.green(),
                    timestamp=datetime.datetime.utcnow()
                )
                approved_embed.add_field(name="👤 Eingereicht von", value=submission['username'], inline=True)
                approved_embed.add_field(name="✅ Genehmigt von", value=reviewer.mention, inline=True)
                approved_embed.set_image(url=submission['file_url'])
                approved_embed.set_footer(text=f"Ursprünglich eingereicht: {datetime.datetime.fromtimestamp(submission['submitted_at']).strftime('%Y-%m-%d %H:%M')}")
                
                await approved_channel.send(embed=approved_embed)
        
        updated_embed = message.embeds[0]
        updated_embed.color = discord.Color.green()
        updated_embed.title = "✅ GENEHMIGT"
        updated_embed.add_field(name="✅ Genehmigt von", value=reviewer.mention, inline=True)
        await message.edit(embed=updated_embed)
        
        asyncio.create_task(self._send_approval_dm(submission['user_id'], submission['filename']))

    async def handle_decline(self, message: discord.Message, submission: Dict[str, Any], reviewer: discord.Member):
        """Handle decline of a submission"""
        
        await self.update_submission_status(message.id, 'declined', reviewer.id)
        
        updated_embed = message.embeds[0]
        updated_embed.color = discord.Color.red()
        updated_embed.title = "❌ ABGELEHNT"
        updated_embed.add_field(name="❌ Abgelehnt von", value=reviewer.mention, inline=True)
        await message.edit(embed=updated_embed)
        
        asyncio.create_task(self._send_decline_dm(submission['user_id'], submission['filename']))

    async def _send_approval_dm(self, user_id: int, filename: str):
        """Background task to send approval DM"""
        try:
            user = await self.get_user_cached(user_id)
            if user:
                await user.send(f"✅ Deine Einreichung '{filename}' wurde genehmigt und veröffentlicht!")
        except:
            pass

    async def _send_decline_dm(self, user_id: int, filename: str):
        """Background task to send decline DM"""
        try:
            user = await self.get_user_cached(user_id)
            if user:
                await user.send(f"❌ Deine Einreichung '{filename}' wurde abgelehnt.")
        except:
            pass

    @commands.Cog.listener()
    async def on_message(self, message):
        """Auto-delete unerlaubte Nachrichten im Upload-Channel"""
        
        if message.author.bot:
            return
        
        if message.channel.id != self.upload_channel_id:
            return
        
        if isinstance(message.author, discord.Member) and self.is_admin(message.author):
            return
        
        if isinstance(message.author, discord.Member) and self.can_use_review(message.author):
            if not message.content.startswith('/'):
                try:
                    await message.delete()
                except:
                    pass
            return
        
        try:
            await message.delete()
        except:
            pass

async def setup(bot):
    await bot.add_cog(ReviewSystem(bot))