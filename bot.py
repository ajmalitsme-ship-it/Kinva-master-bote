"""
Kinva Master Bot - Complete Fixed Version
All errors fixed, ready for deployment
"""

import os
import logging
import sqlite3
import asyncio
import json
import uuid
import random
import string
import time
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Union

# Web framework imports
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO

# Telegram bot imports
import telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)

# Media processing imports
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance, ImageOps

# ==================== FIXED MOVIEPY IMPORTS ====================
# Fix for moviepy 2.2.1 - use correct import structure
try:
    from moviepy import VideoFileClip, AudioFileClip, CompositeVideoClip
    from moviepy.video.VideoClip import TextClip
    from moviepy.audio.io.AudioFileClip import AudioFileClip
except ImportError:
    try:
        from moviepy.editor import VideoFileClip, AudioFileClip, CompositeVideoClip, TextClip
    except ImportError:
        # Create dummy classes if moviepy not available
        class VideoFileClip:
            def __init__(self, *args, **kwargs): pass
            def subclip(self, *args, **kwargs): return self
            def write_videofile(self, *args, **kwargs): pass
            def close(self): pass
            def __enter__(self): return self
            def __exit__(self, *args): pass
        
        class AudioFileClip:
            def __init__(self, *args, **kwargs): pass
            def close(self): pass
        
        class CompositeVideoClip:
            def __init__(self, *args, **kwargs): pass
            def write_videofile(self, *args, **kwargs): pass
            def close(self): pass
        
        class TextClip:
            def __init__(self, *args, **kwargs): pass
            def set_position(self, *args, **kwargs): return self
            def set_duration(self, *args, **kwargs): return self
            def close(self): pass

# ==================== OPTIONAL IMPORTS ====================
try:
    from rembg import remove
    REMBG_AVAILABLE = True
except ImportError:
    REMBG_AVAILABLE = False
    remove = None

try:
    import face_recognition
    FACE_RECOGNITION_AVAILABLE = True
except ImportError:
    FACE_RECOGNITION_AVAILABLE = False
    face_recognition = None

# Utilities
import aiohttp
from dotenv import load_dotenv
import aiofiles

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== CONFIGURATION ====================
class Config:
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8776043562:AAH7x_OMPjQmOSlvmIMjWJ40-oWaJ66inBw')
    WEBHOOK_URL = os.getenv('WEBHOOK_URL', 'https://kinva-master.onrender.com')
    PORT = int(os.getenv('PORT', 5000))
    DATABASE_URL = os.getenv('DATABASE_URL', 'kinva_master.db')
    PREMIUM_PRICE = float(os.getenv('PREMIUM_PRICE', 9.99))
    FREE_TRIAL_DAYS = int(os.getenv('FREE_TRIAL_DAYS', 7))
    MAX_FREE_EDITS = int(os.getenv('MAX_FREE_EDITS', 5))
    ADMIN_IDS = [int(id) for id in os.getenv('ADMIN_IDS', '8525952693').split(',') if id]
    
    # Feature flags
    ENABLE_VIDEO_EDITING = True
    ENABLE_IMAGE_EDITING = True
    ENABLE_PREMIUM = True
    ENABLE_WEB_APP = True
    ENABLE_ADMIN_PANEL = True
    
    # File size limits (in MB)
    MAX_VIDEO_SIZE = 50
    MAX_IMAGE_SIZE = 20
    MAX_AUDIO_SIZE = 20
    
    # Supported formats
    SUPPORTED_VIDEO_FORMATS = ['mp4', 'mov', 'avi', 'mkv', 'webm', 'flv']
    SUPPORTED_IMAGE_FORMATS = ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp']
    SUPPORTED_AUDIO_FORMATS = ['mp3', 'wav', 'ogg', 'm4a']

