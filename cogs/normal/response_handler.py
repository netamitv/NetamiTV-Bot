import discord
import asyncio
import logging
from discord.ext import commands
from discord.ext.commands import Cog

class ResponseHandler(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.success_icon = "https://cdn.discordapp.com/attachments/1323346647794712586/1339243104427053117/success.png"
        self.error_icon = "https://cdn.discordapp.com/attachments/1323346647794712586/1339243104154161163/failed.png"
        self.logger = logging.getLogger(__name__)

    async def safe_send(self, ctx, embed=None, content=None, max_retries=5):
        retry_attempts = 0
        delay = 1

        while retry_attempts < max_retries:
            try:
                if embed:
                    return await ctx.send(embed=embed)
                else:
                    return await ctx.send(content=content)
            except discord.HTTPException as e:
                if e.status == 429:
                    self.logger.warning(f"Rate limited, waiting {delay} seconds")
                    await asyncio.sleep(delay)
                    retry_attempts += 1
                    delay *= 2
                else:
                    self.logger.error(f"HTTP Exception: {e}")
                    raise e
            except Exception as e:
                self.logger.error(f"Unexpected error: {e}")
                raise e

        await asyncio.sleep(10)
        try:
            if embed:
                return await ctx.send(embed=embed)
            else:
                return await ctx.send(content=content)
        except Exception as e:
            self.logger.error(f"Final send attempt failed: {e}")
            return None

    async def safe_edit(self, message, embed=None, content=None, max_retries=5):
        retry_attempts = 0
        delay = 1

        while retry_attempts < max_retries:
            try:
                if embed:
                    return await message.edit(embed=embed)
                else:
                    return await message.edit(content=content)
            except discord.HTTPException as e:
                if e.status == 429:
                    self.logger.warning(f"Rate limited during edit, waiting {delay} seconds")
                    await asyncio.sleep(delay)
                    retry_attempts += 1
                    delay *= 2
                else:
                    self.logger.error(f"HTTP Exception during edit: {e}")
                    raise e
            except Exception as e:
                self.logger.error(f"Unexpected error during edit: {e}")
                raise e

        await asyncio.sleep(10)
        try:
            if embed:
                return await message.edit(embed=embed)
            else:
                return await message.edit(content=content)
        except Exception as e:
            self.logger.error(f"Final edit attempt failed: {e}")
            return None

    async def handle_command_response(self, ctx, content):
        loading_embed = discord.Embed(
            title="⏳ Processing",
            description=f"👁️ {content}",
            color=0x3498db
        )
        message = await self.safe_send(ctx, embed=loading_embed)
        
        if not message:
            message = await self.safe_send(ctx, content=f"⏳ Processing: {content}")
            if not message:
                try:
                    message = await ctx.send(f"⏳ Processing: {content}")
                except:
                    return

        await asyncio.sleep(1)

        success_embed = discord.Embed(
            title="✅ Response",
            description=f"👁️ {content}",
            color=0x2ecc71
        )
        success_embed.set_thumbnail(url=self.success_icon)
        
        edit_result = await self.safe_edit(message, embed=success_embed)
        
        if not edit_result:
            await self.safe_edit(message, content=f"✅ Response: {content}")

    @Cog.listener()
    async def on_command(self, ctx):
        self.bot._old_send = ctx.send
        ctx.send = lambda content: self.handle_command_response(ctx, content)

    @Cog.listener()
    async def on_command(self, ctx):
        self.bot._old_send = ctx.send
        ctx.send = lambda content: self.handle_command_response(ctx, content)

    @Cog.listener()
    async def on_command_completion(self, ctx):
        if hasattr(self.bot, '_old_send'):
            ctx.send = self.bot._old_send

async def setup(bot):
    await bot.add_cog(ResponseHandler(bot))