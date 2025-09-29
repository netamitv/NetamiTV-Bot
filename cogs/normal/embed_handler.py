import discord
import asyncio
import logging
import time
import json
import os
from discord.ext import commands
from typing import Dict, List, Optional, Union
from datetime import datetime, timedelta
from collections import defaultdict, deque

logger = logging.getLogger(__name__)

class Emojis:
    """Emoji constants for embeds"""
    LOADING = "⏳"
    SUCCESS = "✅"
    ERROR = "❌"
    WARNING = "⚠️"
    INFO = "ℹ️"
    EYES = "👀"
    CLOCK = "🕐"
    SHIELD = "🛡️"
    FIRE = "🔥"
    STAR = "⭐"
    HEART = "❤️"
    THUMBS_UP = "👍"
    THUMBS_DOWN = "👎"

class RateLimitManager:
    """Advanced rate limit manager for embed operations"""
    
    def __init__(self):
        self.user_requests: Dict[int, deque] = defaultdict(lambda: deque(maxlen=50))
        self.channel_requests: Dict[int, deque] = defaultdict(lambda: deque(maxlen=100))
        self.global_requests: deque = deque(maxlen=1000)
        self.blocked_users: Dict[int, float] = {}
        self.blocked_channels: Dict[int, float] = {}
        
        self.user_limit = 10  # requests per minute
        self.channel_limit = 30  # requests per minute
        self.global_limit = 500  # requests per minute
        self.block_duration = 300  # 5 minutes
        
        asyncio.create_task(self._cleanup_task())
    
    async def _cleanup_task(self):
        """Periodic cleanup of old data"""
        while True:
            try:
                await asyncio.sleep(60)
                current_time = time.time()
                
                self.blocked_users = {
                    user_id: block_time for user_id, block_time in self.blocked_users.items()
                    if current_time - block_time < self.block_duration
                }
                self.blocked_channels = {
                    channel_id: block_time for channel_id, block_time in self.blocked_channels.items()
                    if current_time - block_time < self.block_duration
                }
                
                cutoff_time = current_time - 60
                
                for user_id in list(self.user_requests.keys()):
                    requests = self.user_requests[user_id]
                    while requests and requests[0] < cutoff_time:
                        requests.popleft()
                    if not requests:
                        del self.user_requests[user_id]
                
                for channel_id in list(self.channel_requests.keys()):
                    requests = self.channel_requests[channel_id]
                    while requests and requests[0] < cutoff_time:
                        requests.popleft()
                    if not requests:
                        del self.channel_requests[channel_id]
                
                while self.global_requests and self.global_requests[0] < cutoff_time:
                    self.global_requests.popleft()
                    
            except Exception as e:
                logger.error(f"Error in rate limit cleanup: {e}")
    
    def is_rate_limited(self, user_id: int, channel_id: int) -> tuple[bool, str, int]:
        """Check if user/channel is rate limited"""
        current_time = time.time()
        
        if user_id in self.blocked_users:
            remaining = int(self.blocked_users[user_id] + self.block_duration - current_time)
            if remaining > 0:
                return True, "user_blocked", remaining
            else:
                del self.blocked_users[user_id]
        
        if channel_id in self.blocked_channels:
            remaining = int(self.blocked_channels[channel_id] + self.block_duration - current_time)
            if remaining > 0:
                return True, "channel_blocked", remaining
            else:
                del self.blocked_channels[channel_id]
        
        user_requests = self.user_requests[user_id]
        if len(user_requests) >= self.user_limit:
            self.blocked_users[user_id] = current_time
            return True, "user_limit", self.block_duration
        
        channel_requests = self.channel_requests[channel_id]
        if len(channel_requests) >= self.channel_limit:
            self.blocked_channels[channel_id] = current_time
            return True, "channel_limit", self.block_duration
        
        if len(self.global_requests) >= self.global_limit:
            return True, "global_limit", 60
        
        return False, "", 0
    
    def add_request(self, user_id: int, channel_id: int):
        """Record a new request"""
        current_time = time.time()
        self.user_requests[user_id].append(current_time)
        self.channel_requests[channel_id].append(current_time)
        self.global_requests.append(current_time)
    
    def get_stats(self) -> Dict:
        """Get rate limiting statistics"""
        return {
            "active_users": len(self.user_requests),
            "active_channels": len(self.channel_requests),
            "blocked_users": len(self.blocked_users),
            "blocked_channels": len(self.blocked_channels),
            "global_requests_last_minute": len(self.global_requests)
        }

