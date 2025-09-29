import discord
from discord.ext import commands
from discord import app_commands
import json
import asyncio
import os
import time
import logging
from typing import Dict, Optional, List
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TicketConfig:
    def __init__(self, config_path: str = "ticket_config.json"):
        self.config_path = config_path
        self._last_save = time.time()
        self.config = self.load_config()
        
    def load_config(self) -> Dict:
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r", encoding='utf-8') as f:
                    config = json.load(f)
                    return self._validate_config(config)
            else:
                return self._create_default_config()
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load config: {e}")
            if os.path.exists(self.config_path):
                backup_path = f"{self.config_path}.backup.{int(time.time())}"
                os.rename(self.config_path, backup_path)
                logger.info(f"Corrupted config backed up to {backup_path}")
            return self._create_default_config()
    
    def _validate_config(self, config: Dict) -> Dict:
        default = self._create_default_config()
        
        for key in default:
            if key not in config:
                config[key] = default[key]
                
        if not isinstance(config.get("ticket_panels"), dict):
            config["ticket_panels"] = {}
        if not isinstance(config.get("active_tickets"), dict):
            config["active_tickets"] = {}
        if not isinstance(config.get("statistics"), dict):
            config["statistics"] = default["statistics"]
        else:
            for stat_key in default["statistics"]:
                if stat_key not in config["statistics"]:
                    config["statistics"][stat_key] = default["statistics"][stat_key]
        if not isinstance(config.get("user_cooldowns"), dict):
            config["user_cooldowns"] = {}
        if not isinstance(config.get("settings"), dict):
            config["settings"] = default["settings"]
        else:
            for setting_key in default["settings"]:
                if setting_key not in config["settings"]:
                    config["settings"][setting_key] = default["settings"][setting_key]
            
        return config
    
    def _create_default_config(self) -> Dict:
        config = {
            "ticket_panels": {},
            "active_tickets": {},
            "user_cooldowns": {},
            "statistics": {
                "total_tickets": 0,
                "tickets_closed": 0,
                "average_response_time": 0
            },
            "settings": {
                "max_tickets_per_user": 3,
                "ticket_cooldown": 300,
                "auto_close_inactive": 86400,
                "transcript_enabled": True,
                "dm_notifications": True
            }
        }
        self.save_config(config)
        return config
    
    def save_config(self, config: Optional[Dict] = None) -> bool:
        try:
            current_time = time.time()
            if current_time - self._last_save < 1:
                return False
                
            config_to_save = config or self.config
            
            if os.path.exists(self.config_path):
                backup_path = f"{self.config_path}.bak"
                with open(self.config_path, "r", encoding='utf-8') as src:
                    with open(backup_path, "w", encoding='utf-8') as dst:
                        dst.write(src.read())
            
            with open(self.config_path, "w", encoding='utf-8') as f:
                json.dump(config_to_save, f, indent=4, ensure_ascii=False)
            
            self._last_save = current_time
            return True
            
        except IOError as e:
            logger.error(f"Failed to save config: {e}")
            return False

class RateLimiter:
    def __init__(self):
        self.user_attempts: Dict[int, List[float]] = {}
        self.global_attempts: List[float] = []
        
    def is_rate_limited(self, user_id: int, max_per_user: int = 3, window: int = 300, 
                       global_max: int = 50, global_window: int = 60) -> tuple[bool, int]:
        current_time = time.time()
        
        self._cleanup_old_attempts(current_time, window, global_window)
        
        user_attempts = self.user_attempts.get(user_id, [])
        if len(user_attempts) >= max_per_user:
            oldest_attempt = min(user_attempts)
            time_until_reset = int(oldest_attempt + window - current_time)
            return True, time_until_reset
        
        if len(self.global_attempts) >= global_max:
            oldest_global = min(self.global_attempts)
            time_until_reset = int(oldest_global + global_window - current_time)
            return True, time_until_reset
            
        return False, 0
    
    def add_attempt(self, user_id: int):
        current_time = time.time()
        
        if user_id not in self.user_attempts:
            self.user_attempts[user_id] = []
        
        self.user_attempts[user_id].append(current_time)
        self.global_attempts.append(current_time)
    
    def _cleanup_old_attempts(self, current_time: float, user_window: int, global_window: int):
        for user_id in list(self.user_attempts.keys()):
            self.user_attempts[user_id] = [
                attempt for attempt in self.user_attempts[user_id]
                if current_time - attempt < user_window
            ]
            if not self.user_attempts[user_id]:
                del self.user_attempts[user_id]
        
        self.global_attempts = [
            attempt for attempt in self.global_attempts
            if current_time - attempt < global_window
        ]

