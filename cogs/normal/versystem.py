import discord
from discord.ext import commands
from discord import app_commands
import json
import os

class VerifyButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="✅ Verifizieren",
            style=discord.ButtonStyle.green,
            custom_id="verify_button"
        )
        
    async def callback(self, interaction: discord.Interaction):
        try:
            config_file = 'data/verify_config.json'
            if os.path.exists(config_file):
                with open(config_file, 'r') as f:
                    config = json.load(f)
                    
                role_id = config.get('role_id')
                if role_id:
                    role = interaction.guild.get_role(role_id)
                    if role:
                        await interaction.user.add_roles(role)
                        await interaction.response.send_message(
                            f"✅ Du wurdest erfolgreich verifiziert und hast die Rolle {role.mention} erhalten!", 
                            ephemeral=True
                        )
                        return
                        
            await interaction.response.send_message(
                "❌ Es ist ein Fehler aufgetreten. Bitte kontaktiere einen Administrator.",
                ephemeral=True
            )
            
        except Exception as e:
            await interaction.response.send_message(
                "❌ Es ist ein Fehler aufgetreten. Bitte kontaktiere einen Administrator.",
                ephemeral=True
            )

class VerifyModal(discord.ui.Modal, title="Verify System erstellen"):
    def __init__(self):
        super().__init__()
        self.title_input = discord.ui.TextInput(
            label="Titel",
            placeholder="Willkommen auf unserem Server!",
            style=discord.TextStyle.short,
            required=True
        )
        self.description_input = discord.ui.TextInput(
            label="Beschreibung",
            placeholder="Klicke auf den Button um dich zu verifizieren...",
            style=discord.TextStyle.paragraph,
            required=True
        )
        self.role_id_input = discord.ui.TextInput(
            label="Rollen ID",
            placeholder="Die ID der Rolle die vergeben werden soll",
            style=discord.TextStyle.short,
            required=True
        )
        self.color_input = discord.ui.TextInput(
            label="Embed Farbe (optional)",
            placeholder="#00ff00 oder leer lassen für Standard-Blau",
            style=discord.TextStyle.short,
            required=False
        )

        self.add_item(self.title_input)
        self.add_item(self.description_input)
        self.add_item(self.role_id_input)
        self.add_item(self.color_input)

    async def on_submit(self, interaction: discord.Interaction):
        # Validiere Rollen ID
        try:
            role_id = int(self.role_id_input.value)
            role = interaction.guild.get_role(role_id)
            if not role:
                await interaction.response.send_message("❌ Rolle nicht gefunden!", ephemeral=True)
                return
        except ValueError:
            await interaction.response.send_message("❌ Ungültige Rollen ID!", ephemeral=True)
            return

        # Parse Farbe
        color = discord.Color.blue()
        if self.color_input.value:
            try:
                color_value = self.color_input.value
                if color_value.startswith('#'):
                    color = discord.Color(int(color_value[1:], 16))
                else:
                    color = discord.Color(int(color_value, 16))
            except:
                await interaction.response.send_message("❌ Ungültiges Farbformat! Nutze #RRGGBB", ephemeral=True)
                return

        # Erstelle Embed
        embed = discord.Embed(
            title=self.title_input.value,
            description=self.description_input.value,
            color=color
        )
        embed.add_field(
            name="📝 Rolle",
            value=f"Du erhältst: {role.mention}",
            inline=False
        )

        # Erstelle View mit Button
        view = discord.ui.View(timeout=None)
        view.add_item(VerifyButton())

        # Sende Embed
        verify_msg = await interaction.channel.send(embed=embed, view=view)

        # Speichere Konfiguration
        cog = interaction.client.get_cog("VerifySystem")
        cog.config['role_id'] = role_id
        cog.config['message_id'] = verify_msg.id
        cog.config['channel_id'] = interaction.channel.id
        cog.save_config()

        await interaction.response.send_message("✅ Verify-System wurde eingerichtet!", ephemeral=True)

class VerifySystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config_file = 'data/verify_config.json'
        
        # Erstelle data Ordner falls nicht vorhanden
        if not os.path.exists('data'):
            os.makedirs('data')
            
        # Lade oder erstelle Konfig
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r') as f:
                self.config = json.load(f)
        else:
            self.config = {
                'role_id': None,
                'message_id': None,
                'channel_id': None
            }
            self.save_config()

    def save_config(self):
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, indent=4)

    @app_commands.command(name="verify", description="Erstelle ein Verifizierungs-System")
    async def verify(self, interaction: discord.Interaction):
        """Create verify system with modal input"""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Du hast keine Berechtigung für diesen Befehl!", ephemeral=True)
            return

        modal = VerifyModal()
        await interaction.response.send_modal(modal)

    # Event Listener für Button Interaktionen von vorherigen Embeds
    @commands.Cog.listener()
    async def on_ready(self):
        # Registriere View für bestehende Buttons
        if self.config['message_id']:
            view = discord.ui.View(timeout=None)
            view.add_item(VerifyButton())
            self.bot.add_view(view)

async def setup(bot):
    await bot.add_cog(VerifySystem(bot))

