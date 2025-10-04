import discord
from discord import app_commands
from discord.ext import commands, tasks
import aiohttp
import asyncio
import json
import os
from datetime import datetime
import logging
import feedparser
import re

logger = logging.getLogger(__name__)

class YouTubeNotifications(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config_file = 'youtube_config.json'
        self.config = self.load_config()
        self.session = None
        self.posted_videos = set()
        self.last_check = {}  # Add timestamp tracking for each channel
        
    def load_config(self):
        """Load configuration from JSON file"""
        default_config = {
            "channels": {},  # Dictionary of channel configs
            "discord_channel_id": 0,
            "check_interval": 60,  # seconds
            "enabled": False,
            "posted_videos": []  # Add this to persist posted videos
        }
        
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # Ensure channels dict exists
                    if 'channels' not in config:
                        config['channels'] = {}
                    if 'posted_videos' not in config:  # Add this to load posted videos
                        config['posted_videos'] = []
                    self.posted_videos = set(config['posted_videos'])  # Initialize posted videos set
                    return config
            except Exception as e:
                logger.error(f"Error loading config: {e}")
                return default_config
        else:
            self.save_config(default_config)
            return default_config

    def save_config(self, config=None):
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
            self.check_youtube_feed.start()

    async def cog_unload(self):
        """Cleanup when cog is unloaded"""
        if self.session:
            await self.session.close()
        if self.check_youtube_feed.is_running():
            self.check_youtube_feed.cancel()

    async def get_channel_info(self, channel_id):
        """Get channel information from RSS feed"""
        rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        try:
            async with self.session.get(rss_url) as response:
                if response.status == 200:
                    feed_content = await response.text()
                    feed = feedparser.parse(feed_content)
                    
                    if feed.entries:
                        channel_info = {
                            'title': feed.feed.title,
                            'link': feed.feed.link,
                            'description': feed.feed.description if 'description' in feed.feed else '',
                            'thumbnail': self.extract_channel_thumbnail(feed_content)
                        }
                        return channel_info
        except Exception as e:
            logger.error(f"Error getting channel info: {e}")
        return None

    def extract_channel_thumbnail(self, feed_content):
        """Extract channel thumbnail URL from feed XML"""
        try:
            match = re.search(r'https://yt3\.googleusercontent\.com/[^"<]+', feed_content)
            return match.group(0) if match else None
        except:
            return None

    def create_video_embed(self, entry, channel_info):
        """Create embed for video notification"""
        try:
            embed = discord.Embed(
                title=entry.title,
                url=entry.link,
                color=0xFF0000,
                timestamp=datetime.strptime(entry.published, "%Y-%m-%dT%H:%M:%S%z")
            )
            
            embed.set_author(
                name=channel_info['title'],
                url=channel_info['link'],
                icon_url=channel_info['thumbnail']
            )

            # Extract video ID and create thumbnail URL
            video_id = entry.yt_videoid
            thumbnail_url = f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"
            embed.set_image(url=thumbnail_url)
            
            if hasattr(entry, 'summary'):
                description = entry.summary[:500]
                if len(entry.summary) > 500:
                    description += "..."
                embed.description = description

            embed.set_footer(
                text="YouTube Video Benachrichtigung",
                icon_url="https://www.youtube.com/s/desktop/9cc6dbeb/img/favicon_144x144.png"
            )
            
            return embed
        except Exception as e:
            logger.error(f"Error creating video embed: {e}")
            return None

    def create_watch_button(self, video_url):
        """Create view with watch button"""
        view = discord.ui.View(timeout=None)
        button = discord.ui.Button(
            label="Video anschauen",
            style=discord.ButtonStyle.link,
            url=video_url,
            emoji="▶️"
        )
        view.add_item(button)
        return view

    @tasks.loop(seconds=30)
    async def check_youtube_feed(self):
        if not self.config.get('enabled', False):
            logger.info("YouTube notifications are disabled")
            return

        current_time = datetime.now().timestamp()
        channels_to_check = dict(self.config['channels'])
        channels_to_remove = []

        for channel_id, channel_config in channels_to_check.items():
            if not channel_config.get('enabled', True):
                logger.debug(f"Channel {channel_id} is disabled")
                continue

            # Add cooldown check to avoid rate limiting
            if channel_id in self.last_check and current_time - self.last_check[channel_id] < 25:
                continue

            self.last_check[channel_id] = current_time
            
            discord_channel_id = channel_config.get('discord_channel_id')
            if not discord_channel_id:
                logger.debug(f"No Discord channel ID for {channel_id}, skipping")
                continue

            # Try to get channel through all available methods
            discord_channel = None
            guild_id = channel_config.get('guild_id')

            # Try method 1: Direct channel fetch
            discord_channel = self.bot.get_channel(discord_channel_id)
            
            # Try method 2: Through guild if method 1 failed
            if not discord_channel and guild_id:
                for guild in self.bot.guilds:
                    if guild.id == guild_id:
                        discord_channel = guild.get_channel(discord_channel_id)
                        if discord_channel:
                            logger.info(f"Found channel through guild search: {guild.name}")
                            break

            if not discord_channel:
                logger.warning(f"Could not find Discord channel {discord_channel_id}, skipping for now")
                continue

            try:
                rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
                async with self.session.get(rss_url) as response:
                    if response.status != 200:
                        logger.warning(f"YouTube API returned status {response.status} for channel {channel_id}")
                        continue

                    feed_content = await response.text()
                    feed = feedparser.parse(feed_content)
                    
                    if not feed.entries:
                        logger.debug(f"No entries found for channel {channel_id}")
                        continue
                        
                    latest_entry = feed.entries[0]
                    latest_id = latest_entry.yt_videoid
                    current_id = channel_config.get('latest_video_id')
                    
                    logger.debug(f"Channel {channel_id}: Latest video ID: {latest_id}, Current ID: {current_id}")
                    
                    # Enhanced video detection logic
                    is_new_video = (
                        latest_id != current_id and
                        latest_id not in self.posted_videos and
                        datetime.strptime(latest_entry.published, "%Y-%m-%dT%H:%M:%S%z").timestamp() > current_time - 3600
                    )
                    
                    if is_new_video:
                        logger.info(f"New video detected for channel {channel_id}: {latest_id}")
                        
                        # Update tracking
                        self.config['channels'][channel_id]['latest_video_id'] = latest_id
                        self.posted_videos.add(latest_id)
                        self.config['posted_videos'] = list(self.posted_videos)
                        self.save_config()
                        
                        # Get channel info and send notification
                        channel_info = {
                            'title': feed.feed.title,
                            'link': feed.feed.link,
                            'thumbnail': self.extract_channel_thumbnail(feed_content)
                        }
                        
                        embed = self.create_video_embed(latest_entry, channel_info)
                        view = self.create_watch_button(latest_entry.link)
                        
                        # Handle role mention
                        content = None
                        if 'ping_role_id' in channel_config:
                            role = discord_channel.guild.get_role(channel_config['ping_role_id'])
                            if role:
                                content = role.mention
                        
                        try:
                            await discord_channel.send(content=content, embed=embed, view=view)
                            logger.info(f"Successfully posted notification for {channel_info['title']}")
                        except Exception as e:
                            logger.error(f"Failed to send notification: {e}")
                            self.posted_videos.remove(latest_id)
                            self.config['posted_videos'] = list(self.posted_videos)
                            self.save_config()
                    else:
                        logger.debug(f"No new videos for channel {channel_id}")
            
            except Exception as e:
                logger.error(f"Error checking channel {channel_id}: {e}")

        # Remove invalid channels after iteration
        if channels_to_remove:
            for channel_id in channels_to_remove:
                if channel_id in self.config['channels']:
                    logger.info(f"Removing invalid channel configuration for {channel_id}")
                    del self.config['channels'][channel_id]
            self.save_config()

    class ConfirmLatestVideo(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)
            self.value = None

        @discord.ui.button(label="Ja", style=discord.ButtonStyle.green)
        async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.value = True
            self.stop()
            await interaction.response.defer()

        @discord.ui.button(label="Nein", style=discord.ButtonStyle.red)
        async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.value = False
            self.stop()
            await interaction.response.defer()

    @app_commands.command(name="youtube_add", description="Füge einen YouTube Kanal zur Überwachung hinzu")
    @app_commands.describe(
        channel_id="YouTube Channel ID",
        ping_role="Role die gepingt werden soll (optional)"
    )
    async def youtube_add(
        self,
        interaction: discord.Interaction,
        channel_id: str,
        ping_role: discord.Role = None
    ):
        """Add a YouTube channel to monitor"""
        if not self.bot.is_authorized(interaction.user.id):
            await interaction.response.send_message("❌ Du bist nicht berechtigt, diesen Befehl zu verwenden.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            # Test if channel exists
            rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
            async with self.session.get(rss_url) as response:
                if response.status != 200:
                    await interaction.followup.send("❌ YouTube Kanal nicht gefunden.", ephemeral=True)
                    return
                
                feed_content = await response.text()
                feed = feedparser.parse(feed_content)
                
                if not feed.entries:
                    await interaction.followup.send("❌ Keine Videos im Kanal gefunden.", ephemeral=True)
                    return
                
                # Add channel to config
                self.config['channels'][channel_id] = {
                    'enabled': True,
                    'latest_video_id': feed.entries[0].yt_videoid,
                    'ping_role_id': ping_role.id if ping_role else None
                }
                self.save_config()
                
                channel_info = {
                    'title': feed.feed.title,
                    'link': feed.feed.link,
                    'thumbnail': self.extract_channel_thumbnail(feed_content)
                }
                
                embed = discord.Embed(
                    title="✅ YouTube Kanal hinzugefügt",
                    description=f"**{channel_info['title']}** wurde zur Überwachung hinzugefügt.",
                    color=0x00FF00,
                    url=channel_info['link']
                )
                
                if ping_role:
                    embed.add_field(name="🔔 Ping Role", value=ping_role.mention)
                
                if channel_info['thumbnail']:
                    embed.set_thumbnail(url=channel_info['thumbnail'])
                
                await interaction.followup.send(embed=embed, ephemeral=True)
                
        except Exception as e:
            logger.error(f"Error adding YouTube channel: {e}")
            await interaction.followup.send("❌ Fehler beim Hinzufügen des Kanals.", ephemeral=True)

    @app_commands.command(name="youtube_remove", description="Entferne einen YouTube Kanal von der Überwachung")
    @app_commands.describe(channel_id="YouTube Channel ID")
    async def youtube_remove(self, interaction: discord.Interaction, channel_id: str):
        """Remove a YouTube channel from monitoring"""
        if not self.bot.is_authorized(interaction.user.id):
            await interaction.response.send_message("❌ Du bist nicht berechtigt, diesen Befehl zu verwenden.", ephemeral=True)
            return

        if channel_id in self.config['channels']:
            channel_info = None
            try:
                rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
                async with self.session.get(rss_url) as response:
                    if response.status == 200:
                        feed_content = await response.text()
                        feed = feedparser.parse(feed_content)
                        channel_info = {
                            'title': feed.feed.title,
                            'thumbnail': self.extract_channel_thumbnail(feed_content)
                        }
            except:
                pass

            del self.config['channels'][channel_id]
            self.save_config()

            embed = discord.Embed(
                title="🗑️ YouTube Kanal entfernt",
                description=f"**{channel_info['title'] if channel_info else channel_id}** wurde von der Überwachung entfernt.",
                color=0xFF0000
            )
            
            if channel_info and channel_info['thumbnail']:
                embed.set_thumbnail(url=channel_info['thumbnail'])
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message("❌ Dieser Kanal wird nicht überwacht.", ephemeral=True)

    @app_commands.command(name="youtube_list", description="Liste alle überwachten YouTube Kanäle")
    async def youtube_list(self, interaction: discord.Interaction):
        """List all monitored YouTube channels"""
        if not self.bot.is_authorized(interaction.user.id):
            await interaction.response.send_message("❌ Du bist nicht berechtigt, diesen Befehl zu verwenden.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        embed = discord.Embed(
            title="📋 Überwachte YouTube Kanäle",
            color=0xFF0000
        )

        if not self.config['channels']:
            embed.description = "*Keine Kanäle konfiguriert*"
        else:
            for channel_id, channel_config in self.config['channels'].items():
                try:
                    rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
                    async with self.session.get(rss_url) as response:
                        if response.status == 200:
                            feed_content = await response.text()
                            feed = feedparser.parse(feed_content)
                            
                            status = "✅" if channel_config.get('enabled', True) else "❌"
                            
                            # Fix role mention display
                            ping_role_id = channel_config.get('ping_role_id')
                            if ping_role_id:
                                role = interaction.guild.get_role(ping_role_id)
                                ping_role = role.name if role else "Nicht gefunden"
                            else:
                                ping_role = "Keine"
                                
                            discord_channel = self.bot.get_channel(channel_config.get('discord_channel_id'))
                            channel_mention = discord_channel.mention if discord_channel else "Nicht gefunden"
                            
                            value = f"**Status:** {status}\n**Channel:** {channel_mention}\n**Ping Role:** {ping_role}\n**ID:** `{channel_id}`"
                            embed.add_field(
                                name=f"📺 {feed.feed.title}",
                                value=value,
                                inline=False
                            )
                except:
                    embed.add_field(
                        name=f"❌ Unbekannter Kanal",
                        value=f"**ID:** `{channel_id}`\n*Kanal nicht verfügbar*",
                        inline=False
                    )

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="youtube_toggle_channel", description="Aktiviere/Deaktiviere einen bestimmten YouTube Kanal")
    @app_commands.describe(channel_id="YouTube Channel ID")
    async def youtube_toggle_channel(self, interaction: discord.Interaction, channel_id: str):
        """Toggle a specific YouTube channel"""
        if not self.bot.is_authorized(interaction.user.id):
            await interaction.response.send_message("❌ Du bist nicht berechtigt, diesen Befehl zu verwenden.", ephemeral=True)
            return

        if channel_id not in self.config['channels']:
            await interaction.response.send_message("❌ Dieser Kanal wird nicht überwacht.", ephemeral=True)
            return

        # Toggle channel status
        self.config['channels'][channel_id]['enabled'] = not self.config['channels'][channel_id].get('enabled', True)
        self.save_config()

        try:
            rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
            async with self.session.get(rss_url) as response:
                if response.status == 200:
                    feed_content = await response.text()
                    feed = feedparser.parse(feed_content)
                    
                    status = "aktiviert" if self.config['channels'][channel_id]['enabled'] else "deaktiviert"
                    color = 0x00FF00 if self.config['channels'][channel_id]['enabled'] else 0xFF0000
                    
                    embed = discord.Embed(
                        title=f"🔄 {feed.feed.title}",
                        description=f"Benachrichtigungen wurden **{status}**",
                        color=color
                    )
                    
                    thumbnail = self.extract_channel_thumbnail(feed_content)
                    if thumbnail:
                        embed.set_thumbnail(url=thumbnail)
                    
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return

        except Exception as e:
            logger.error(f"Error toggling channel: {e}")

        # Fallback response if channel info couldn't be fetched
        status = "aktiviert" if self.config['channels'][channel_id]['enabled'] else "deaktiviert"
        await interaction.response.send_message(f"Kanal wurde {status}.", ephemeral=True)

    @app_commands.command(name="youtube_embed", description="Sende YouTube Video Updates in einen Channel")
    async def youtube_embed(
        self,
        interaction: discord.Interaction,
        channel_id: str,
        discord_channel: discord.TextChannel,
        ping_role: discord.Role = None
    ):
        if not self.bot.is_authorized(interaction.user.id):
            await interaction.response.send_message("❌ Du bist nicht berechtigt, diesen Befehl zu verwenden.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        # Verify channel permissions first
        channel_permissions = discord_channel.permissions_for(discord_channel.guild.me)
        if not (channel_permissions.send_messages and channel_permissions.embed_links):
            await interaction.followup.send(
                "❌ Der Bot hat nicht die nötigen Berechtigungen im ausgewählten Kanal.\n"
                "Benötigt werden: Nachrichten senden, Embeds senden",
                ephemeral=True
            )
            return

        # Test channel access
        try:
            await discord_channel.send("🔄 Teste Kanalzugriff...", delete_after=2)
        except discord.Forbidden:
            await interaction.followup.send("❌ Kann keine Nachrichten in diesem Kanal senden.", ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(f"❌ Fehler beim Testen des Kanalzugriffs: {str(e)}", ephemeral=True)
            return

        try:
            # Test if YouTube channel exists and get latest video
            rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
            async with self.session.get(rss_url) as response:
                if response.status != 200:
                    await interaction.followup.send("❌ YouTube Kanal nicht gefunden.", ephemeral=True)
                    return
                
                feed_content = await response.text()
                feed = feedparser.parse(feed_content)
                
                if not feed.entries:
                    await interaction.followup.send("❌ Keine Videos im Kanal gefunden.", ephemeral=True)
                    return

                latest_entry = feed.entries[0]
                channel_info = {
                    'title': feed.feed.title,
                    'link': feed.feed.link,
                    'thumbnail': self.extract_channel_thumbnail(feed_content)
                }

                # Create confirmation embed with latest video info
                confirm_embed = discord.Embed(
                    title="🎥 Letztes Video bestätigen",
                    description=f"Ist dies das letzte Video von **{channel_info['title']}**?",
                    color=0xFF0000
                )
                
                confirm_embed.add_field(
                    name="Video Titel",
                    value=latest_entry.title,
                    inline=False
                )
                
                video_id = latest_entry.yt_videoid
                thumbnail_url = f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"
                confirm_embed.set_image(url=thumbnail_url)
                
                if channel_info['thumbnail']:
                    confirm_embed.set_thumbnail(url=channel_info['thumbnail'])

                # Send confirmation message with buttons
                view = self.ConfirmLatestVideo()
                confirm_msg = await interaction.followup.send(embed=confirm_embed, view=view, ephemeral=True)

                # Wait for button interaction
                await view.wait()
                
                if view.value is None:
                    await confirm_msg.edit(content="❌ Zeitüberschreitung - Setup abgebrochen.", embed=None, view=None)
                    return
                elif not view.value:
                    await confirm_msg.edit(content="❌ Setup abgebrochen.", embed=None, view=None)
                    return

                # Continue with channel setup if confirmed
                if not self.config.get('enabled', False):
                    self.config['enabled'] = True
                    self.check_youtube_feed.start()
                
                self.config['channels'][channel_id] = {
                    'enabled': True,
                    'latest_video_id': video_id,
                    'discord_channel_id': discord_channel.id,
                    'guild_id': discord_channel.guild.id,
                    'ping_role_id': ping_role.id if ping_role else None
                }
                self.save_config()
                
                # Add video ID to posted videos
                self.posted_videos.add(video_id)
                self.config['posted_videos'] = list(self.posted_videos)
                self.save_config()

                # Send success message
                setup_embed = discord.Embed(
                    title="✅ YouTube Kanal eingerichtet",
                    description=f"**{channel_info['title']}** wurde eingerichtet.\nUpdates werden in {discord_channel.mention} gesendet.",
                    color=0x00FF00,
                    url=channel_info['link']
                )
                
                if ping_role:
                    setup_embed.add_field(name="🔔 Ping Role", value=ping_role.mention)
                
                if channel_info['thumbnail']:
                    setup_embed.set_thumbnail(url=channel_info['thumbnail'])
                
                await interaction.followup.send(embed=setup_embed, ephemeral=True)
                
        except Exception as e:
            logger.error(f"Error setting up YouTube channel: {e}")
            await interaction.followup.send("❌ Fehler beim Einrichten des Kanals.", ephemeral=True)

    @tasks.loop(seconds=30)
    async def check_youtube_feed(self):
        if not self.config.get('enabled', False):
            logger.info("YouTube notifications are disabled")
            return

        current_time = datetime.now().timestamp()
        channels_to_check = dict(self.config['channels'])
        channels_to_remove = []

        for channel_id, channel_config in channels_to_check.items():
            if not channel_config.get('enabled', True):
                logger.debug(f"Channel {channel_id} is disabled")
                continue

            # Add cooldown check to avoid rate limiting
            if channel_id in self.last_check and current_time - self.last_check[channel_id] < 25:
                continue

            self.last_check[channel_id] = current_time
            
            discord_channel_id = channel_config.get('discord_channel_id')
            if not discord_channel_id:
                logger.debug(f"No Discord channel ID for {channel_id}, skipping")
                continue

            # Try to get channel through all available methods
            discord_channel = None
            guild_id = channel_config.get('guild_id')

            # Try method 1: Direct channel fetch
            discord_channel = self.bot.get_channel(discord_channel_id)
            
            # Try method 2: Through guild if method 1 failed
            if not discord_channel and guild_id:
                for guild in self.bot.guilds:
                    if guild.id == guild_id:
                        discord_channel = guild.get_channel(discord_channel_id)
                        if discord_channel:
                            logger.info(f"Found channel through guild search: {guild.name}")
                            break

            if not discord_channel:
                logger.warning(f"Could not find Discord channel {discord_channel_id}, skipping for now")
                continue

            try:
                rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
                async with self.session.get(rss_url) as response:
                    if response.status != 200:
                        logger.warning(f"YouTube API returned status {response.status} for channel {channel_id}")
                        continue

                    feed_content = await response.text()
                    feed = feedparser.parse(feed_content)
                    
                    if not feed.entries:
                        logger.debug(f"No entries found for channel {channel_id}")
                        continue
                        
                    latest_entry = feed.entries[0]
                    latest_id = latest_entry.yt_videoid
                    current_id = channel_config.get('latest_video_id')
                    
                    logger.debug(f"Channel {channel_id}: Latest video ID: {latest_id}, Current ID: {current_id}")
                    
                    # Enhanced video detection logic
                    is_new_video = (
                        latest_id != current_id and
                        latest_id not in self.posted_videos and
                        datetime.strptime(latest_entry.published, "%Y-%m-%dT%H:%M:%S%z").timestamp() > current_time - 3600
                    )
                    
                    if is_new_video:
                        logger.info(f"New video detected for channel {channel_id}: {latest_id}")
                        
                        # Update tracking
                        self.config['channels'][channel_id]['latest_video_id'] = latest_id
                        self.posted_videos.add(latest_id)
                        self.config['posted_videos'] = list(self.posted_videos)
                        self.save_config()
                        
                        # Get channel info and send notification
                        channel_info = {
                            'title': feed.feed.title,
                            'link': feed.feed.link,
                            'thumbnail': self.extract_channel_thumbnail(feed_content)
                        }
                        
                        embed = self.create_video_embed(latest_entry, channel_info)
                        view = self.create_watch_button(latest_entry.link)
                        
                        # Handle role mention
                        content = None
                        if 'ping_role_id' in channel_config:
                            role = discord_channel.guild.get_role(channel_config['ping_role_id'])
                            if role:
                                content = role.mention
                        
                        try:
                            await discord_channel.send(content=content, embed=embed, view=view)
                            logger.info(f"Successfully posted notification for {channel_info['title']}")
                        except Exception as e:
                            logger.error(f"Failed to send notification: {e}")
                            self.posted_videos.remove(latest_id)
                            self.config['posted_videos'] = list(self.posted_videos)
                            self.save_config()
                    else:
                        logger.debug(f"No new videos for channel {channel_id}")
            
            except Exception as e:
                logger.error(f"Error checking channel {channel_id}: {e}")

        # Remove invalid channels after iteration
        if channels_to_remove:
            for channel_id in channels_to_remove:
                if channel_id in self.config['channels']:
                    logger.info(f"Removing invalid channel configuration for {channel_id}")
                    del self.config['channels'][channel_id]
            self.save_config()

async def setup(bot):
    await bot.add_cog(YouTubeNotifications(bot))
        # Remove invalid channels after iteration
        if channels_to_remove:
            for channel_id in channels_to_remove:
                if channel_id in self.config['channels']:
                    logger.info(f"Removing invalid channel configuration for {channel_id}")
                    del self.config['channels'][channel_id]
            self.save_config()

async def setup(bot):
    await bot.add_cog(YouTubeNotifications(bot))
