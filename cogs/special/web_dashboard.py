import discord
from discord.ext import commands
import asyncio
import threading
import sqlite3
import json
import re
import os
from datetime import datetime, timedelta
from flask import Flask, render_template, session, redirect, url_for, request, jsonify
from flask_session import Session
import requests
from functools import wraps

class WebDashboard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.app = None
        self.server_thread = None
        
        # Dashboard Configuration
        self.DISCORD_CLIENT_ID = ''
        self.DISCORD_CLIENT_SECRET = ''
        self.DISCORD_REDIRECT_URI = ''
        self.DISCORD_API_ENDPOINT = ''
        
        self.AUTHORIZED_USERS = [
            'netamitv',
            'n1yshi',
            'hannahhtalea'
        ]
        
        # AutoMod Configuration
        self.AUTO_MOD_CONFIG = {
            "banned_words": [
                "n1gg", "niger", "nigger", "n1gger",
                "NIGGER", "bitch", "bastard",
                "hurensohn", "hure", "fotze", "schlampe",
                "discord.gg/", "discord.com/invite/",
                "steamcommunity.com",
                "discordapp.com/invite"
            ],
            "spam_detection": {
                "max_duplicate_messages": 3,
                "time_window": 5
            },
            "spam_exempt_users": [
                ,
                ,
                ,
                ,
            ]
        }
        
        self.user_message_history = {}
        self.init_database()
        self.setup_flask_app()
        
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
            print("✅ Dashboard database initialized")
        except Exception as e:
            print(f"❌ Dashboard database error: {e}")

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
            print(f"Fehler beim Loggen des Audit Events: {e}")

    def get_banned_word_details(self, content):
        """Get detailed information about which banned words were found"""
        found_words = []
        content_lower = content.lower()
        
        for word in self.AUTO_MOD_CONFIG["banned_words"]:
            if word.lower() in content_lower:
                pattern = re.compile(re.escape(word.lower()), re.IGNORECASE)
                matches = list(pattern.finditer(content))
                
                for match in matches:
                    start = max(0, match.start() - 10)
                    end = min(len(content), match.end() + 10)
                    context = content[start:end]
                    
                    found_words.append({
                        'word': word,
                        'position': match.start(),
                        'context': context,
                        'full_match': match.group()
                    })
        
        return found_words

    def setup_flask_app(self):
        """Setup Flask application"""
        current_dir = os.path.dirname(__file__)
        template_path = os.path.join(current_dir, 'templates')
        
        self.app = Flask(__name__, 
                        template_folder=template_path,
                        static_folder='static')
        self.app.config['SECRET_KEY'] = 'automod-dashboard-secret-key-change-this'
        self.app.config['SESSION_TYPE'] = 'filesystem'
        Session(self.app)
        
        def require_auth(f):
            @wraps(f)
            def decorated_function(*args, **kwargs):
                if 'discord_user' not in session:
                    return redirect(url_for('login'))
                
                discord_user = session['discord_user']
                username = discord_user.get('username', '').lower()
                
                if username not in [user.lower() for user in self.AUTHORIZED_USERS]:
                    return render_template('unauthorized.html', username=username)
                
                return f(*args, **kwargs)
            return decorated_function

        @self.app.route('/')
        def index():
            if 'discord_user' in session:
                return redirect(url_for('dashboard'))
            return render_template('index.html')

        @self.app.route('/login')
        def login():
            discord_login_url = f"{self.DISCORD_API_ENDPOINT}/oauth2/authorize?client_id={self.DISCORD_CLIENT_ID}&redirect_uri={self.DISCORD_REDIRECT_URI}&response_type=code&scope=identify"
            return redirect(discord_login_url)

        @self.app.route('/callback')
        def callback():
            code = request.args.get('code')
            
            if not code:
                return redirect(url_for('index'))
            
            data = {
                'client_id': self.DISCORD_CLIENT_ID,
                'client_secret': self.DISCORD_CLIENT_SECRET,
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': self.DISCORD_REDIRECT_URI
            }
            
            headers = {'Content-Type': 'application/x-www-form-urlencoded'}
            
            response = requests.post(f"{self.DISCORD_API_ENDPOINT}/oauth2/token", data=data, headers=headers)
            
            if response.status_code != 200:
                return redirect(url_for('index'))
            
            token_data = response.json()
            access_token = token_data['access_token']
            
            headers = {'Authorization': f"Bearer {access_token}"}
            user_response = requests.get(f"{self.DISCORD_API_ENDPOINT}/users/@me", headers=headers)
            
            if user_response.status_code != 200:
                return redirect(url_for('index'))
            
            user_data = user_response.json()
            session['discord_user'] = user_data
            
            return redirect(url_for('dashboard'))

        @self.app.route('/dashboard')
        @require_auth
        def dashboard():
            conn = sqlite3.connect('audit_logs.db')
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM audit_logs ORDER BY timestamp DESC LIMIT 50')
            logs = cursor.fetchall()
            conn.close()
            
            log_list = []
            for log in logs:
                log_dict = {
                    'id': log[0], 'timestamp': log[1], 'user_id': log[2],
                    'username': log[3], 'discriminator': log[4], 'action_type': log[5],
                    'reason': log[6], 'message_content': log[7], 'channel_id': log[8],
                    'channel_name': log[9], 'guild_id': log[10], 'details': log[11],
                    'severity': log[12]
                }
                log_list.append(log_dict)
            
            return render_template('dashboard.html', logs=log_list, user=session['discord_user'])

        @self.app.route('/api/logs')
        @require_auth
        def api_logs():
            page = int(request.args.get('page', 1))
            per_page = int(request.args.get('per_page', 25))
            action_type = request.args.get('action_type', '')
            severity = request.args.get('severity', '')
            user_search = request.args.get('user_search', '')
            category = request.args.get('category', 'all')
            
            conn = sqlite3.connect('audit_logs.db')
            cursor = conn.cursor()
            
            query = "SELECT * FROM audit_logs WHERE 1=1"
            params = []
            
            if category == 'bot':
                bot_actions = ['ticket_created', 'ticket_closed', 'temp_channel_created', 'temp_channel_deleted', 'automod_action']
                query += f" AND action_type IN ({','.join(['?' for _ in bot_actions])})"
                params.extend(bot_actions)
            elif category == 'moderation':
                mod_actions = ['user_banned', 'user_kicked', 'user_timeout', 'message_deleted', 'spam_detected', 'word_filter']
                query += f" AND action_type IN ({','.join(['?' for _ in mod_actions])})"
                params.extend(mod_actions)
            elif category == 'server':
                server_actions = ['member_joined', 'member_left', 'role_added', 'role_removed', 'channel_created', 'channel_deleted', 'channel_updated', 'server_updated']
                query += f" AND action_type IN ({','.join(['?' for _ in server_actions])})"
                params.extend(server_actions)
            
            if action_type:
                query += " AND action_type = ?"
                params.append(action_type)
            
            if severity:
                query += " AND severity = ?"
                params.append(severity)
            
            if user_search:
                query += " AND (username LIKE ? OR user_id LIKE ?)"
                params.extend([f"%{user_search}%", f"%{user_search}%"])
            
            query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
            params.extend([per_page, (page - 1) * per_page])
            
            cursor.execute(query, params)
            logs = cursor.fetchall()
            
            count_query = query.replace("SELECT *", "SELECT COUNT(*)").split("ORDER BY")[0]
            cursor.execute(count_query, params[:-2])
            total_count = cursor.fetchone()[0]
            
            conn.close()
            
            log_list = []
            for log in logs:
                log_dict = {
                    'id': log[0], 'timestamp': log[1], 'user_id': log[2],
                    'username': log[3], 'discriminator': log[4], 'action_type': log[5],
                    'reason': log[6], 'message_content': log[7], 'channel_id': log[8],
                    'channel_name': log[9], 'guild_id': log[10], 'details': log[11],
                    'severity': log[12]
                }
                log_list.append(log_dict)
            
            return jsonify({
                'logs': log_list, 'total': total_count, 'page': page,
                'per_page': per_page, 'total_pages': (total_count + per_page - 1) // per_page
            })

        @self.app.route('/logout')
        def logout():
            session.clear()
            return redirect(url_for('index'))

    def start_flask_server(self):
        """Start Flask server in a separate thread"""
        try:
            self.app.run(host='0.0.0.0', port=12902, debug=False, use_reloader=False)
        except Exception as e:
            print(f"❌ Flask server error: {e}")

    @commands.Cog.listener()
    async def on_ready(self):
        """Start the web dashboard when the bot is ready"""
        if self.server_thread is None:
            print("🌐 Starting AutoMod Web Dashboard...")
            self.server_thread = threading.Thread(target=self.start_flask_server, daemon=True)
            self.server_thread.start()
            print(f"✅ Web Dashboard started on http://neko.wisp.uno:12902")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        # Check for banned words
        content = message.content
        banned_word_details = self.get_banned_word_details(content)
        
        if banned_word_details:
            await message.delete()
            
            details_text = f"Gefundene verbotene Wörter: {len(banned_word_details)}\n"
            for detail in banned_word_details:
                details_text += f"- '{detail['word']}' an Position {detail['position']}: '{detail['context']}'\n"
            
            try:
                await message.author.ban(reason="AutoMod: Verwendung verbotener Wörter")
                action_taken = "Benutzer gebannt"
                
                try:
                    await message.author.send("⚠️ Du wurdest wegen der Verwendung verbotener Wörter gebannt.")
                except discord.HTTPException:
                    pass
                    
            except discord.HTTPException:
                action_taken = "Ban fehlgeschlagen - keine Berechtigung"

            self.log_audit_event(
                user_id=message.author.id,
                username=message.author.name,
                discriminator=message.author.discriminator,
                action_type="word_filter",
                reason=f"Verwendung verbotener Wörter - {action_taken}",
                message_content=content,
                channel_id=message.channel.id,
                channel_name=message.channel.name,
                guild_id=message.guild.id if message.guild else None,
                details=details_text,
                severity="high"
            )

            log_channel = discord.utils.get(message.guild.channels, name="mod-logs")
            if log_channel:
                embed = discord.Embed(
                    title="🛡️ AutoMod Action - Wort-Filter",
                    description=f"**Benutzer:** {message.author.mention} ({message.author.name}#{message.author.discriminator})\n"
                               f"**Aktion:** {action_taken}\n"
                               f"**Kanal:** {message.channel.mention}\n"
                               f"**Grund:** Verwendung verbotener Wörter",
                    color=discord.Color.red(),
                    timestamp=datetime.utcnow()
                )
                
                embed.add_field(
                    name="Nachrichteninhalt",
                    value=f"```{content[:1000]}{'...' if len(content) > 1000 else ''}```",
                    inline=False
                )
                
                embed.add_field(
                    name="Gefundene Wörter",
                    value=f"```{details_text[:1000]}{'...' if len(details_text) > 1000 else ''}```",
                    inline=False
                )
                
                await log_channel.send(embed=embed)

        user_id = message.author.id
        
        if user_id in self.AUTO_MOD_CONFIG["spam_exempt_users"]:
            return
            
        current_time = datetime.utcnow()
        
        if user_id not in self.user_message_history:
            self.user_message_history[user_id] = []
            
        self.user_message_history[user_id].append({
            'time': current_time,
            'content': content,
            'channel_id': message.channel.id
        })
        
        self.user_message_history[user_id] = [
            msg for msg in self.user_message_history[user_id]
            if (current_time - msg['time']).seconds <= self.AUTO_MOD_CONFIG["spam_detection"]["time_window"]
        ]
        
        if len(self.user_message_history[user_id]) >= self.AUTO_MOD_CONFIG["spam_detection"]["max_duplicate_messages"]:
            recent_messages = self.user_message_history[user_id][-self.AUTO_MOD_CONFIG["spam_detection"]["max_duplicate_messages"]:]
            
            is_spam = True
            first_content = recent_messages[0]['content'].lower().strip()
            
            for msg in recent_messages[1:]:
                if msg['content'].lower().strip() != first_content:
                    is_spam = False
                    break
            
            if is_spam:
                try:
                    deleted_count = 0
                    async for msg in message.channel.history(limit=50):
                        if msg.author.id == user_id and deleted_count < self.AUTO_MOD_CONFIG["spam_detection"]["max_duplicate_messages"]:
                            await msg.delete()
                            deleted_count += 1
                    
                    await message.author.timeout(
                        discord.utils.utcnow() + timedelta(minutes=5), 
                        reason="AutoMod: Spam-Erkennung"
                    )
                    
                    action_taken = "Benutzer timeout (5 Minuten)"
                    
                    try:
                        await message.author.send("⚠️ Du wurdest wegen Spamming für 5 Minuten stummgeschaltet.")
                    except discord.HTTPException:
                        pass
                        
                except discord.HTTPException:
                    action_taken = "Timeout fehlgeschlagen - keine Berechtigung"

                spam_details = f"Spam-Nachrichten erkannt:\n"
                for i, msg in enumerate(recent_messages):
                    spam_details += f"{i+1}. '{msg['content'][:100]}{'...' if len(msg['content']) > 100 else ''}'\n"
                
                self.log_audit_event(
                    user_id=message.author.id,
                    username=message.author.name,
                    discriminator=message.author.discriminator,
                    action_type="spam_detected",
                    reason=f"Spam-Erkennung - {action_taken}",
                    message_content=content,
                    channel_id=message.channel.id,
                    channel_name=message.channel.name,
                    guild_id=message.guild.id if message.guild else None,
                    details=spam_details,
                    severity="medium"
                )

    @commands.command(name="dashboard_stats")
    @commands.has_permissions(manage_messages=True)
    async def dashboard_stats(self, ctx):
        """Show dashboard statistics"""
        try:
            conn = sqlite3.connect('audit_logs.db')
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM audit_logs WHERE timestamp >= datetime('now', '-24 hours')")
            last_24h = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM audit_logs WHERE timestamp >= datetime('now', '-7 days')")
            last_7d = cursor.fetchone()[0]
            
            cursor.execute("SELECT action_type, COUNT(*) FROM audit_logs GROUP BY action_type")
            action_stats = cursor.fetchall()
            
            conn.close()
            
            embed = discord.Embed(
                title="📊 AutoMod Dashboard Statistiken",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(name="Letzte 24 Stunden", value=str(last_24h), inline=True)
            embed.add_field(name="Letzte 7 Tage", value=str(last_7d), inline=True)
            embed.add_field(name="Web Dashboard", value="[Hier klicken]()", inline=True)
            
            if action_stats:
                stats_text = "\n".join([f"{action}: {count}" for action, count in action_stats])
                embed.add_field(name="Aktionen nach Typ", value=f"```{stats_text}```", inline=False)
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"Fehler beim Abrufen der Statistiken: {e}")

async def setup(bot):
    await bot.add_cog(WebDashboard(bot))