class EmbedCache:
    """Cache system for frequently used embeds"""
    
    def __init__(self, max_size: int = 1000, ttl: int = 300):
        self.cache: Dict[str, tuple] = {}
        self.max_size = max_size
        self.ttl = ttl
        
        asyncio.create_task(self._cleanup_cache())
    
    async def _cleanup_cache(self):
        """Periodic cache cleanup"""
        while True:
            try:
                await asyncio.sleep(60)
                current_time = time.time()
                
                expired_keys = [
                    key for key, (embed, timestamp) in self.cache.items()
                    if current_time - timestamp > self.ttl
                ]
                
                for key in expired_keys:
                    del self.cache[key]
                
                if len(self.cache) > self.max_size:
                    sorted_items = sorted(
                        self.cache.items(),
                        key=lambda x: x[1][1]
                    )
                    
                    self.cache = dict(sorted_items[-self.max_size:])
                    
            except Exception as e:
                logger.error(f"Error in cache cleanup: {e}")
    
    def get(self, key: str) -> Optional[discord.Embed]:
        """Get embed from cache"""
        if key in self.cache:
            embed, timestamp = self.cache[key]
            if time.time() - timestamp < self.ttl:
                return embed.copy()
            else:
                del self.cache[key]
        return None
    
    def set(self, key: str, embed: discord.Embed):
        """Store embed in cache"""
        self.cache[key] = (embed.copy(), time.time())

