import discord
from discord import app_commands
from discord.ext import commands, tasks
import aiohttp
import asyncio
import json
import os
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class TwitchNotifications(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config_file = 'twitch_config.json'
        self.config = self.load_config()
        self.session = None
        self.access_token = None
        self.stream_status = {}
        self.notification_messages = {}
        self.temp_messages = {}
        
    def load_config(self):
        """Load configuration from JSON file"""
        default_config = {
            "client_id": "",
            "client_secret": "",
            "twitch_username": "",
            "discord_channel_id": 0,
            "ping_role_id": 0,  # Role to ping when going live
            "check_interval": 60,  # seconds
            "enabled": False,
            "persistent_message_id": 0,  # ID of the persistent notification message
            "persistent_thread_id": 0   # ID of the persistent thread
        }
        
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    for key, value in default_config.items():
                        if key not in config:
                            config[key] = value
                    return config
            except Exception as e:
                logger.error(f"Error loading config: {e}")
                return default_config
        else:
            self.save_config(default_config)
            return default_config
    
    def save_config(self, config=None):
        """Save configuration to JSON file"""
        if config is None:
            config = self.config
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving config: {e}")
    
    async def cog_load(self):
        """Initialize the cog"""
        self.session = aiohttp.ClientSession()
        if self.config.get('enabled', False):
            await self.get_access_token()
            self.check_stream_status.start()
    
    async def cog_unload(self):
        """Cleanup when cog is unloaded"""
        if self.session:
            await self.session.close()
        if self.check_stream_status.is_running():
            self.check_stream_status.cancel()
    
    async def get_access_token(self):
        """Get OAuth token from Twitch"""
        if not self.config.get('client_id') or not self.config.get('client_secret'):
            logger.error("Twitch Client ID or Client Secret not configured")
            return False
            
        url = 'https://id.twitch.tv/oauth2/token'
        params = {
            'client_id': self.config['client_id'],
            'client_secret': self.config['client_secret'],
            'grant_type': 'client_credentials'
        }
        
        try:
            async with self.session.post(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    self.access_token = data['access_token']
                    logger.info("Successfully obtained Twitch access token")
                    return True
                else:
                    logger.error(f"Failed to get access token: {response.status}")
                    return False
        except Exception as e:
            logger.error(f"Error getting access token: {e}")
            return False
    
    async def get_user_info(self, username):
        """Get user information from Twitch API"""
        if not self.access_token:
            return None
            
        url = 'https://api.twitch.tv/helix/users'
        headers = {
            'Client-ID': self.config['client_id'],
            'Authorization': f'Bearer {self.access_token}'
        }
        params = {'login': username}
        
        try:
            async with self.session.get(url, headers=headers, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data['data']:
                        return data['data'][0]
                elif response.status == 401:
                    await self.get_access_token()
                    return await self.get_user_info(username)
                else:
                    logger.error(f"Failed to get user info: {response.status}")
        except Exception as e:
            logger.error(f"Error getting user info: {e}")
        return None
    
    async def get_stream_info(self, user_id):
        """Get stream information from Twitch API"""
        if not self.access_token:
            return None
            
        url = 'https://api.twitch.tv/helix/streams'
        headers = {
            'Client-ID': self.config['client_id'],
            'Authorization': f'Bearer {self.access_token}'
        }
        params = {'user_id': user_id}
        
        try:
            async with self.session.get(url, headers=headers, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return data['data'][0] if data['data'] else None
                elif response.status == 401:
                    await self.get_access_token()
                    return await self.get_stream_info(user_id)
                else:
                    logger.error(f"Failed to get stream info: {response.status}")
        except Exception as e:
            logger.error(f"Error getting stream info: {e}")
        return None
    
    async def get_vod_info(self, user_id):
        """Get latest VOD information from Twitch API"""
        if not self.access_token:
            return None
            
        url = 'https://api.twitch.tv/helix/videos'
        headers = {
            'Client-ID': self.config['client_id'],
            'Authorization': f'Bearer {self.access_token}'
        }
        params = {
            'user_id': user_id,
            'type': 'archive',
            'first': 1
        }
        
        try:
            async with self.session.get(url, headers=headers, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return data['data'][0] if data['data'] else None
                elif response.status == 401:
                    await self.get_access_token()
                    return await self.get_vod_info(user_id)
                else:
                    logger.error(f"Failed to get VOD info: {response.status}")
        except Exception as e:
            logger.error(f"Error getting VOD info: {e}")
        return None
    
    def create_live_embed(self, user_info, stream_info):
        """Create embed for live notification - Notify Me bot style"""
        embed = discord.Embed(
            color=0x9146FF,
            timestamp=datetime.utcnow()
        )
        
        embed.add_field(
            name="🔴 LIVE",
            value=f"**[{user_info['display_name']}](https://www.twitch.tv/{user_info['login']})** ist jetzt live auf Twitch!",
            inline=False
        )
        
        embed.add_field(
            name="📺 Stream Titel",
            value=f"**{stream_info['title']}**",
            inline=False
        )
        
        embed.add_field(
            name="🎮 Spiel",
            value=stream_info['game_name'] or "Keine Kategorie",
            inline=True
        )
        
        embed.add_field(
            name="👥 Zuschauer",
            value=f"{stream_info['viewer_count']:,}",
            inline=True
        )
        
        started_at = datetime.fromisoformat(stream_info['started_at'].replace('Z', '+00:00'))
        embed.add_field(
            name="⏰ Gestartet",
            value=f"<t:{int(started_at.timestamp())}:R>",
            inline=True
        )
        
        embed.set_author(
            name=f"{user_info['display_name']} - Twitch",
            icon_url=user_info['profile_image_url'],
            url=f"https://www.twitch.tv/{user_info['login']}"
        )
        
        thumbnail_url = stream_info['thumbnail_url'].replace('{width}', '1920').replace('{height}', '1080')
        embed.set_image(url=thumbnail_url)
        
        embed.set_footer(
            text="Twitch Stream Benachrichtigung",
            icon_url="https://assets.help.twitch.tv/Glitch_Purple_RGB.png"
        )
        
        return embed
    
    def create_offline_embed(self, user_info, vod_url=None):
        """Create embed for offline notification with optional VOD link"""
        embed = discord.Embed(
            color=0x808080,
            timestamp=datetime.utcnow()
        )
        
        description = f"**[{user_info['display_name']}](https://www.twitch.tv/{user_info['login']})** ist jetzt offline."
        if vod_url:
            description += f"\n\n🎬 [Zum letzten VOD]({vod_url})"
        
        embed.add_field(
            name="⚫ OFFLINE",
            value=description,
            inline=False
        )
        
        embed.add_field(
            name="💜 Danke fürs Zuschauen!",
            value="Der Stream ist beendet. Schaut gerne beim nächsten Mal wieder vorbei!",
            inline=False
        )
        
        embed.set_author(
            name=f"{user_info['display_name']} - Twitch",
            icon_url=user_info['profile_image_url'],
            url=f"https://www.twitch.tv/{user_info['login']}"
        )
        
        banner_url = user_info.get('offline_image_url') or user_info['profile_image_url']
        embed.set_image(url=banner_url)
        
        embed.set_footer(
            text="Twitch Stream Benachrichtigung",
            icon_url="https://assets.help.twitch.tv/Glitch_Purple_RGB.png"
        )
        
        return embed
    
    def create_preview_embed(self, user_info):
        """Create preview embed to show how notifications will look"""
        embed = discord.Embed(
            color=0x9146FF,
            timestamp=datetime.utcnow()
        )
        
        embed.add_field(
            name="🔴 LIVE",
            value=f"**[{user_info['display_name']}](https://www.twitch.tv/{user_info['login']})** ist jetzt live auf Twitch!",
            inline=False
        )
        
        embed.add_field(
            name="📺 Stream Titel",
            value="**Beispiel Stream Titel - So werden die Benachrichtigungen aussehen!**",
            inline=False
        )
        
        embed.add_field(
            name="🎮 Spiel",
            value="Just Chatting",
            inline=True
        )
        
        embed.add_field(
            name="👥 Zuschauer",
            value="1,234",
            inline=True
        )
        
        embed.add_field(
            name="⏰ Gestartet",
            value="vor wenigen Sekunden",
            inline=True
        )
        
        embed.set_author(
            name=f"{user_info['display_name']} - Twitch",
            icon_url=user_info['profile_image_url'],
            url=f"https://www.twitch.tv/{user_info['login']}"
        )
        
        embed.set_image(url="https://static-cdn.jtvnw.net/previews-ttv/live_user_placeholder-1920x1080.jpg")
        
        embed.set_footer(
            text="🎯 VORSCHAU - So werden deine Twitch Benachrichtigungen aussehen!",
            icon_url="https://assets.help.twitch.tv/Glitch_Purple_RGB.png"
        )
        
        return embed
    
    def create_watch_button(self, username):
        """Create view with watch button"""
        view = discord.ui.View(timeout=None)
        button = discord.ui.Button(
            label="Jetzt anschauen",
            style=discord.ButtonStyle.link,
            url=f"https://www.twitch.tv/{username}",
            emoji="📺"
        )
        view.add_item(button)
        return view
    
    async def get_or_create_persistent_message(self, channel, user_info):
        """Get existing persistent message or create new one"""
        persistent_msg_id = self.config.get('persistent_message_id', 0)
        persistent_thread_id = self.config.get('persistent_thread_id', 0)
        
        message = None
        thread = None
        
        if persistent_msg_id:
            try:
                message = await channel.fetch_message(persistent_msg_id)
                
                if hasattr(message, 'thread') and message.thread:
                    thread = message.thread
                    if thread.id != persistent_thread_id:
                        self.config['persistent_thread_id'] = thread.id
                        self.save_config()
                        logger.info(f"Updated thread ID in config: {thread.id}")
                elif persistent_thread_id:
                    try:
                        thread = await self.bot.fetch_channel(persistent_thread_id)
                        if not hasattr(thread, 'parent_id') or thread.parent_id != message.id:
                            logger.warning(f"Thread {persistent_thread_id} doesn't belong to message {message.id}")
                            thread = None
                    except discord.NotFound:
                        logger.warning(f"Thread {persistent_thread_id} not found")
                        thread = None
                        
            except discord.NotFound:
                logger.warning(f"Message {persistent_msg_id} not found, creating new setup")
                message = None
                thread = None
                self.config['persistent_message_id'] = 0
                self.config['persistent_thread_id'] = 0
                self.save_config()
        
        if not message:
            embed = self.create_offline_embed(user_info)
            view = self.create_watch_button(user_info['login'])
            
            message = await channel.send(embed=embed, view=view)
            
            self.config['persistent_message_id'] = message.id
            self.save_config()
            
            logger.info(f"Created persistent message for {user_info['display_name']}")
            
            try:
                thread = await message.create_thread(
                    name=f"🎬 {user_info['display_name']} VODs",
                    auto_archive_duration=10080
                )
                
                self.config['persistent_thread_id'] = thread.id
                self.save_config()
                
                await asyncio.sleep(1)
                
                await thread.send("🎬 Hier werden automatisch VOD-Links gepostet!")
                await asyncio.sleep(0.5)
                await thread.send("📋 Alle VODs werden hier archiviert.")
                
                logger.info(f"Created and activated thread: {thread.name} (ID: {thread.id})")
                
            except Exception as e:
                logger.error(f"Error creating thread for new message: {e}")
                thread = None
        
        elif not thread:
            try:
                thread = await message.create_thread(
                    name=f"🎬 {user_info['display_name']} VODs",
                    auto_archive_duration=10080
                )
                
                self.config['persistent_thread_id'] = thread.id
                self.save_config()
                
                await asyncio.sleep(1)
                
                await thread.send("🎬 Hier werden automatisch VOD-Links gepostet!")
                await asyncio.sleep(0.5)
                await thread.send("📋 Alle VODs werden hier archiviert.")
                
                logger.info(f"Created thread for existing message: {thread.name} (ID: {thread.id})")
                
            except Exception as e:
                logger.error(f"Error creating thread for existing message: {e}")
                try:
                    async for existing_thread in channel.archived_threads(limit=50):
                        if existing_thread.parent_id == message.id:
                            thread = existing_thread
                            self.config['persistent_thread_id'] = thread.id
                            self.save_config()
                            logger.info(f"Found existing archived thread: {thread.name}")
                            break
                except Exception as search_error:
                    logger.error(f"Error searching for existing threads: {search_error}")
        
        return message, thread
    
        
    @tasks.loop(seconds=60)
    async def check_stream_status(self):
        """Check stream status periodically"""
        if not self.config.get('enabled', False):
            return
            
        username = self.config.get('twitch_username')
        channel_id = self.config.get('discord_channel_id')
        
        if not username or not channel_id:
            return
        
        try:
            user_info = await self.get_user_info(username)
            if not user_info:
                return
            
            user_id = user_info['id']
            
            stream_info = await self.get_stream_info(user_id)
            is_live = stream_info is not None
            
            was_live = self.stream_status.get(user_id, False)
            
            channel = self.bot.get_channel(channel_id)
            if not channel:
                logger.error(f"Discord channel {channel_id} not found")
                return
            
            message, thread = await self.get_or_create_persistent_message(channel, user_info)
            
                        
            if is_live and not was_live:
                embed = self.create_live_embed(user_info, stream_info)
                view = self.create_watch_button(username)
                
                content = None
                ping_role_id = self.config.get('ping_role_id', 0)
                if ping_role_id:
                    guild = channel.guild
                    role = guild.get_role(ping_role_id)
                    if role:
                        content = f"{role.mention}"
                        logger.info(f"Pinging role {role.name} for live notification")
                
                await message.edit(content=content, embed=embed, view=view)
                
                # Clear any previous VOD info
                try:
                    last_vod = await self.get_vod_info(user_id)
                    if last_vod:
                        self.last_vod_id = last_vod['id']
                except:
                    self.last_vod_id = None
                    
                self.stream_status[user_id] = True
                logger.info(f"Updated persistent message - {username} went live")
                
            elif not is_live and was_live:
                # Wait briefly for VOD to be available
                await asyncio.sleep(10)
                vod_info = await self.get_vod_info(user_id)
                vod_url = vod_info['url'] if vod_info else None
                
                embed = self.create_offline_embed(user_info, vod_url)
                view = self.create_watch_button(username)
                
                await message.edit(content=None, embed=embed, view=view)
                
                if thread:
                    await self.post_vod_link(user_id, thread.id)
                
                self.stream_status[user_id] = False
                logger.info(f"Updated persistent message - {username} went offline")
                
        except Exception as e:
            logger.error(f"Error checking stream status: {e}")
    
    async def post_vod_link(self, user_id, thread_id):
        """Post VOD link in the thread when available"""
        try:
            for attempt in range(10):  # Try for 5 minutes (10 attempts * 30 seconds)
                await asyncio.sleep(30)
                
                vod_info = await self.get_vod_info(user_id)
                if vod_info and vod_info.get('url'):
                    created_at = datetime.fromisoformat(vod_info['created_at'].replace('Z', '+00:00'))
                    if datetime.utcnow().replace(tzinfo=created_at.tzinfo) - created_at < timedelta(hours=2):
                        # Get thread and parent message
                        thread = await self.bot.fetch_channel(thread_id)
                        parent_channel = await self.bot.fetch_channel(thread.parent_id)
                        if thread and parent_channel:
                            # Create VOD embed for thread
                            thumbnail_url = vod_info['thumbnail_url'].replace('{width}', '1920').replace('{height}', '1080')
                            vod_embed = discord.Embed(
                                title="🎬 VOD verfügbar!",
                                description=f"**{vod_info['title']}**\n\n[Direkt zum VOD]({vod_info['url']})",
                                color=0x9146FF,
                                url=vod_info['url']
                            )
                            vod_embed.add_field(name="Dauer", value=vod_info['duration'], inline=True)
                            vod_embed.add_field(name="Aufrufe", value=f"{vod_info['view_count']:,}", inline=True)
                            vod_embed.add_field(name="Erstellt", value=f"<t:{int(created_at.timestamp())}:R>", inline=True)
                            vod_embed.set_image(url=thumbnail_url)

                            # Create and send VOD message in thread
                            view = discord.ui.View()
                            view.add_item(discord.ui.Button(
                                label="VOD anschauen",
                                style=discord.ButtonStyle.link,
                                url=vod_info['url'],
                                emoji="🎬"
                            ))
                            await thread.send(embed=vod_embed, view=view)

                            # Update offline message with VOD link
                            try:
                                persistent_msg = await parent_channel.fetch_message(self.config['persistent_message_id'])
                                if persistent_msg:
                                    user_info = await self.get_user_info(self.config['twitch_username'])
                                    if user_info:
                                        offline_embed = self.create_offline_embed(user_info, vod_info['url'])
                                        view = self.create_watch_button(user_info['login'])
                                        await persistent_msg.edit(embed=offline_embed, view=view)
                            except Exception as e:
                                logger.error(f"Error updating offline message with VOD: {e}")

                            logger.info(f"Successfully posted VOD link in thread and updated offline message")
                            return True

                logger.debug(f"VOD not found yet, attempt {attempt + 1}/10")
                
            logger.warning("No VOD found after maximum attempts")
            return False

        except Exception as e:
            logger.error(f"Error posting VOD link: {e}")
            return False

    @check_stream_status.before_loop
    async def before_check_stream_status(self):
        """Wait for bot to be ready before starting the loop"""
        await self.bot.wait_until_ready()
        if self.config.get('check_interval', 60) != 60:
            self.check_stream_status.change_interval(seconds=self.config['check_interval'])
    
    # Slash Commands
    @app_commands.command(name="twitch_setup", description="Konfiguriere Twitch-Benachrichtigungen")
    @app_commands.describe(
        client_id="Twitch Client ID",
        client_secret="Twitch Client Secret",
        username="Twitch Username zum Überwachen",
        channel="Discord Channel für Benachrichtigungen",
        ping_role="Role die gepingt werden soll (optional)"
    )
    async def twitch_setup(
        self, 
        interaction: discord.Interaction,
        client_id: str,
        client_secret: str,
        username: str,
        channel: discord.TextChannel,
        ping_role: discord.Role = None
    ):
        """Setup Twitch notifications"""
        if not self.bot.is_authorized(interaction.user.id):
            await interaction.response.send_message("❌ Du bist nicht berechtigt, diesen Befehl zu verwenden.", ephemeral=True)
            return
        
        # Update config
        self.config['client_id'] = client_id
        self.config['client_secret'] = client_secret
        self.config['twitch_username'] = username.lower()
        self.config['discord_channel_id'] = channel.id
        self.config['ping_role_id'] = ping_role.id if ping_role else 0
        self.config['enabled'] = True
        
        self.save_config()
        
        await interaction.response.defer(ephemeral=True)
        
        if await self.get_access_token():
            user_info = await self.get_user_info(username)
            if user_info:
                message, thread = await self.get_or_create_persistent_message(channel, user_info)
                
                if not self.check_stream_status.is_running():
                    self.check_stream_status.start()
                
                description = f"Überwache jetzt **{user_info['display_name']}** in {channel.mention}"
                if ping_role:
                    description += f"\n🔔 Ping Role: {ping_role.mention}"
                description += f"\n\n📌 Persistente Nachricht wurde erstellt und wird automatisch aktualisiert!"
                
                embed = discord.Embed(
                    title="✅ Twitch-Benachrichtigungen konfiguriert!",
                    description=description,
                    color=0x00FF00
                )
                embed.set_thumbnail(url=user_info['profile_image_url'])
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.followup.send("❌ Twitch-Benutzer nicht gefunden. Überprüfe den Benutzernamen.", ephemeral=True)
        else:
            await interaction.followup.send("❌ Fehler bei der Twitch-API-Authentifizierung. Überprüfe Client ID und Secret.", ephemeral=True)
    
    @app_commands.command(name="twitch_status", description="Zeige aktuellen Status der Twitch-Überwachung")
    async def twitch_status(self, interaction: discord.Interaction):
        """Show current Twitch monitoring status"""
        if not self.bot.is_authorized(interaction.user.id):
            await interaction.response.send_message("❌ Du bist nicht berechtigt, diesen Befehl zu verwenden.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="📊 Twitch-Benachrichtigungen Status",
            color=0x9146FF
        )
        
        ping_role_id = self.config.get('ping_role_id', 0)
        ping_role_text = f"<@&{ping_role_id}>" if ping_role_id else "Keine"
        
        embed.add_field(
            name="🔧 Konfiguration",
            value=f"**Aktiviert:** {'✅' if self.config.get('enabled') else '❌'}\n"
                  f"**Username:** {self.config.get('twitch_username', 'Nicht gesetzt')}\n"
                  f"**Channel:** <#{self.config.get('discord_channel_id', 0)}>\n"
                  f"**Ping Role:** {ping_role_text}\n"
                  f"**Intervall:** {self.config.get('check_interval', 60)}s",
            inline=False
        )
        
        embed.add_field(
            name="🔄 Service Status",
            value=f"**Loop läuft:** {'✅' if self.check_stream_status.is_running() else '❌'}\n"
                  f"**Token:** {'✅' if self.access_token else '❌'}\n"
                  f"**Session:** {'✅' if self.session and not self.session.closed else '❌'}",
            inline=False
        )
        
        if self.stream_status:
            status_text = ""
            for user_id, is_live in self.stream_status.items():
                status_text += f"User {user_id}: {'🔴 LIVE' if is_live else '⚫ OFFLINE'}\n"
            embed.add_field(name="📺 Stream Status", value=status_text or "Keine Daten", inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="twitch_toggle", description="Aktiviere/Deaktiviere Twitch-Benachrichtigungen")
    async def twitch_toggle(self, interaction: discord.Interaction):
        """Toggle Twitch notifications on/off"""
        if not self.bot.is_authorized(interaction.user.id):
            await interaction.response.send_message("❌ Du bist nicht berechtigt, diesen Befehl zu verwenden.", ephemeral=True)
            return
        
        self.config['enabled'] = not self.config.get('enabled', False)
        self.save_config()
        
        if self.config['enabled']:
            if not self.check_stream_status.is_running():
                await self.get_access_token()
                self.check_stream_status.start()
            status = "✅ aktiviert"
            color = 0x00FF00
        else:
            if self.check_stream_status.is_running():
                self.check_stream_status.cancel()
            status = "❌ deaktiviert"
            color = 0xFF0000
        
        embed = discord.Embed(
            title="🔄 Twitch-Benachrichtigungen",
            description=f"Benachrichtigungen wurden {status}",
            color=color
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
        
    @app_commands.command(name="twitch_test", description="Teste die Twitch-API-Verbindung")
    async def twitch_test(self, interaction: discord.Interaction):
        """Test Twitch API connection"""
        if not self.bot.is_authorized(interaction.user.id):
            await interaction.response.send_message("❌ Du bist nicht berechtigt, diesen Befehl zu verwenden.", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        
        username = self.config.get('twitch_username')
        if not username:
            await interaction.followup.send("❌ Kein Twitch-Username konfiguriert.", ephemeral=True)
            return
        
        # Test API connection
        if await self.get_access_token():
            user_info = await self.get_user_info(username)
            if user_info:
                stream_info = await self.get_stream_info(user_info['id'])
                
                embed = discord.Embed(
                    title="✅ Twitch-API Test erfolgreich",
                    color=0x00FF00
                )
                
                embed.add_field(
                    name="👤 Benutzer",
                    value=f"**{user_info['display_name']}**\n{user_info['description'][:100]}...",
                    inline=False
                )
                
                embed.add_field(
                    name="📺 Stream Status",
                    value="🔴 LIVE" if stream_info else "⚫ OFFLINE",
                    inline=True
                )
                
                if stream_info:
                    embed.add_field(
                        name="🎮 Spielt",
                        value=stream_info['game_name'],
                        inline=True
                    )
                    embed.add_field(
                        name="👥 Zuschauer",
                        value=f"{stream_info['viewer_count']:,}",
                        inline=True
                    )
                
                embed.set_thumbnail(url=user_info['profile_image_url'])
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.followup.send("❌ Benutzer nicht gefunden.", ephemeral=True)
        else:
            await interaction.followup.send("❌ Fehler bei der API-Authentifizierung.", ephemeral=True)
    
    @app_commands.command(name="twitch_delete", description="Lösche die Twitch-Benachrichtigungen Konfiguration")
    async def twitch_delete(self, interaction: discord.Interaction):
        """Delete Twitch notifications setup"""
        if not self.bot.is_authorized(interaction.user.id):
            await interaction.response.send_message("❌ Du bist nicht berechtigt, diesen Befehl zu verwenden.", ephemeral=True)
            return
        
        if not self.config.get('enabled') and not self.config.get('twitch_username'):
            await interaction.response.send_message("❌ Keine Twitch-Konfiguration gefunden.", ephemeral=True)
            return
        
        if self.check_stream_status.is_running():
            self.check_stream_status.cancel()
        
        self.stream_status.clear()
        self.notification_messages.clear()
        
        old_username = self.config.get('twitch_username', 'Unbekannt')
        self.config = {
            "client_id": "",
            "client_secret": "",
            "twitch_username": "",
            "discord_channel_id": 0,
            "check_interval": 60,
            "enabled": False
        }
        self.save_config()
        
        self.access_token = None
        
        embed = discord.Embed(
            title="🗑️ Twitch-Konfiguration gelöscht",
            description=f"Die Überwachung von **{old_username}** wurde beendet und alle Einstellungen wurden zurückgesetzt.",
            color=0xFF4444
        )
        
        embed.add_field(
            name="✅ Gelöscht",
            value="• API-Credentials\n• Twitch-Username\n• Discord-Channel\n• Monitoring-Status",
            inline=False
        )
        
        embed.add_field(
            name="ℹ️ Info",
            value="Du kannst jederzeit mit `/twitch_setup` eine neue Konfiguration erstellen.",
            inline=False
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="twitch_preview", description="Zeige eine Vorschau der Twitch-Benachrichtigungen")
    async def twitch_preview(self, interaction: discord.Interaction):
        """Show preview of Twitch notifications"""
        if not self.bot.is_authorized(interaction.user.id):
            await interaction.response.send_message("❌ Du bist nicht berechtigt, diesen Befehl zu verwenden.", ephemeral=True)
            return
        
        username = self.config.get('twitch_username')
        if not username:
            await interaction.response.send_message("❌ Kein Twitch-Username konfiguriert. Verwende `/twitch_setup` zuerst.", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        if await self.get_access_token():
            user_info = await self.get_user_info(username)
            if user_info:
                preview_embed = self.create_preview_embed(user_info)
                preview_view = self.create_watch_button(username)
                
                preview_message = await interaction.followup.send(embed=preview_embed, view=preview_view)
                
                try:
                    preview_thread = await preview_message.create_thread(
                        name=f"🎯 VORSCHAU - {user_info['display_name']} Stream Chat",
                        auto_archive_duration=60  # 1 hour for preview
                    )
                    
                    await preview_thread.send("🎬 Dies ist eine Vorschau! Hier werden später VOD-Links gepostet.")
                except Exception as e:
                    logger.error(f"Error creating preview thread: {e}")
            else:
                await interaction.followup.send("❌ Twitch-Benutzer nicht gefunden.", ephemeral=True)
        else:
            await interaction.followup.send("❌ Fehler bei der API-Authentifizierung.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(TwitchNotifications(bot))