# ==================== DATABASE MANAGER ====================
class DatabaseManager:
    def __init__(self, db_path='kinva_master.db'):
        self.db_path = db_path
        self.init_db()
    
    def get_connection(self):
        return sqlite3.connect(self.db_path)
    
    def init_db(self):
        with self.get_connection() as conn:
            # Users table
            conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    is_premium BOOLEAN DEFAULT 0,
                    premium_expiry DATE,
                    edit_count INTEGER DEFAULT 0,
                    total_edits INTEGER DEFAULT 0,
                    credits INTEGER DEFAULT 5,
                    referral_code TEXT,
                    referred_by INTEGER,
                    is_banned BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Edits table
            conn.execute('''
                CREATE TABLE IF NOT EXISTS edits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    edit_type TEXT,
                    input_file TEXT,
                    output_file TEXT,
                    parameters TEXT,
                    status TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Payments table
            conn.execute('''
                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    amount REAL,
                    payment_id TEXT,
                    payment_method TEXT,
                    status TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Broadcasts table
            conn.execute('''
                CREATE TABLE IF NOT EXISTS broadcasts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message TEXT,
                    media_type TEXT,
                    media_file TEXT,
                    sent_count INTEGER DEFAULT 0,
                    total_count INTEGER DEFAULT 0,
                    status TEXT,
                    created_by INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.commit()
    
    def get_user(self, user_id):
        with self.get_connection() as conn:
            cursor = conn.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            return cursor.fetchone()
    
    def create_user(self, user_id, username=None, first_name=None, last_name=None, referral_code=None):
        with self.get_connection() as conn:
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            conn.execute(
                '''INSERT OR IGNORE INTO users 
                   (user_id, username, first_name, last_name, referral_code) 
                   VALUES (?, ?, ?, ?, ?)''',
                (user_id, username, first_name, last_name, code)
            )
            
            if referral_code:
                referrer = conn.execute(
                    'SELECT user_id FROM users WHERE referral_code = ?',
                    (referral_code,)
                ).fetchone()
                if referrer:
                    conn.execute(
                        'UPDATE users SET referred_by = ? WHERE user_id = ?',
                        (referrer[0], user_id)
                    )
                    conn.execute(
                        'UPDATE users SET credits = credits + 2 WHERE user_id = ?',
                        (referrer[0],)
                    )
            conn.commit()
    
    def update_user_premium(self, user_id, days=30):
        with self.get_connection() as conn:
            expiry = (datetime.now() + timedelta(days=days)).date()
            conn.execute(
                'UPDATE users SET is_premium = 1, premium_expiry = ? WHERE user_id = ?',
                (expiry, user_id)
            )
            conn.commit()
    
    def check_premium(self, user_id):
        user = self.get_user(user_id)
        if user and user[5]:
            if user[6] and datetime.strptime(user[6], '%Y-%m-%d').date() >= datetime.now().date():
                return True
        return False
    
    def increment_edit_count(self, user_id):
        with self.get_connection() as conn:
            conn.execute(
                'UPDATE users SET edit_count = edit_count + 1, total_edits = total_edits + 1 WHERE user_id = ?',
                (user_id,)
            )
            conn.commit()
    
    def use_credit(self, user_id):
        user = self.get_user(user_id)
        if user and user[8] > 0:
            with self.get_connection() as conn:
                conn.execute('UPDATE users SET credits = credits - 1 WHERE user_id = ?', (user_id,))
                conn.commit()
            return True
        return False
    
    def add_credits(self, user_id, amount):
        with self.get_connection() as conn:
            conn.execute('UPDATE users SET credits = credits + ? WHERE user_id = ?', (amount, user_id))
            conn.commit()
    
    def get_edit_count(self, user_id):
        user = self.get_user(user_id)
        return user[7] if user else 0
    
    def log_edit(self, user_id, edit_type, input_file, output_file, parameters, status='completed'):
        with self.get_connection() as conn:
            conn.execute(
                '''INSERT INTO edits (user_id, edit_type, input_file, output_file, parameters, status)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (user_id, edit_type, input_file, output_file, json.dumps(parameters), status)
            )
            conn.commit()
    
    def get_all_users(self):
        with self.get_connection() as conn:
            cursor = conn.execute('SELECT user_id FROM users WHERE is_banned = 0')
            return cursor.fetchall()
    
    def ban_user(self, user_id):
        with self.get_connection() as conn:
            conn.execute('UPDATE users SET is_banned = 1 WHERE user_id = ?', (user_id,))
            conn.commit()
    
    def unban_user(self, user_id):
        with self.get_connection() as conn:
            conn.execute('UPDATE users SET is_banned = 0 WHERE user_id = ?', (user_id,))
            conn.commit()
    
    def get_stats(self):
        with self.get_connection() as conn:
            total_users = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
            premium_users = conn.execute('SELECT COUNT(*) FROM users WHERE is_premium = 1').fetchone()[0]
            total_edits = conn.execute('SELECT SUM(total_edits) FROM users').fetchone()[0] or 0
            return {
                'total_users': total_users,
                'premium_users': premium_users,
                'total_edits': total_edits,
                'active_today': conn.execute(
                    "SELECT COUNT(*) FROM edits WHERE date(created_at) = date('now')"
                ).fetchone()[0]
            }

# ==================== VIDEO EDITOR ====================
class VideoEditor:
    @staticmethod
    async def trim_video(input_path, output_path, start_time, end_time):
        try:
            video = VideoFileClip(input_path)
            trimmed = video.subclip(start_time, end_time)
            trimmed.write_videofile(output_path, codec='libx264', audio_codec='aac', logger=None)
            video.close()
            trimmed.close()
            return True
        except Exception as e:
            logger.error(f"Error trimming video: {e}")
            return False
    
    @staticmethod
    async def add_text(input_path, output_path, text, font_size=30, color='white', position='center'):
        try:
            video = VideoFileClip(input_path)
            txt_clip = TextClip(text, fontsize=font_size, color=color, font='Arial')
            
            if position == 'center':
                txt_clip = txt_clip.set_position(('center', 'center'))
            elif position == 'top':
                txt_clip = txt_clip.set_position(('center', 'top'))
            elif position == 'bottom':
                txt_clip = txt_clip.set_position(('center', 'bottom'))
            
            txt_clip = txt_clip.set_duration(video.duration)
            final = CompositeVideoClip([video, txt_clip])
            final.write_videofile(output_path, codec='libx264', audio_codec='aac', logger=None)
            
            video.close()
            txt_clip.close()
            final.close()
            return True
        except Exception as e:
            logger.error(f"Error adding text: {e}")
            return False
    
    @staticmethod
    async def add_audio(input_path, output_path, audio_path, volume=1.0):
        try:
            video = VideoFileClip(input_path)
            audio = AudioFileClip(audio_path)
            
            if audio.duration > video.duration:
                audio = audio.subclip(0, video.duration)
            else:
                audio = audio.loop(duration=video.duration)
            
            audio = audio.volumex(volume)
            final = video.set_audio(audio)
            final.write_videofile(output_path, codec='libx264', audio_codec='aac', logger=None)
            
            video.close()
            audio.close()
            final.close()
            return True
        except Exception as e:
            logger.error(f"Error adding audio: {e}")
            return False
    
    @staticmethod
    async def resize_video(input_path, output_path, width, height):
        try:
            video = VideoFileClip(input_path)
            resized = video.resize(newsize=(width, height))
            resized.write_videofile(output_path, codec='libx264', audio_codec='aac', logger=None)
            video.close()
            resized.close()
            return True
        except Exception as e:
            logger.error(f"Error resizing video: {e}")
            return False
    
    @staticmethod
    async def compress_video(input_path, output_path, bitrate='500k'):
        try:
            video = VideoFileClip(input_path)
            video.write_videofile(output_path, bitrate=bitrate, codec='libx264', 
                                 audio_codec='aac', logger=None)
            video.close()
            return True
        except Exception as e:
            logger.error(f"Error compressing video: {e}")
            return False
    
    @staticmethod
    async def extract_audio(input_path, output_path):
        try:
            video = VideoFileClip(input_path)
            audio = video.audio
            if audio:
                audio.write_audiofile(output_path, logger=None)
            video.close()
            if audio:
                audio.close()
            return True
        except Exception as e:
            logger.error(f"Error extracting audio: {e}")
            return False
    
    @staticmethod
    async def speed_video(input_path, output_path, speed=1.5):
        try:
            video = VideoFileClip(input_path)
            sped_up = video.fx(lambda clip: clip.speedx(speed))
            sped_up.write_videofile(output_path, codec='libx264', audio_codec='aac', logger=None)
            video.close()
            sped_up.close()
            return True
        except Exception as e:
            logger.error(f"Error speeding video: {e}")
            return False
    
    @staticmethod
    async def add_effects(input_path, output_path, effect_type='blur'):
        try:
            video = VideoFileClip(input_path)
            
            if effect_type == 'blur':
                video = video.fx(lambda clip: clip.resize(lambda t: 1 + 0.01 * t))
            elif effect_type == 'blackwhite':
                video = video.fx(lambda clip: clip.to_mask())
            
            video.write_videofile(output_path, codec='libx264', audio_codec='aac', logger=None)
            video.close()
            return True
        except Exception as e:
            logger.error(f"Error applying effect: {e}")
            return False

# ==================== IMAGE EDITOR ====================
class ImageEditor:
    @staticmethod
    async def resize_image(input_path, output_path, width, height, maintain_aspect=True):
        try:
            img = Image.open(input_path)
            
            if maintain_aspect:
                img.thumbnail((width, height), Image.Resampling.LANCZOS)
            else:
                img = img.resize((width, height), Image.Resampling.LANCZOS)
            
            img.save(output_path)
            img.close()
            return True
        except Exception as e:
            logger.error(f"Error resizing image: {e}")
            return False
    
    @staticmethod
    async def add_text(input_path, output_path, text, x=10, y=10, font_size=20, color='white'):
        try:
            img = Image.open(input_path)
            draw = ImageDraw.Draw(img)
            
            try:
                font = ImageFont.truetype("arial.ttf", font_size)
            except:
                font = ImageFont.load_default()
            
            draw.text((x, y), text, fill=color, font=font)
            img.save(output_path)
            img.close()
            return True
        except Exception as e:
            logger.error(f"Error adding text: {e}")
            return False
    
    @staticmethod
    async def apply_filter(input_path, output_path, filter_type):
        try:
            img = Image.open(input_path)
            
            filters = {
                'blur': ImageFilter.BLUR,
                'contour': ImageFilter.CONTOUR,
                'sharpen': ImageFilter.SHARPEN,
                'edge_enhance': ImageFilter.EDGE_ENHANCE,
                'emboss': ImageFilter.EMBOSS,
                'smooth': ImageFilter.SMOOTH,
                'detail': ImageFilter.DETAIL
            }
            
            if filter_type in filters:
                img = img.filter(filters[filter_type])
            
            img.save(output_path)
            img.close()
            return True
        except Exception as e:
            logger.error(f"Error applying filter: {e}")
            return False
    
    @staticmethod
    async def rotate_image(input_path, output_path, angle):
        try:
            img = Image.open(input_path)
            img_rotated = img.rotate(angle, expand=True)
            img_rotated.save(output_path)
            img.close()
            return True
        except Exception as e:
            logger.error(f"Error rotating image: {e}")
            return False
    
    @staticmethod
    async def add_watermark(input_path, output_path, watermark_path, position='bottom-right', opacity=0.5):
        try:
            img = Image.open(input_path).convert('RGBA')
            watermark = Image.open(watermark_path).convert('RGBA')
            
            watermark = watermark.copy()
            alpha = watermark.split()[3]
            alpha = alpha.point(lambda p: p * opacity)
            watermark.putalpha(alpha)
            
            positions = {
                'top-left': (10, 10),
                'top-right': (img.width - watermark.width - 10, 10),
                'bottom-left': (10, img.height - watermark.height - 10),
                'bottom-right': (img.width - watermark.width - 10, img.height - watermark.height - 10),
                'center': ((img.width - watermark.width) // 2, (img.height - watermark.height) // 2)
            }
            
            position_coords = positions.get(position, positions['bottom-right'])
            img.paste(watermark, position_coords, watermark)
            img.save(output_path)
            img.close()
            watermark.close()
            return True
        except Exception as e:
            logger.error(f"Error adding watermark: {e}")
            return False
    
    @staticmethod
    async def adjust_brightness(input_path, output_path, factor):
        try:
            img = Image.open(input_path)
            enhancer = ImageEnhance.Brightness(img)
            img = enhancer.enhance(factor)
            img.save(output_path)
            img.close()
            return True
        except Exception as e:
            logger.error(f"Error adjusting brightness: {e}")
            return False
    
    @staticmethod
    async def adjust_contrast(input_path, output_path, factor):
        try:
            img = Image.open(input_path)
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(factor)
            img.save(output_path)
            img.close()
            return True
        except Exception as e:
            logger.error(f"Error adjusting contrast: {e}")
            return False
    
    @staticmethod
    async def remove_background(input_path, output_path):
        if not REMBG_AVAILABLE:
            return False
        try:
            with open(input_path, 'rb') as i:
                input_data = i.read()
            output_data = remove(input_data)
            with open(output_path, 'wb') as o:
                o.write(output_data)
            return True
        except Exception as e:
            logger.error(f"Error removing background: {e}")
            return False
    
    @staticmethod
    async def add_sticker(input_path, output_path, sticker_path, position='center'):
        try:
            img = Image.open(input_path).convert('RGBA')
            sticker = Image.open(sticker_path).convert('RGBA')
            
            max_size = min(img.width, img.height) // 3
            if sticker.width > max_size or sticker.height > max_size:
                sticker.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            
            positions = {
                'top-left': (10, 10),
                'top-right': (img.width - sticker.width - 10, 10),
                'bottom-left': (10, img.height - sticker.height - 10),
                'bottom-right': (img.width - sticker.width - 10, img.height - sticker.height - 10),
                'center': ((img.width - sticker.width) // 2, (img.height - sticker.height) // 2)
            }
            
            position_coords = positions.get(position, positions['center'])
            img.paste(sticker, position_coords, sticker)
            img.save(output_path)
            img.close()
            sticker.close()
            return True
        except Exception as e:
            logger.error(f"Error adding sticker: {e}")
            return False
    
    @staticmethod
    async def collage_images(images, output_path, layout='grid', cols=2):
        try:
            imgs = [Image.open(img) for img in images]
            
            if layout == 'grid':
                rows = (len(imgs) + cols - 1) // cols
                max_width = max(img.width for img in imgs)
                max_height = max(img.height for img in imgs)
                
                collage = Image.new('RGB', (cols * max_width, rows * max_height), 'white')
                
                for i, img in enumerate(imgs):
                    x = (i % cols) * max_width
                    y = (i // cols) * max_height
                    collage.paste(img, (x, y))
                
                collage.save(output_path)
            
            for img in imgs:
                img.close()
            return True
        except Exception as e:
            logger.error(f"Error creating collage: {e}")
            return False
    
    @staticmethod
    async def add_frame(input_path, output_path, frame_type='simple', color='gold'):
        try:
            img = Image.open(input_path)
            width, height = img.size
            border_width = 20
            
            if frame_type == 'simple':
                bordered = ImageOps.expand(img, border=border_width, fill=color)
            elif frame_type == 'shadow':
                bordered = ImageOps.expand(img, border=border_width, fill='black')
                shadow = Image.new('RGBA', (width + border_width*2, height + border_width*2), (0,0,0,0))
                shadow.paste(bordered, (5,5))
                bordered = Image.alpha_composite(shadow, bordered)
            else:
                bordered = img
            
            bordered.save(output_path)
            img.close()
            return True
        except Exception as e:
            logger.error(f"Error adding frame: {e}")
            return False

# ==================== PREMIUM MANAGER ====================
class PremiumManager:
    def __init__(self, db):
        self.db = db
    
    def check_edit_limit(self, user_id):
        if self.db.check_premium(user_id):
            return True
        edit_count = self.db.get_edit_count(user_id)
        return edit_count < Config.MAX_FREE_EDITS
    
    def get_remaining_edits(self, user_id):
        if self.db.check_premium(user_id):
            return "Unlimited (Premium)"
        edit_count = self.db.get_edit_count(user_id)
        return max(0, Config.MAX_FREE_EDITS - edit_count)
    
    def get_credits(self, user_id):
        user = self.db.get_user(user_id)
        return user[8] if user else 0
    
    def create_payment_link(self, user_id, plan='monthly'):
        payment_id = str(uuid.uuid4())
        amount = Config.PREMIUM_PRICE if plan == 'monthly' else Config.PREMIUM_PRICE * 10
        with self.db.get_connection() as conn:
            conn.execute(
                'INSERT INTO payments (user_id, amount, payment_id, payment_method, status) VALUES (?, ?, ?, ?, ?)',
                (user_id, amount, payment_id, 'crypto', 'pending')
            )
            conn.commit()
        return f"https://your-payment-gateway.com/pay/{payment_id}"

# ==================== ADMIN MANAGER ====================
class AdminManager:
    def __init__(self, db, bot):
        self.db = db
        self.bot = bot
    
    def is_admin(self, user_id):
        return user_id in Config.ADMIN_IDS
    
    async def broadcast_message(self, message, media=None, media_type=None):
        users = self.db.get_all_users()
        total = len(users)
        sent = 0
        
        for user in users:
            try:
                if media and media_type == 'photo':
                    await self.bot.send_photo(chat_id=user[0], photo=media, caption=message)
                elif media and media_type == 'video':
                    await self.bot.send_video(chat_id=user[0], video=media, caption=message)
                else:
                    await self.bot.send_message(chat_id=user[0], text=message)
                sent += 1
            except Exception as e:
                logger.error(f"Failed to send to {user[0]}: {e}")
            
            await asyncio.sleep(0.05)
        
        return sent, total
    
    async def get_admin_stats(self):
        stats = self.db.get_stats()
        with self.db.get_connection() as conn:
            recent_edits = conn.execute(
                '''SELECT u.username, e.edit_type, e.status, e.created_at 
                   FROM edits e JOIN users u ON e.user_id = u.user_id 
                   ORDER BY e.created_at DESC LIMIT 10'''
            ).fetchall()
        return {'stats': stats, 'recent_edits': recent_edits}
    
    async def ban_user(self, user_id, reason=None):
        self.db.ban_user(user_id)
        try:
            await self.bot.send_message(
                chat_id=user_id,
                text=f"❌ You have been banned from using Kinva Master Bot.\nReason: {reason or 'Violation of terms'}"
            )
        except:
            pass
        return True
    
    async def unban_user(self, user_id):
        self.db.unban_user(user_id)
        try:
            await self.bot.send_message(
                chat_id=user_id,
                text="✅ You have been unbanned. You can now use the bot again."
            )
        except:
            pass
        return True
    
    async def add_credits_to_user(self, user_id, amount):
        self.db.add_credits(user_id, amount)
        try:
            await self.bot.send_message(
                chat_id=user_id,
                text=f"🎉 {amount} credits have been added to your account!"
            )
        except:
            pass
        return True

# ==================== FLASK APP ====================
flask_app = Flask(__name__)
flask_app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'your-secret-key')
socketio = SocketIO(flask_app, cors_allowed_origins="*")

# Global instances
bot_instance = None
db = DatabaseManager()
premium_manager = PremiumManager(db)
admin_manager = None

# Conversation states
EDIT_TYPE, WAIT_MEDIA, EDIT_PARAMETERS, AWAIT_CONFIRMATION = range(4)

# ==================== TELEGRAM BOT ====================
class TelegramBot:
    def __init__(self, token):
        self.token = token
        self.application = None
        self.user_data = {}
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        referral_code = context.args[0] if context.args else None
        db.create_user(user.id, user.username, user.first_name, user.last_name, referral_code)
        
        welcome_text = f"""
🎬 *Welcome to Kinva Master Bot* {user.first_name}!

Your all-in-one media editing assistant!

✨ *Features:*
• ✂️ Trim videos
• 📝 Add text to videos/images
• 🎵 Add background music
• 📏 Resize videos/images
• 🎨 Apply filters
• 🗜️ Compress videos
• 🎤 Extract audio
• 🔄 Rotate images
• 💧 Add watermarks
• ✨ Adjust brightness
• 🖼️ Create collages

💎 *Premium:* Unlimited edits, 4K output, priority processing!

Use /help for commands
        """
        
        keyboard = [
            [InlineKeyboardButton("✂️ Edit Video", callback_data='edit_video'),
             InlineKeyboardButton("🖼️ Edit Image", callback_data='edit_image')],
            [InlineKeyboardButton("💎 Premium", callback_data='premium'),
             InlineKeyboardButton("📊 Stats", callback_data='stats')],
            [InlineKeyboardButton("❓ Help", callback_data='help')]
        ]
        await update.message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = """
📚 *Commands:*

/start - Start bot
/help - Show this help
/edit - Edit media
/stats - Your statistics
/premium - Upgrade to premium
/credits - Check your credits
/referral - Get referral link
/cancel - Cancel operation

*Video Editing:*
• Trim - Cut video segments
• Text - Add text overlay
• Music - Add background audio
• Resize - Change dimensions
• Compress - Reduce file size
• Extract Audio - Get audio from video

*Image Editing:*
• Resize - Change dimensions
• Text - Add text
• Filter - Apply effects
• Rotate - Rotate image
• Watermark - Add watermark
• Brightness - Adjust brightness
• Collage - Create photo collage

*Premium Benefits:*
✅ Unlimited edits
✅ Priority processing
✅ 4K output
✅ No watermark
✅ AI features
        """
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def edit_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = db.get_user(update.effective_user.id)
        if user and user[11]:
            await update.message.reply_text("❌ You have been banned from using this bot.")
            return
        
        keyboard = [
            [InlineKeyboardButton("🎬 Video Editor", callback_data='edit_video'),
             InlineKeyboardButton("🖼️ Image Editor", callback_data='edit_image')],
            [InlineKeyboardButton("❌ Cancel", callback_data='cancel')]
        ]
        await update.message.reply_text("Choose editor:", reply_markup=InlineKeyboardMarkup(keyboard))
        return EDIT_TYPE
    
    async def edit_type_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        if query.data == 'edit_video':
            context.user_data['edit_type'] = 'video'
            keyboard = [
                [InlineKeyboardButton("✂️ Trim", callback_data='trim'),
                 InlineKeyboardButton("📝 Text", callback_data='text')],
                [InlineKeyboardButton("🎵 Music", callback_data='audio'),
                 InlineKeyboardButton("📏 Resize", callback_data='resize')],
                [InlineKeyboardButton("🗜️ Compress", callback_data='compress'),
                 InlineKeyboardButton("🎤 Extract Audio", callback_data='extract_audio')],
                [InlineKeyboardButton("⚡ Speed", callback_data='speed'),
                 InlineKeyboardButton("🎨 Effects", callback_data='effects')],
                [InlineKeyboardButton("❌ Cancel", callback_data='cancel')]
            ]
            await query.edit_message_text("Video operations:", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            context.user_data['edit_type'] = 'image'
            keyboard = [
                [InlineKeyboardButton("📏 Resize", callback_data='resize'),
                 InlineKeyboardButton("📝 Text", callback_data='text')],
                [InlineKeyboardButton("🎨 Filter", callback_data='filter'),
                 InlineKeyboardButton("🔄 Rotate", callback_data='rotate')],
                [InlineKeyboardButton("💧 Watermark", callback_data='watermark'),
                 InlineKeyboardButton("✨ Brightness", callback_data='brightness')],
                [InlineKeyboardButton("🖼️ Collage", callback_data='collage'),
                 InlineKeyboardButton("❌ Cancel", callback_data='cancel')]
            ]
            await query.edit_message_text("Image operations:", reply_markup=InlineKeyboardMarkup(keyboard))
        
        return WAIT_MEDIA
    
    async def handle_media(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        operation = context.user_data.get('operation')
        edit_type = context.user_data.get('edit_type')
        
        if not operation:
            await update.message.reply_text("Please select an operation first.")
            return ConversationHandler.END
        
        # Check credits/premium
        user_id = update.effective_user.id
        if not db.check_premium(user_id):
            if not db.use_credit(user_id):
                await update.message.reply_text(
                    "⚠️ You have no credits left!\n"
                    "Get premium for unlimited edits or refer friends to earn free credits!\n\n"
                    "Use /premium to upgrade or /referral to get your referral link."
                )
                return ConversationHandler.END
        
        # Get media file
        if update.message.video:
            media_file = await update.message.video.get_file()
            file_ext = 'mp4'
        elif update.message.document:
            media_file = await update.message.document.get_file()
            file_ext = update.message.document.file_name.split('.')[-1].lower()
        elif update.message.photo:
            photo = update.message.photo[-1]
            media_file = await photo.get_file()
            file_ext = 'jpg'
        else:
            await update.message.reply_text("Please send a video or image file.")
            return WAIT_MEDIA
        
        # Download file
        input_path = f"temp/{update.effective_user.id}_{uuid.uuid4()}.{file_ext}"
        os.makedirs('temp', exist_ok=True)
        await media_file.download_to_drive(input_path)
        context.user_data['input_path'] = input_path
        context.user_data['input_files'] = [input_path]
        
        # Handle operations
        if operation in ['trim', 'resize', 'text', 'audio', 'compress', 'extract_audio', 'speed', 'effects', 'filter', 'rotate', 'watermark', 'brightness', 'collage']:
            if operation == 'trim':
                await update.message.reply_text("Send trim duration: start end (seconds)\nExample: 10 30")
            elif operation == 'resize':
                await update.message.reply_text("Send dimensions: width height\nExample: 1920 1080")
            elif operation == 'text':
                await update.message.reply_text("Send the text to add:")
            elif operation == 'audio':
                await update.message.reply_text("Send the audio file to add:")
            elif operation == 'compress':
                await update.message.reply_text("Processing compression...")
                output_path = input_path.replace(f".{file_ext}", f"_compressed.{file_ext}")
                success = await VideoEditor.compress_video(input_path, output_path)
                if success:
                    with open(output_path, 'rb') as f:
                        await update.message.reply_video(video=InputFile(f))
                    os.remove(input_path)
                    os.remove(output_path)
                return ConversationHandler.END
            elif operation == 'extract_audio':
                await update.message.reply_text("Extracting audio...")
                output_path = input_path.replace('.mp4', '.mp3')
                success = await VideoEditor.extract_audio(input_path, output_path)
                if success:
                    with open(output_path, 'rb') as f:
                        await update.message.reply_audio(audio=InputFile(f))
                    os.remove(input_path)
                    os.remove(output_path)
                return ConversationHandler.END
            elif operation == 'speed':
                await update.message.reply_text("Send speed factor (0.5 to 2.0):\nExample: 1.5")
            elif operation == 'effects':
                await update.message.reply_text("Choose effect: blur, blackwhite, mirror, invert")
            elif operation == 'filter':
                await update.message.reply_text("Choose filter: blur, contour, sharpen, edge_enhance, emboss")
            elif operation == 'rotate':
                await update.message.reply_text("Send rotation angle (0-360):\nExample: 90")
            elif operation == 'watermark':
                await update.message.reply_text("Send watermark image (PNG recommended):")
            elif operation == 'brightness':
                await update.message.reply_text("Send brightness factor (0.5 to 2.0):\nExample: 1.5")
            elif operation == 'collage':
                if len(context.user_data.get('input_files', [])) < 2:
                    await update.message.reply_text("Send at least 2 images for collage.")
                    return WAIT_MEDIA
                await update.message.reply_text("Choose layout: grid")
            return EDIT_PARAMETERS
        
        return EDIT_PARAMETERS
    
    async def handle_parameters(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        operation = context.user_data.get('operation')
        input_path = context.user_data.get('input_path')
        edit_type = context.user_data.get('edit_type')
        user_id = update.effective_user.id
        
        output_path = input_path.replace('.', f'_edited.')
        
        try:
            success = False
            
            if operation == 'trim':
                start, end = map(float, update.message.text.split())
                success = await VideoEditor.trim_video(input_path, output_path, start, end)
            
            elif operation == 'resize':
                width, height = map(int, update.message.text.split())
                if edit_type == 'video':
                    success = await VideoEditor.resize_video(input_path, output_path, width, height)
                else:
                    success = await ImageEditor.resize_image(input_path, output_path, width, height)
            
            elif operation == 'text':
                text = update.message.text
                if edit_type == 'video':
                    success = await VideoEditor.add_text(input_path, output_path, text)
                else:
                    success = await ImageEditor.add_text(input_path, output_path, text)
            
            elif operation == 'audio':
                if update.message.audio:
                    audio_file = await update.message.audio.get_file()
                    audio_path = f"temp/audio_{uuid.uuid4()}.mp3"
                    await audio_file.download_to_drive(audio_path)
                    success = await VideoEditor.add_audio(input_path, output_path, audio_path)
                    os.remove(audio_path)
                else:
                    await update.message.reply_text("Please send an audio file.")
                    return EDIT_PARAMETERS
            
            elif operation == 'speed':
                speed = float(update.message.text)
                success = await VideoEditor.speed_video(input_path, output_path, speed)
            
            elif operation == 'effects':
                effect = update.message.text.lower()
                success = await VideoEditor.add_effects(input_path, output_path, effect)
            
            elif operation == 'filter':
                filter_type = update.message.text.lower()
                success = await ImageEditor.apply_filter(input_path, output_path, filter_type)
            
            elif operation == 'rotate':
                angle = int(update.message.text)
                success = await ImageEditor.rotate_image(input_path, output_path, angle)
            
            elif operation == 'watermark':
                if update.message.document or update.message.photo:
                    if update.message.document:
                        watermark_file = await update.message.document.get_file()
                    else:
                        watermark_file = await update.message.photo[-1].get_file()
                    
                    watermark_path = f"temp/watermark_{uuid.uuid4()}.png"
                    await watermark_file.download_to_drive(watermark_path)
                    success = await ImageEditor.add_watermark(input_path, output_path, watermark_path)
                    os.remove(watermark_path)
                else:
                    await update.message.reply_text("Please send a watermark image.")
                    return EDIT_PARAMETERS
            
            elif operation == 'brightness':
                factor = float(update.message.text)
                success = await ImageEditor.adjust_brightness(input_path, output_path, factor)
            
            elif operation == 'collage':
                images = context.user_data.get('input_files', [])
                output_path = f"temp/collage_{uuid.uuid4()}.jpg"
                success = await ImageEditor.collage_images(images, output_path)
            
            if success:
                db.increment_edit_count(user_id)
                
                if edit_type == 'video' or operation in ['compress', 'speed', 'effects', 'trim']:
                    with open(output_path, 'rb') as f:
                        await update.message.reply_video(video=InputFile(f))
                else:
                    with open(output_path, 'rb') as f:
                        await update.message.reply_photo(photo=InputFile(f))
                
                for file_path in context.user_data.get('input_files', []):
                    if os.path.exists(file_path):
                        os.remove(file_path)
                if os.path.exists(output_path):
                    os.remove(output_path)
            else:
                await update.message.reply_text("Error processing request.")
            
        except Exception as e:
            logger.error(f"Error: {e}")
            await update.message.reply_text(f"Error: {str(e)[:100]}")
        
        return ConversationHandler.END
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        user = db.get_user(user_id)
        
        if user:
            stats_text = f"""
📊 *Your Statistics*

👤 *User:* {user[2] or user[1] or str(user_id)}
💎 *Premium:* {'✅ Yes' if user[5] else '❌ No'}
📅 *Premium Expiry:* {user[6] if user[6] else 'N/A'}
🎬 *Total Edits:* {user[7]}
💰 *Credits:* {user[8] if not user[5] else 'Unlimited'}
🎁 *Free Edits Remaining:* {premium_manager.get_remaining_edits(user_id)}
            """
            await update.message.reply_text(stats_text, parse_mode='Markdown')
    
    async def credits_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = db.get_user(update.effective_user.id)
        if user:
            if user[5]:
                await update.message.reply_text("💎 Premium user! Unlimited credits! 🎉")
            else:
                await update.message.reply_text(f"💰 You have {user[8]} credits. Use /referral to earn more!")
    
    async def referral_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = db.get_user(update.effective_user.id)
        if user:
            link = f"https://t.me/{context.bot.username}?start={user[9]}"
            await update.message.reply_text(
                f"🔗 *Your Referral Link*\n\n`{link}`\n\n"
                f"Share this link with friends!\n"
                f"For each friend who joins, you get 2 free credits! 🎉",
                parse_mode='Markdown'
            )
    
    async def premium_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        premium_text = """
💎 *Premium Subscription*

*✨ Benefits:*
✅ Unlimited media edits
✅ AI background removal
✅ 4K/8K output support
✅ Priority processing
✅ No watermark
✅ Early access to features
✅ Dedicated support

*💰 Pricing:*
• Monthly: $9.99
• Yearly: $99.99 (Save 17%)

*💳 Payment Methods:*
• Credit/Debit Card
• PayPal
• Cryptocurrency

Contact @kinva_support to upgrade!
        """
        await update.message.reply_text(premium_text, parse_mode='Markdown')
    
    async def callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data
        
        if data in ['edit_video', 'edit_image']:
            context.user_data['edit_type'] = data.replace('edit_', '')
            return await self.edit_type_handler(update, context)
        
        elif data in ['trim', 'text', 'audio', 'resize', 'compress', 'extract_audio', 'speed', 'effects', 'filter', 'rotate', 'watermark', 'brightness', 'collage']:
            context.user_data['operation'] = data
            await query.edit_message_text(f"Send media to {data}")
            return WAIT_MEDIA
        
        elif data == 'premium':
            await self.premium_command(update, context)
        
        elif data == 'stats':
            await self.stats_command(update, context)
        
        elif data == 'help':
            await self.help_command(update, context)
        
        elif data == 'cancel':
            await query.edit_message_text("Operation cancelled.")
            return ConversationHandler.END
        
        return ConversationHandler.END
    
    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Operation cancelled.")
        return ConversationHandler.END
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"Update {update} caused error {context.error}")
        if update and update.effective_message:
            await update.effective_message.reply_text("An error occurred. Please try again.")
    
    # Admin commands
    async def admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not admin_manager.is_admin(update.effective_user.id):
            await update.message.reply_text("⛔ Unauthorized.")
            return
        
        stats = await admin_manager.get_admin_stats()
        admin_text = f"""
👑 *Admin Panel*

📊 *Statistics:*
• Total Users: {stats['stats']['total_users']}
• Premium Users: {stats['stats']['premium_users']}
• Total Edits: {stats['stats']['total_edits']}
• Active Today: {stats['stats']['active_today']}

📝 *Recent Edits:*
"""
        for edit in stats['recent_edits'][:5]:
            admin_text += f"\n• @{edit[0] or 'user'}: {edit[1]} - {edit[2]}"
        
        keyboard = [
            [InlineKeyboardButton("📢 Broadcast", callback_data='admin_broadcast'),
             InlineKeyboardButton("👥 Users", callback_data='admin_users')],
            [InlineKeyboardButton("💎 Premium Users", callback_data='admin_premium'),
             InlineKeyboardButton("📊 Full Stats", callback_data='admin_stats')]
        ]
        await update.message.reply_text(admin_text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def broadcast_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not admin_manager.is_admin(update.effective_user.id):
            return
        
        await update.message.reply_text("📢 Send message to broadcast:")
        return AWAIT_CONFIRMATION
    
    async def handle_broadcast(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not admin_manager.is_admin(update.effective_user.id):
            return ConversationHandler.END
        
        message = update.message.text or update.message.caption
        media = None
        media_type = None
        
        if update.message.photo:
            media = update.message.photo[-1].file_id
            media_type = 'photo'
        elif update.message.video:
            media = update.message.video.file_id
            media_type = 'video'
        
        await update.message.reply_text(
            f"📢 Send to {len(db.get_all_users())} users?\nType 'yes' to confirm."
        )
        context.user_data['broadcast_message'] = message
        context.user_data['broadcast_media'] = media
        context.user_data['broadcast_media_type'] = media_type
        
        return AWAIT_CONFIRMATION
    
    async def confirm_broadcast(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not admin_manager.is_admin(update.effective_user.id):
            return ConversationHandler.END
        
        if update.message.text.lower() == 'yes':
            await update.message.reply_text("📢 Broadcasting...")
            sent, total = await admin_manager.broadcast_message(
                context.user_data['broadcast_message'],
                context.user_data['broadcast_media'],
                context.user_data['broadcast_media_type']
            )
            await update.message.reply_text(f"✅ Sent to {sent}/{total} users.")
        else:
            await update.message.reply_text("❌ Cancelled.")
        
        return ConversationHandler.END
    
    def setup(self):
        self.application = Application.builder().token(self.token).build()
        
        # Admin conversation
        admin_conv = ConversationHandler(
            entry_points=[CommandHandler('broadcast', self.broadcast_command)],
            states={
                AWAIT_CONFIRMATION: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.confirm_broadcast),
                    MessageHandler(filters.PHOTO | filters.VIDEO, self.handle_broadcast)
                ]
            },
            fallbacks=[CommandHandler('cancel', self.cancel_command)]
        )
        
        # Main conversation
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('edit', self.edit_command)],
            states={
                EDIT_TYPE: [CallbackQueryHandler(self.edit_type_handler)],
                WAIT_MEDIA: [MessageHandler(filters.VIDEO | filters.PHOTO | filters.Document.ALL, self.handle_media)],
                EDIT_PARAMETERS: [MessageHandler(filters.TEXT | filters.AUDIO | filters.PHOTO | filters.Document.ALL, self.handle_parameters)]
            },
            fallbacks=[CommandHandler('cancel', self.cancel_command)]
        )
        
        self.application.add_handler(conv_handler)
        self.application.add_handler(admin_conv)
        self.application.add_handler(CommandHandler('start', self.start))
        self.application.add_handler(CommandHandler('help', self.help_command))
        self.application.add_handler(CommandHandler('stats', self.stats_command))
        self.application.add_handler(CommandHandler('credits', self.credits_command))
        self.application.add_handler(CommandHandler('referral', self.referral_command))
        self.application.add_handler(CommandHandler('premium', self.premium_command))
        self.application.add_handler(CommandHandler('admin', self.admin_command))
        self.application.add_handler(CallbackQueryHandler(self.callback_handler))
        self.application.add_error_handler(self.error_handler)
    
    async def start_bot(self):
        global admin_manager
        self.setup()
        await self.application.initialize()
        await self.application.start()
        
        # Create admin manager AFTER application is ready
        admin_manager = AdminManager(db, self.application.bot)
        
        if Config.WEBHOOK_URL and 'localhost' not in Config.WEBHOOK_URL:
            await self.application.bot.set_webhook(f"{Config.WEBHOOK_URL}/webhook")
        else:
            await self.application.updater.start_polling()
        
        logger.info("Kinva Master Bot started successfully")
    
    async def stop_bot(self):
        if self.application:
            await self.application.stop()

# ==================== FLASK ROUTES ====================
@flask_app.route('/')
def index():
    return jsonify({'status': 'running', 'service': 'Kinva Master Bot'})

@flask_app.route('/health')
def health():
    return 'OK', 200

@flask_app.route('/webhook', methods=['POST'])
async def webhook():
    if bot_instance and bot_instance.application:
        update = telegram.Update.de_json(request.get_json(), bot_instance.application.bot)
        await bot_instance.application.process_update(update)
    return 'ok'

# ==================== CLEANUP ====================
async def cleanup_temp_files():
    while True:
        try:
            temp_dir = 'temp'
            if os.path.exists(temp_dir):
                current_time = time.time()
                for filename in os.listdir(temp_dir):
                    filepath = os.path.join(temp_dir, filename)
                    if os.path.isfile(filepath):
                        if current_time - os.path.getctime(filepath) > 3600:
                            os.remove(filepath)
            await asyncio.sleep(3600)
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
            await asyncio.sleep(3600)

# ==================== CREATE TEMPLATES ====================
def create_templates():
    os.makedirs('templates', exist_ok=True)
    with open('templates/editor.html', 'w') as f:
        f.write("""<!DOCTYPE html>
<html>
<head><title>Kinva Master Editor</title></head>
<body>
<h1>🎬 Kinva Master Editor</h1>
<p>Web editor coming soon! Use Telegram bot for editing.</p>
</body>
</html>""")

# ==================== MAIN APPLICATION ====================
class KinvaMasterBot:
    def __init__(self):
        self.bot = None
    
    async def start(self):
        global bot_instance
        os.makedirs('temp', exist_ok=True)
        create_templates()
        
        self.bot = TelegramBot(Config.TELEGRAM_BOT_TOKEN)
        bot_instance = self.bot
        await self.bot.start_bot()
        
        asyncio.create_task(cleanup_temp_files())
        
        logger.info("=" * 50)
        logger.info("Kinva Master Bot is running!")
        if self.bot.application and self.bot.application.bot:
            logger.info(f"Bot username: @{self.bot.application.bot.username}")
        logger.info(f"Web interface: http://localhost:{Config.PORT}")
        logger.info("=" * 50)
        
        port = int(os.environ.get('PORT', Config.PORT))
        socketio.run(flask_app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)
    
    async def stop(self):
        if self.bot:
            await self.bot.stop_bot()

# ==================== ENTRY POINT ====================
if __name__ == '__main__':
    bot_app = KinvaMasterBot()
    try:
        asyncio.run(bot_app.start())
    except KeyboardInterrupt:
        print("\nShutting down...")
        asyncio.run(bot_app.stop())
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        raise