class EmbedHandler(commands.Cog):
    """Enhanced embed handler with advanced rate limiting and caching"""
    
    def __init__(self, bot):
        self.bot = bot
        self.emojis = Emojis()
        self.rate_limiter = RateLimitManager()
        self.embed_cache = EmbedCache()
        
        self.success_icon = "https://cdn.discordapp.com/attachments/1345425154192179361/1345425196315709511/success.png?ex=67c4805b&is=67c32edb&hm=bd460878e398473465c9fc209b0a7c40336d4b75f8a508748208a14745fd0437&"
        self.error_icon = "https://cdn.discordapp.com/attachments/1345425154192179361/1345425187251818588/failed.png?ex=67c48059&is=67c32ed9&hm=66869b484ff53d1a3a99fc892fa1b46344c26f73407b59255aff8ed5162a2647&"
        
        self.logger = logging.getLogger(__name__)
        
        self.stats = {
            "messages_sent": 0,
            "messages_edited": 0,
            "rate_limit_hits": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "errors": 0
        }
        
        self.config = self._load_config()
    
    def _load_config(self) -> Dict:
        """Load embed handler configuration"""
        config_path = "embed_handler_config.json"
        default_config = {
            "rate_limiting": {
                "enabled": True,
                "user_limit": 10,
                "channel_limit": 30,
                "global_limit": 500,
                "block_duration": 300
            },
            "caching": {
                "enabled": True,
                "max_size": 1000,
                "ttl": 300
            },
            "retry_settings": {
                "max_retries": 5,
                "initial_delay": 1,
                "max_delay": 60,
                "exponential_base": 2
            }
        }
        
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    for key in default_config:
                        if key not in config:
                            config[key] = default_config[key]
                    return config
            else:
                with open(config_path, 'w', encoding='utf-8') as f:
                    json.dump(default_config, f, indent=4)
                return default_config
        except Exception as e:
            self.logger.error(f"Error loading config: {e}")
            return default_config
    
    def _check_rate_limit(self, ctx_or_interaction) -> tuple[bool, str]:
        """Check rate limits before sending"""
        if not self.config["rate_limiting"]["enabled"]:
            return False, ""
        
        if hasattr(ctx_or_interaction, 'author'):
            user_id = ctx_or_interaction.author.id
            channel_id = ctx_or_interaction.channel.id
        else:
            user_id = ctx_or_interaction.user.id
            channel_id = ctx_or_interaction.channel.id if ctx_or_interaction.channel else 0
        
        is_limited, limit_type, remaining = self.rate_limiter.is_rate_limited(user_id, channel_id)
        
        if is_limited:
            self.stats["rate_limit_hits"] += 1
            
            if limit_type == "user_blocked":
                return True, f"You are temporarily blocked from using embeds. Try again in {remaining} seconds."
            elif limit_type == "channel_blocked":
                return True, f"This channel is temporarily rate limited. Try again in {remaining} seconds."
            elif limit_type == "user_limit":
                return True, f"You've exceeded the embed limit. Please wait {remaining} seconds."
            elif limit_type == "channel_limit":
                return True, f"Channel embed limit exceeded. Please wait {remaining} seconds."
            elif limit_type == "global_limit":
                return True, f"Global rate limit reached. Please wait {remaining} seconds."
        
        return False, ""
    
    async def _handle_rate_limit_error(self, ctx_or_interaction, message: str):
        """Handle rate limit errors gracefully"""
        embed = discord.Embed(
            title=f"{self.emojis.WARNING} Rate Limited",
            description=message,
            color=discord.Color.orange()
        )
        embed.add_field(
            name="Why am I seeing this?",
            value="Rate limiting prevents spam and ensures the bot remains responsive for everyone.",
            inline=False
        )
        embed.set_footer(text="Please wait before trying again.")
        
        try:
            if hasattr(ctx_or_interaction, 'send'):  # Context
                await ctx_or_interaction.send(embed=embed, ephemeral=True)
            else:
                if ctx_or_interaction.response.is_done():
                    await ctx_or_interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    await ctx_or_interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            self.logger.error(f"Error sending rate limit message: {e}")

    async def safe_send(self, channel, embed=None, content=None, max_retries=None, **kwargs):
        """Enhanced safe send with rate limiting and intelligent retry logic"""
        if max_retries is None:
            max_retries = self.config["retry_settings"]["max_retries"]
        
        retry_attempts = 0
        delay = self.config["retry_settings"]["initial_delay"]
        max_delay = self.config["retry_settings"]["max_delay"]
        exponential_base = self.config["retry_settings"]["exponential_base"]
        
        while retry_attempts < max_retries:
            try:
                if embed and content:
                    result = await channel.send(content=content, embed=embed, **kwargs)
                elif embed:
                    result = await channel.send(embed=embed, **kwargs)
                else:
                    result = await channel.send(content=content, **kwargs)
                
                self.stats["messages_sent"] += 1
                return result
                
            except discord.HTTPException as e:
                if e.status == 429:
                    retry_after = float(e.response.headers.get('Retry-After', delay))
                    self.logger.warning(f"Discord rate limited, waiting {retry_after} seconds")
                    
                    await asyncio.sleep(retry_after)
                    retry_attempts += 1
                    
                elif e.status in [400, 403, 404]:
                    self.logger.error(f"Client error {e.status}: {e}")
                    self.stats["errors"] += 1
                    raise e
                    
                elif e.status >= 500:
                    self.logger.warning(f"Server error {e.status}, retrying in {delay} seconds")
                    await asyncio.sleep(delay)
                    retry_attempts += 1
                    delay = min(delay * exponential_base, max_delay)
                    
                else:
                    self.logger.error(f"HTTP Exception {e.status}: {e}")
                    self.stats["errors"] += 1
                    raise e
                    
            except discord.Forbidden:
                self.logger.error("Missing permissions to send message")
                self.stats["errors"] += 1
                raise
                
            except Exception as e:
                self.logger.error(f"Unexpected error in safe_send: {e}")
                self.stats["errors"] += 1
                if retry_attempts < max_retries - 1:
                    await asyncio.sleep(delay)
                    retry_attempts += 1
                    delay = min(delay * exponential_base, max_delay)
                else:
                    raise e
        
        self.logger.warning("All retries failed, making final attempt")
        await asyncio.sleep(10)
        
        try:
            if embed and content:
                result = await channel.send(content=content, embed=embed, **kwargs)
            elif embed:
                result = await channel.send(embed=embed, **kwargs)
            else:
                result = await channel.send(content=content, **kwargs)
            
            self.stats["messages_sent"] += 1
            return result
            
        except Exception as e:
            self.logger.error(f"Final send attempt failed: {e}")
            self.stats["errors"] += 1
            return None

    async def safe_edit(self, message, embed=None, content=None, max_retries=None, **kwargs):
        """Enhanced safe edit with rate limiting and intelligent retry logic"""
        if max_retries is None:
            max_retries = self.config["retry_settings"]["max_retries"]
        
        retry_attempts = 0
        delay = self.config["retry_settings"]["initial_delay"]
        max_delay = self.config["retry_settings"]["max_delay"]
        exponential_base = self.config["retry_settings"]["exponential_base"]
        
        while retry_attempts < max_retries:
            try:
                if embed and content:
                    result = await message.edit(content=content, embed=embed, **kwargs)
                elif embed:
                    result = await message.edit(embed=embed, **kwargs)
                else:
                    result = await message.edit(content=content, **kwargs)
                
                self.stats["messages_edited"] += 1
                return result
                
            except discord.HTTPException as e:
                if e.status == 429:
                    retry_after = float(e.response.headers.get('Retry-After', delay))
                    self.logger.warning(f"Rate limited during edit, waiting {retry_after} seconds")
                    await asyncio.sleep(retry_after)
                    retry_attempts += 1
                    
                elif e.status in [400, 403, 404]:
                    self.logger.error(f"Client error during edit {e.status}: {e}")
                    self.stats["errors"] += 1
                    raise e
                    
                elif e.status >= 500:
                    self.logger.warning(f"Server error during edit {e.status}, retrying in {delay} seconds")
                    await asyncio.sleep(delay)
                    retry_attempts += 1
                    delay = min(delay * exponential_base, max_delay)
                    
                else:
                    self.logger.error(f"HTTP Exception during edit {e.status}: {e}")
                    self.stats["errors"] += 1
                    raise e
                    
            except Exception as e:
                self.logger.error(f"Unexpected error during edit: {e}")
                self.stats["errors"] += 1
                if retry_attempts < max_retries - 1:
                    await asyncio.sleep(delay)
                    retry_attempts += 1
                    delay = min(delay * exponential_base, max_delay)
                else:
                    raise e
        
        self.logger.warning("All edit retries failed, making final attempt")
        await asyncio.sleep(10)
        
        try:
            if embed and content:
                result = await message.edit(content=content, embed=embed, **kwargs)
            elif embed:
                result = await message.edit(embed=embed, **kwargs)
            else:
                result = await message.edit(content=content, **kwargs)
            
            self.stats["messages_edited"] += 1
            return result
            
        except Exception as e:
            self.logger.error(f"Final edit attempt failed: {e}")
            self.stats["errors"] += 1
            return None

    async def send_loading_embed(self, ctx, title: str, description: str, **kwargs):
        """Send loading embed with rate limiting"""
        is_limited, message = self._check_rate_limit(ctx)
        if is_limited:
            await self._handle_rate_limit_error(ctx, message)
            return None
        
        cache_key = f"loading_{hash(title + description)}"
        embed = self.embed_cache.get(cache_key)
        
        if embed:
            self.stats["cache_hits"] += 1
        else:
            self.stats["cache_misses"] += 1
            embed = discord.Embed(
                title=f"{self.emojis.LOADING} {title}",
                description=f"{self.emojis.EYES} {description}",
                color=0x3498db
            )
            embed.set_footer(text="Processing your request...")
            embed.timestamp = datetime.utcnow()
            
            if self.config["caching"]["enabled"]:
                self.embed_cache.set(cache_key, embed)
        
        if hasattr(ctx, 'author'):
            self.rate_limiter.add_request(ctx.author.id, ctx.channel.id)
        else:
            self.rate_limiter.add_request(ctx.user.id, ctx.channel.id if ctx.channel else 0)
        
        return await self.safe_send(ctx.channel, embed=embed, **kwargs)

    async def send_success_embed(self, ctx, title: str, description: str, **kwargs):
        """Send success embed with rate limiting"""
        is_limited, message = self._check_rate_limit(ctx)
        if is_limited:
            await self._handle_rate_limit_error(ctx, message)
            return None
        
        cache_key = f"success_{hash(title + description)}"
        embed = self.embed_cache.get(cache_key)
        
        if embed:
            self.stats["cache_hits"] += 1
        else:
            self.stats["cache_misses"] += 1
            embed = discord.Embed(
                title=f"{self.emojis.SUCCESS} {title}",
                description=f"{self.emojis.EYES} {description}",
                color=0x2ecc71
            )
            embed.set_thumbnail(url=self.success_icon)
            embed.set_footer(text="Operation completed successfully")
            embed.timestamp = datetime.utcnow()
            
            if self.config["caching"]["enabled"]:
                self.embed_cache.set(cache_key, embed)
        
        if hasattr(ctx, 'author'):
            self.rate_limiter.add_request(ctx.author.id, ctx.channel.id)
        else:
            self.rate_limiter.add_request(ctx.user.id, ctx.channel.id if ctx.channel else 0)
        
        return await self.safe_send(ctx.channel, embed=embed, **kwargs)

    async def send_error_embed(self, ctx, title: str, description: str, **kwargs):
        """Send error embed with rate limiting"""
        is_limited, message = self._check_rate_limit(ctx)
        if is_limited:
            await self._handle_rate_limit_error(ctx, message)
            return None
        
        cache_key = f"error_{hash(title + description)}"
        embed = self.embed_cache.get(cache_key)
        
        if embed:
            self.stats["cache_hits"] += 1
        else:
            self.stats["cache_misses"] += 1
            embed = discord.Embed(
                title=f"{self.emojis.ERROR} {title}",
                description=f"{self.emojis.EYES} {description}",
                color=0xe74c3c
            )
            embed.set_thumbnail(url=self.error_icon)
            embed.set_footer(text="Please try again or contact support")
            embed.timestamp = datetime.utcnow()
            
            if self.config["caching"]["enabled"]:
                self.embed_cache.set(cache_key, embed)
        
        if hasattr(ctx, 'author'):
            self.rate_limiter.add_request(ctx.author.id, ctx.channel.id)
        else:
            self.rate_limiter.add_request(ctx.user.id, ctx.channel.id if ctx.channel else 0)
        
        return await self.safe_send(ctx.channel, embed=embed, **kwargs)

    async def send_warning_embed(self, ctx, title: str, description: str, **kwargs):
        """Send warning embed with rate limiting"""
        is_limited, message = self._check_rate_limit(ctx)
        if is_limited:
            await self._handle_rate_limit_error(ctx, message)
            return None
        
        embed = discord.Embed(
            title=f"{self.emojis.WARNING} {title}",
            description=f"{self.emojis.EYES} {description}",
            color=0xf39c12
        )
        embed.set_footer(text="Please review this warning")
        embed.timestamp = datetime.utcnow()
        
        if hasattr(ctx, 'author'):
            self.rate_limiter.add_request(ctx.author.id, ctx.channel.id)
        else:
            self.rate_limiter.add_request(ctx.user.id, ctx.channel.id if ctx.channel else 0)
        
        return await self.safe_send(ctx.channel, embed=embed, **kwargs)

    async def send_info_embed(self, ctx, title: str, description: str, **kwargs):
        """Send info embed with rate limiting"""
        is_limited, message = self._check_rate_limit(ctx)
        if is_limited:
            await self._handle_rate_limit_error(ctx, message)
            return None
        
        embed = discord.Embed(
            title=f"{self.emojis.INFO} {title}",
            description=f"{self.emojis.EYES} {description}",
            color=0x3498db
        )
        embed.set_footer(text="Information")
        embed.timestamp = datetime.utcnow()
        
        if hasattr(ctx, 'author'):
            self.rate_limiter.add_request(ctx.author.id, ctx.channel.id)
        else:
            self.rate_limiter.add_request(ctx.user.id, ctx.channel.id if ctx.channel else 0)
        
        return await self.safe_send(ctx.channel, embed=embed, **kwargs)

    async def create_loading_embed(self, title: str, description: str):
        """Create a loading embed without sending"""
        embed = discord.Embed(
            title=f"{self.emojis.LOADING} {title}",
            description=f"{self.emojis.EYES} {description}",
            color=0x3498db
        )
        embed.set_footer(text="Processing...")
        embed.timestamp = datetime.utcnow()
        return embed

    async def create_success_embed(self, title: str, description: str):
        """Create a success embed without sending"""
        embed = discord.Embed(
            title=f"{self.emojis.SUCCESS} {title}",
            description=f"{self.emojis.EYES} {description}",
            color=0x2ecc71
        )
        embed.set_thumbnail(url=self.success_icon)
        embed.set_footer(text="Success")
        embed.timestamp = datetime.utcnow()
        return embed

    async def create_error_embed(self, title: str, description: str):
        """Create an error embed without sending"""
        embed = discord.Embed(
            title=f"{self.emojis.ERROR} {title}",
            description=f"{self.emojis.EYES} {description}",
            color=0xe74c3c
        )
        embed.set_thumbnail(url=self.error_icon)
        embed.set_footer(text="Error")
        embed.timestamp = datetime.utcnow()
        return embed

    async def create_warning_embed(self, title: str, description: str):
        """Create a warning embed without sending"""
        embed = discord.Embed(
            title=f"{self.emojis.WARNING} {title}",
            description=f"{self.emojis.EYES} {description}",
            color=0xf39c12
        )
        embed.set_footer(text="Warning")
        embed.timestamp = datetime.utcnow()
        return embed

    async def create_info_embed(self, title: str, description: str):
        """Create an info embed without sending"""
        embed = discord.Embed(
            title=f"{self.emojis.INFO} {title}",
            description=f"{self.emojis.EYES} {description}",
            color=0x3498db
        )
        embed.set_footer(text="Information")
        embed.timestamp = datetime.utcnow()
        return embed

    # Utility methods
    def get_stats(self) -> Dict:
        """Get embed handler statistics"""
        rate_limit_stats = self.rate_limiter.get_stats()
        return {
            **self.stats,
            **rate_limit_stats,
            "cache_size": len(self.embed_cache.cache)
        }

    def reset_stats(self):
        """Reset statistics"""
        self.stats = {
            "messages_sent": 0,
            "messages_edited": 0,
            "rate_limit_hits": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "errors": 0
        }

    async def clear_cache(self):
        """Clear embed cache"""
        self.embed_cache.cache.clear()

    async def clear_rate_limits(self, user_id: Optional[int] = None, channel_id: Optional[int] = None):
        """Clear rate limits for specific user/channel or all"""
        if user_id:
            self.rate_limiter.user_requests.pop(user_id, None)
            self.rate_limiter.blocked_users.pop(user_id, None)
        
        if channel_id:
            self.rate_limiter.channel_requests.pop(channel_id, None)
            self.rate_limiter.blocked_channels.pop(channel_id, None)
        
        if not user_id and not channel_id:
            self.rate_limiter.user_requests.clear()
            self.rate_limiter.channel_requests.clear()
            self.rate_limiter.blocked_users.clear()
            self.rate_limiter.blocked_channels.clear()
            self.rate_limiter.global_requests.clear()

async def setup(bot):
    await bot.add_cog(EmbedHandler(bot))