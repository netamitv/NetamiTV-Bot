import discord
from discord.ext import commands, tasks
import aiohttp
import logging
import asyncio

logger = logging.getLogger(__name__)

class WebsiteMonitor(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.website_url = ""  # Replace with your website URL
        self.channel_id =   # Replace with your actual channel ID
        self.online_name = "🌐 • WEBSITE [🟢]"
        self.offline_name = "🌐 • WEBSITE [🔴]"
        self.current_status = None
        self.check_website.start()
    
    def cog_unload(self):
        self.check_website.cancel()
    
    async def is_website_online(self):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.website_url, timeout=10) as response:
                    return 200 <= response.status < 400
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return False
        except Exception as e:
            logger.error(f"Error checking website status: {e}")
            return False
    
    @tasks.loop(minutes=1)
    async def check_website(self):
        try:
            is_online = await self.is_website_online()
            
            channel = self.bot.get_channel(self.channel_id)
            if not channel:
                logger.error(f"Channel with ID {self.channel_id} not found")
                return
            
            if self.current_status is None or self.current_status != is_online:
                self.current_status = is_online
                new_name = self.online_name if is_online else self.offline_name
                
                try:
                    await channel.edit(name=new_name)
                    logger.info(f"Updated channel name to {new_name} (Website {'online' if is_online else 'offline'})")
                except discord.Forbidden:
                    logger.error("Bot doesn't have permission to edit channel name")
                except discord.HTTPException as e:
                    logger.error(f"Failed to update channel name: {e}")
        except Exception as e:
            logger.error(f"Error in website monitoring task: {e}")
    
    @check_website.before_loop
    async def before_check_website(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(5)

async def setup(bot):
    await bot.add_cog(WebsiteMonitor(bot))