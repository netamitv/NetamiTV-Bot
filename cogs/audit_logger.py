import discord
from discord.ext import commands
import sqlite3
import asyncio
from datetime import datetime

class AuditLogger(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.init_database()

    def init_database(self):
        """Initialize the audit log database"""
        try:
            conn = sqlite3.connect('audit_logs.db')
            cursor = conn.cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    user_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    discriminator TEXT,
                    action_type TEXT NOT NULL,
                    reason TEXT,
                    message_content TEXT,
                    channel_id TEXT,
                    channel_name TEXT,
                    guild_id TEXT,
                    details TEXT,
                    severity TEXT DEFAULT 'medium'
                )
            ''')
            
            conn.commit()
            conn.close()
            print("✅ Audit log database initialized successfully")
        except Exception as e:
            print(f"❌ Error initializing audit log database: {e}")

    def log_audit_event(self, user_id, username, discriminator, action_type, reason,
                       message_content=None, channel_id=None, channel_name=None,
                       guild_id=None, details=None, severity='medium'):
        """Log an audit event to the database"""
        try:
            conn = sqlite3.connect('audit_logs.db')
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO audit_logs 
                (user_id, username, discriminator, action_type, reason, message_content, 
                 channel_id, channel_name, guild_id, details, severity)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (str(user_id), username, discriminator, action_type, reason, message_content,
                  str(channel_id) if channel_id else None, channel_name, str(guild_id) if guild_id else None, details, severity))
            
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"❌ Error logging audit event: {e}")

    # Member Events
    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Log when a member joins the server"""
        self.log_audit_event(
            user_id=member.id,
            username=member.name,
            discriminator=member.discriminator,
            action_type='member_joined',
            reason='Mitglied ist dem Server beigetreten',
            guild_id=member.guild.id,
            details=f'Account erstellt: {member.created_at.strftime("%Y-%m-%d %H:%M:%S")}',
            severity='low'
        )

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        """Log when a member leaves the server"""
        self.log_audit_event(
            user_id=member.id,
            username=member.name,
            discriminator=member.discriminator,
            action_type='member_left',
            reason='Mitglied hat den Server verlassen',
            guild_id=member.guild.id,
            details=f'Beigetreten am: {member.joined_at.strftime("%Y-%m-%d %H:%M:%S") if member.joined_at else "Unbekannt"}',
            severity='low'
        )

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        """Log when a member is banned"""
        reason = "Kein Grund angegeben"
        try:
            async for entry in guild.audit_logs(action=discord.AuditLogAction.ban, limit=1):
                if entry.target.id == user.id:
                    reason = entry.reason or "Kein Grund angegeben"
                    break
        except:
            pass

        self.log_audit_event(
            user_id=user.id,
            username=user.name,
            discriminator=user.discriminator,
            action_type='user_banned',
            reason=reason,
            guild_id=guild.id,
            severity='high'
        )

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        """Log when a member is unbanned"""
        reason = "Kein Grund angegeben"
        try:
            async for entry in guild.audit_logs(action=discord.AuditLogAction.unban, limit=1):
                if entry.target.id == user.id:
                    reason = entry.reason or "Kein Grund angegeben"
                    break
        except:
            pass

        self.log_audit_event(
            user_id=user.id,
            username=user.name,
            discriminator=user.discriminator,
            action_type='user_unbanned',
            reason=reason,
            guild_id=guild.id,
            severity='medium'
        )

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        """Log when a message is deleted"""
        if message.author.bot:
            return
            
        self.log_audit_event(
            user_id=message.author.id,
            username=message.author.name,
            discriminator=message.author.discriminator,
            action_type='message_deleted',
            reason='Nachricht wurde gelöscht',
            message_content=message.content[:500] if message.content else "Keine Textinhalte",
            channel_id=message.channel.id,
            channel_name=message.channel.name,
            guild_id=message.guild.id if message.guild else None,
            severity='low'
        )

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages):
        """Log when messages are bulk deleted"""
        if not messages:
            return
            
        channel = messages[0].channel
        guild = messages[0].guild
        
        self.log_audit_event(
            user_id=0,
            username='System',
            discriminator='0000',
            action_type='bulk_message_delete',
            reason=f'{len(messages)} Nachrichten wurden massengelöscht',
            channel_id=channel.id,
            channel_name=channel.name,
            guild_id=guild.id if guild else None,
            details=f'Anzahl gelöschter Nachrichten: {len(messages)}',
            severity='medium'
        )

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        """Log role changes"""
        if before.roles != after.roles:
            added_roles = set(after.roles) - set(before.roles)
            removed_roles = set(before.roles) - set(after.roles)
            
            for role in added_roles:
                self.log_audit_event(
                    user_id=after.id,
                    username=after.name,
                    discriminator=after.discriminator,
                    action_type='role_added',
                    reason=f'Rolle "{role.name}" hinzugefügt',
                    guild_id=after.guild.id,
                    details=f'Rolle: {role.name} (ID: {role.id})',
                    severity='low'
                )
            
            for role in removed_roles:
                self.log_audit_event(
                    user_id=after.id,
                    username=after.name,
                    discriminator=after.discriminator,
                    action_type='role_removed',
                    reason=f'Rolle "{role.name}" entfernt',
                    guild_id=after.guild.id,
                    details=f'Rolle: {role.name} (ID: {role.id})',
                    severity='low'
                )

    # Channel Events
    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        """Log when a channel is created"""
        self.log_audit_event(
            user_id=0,
            username='System',
            discriminator='0000',
            action_type='channel_created',
            reason=f'Channel "{channel.name}" wurde erstellt',
            channel_id=channel.id,
            channel_name=channel.name,
            guild_id=channel.guild.id,
            details=f'Channel-Typ: {channel.type}',
            severity='low'
        )

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        """Log when a channel is deleted"""
        self.log_audit_event(
            user_id=0,
            username='System',
            discriminator='0000',
            action_type='channel_deleted',
            reason=f'Channel "{channel.name}" wurde gelöscht',
            channel_id=channel.id,
            channel_name=channel.name,
            guild_id=channel.guild.id,
            details=f'Channel-Typ: {channel.type}',
            severity='medium'
        )

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        """Log when a channel is updated"""
        changes = []
        
        if before.name != after.name:
            changes.append(f'Name: "{before.name}" → "{after.name}"')
        
        if hasattr(before, 'topic') and hasattr(after, 'topic') and before.topic != after.topic:
            changes.append(f'Topic geändert')
        
        if changes:
            self.log_audit_event(
                user_id=0,
                username='System',
                discriminator='0000',
                action_type='channel_updated',
                reason=f'Channel "{after.name}" wurde aktualisiert',
                channel_id=after.id,
                channel_name=after.name,
                guild_id=after.guild.id,
                details='; '.join(changes),
                severity='low'
            )

    # Voice Events
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Log voice channel events"""
        if before.channel != after.channel:
            if before.channel is None and after.channel is not None:
                self.log_audit_event(
                    user_id=member.id,
                    username=member.name,
                    discriminator=member.discriminator,
                    action_type='voice_channel_joined',
                    reason=f'Voice Channel "{after.channel.name}" beigetreten',
                    channel_id=after.channel.id,
                    channel_name=after.channel.name,
                    guild_id=member.guild.id,
                    severity='low'
                )
            elif before.channel is not None and after.channel is None:
                self.log_audit_event(
                    user_id=member.id,
                    username=member.name,
                    discriminator=member.discriminator,
                    action_type='voice_channel_left',
                    reason=f'Voice Channel "{before.channel.name}" verlassen',
                    channel_id=before.channel.id,
                    channel_name=before.channel.name,
                    guild_id=member.guild.id,
                    severity='low'
                )

    # Server Events
    @commands.Cog.listener()
    async def on_guild_update(self, before, after):
        """Log server updates"""
        changes = []
        
        if before.name != after.name:
            changes.append(f'Name: "{before.name}" → "{after.name}"')
        
        if before.icon != after.icon:
            changes.append('Server-Icon geändert')
        
        if before.banner != after.banner:
            changes.append('Server-Banner geändert')
        
        if changes:
            self.log_audit_event(
                user_id=0,
                username='System',
                discriminator='0000',
                action_type='server_updated',
                reason='Server-Einstellungen wurden aktualisiert',
                guild_id=after.id,
                details='; '.join(changes),
                severity='low'
            )

    def log_ticket_created(self, user, channel, reason="Ticket erstellt"):
        """Log ticket creation"""
        self.log_audit_event(
            user_id=user.id,
            username=user.name,
            discriminator=user.discriminator,
            action_type='ticket_created',
            reason=reason,
            channel_id=channel.id,
            channel_name=channel.name,
            guild_id=channel.guild.id,
            severity='low'
        )

    def log_ticket_closed(self, user, channel, reason="Ticket geschlossen"):
        """Log ticket closure"""
        self.log_audit_event(
            user_id=user.id,
            username=user.name,
            discriminator=user.discriminator,
            action_type='ticket_closed',
            reason=reason,
            channel_id=channel.id,
            channel_name=channel.name,
            guild_id=channel.guild.id,
            severity='low'
        )

    def log_temp_channel_created(self, user, channel):
        """Log temporary channel creation"""
        self.log_audit_event(
            user_id=user.id,
            username=user.name,
            discriminator=user.discriminator,
            action_type='temp_channel_created',
            reason='Temporärer Channel erstellt',
            channel_id=channel.id,
            channel_name=channel.name,
            guild_id=channel.guild.id,
            severity='low'
        )

    def log_temp_channel_deleted(self, user_id, username, channel_name, guild_id):
        """Log temporary channel deletion"""
        self.log_audit_event(
            user_id=user_id,
            username=username,
            discriminator='0000',
            action_type='temp_channel_deleted',
            reason='Temporärer Channel gelöscht',
            channel_name=channel_name,
            guild_id=guild_id,
            severity='low'
        )

    def log_automod_action(self, user, action_type, reason, message_content=None, channel=None, severity='medium'):
        """Log automod actions"""
        self.log_audit_event(
            user_id=user.id,
            username=user.name,
            discriminator=user.discriminator,
            action_type=action_type,
            reason=reason,
            message_content=message_content,
            channel_id=channel.id if channel else None,
            channel_name=channel.name if channel else None,
            guild_id=channel.guild.id if channel and channel.guild else None,
            severity=severity
        )

    def log_user_timeout(self, user, moderator, reason, duration, guild_id):
        """Log user timeout"""
        self.log_audit_event(
            user_id=user.id,
            username=user.name,
            discriminator=user.discriminator,
            action_type='user_timeout',
            reason=reason,
            guild_id=guild_id,
            details=f'Timeout-Dauer: {duration}, Moderator: {moderator.name}',
            severity='medium'
        )

    def log_user_kick(self, user, moderator, reason, guild_id):
        """Log user kick"""
        self.log_audit_event(
            user_id=user.id,
            username=user.name,
            discriminator=user.discriminator,
            action_type='user_kicked',
            reason=reason,
            guild_id=guild_id,
            details=f'Moderator: {moderator.name}',
            severity='high'
        )

async def setup(bot):
    await bot.add_cog(AuditLogger(bot))