class TicketButton(discord.ui.View):
    def __init__(self, rate_limiter: RateLimiter):
        super().__init__(timeout=None)
        self.rate_limiter = rate_limiter
        
    @discord.ui.button(
        label="🎫 Create Ticket", 
        style=discord.ButtonStyle.primary, 
        emoji="🎫", 
        custom_id="ticket_button"
    )
    async def ticket_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer(ephemeral=True)
            
            ticket_system = interaction.client.get_cog("TicketSystem")
            if not ticket_system:
                await interaction.followup.send(
                    "❌ Ticket system is currently unavailable. Please try again later.",
                    ephemeral=True
                )
                return
            
            is_limited, time_left = self.rate_limiter.is_rate_limited(interaction.user.id)
            if is_limited:
                embed = discord.Embed(
                    title="⏰ Rate Limited",
                    description=f"Please wait **{time_left}** seconds before creating another ticket.",
                    color=discord.Color.orange()
                )
                embed.set_footer(text="This helps prevent spam and ensures quality support.")
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            success = await ticket_system.create_ticket(interaction)
            if success:
                self.rate_limiter.add_attempt(interaction.user.id)
                
        except Exception as e:
            logger.error(f"Error in ticket button: {e}")
            try:
                await interaction.followup.send(
                    "❌ An unexpected error occurred. Please try again later.",
                    ephemeral=True
                )
            except:
                pass

class TicketControls(discord.ui.View):
    def __init__(self, ticket_id: str):
        super().__init__(timeout=None)
        self.ticket_id = ticket_id
        
    @discord.ui.button(
        label="✋ Claim Ticket", 
        style=discord.ButtonStyle.green, 
        emoji="✋", 
        custom_id="claim_button"
    )
    async def claim_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            ticket_system = interaction.client.get_cog("TicketSystem")
            if not ticket_system:
                await interaction.response.send_message(
                    "❌ Ticket system unavailable.", ephemeral=True
                )
                return
            
            if not (interaction.user.guild_permissions.manage_channels or 
                   interaction.user.guild_permissions.administrator):
                embed = discord.Embed(
                    title="❌ Insufficient Permissions",
                    description="You need `Manage Channels` permission to claim tickets.",
                    color=discord.Color.red()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            ticket_data = ticket_system.config.config["active_tickets"].get(str(interaction.channel.id))
            if not ticket_data:
                await interaction.response.send_message(
                    "❌ This channel is not a valid ticket.", ephemeral=True
                )
                return
            
            if ticket_data.get("claimed_by"):
                claimer = interaction.guild.get_member(ticket_data["claimed_by"])
                claimer_name = claimer.display_name if claimer else "Unknown User"
                
                embed = discord.Embed(
                    title="⚠️ Already Claimed",
                    description=f"This ticket is already claimed by **{claimer_name}**.",
                    color=discord.Color.orange()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            ticket_data["claimed_by"] = interaction.user.id
            ticket_data["claimed_at"] = time.time()
            ticket_system.config.save_config()
            
            embed = discord.Embed(
                title="✅ Ticket Claimed Successfully",
                description=f"This ticket is now being handled by {interaction.user.mention}",
                color=discord.Color.green()
            )
            embed.add_field(
                name="📋 Next Steps", 
                value="• Review the user's issue\n• Provide assistance\n• Close when resolved", 
                inline=False
            )
            embed.set_footer(text=f"Claimed by {interaction.user.display_name}")
            embed.timestamp = datetime.utcnow()
            
            self.children[0].disabled = True
            self.children[0].label = f"Claimed by {interaction.user.display_name}"
            self.children[1].disabled = False
            
            await interaction.response.send_message(embed=embed)
            await interaction.edit_original_response(view=self)
            
            logger.info(f"Ticket {self.ticket_id} claimed by {interaction.user.id}")
            
        except Exception as e:
            logger.error(f"Error claiming ticket: {e}")
            await interaction.response.send_message(
                "❌ An error occurred while claiming the ticket.", ephemeral=True
            )

    @discord.ui.button(
        label="🔒 Close Ticket", 
        style=discord.ButtonStyle.danger, 
        emoji="🔒", 
        custom_id="close_button"
    )
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            ticket_system = interaction.client.get_cog("TicketSystem")
            if not ticket_system:
                await interaction.response.send_message(
                    "❌ Ticket system unavailable.", ephemeral=True
                )
                return
            
            ticket_data = ticket_system.config.config["active_tickets"].get(str(interaction.channel.id))
            if not ticket_data:
                await interaction.response.send_message(
                    "❌ This channel is not a valid ticket.", ephemeral=True
                )
                return
            
            user_id = interaction.user.id
            ticket_owner = ticket_data.get("user_id")
            claimed_by = ticket_data.get("claimed_by")
            has_permissions = (
                user_id == ticket_owner or 
                user_id == claimed_by or
                interaction.user.guild_permissions.manage_channels or
                interaction.user.guild_permissions.administrator
            )
            
            if not has_permissions:
                embed = discord.Embed(
                    title="❌ Cannot Close Ticket",
                    description="Only the ticket owner, assigned staff, or administrators can close this ticket.",
                    color=discord.Color.red()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            confirm_view = TicketCloseConfirmation(ticket_data, ticket_system)
            
            embed = discord.Embed(
                title="⚠️ Confirm Ticket Closure",
                description="Are you sure you want to close this ticket?",
                color=discord.Color.orange()
            )
            embed.add_field(
                name="📋 What happens next:",
                value="• Transcript will be sent to the user\n• Channel will be deleted\n• Ticket data will be archived",
                inline=False
            )
            embed.set_footer(text="This action cannot be undone.")
            
            await interaction.response.send_message(embed=embed, view=confirm_view, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error in close button: {e}")
            await interaction.response.send_message(
                "❌ An error occurred while processing the close request.", ephemeral=True
            )

class TicketCloseConfirmation(discord.ui.View):
    def __init__(self, ticket_data: Dict, ticket_system):
        super().__init__(timeout=30)
        self.ticket_data = ticket_data
        self.ticket_system = ticket_system
    
    @discord.ui.button(label="✅ Confirm Close", style=discord.ButtonStyle.danger)
    async def confirm_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer()
            
            user = interaction.guild.get_member(self.ticket_data["user_id"])
            claimed_by = None
            if self.ticket_data.get("claimed_by"):
                claimed_by = interaction.guild.get_member(self.ticket_data["claimed_by"])
            
            if user and self.ticket_system.config.config["settings"]["transcript_enabled"]:
                await self._send_transcript(interaction, user, claimed_by)
            
            try:
                if "statistics" not in self.ticket_system.config.config:
                    self.ticket_system.config.config["statistics"] = {
                        "total_tickets": 0,
                        "tickets_closed": 0,
                        "average_response_time": 0
                    }
                
                if "tickets_closed" not in self.ticket_system.config.config["statistics"]:
                    self.ticket_system.config.config["statistics"]["tickets_closed"] = 0
                
                self.ticket_system.config.config["statistics"]["tickets_closed"] += 1
            except Exception as e:
                logger.error(f"Error updating statistics: {e}")
            
            embed = discord.Embed(
                title="🔒 Closing Ticket",
                description="This ticket will be closed in **5 seconds**...",
                color=discord.Color.yellow()
            )
            embed.add_field(
                name="📊 Feedback", 
                value="Thank you for using our support system!", 
                inline=False
            )
            embed.set_footer(text="We hope your issue was resolved successfully.")
            
            await interaction.followup.send(embed=embed)
            
            await asyncio.sleep(5)
            
            audit_logger = interaction.client.get_cog("AuditLogger")
            if audit_logger and user:
                audit_logger.log_ticket_closed(user, interaction.channel, f"Ticket geschlossen von {interaction.user.display_name}")
            
            channel_id = str(interaction.channel.id)
            if channel_id in self.ticket_system.config.config["active_tickets"]:
                del self.ticket_system.config.config["active_tickets"][channel_id]
            
            self.ticket_system.config.save_config()
            
            await interaction.channel.delete(reason=f"Ticket closed by {interaction.user}")
            
            logger.info(f"Ticket {channel_id} closed by {interaction.user.id}")
            
        except Exception as e:
            logger.error(f"Error closing ticket: {e}")
            try:
                await interaction.followup.send("❌ Error occurred while closing ticket.")
            except:
                pass
    
    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="✅ Closure Cancelled",
            description="The ticket will remain open.",
            color=discord.Color.green()
        )
        await interaction.response.edit_message(embed=embed, view=None)
    
    async def _send_transcript(self, interaction: discord.Interaction, user: discord.Member, claimed_by: Optional[discord.Member]):
        try:
            created_at = self.ticket_data.get('created_at', time.time())
            closed_at = time.time()
            
            transcript = discord.Embed(
                title="🎫 Ticket Transcript",
                description="Your support ticket has been closed.",
                color=discord.Color.blue()
            )
            
            transcript.add_field(
                name="📋 Ticket Information",
                value=f"**Server:** {interaction.guild.name}\n"
                      f"**Channel:** #{interaction.channel.name}\n"
                      f"**Closed by:** {interaction.user.display_name}\n"
                      f"**Created:** <t:{int(created_at)}:R>\n"
                      f"**Closed:** <t:{int(closed_at)}:R>\n"
                      f"**Handled by:** {claimed_by.display_name if claimed_by else 'Not claimed'}",
                inline=False
            )
            
            transcript.add_field(
                name="💬 Support Feedback",
                value="We hope your issue was resolved satisfactorily. "
                      "If you need further assistance, feel free to create a new ticket.",
                inline=False
            )
            
            transcript.set_footer(
                text=f"Ticket ID: {interaction.channel.id} • {interaction.guild.name}",
                icon_url=interaction.guild.icon.url if interaction.guild.icon else None
            )
            transcript.timestamp = datetime.utcnow()
            
            await user.send(embed=transcript)
            
        except discord.Forbidden:
            logger.warning(f"Could not send transcript to user {user.id} - DMs disabled")
        except Exception as e:
            logger.error(f"Error sending transcript: {e}")

class TicketSystem(commands.Cog):
    """Enhanced ticket system with improved stability and features"""
    
    def __init__(self, bot):
        self.bot = bot
        self.config = TicketConfig()
        self.rate_limiter = RateLimiter()
        self._setup_task = None
        
        asyncio.create_task(self.setup_persistent_views())
    
    async def setup_persistent_views(self):
        try:
            await self.bot.wait_until_ready()
            
            for panel_id in self.config.config["ticket_panels"]:
                try:
                    view = TicketButton(self.rate_limiter)
                    self.bot.add_view(view, message_id=int(panel_id))
                except ValueError:
                    logger.warning(f"Invalid panel ID: {panel_id}")
                    continue
            
            for ticket_id in self.config.config["active_tickets"]:
                try:
                    view = TicketControls(ticket_id)
                    self.bot.add_view(view)
                except Exception as e:
                    logger.warning(f"Failed to add controls for ticket {ticket_id}: {e}")
                    continue
            
            logger.info(f"Setup {len(self.config.config['ticket_panels'])} ticket panels and {len(self.config.config['active_tickets'])} active tickets")
            
        except Exception as e:
            logger.error(f"Error setting up persistent views: {e}")

    @app_commands.command(name="ticketpanel")
    @app_commands.describe(
        channel="Channel where to create the panel",
        category="Category for new tickets",
        title="Title of the ticket panel",
        description="Description text for the ticket panel"
    )
    @app_commands.default_permissions(administrator=True)
    async def ticketpanel(
        self, 
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        category: discord.CategoryChannel,
        title: str = "🎫 Support Tickets",
        description: str = "Need help? Click the button below to create a support ticket!"
    ):
        try:
            if not hasattr(self.bot, 'is_authorized') or not self.bot.is_authorized(interaction.user.id):
                if not interaction.user.guild_permissions.administrator:
                    embed = discord.Embed(
                        title="❌ Access Denied",
                        description="You need administrator permissions to create ticket panels.",
                        color=discord.Color.red()
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return
            
            if not channel.permissions_for(interaction.guild.me).send_messages:
                await interaction.response.send_message(
                    "❌ I don't have permission to send messages in that channel.", 
                    ephemeral=True
                )
                return
            
            if not category.permissions_for(interaction.guild.me).manage_channels:
                await interaction.response.send_message(
                    "❌ I don't have permission to create channels in that category.", 
                    ephemeral=True
                )
                return
            
            embed = discord.Embed(
                title=title,
                description=description,
                color=discord.Color.blue()
            )
            
            embed.add_field(
                name="📋 How it works:",
                value="• Click the button below\n• Describe your issue\n• Wait for staff assistance\n• Your ticket will be handled promptly",
                inline=False
            )
            
            embed.add_field(
                name="⚡ Response Time:",
                value="We typically respond within **15 minutes** during business hours.",
                inline=True
            )
            
            embed.add_field(
                name="🔒 Privacy:",
                value="Only you and staff can see your ticket.",
                inline=True
            )
            
            embed.set_footer(
                text=f"Ticket System • {interaction.guild.name}",
                icon_url=interaction.guild.icon.url if interaction.guild.icon else None
            )
            embed.timestamp = datetime.utcnow()
            
            view = TicketButton(self.rate_limiter)
            msg = await channel.send(embed=embed, view=view)
            
            self.config.config["ticket_panels"][str(msg.id)] = {
                "channel_id": str(channel.id),
                "category_id": str(category.id),
                "created_by": interaction.user.id,
                "created_at": time.time()
            }
            self.config.save_config()
            
            success_embed = discord.Embed(
                title="✅ Ticket Panel Created",
                description=f"Successfully created ticket panel in {channel.mention}",
                color=discord.Color.green()
            )
            success_embed.add_field(
                name="📊 Panel Info:",
                value=f"**Channel:** {channel.mention}\n**Category:** {category.name}\n**Message ID:** {msg.id}",
                inline=False
            )
            
            await interaction.response.send_message(embed=success_embed, ephemeral=True)
            logger.info(f"Ticket panel created by {interaction.user.id} in {channel.id}")
            
        except Exception as e:
            logger.error(f"Error creating ticket panel: {e}")
            await interaction.response.send_message(
                "❌ An error occurred while creating the ticket panel.", 
                ephemeral=True
            )

    async def create_ticket(self, interaction: discord.Interaction) -> bool:
        try:
            panel_data = self.config.config["ticket_panels"].get(str(interaction.message.id))
            if not panel_data:
                await interaction.followup.send(
                    "❌ Invalid ticket panel. Please contact an administrator.", 
                    ephemeral=True
                )
                return False
            
            category = self.bot.get_channel(int(panel_data["category_id"]))
            if not category:
                await interaction.followup.send(
                    "❌ Ticket category no longer exists. Please contact an administrator.", 
                    ephemeral=True
                )
                return False
            
            user = interaction.user
            
            user_tickets = [
                ticket for ticket in self.config.config["active_tickets"].values()
                if ticket["user_id"] == user.id
            ]
            
            max_tickets = self.config.config["settings"]["max_tickets_per_user"]
            if len(user_tickets) >= max_tickets:
                embed = discord.Embed(
                    title="⚠️ Ticket Limit Reached",
                    description=f"You already have **{len(user_tickets)}** open ticket(s). "
                               f"Please close existing tickets before creating new ones.",
                    color=discord.Color.orange()
                )
                
                if user_tickets:
                    ticket_list = []
                    for ticket in user_tickets[:3]:
                        channel = self.bot.get_channel(ticket["channel_id"])
                        if channel:
                            ticket_list.append(f"• {channel.mention}")
                    
                    if ticket_list:
                        embed.add_field(
                            name="📋 Your Open Tickets:",
                            value="\n".join(ticket_list),
                            inline=False
                        )
                
                await interaction.followup.send(embed=embed, ephemeral=True)
                return False
            
            if not category.permissions_for(interaction.guild.me).manage_channels:
                await interaction.followup.send(
                    "❌ I don't have permission to create channels in the ticket category.", 
                    ephemeral=True
                )
                return False
            
            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(
                    read_messages=False,
                    send_messages=False
                ),
                user: discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True,
                    attach_files=True,
                    embed_links=True,
                    read_message_history=True
                ),
                interaction.guild.me: discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True,
                    manage_messages=True,
                    attach_files=True,
                    embed_links=True,
                    read_message_history=True
                )
            }
            
            for role in interaction.guild.roles:
                if role.permissions.manage_channels or role.permissions.administrator:
                    overwrites[role] = discord.PermissionOverwrite(
                        read_messages=True,
                        send_messages=True,
                        manage_messages=True
                    )
            
            channel_name = f"ticket-{user.display_name}".lower().replace(" ", "-")[:50]
            ticket_channel = await category.create_text_channel(
                channel_name,
                overwrites=overwrites,
                topic=f"Support ticket for {user.display_name} (ID: {user.id})"
            )
            
            embed = discord.Embed(
                title="🎫 Welcome to Your Support Ticket",
                description=f"Hello {user.mention}! Thank you for reaching out to our support team.",
                color=discord.Color.green()
            )
            
            embed.add_field(
                name="📝 Please describe your issue:",
                value="• Be as detailed as possible\n• Include any error messages\n• Mention what you were trying to do\n• Add screenshots if helpful",
                inline=False
            )
            
            embed.add_field(
                name="⏱️ What happens next:",
                value="• A staff member will claim your ticket\n• They will assist you with your issue\n• The ticket will be closed when resolved",
                inline=False
            )
            
            embed.add_field(
                name="🔔 Important:",
                value="Please stay patient and avoid pinging staff members directly.",
                inline=False
            )
            
            embed.set_thumbnail(url=user.display_avatar.url)
            embed.set_footer(
                text=f"Ticket created • {interaction.guild.name}",
                icon_url=interaction.guild.icon.url if interaction.guild.icon else None
            )
            embed.timestamp = datetime.utcnow()
            
            controls = TicketControls(str(ticket_channel.id))
            await ticket_channel.send(f"{user.mention}", embed=embed, view=controls)
            
            ticket_data = {
                "user_id": user.id,
                "channel_id": ticket_channel.id,
                "created_at": time.time(),
                "panel_id": str(interaction.message.id),
                "status": "open"
            }
            
            self.config.config["active_tickets"][str(ticket_channel.id)] = ticket_data
            self.config.config["statistics"]["total_tickets"] += 1
            self.config.save_config()
            
            audit_logger = self.bot.get_cog("AuditLogger")
            if audit_logger:
                audit_logger.log_ticket_created(user, ticket_channel, "Ticket erstellt")
            
            success_embed = discord.Embed(
                title="✅ Ticket Created Successfully",
                description=f"Your ticket has been created: {ticket_channel.mention}",
                color=discord.Color.green()
            )
            success_embed.set_footer(text="Please check the ticket channel for further instructions.")
            
            await interaction.followup.send(embed=success_embed, ephemeral=True)
            
            logger.info(f"Ticket created for user {user.id} in channel {ticket_channel.id}")
            return True
            
        except discord.HTTPException as e:
            logger.error(f"Discord HTTP error creating ticket: {e}")
            await interaction.followup.send(
                "❌ Failed to create ticket due to Discord limitations. Please try again later.", 
                ephemeral=True
            )
            return False
        except Exception as e:
            logger.error(f"Unexpected error creating ticket: {e}")
            await interaction.followup.send(
                "❌ An unexpected error occurred while creating your ticket.", 
                ephemeral=True
            )
            return False

    @app_commands.command(name="ticketstats")
    @app_commands.default_permissions(manage_guild=True)
    async def ticket_stats(self, interaction: discord.Interaction):
        """Display ticket system statistics"""
        try:
            stats = self.config.config["statistics"]
            active_tickets = len(self.config.config["active_tickets"])
            panels = len(self.config.config["ticket_panels"])
            
            embed = discord.Embed(
                title="📊 Ticket System Statistics",
                color=discord.Color.blue()
            )
            
            embed.add_field(
                name="📈 Overall Stats",
                value=f"**Total Tickets:** {stats['total_tickets']}\n"
                      f"**Tickets Closed:** {stats['tickets_closed']}\n"
                      f"**Currently Active:** {active_tickets}\n"
                      f"**Ticket Panels:** {panels}",
                inline=False
            )
            
            if active_tickets > 0:
                ticket_list = []
                for ticket_id, ticket_data in list(self.config.config["active_tickets"].items())[:5]:
                    channel = self.bot.get_channel(ticket_data["channel_id"])
                    user = self.bot.get_user(ticket_data["user_id"])
                    if channel and user:
                        claimed = "✅" if ticket_data.get("claimed_by") else "⏳"
                        ticket_list.append(f"{claimed} {channel.mention} - {user.display_name}")
                
                if ticket_list:
                    embed.add_field(
                        name="🎫 Recent Active Tickets",
                        value="\n".join(ticket_list),
                        inline=False
                    )
            
            embed.set_footer(text=f"Statistics for {interaction.guild.name}")
            embed.timestamp = datetime.utcnow()
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error displaying ticket stats: {e}")
            await interaction.response.send_message(
                "❌ Error retrieving ticket statistics.", 
                ephemeral=True
            )

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        """Clean up ticket data when channels are deleted"""
        try:
            channel_id = str(channel.id)
            if channel_id in self.config.config["active_tickets"]:
                del self.config.config["active_tickets"][channel_id]
                self.config.save_config()
                logger.info(f"Cleaned up data for deleted ticket channel {channel_id}")
        except Exception as e:
            logger.error(f"Error cleaning up deleted channel: {e}")

async def setup(bot):
    """Setup function for the cog"""
    await bot.add_cog(TicketSystem(bot))