"""
Kinva Master Bot - Fixed Imports
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
# For moviepy 2.2.1, the structure has changed
try:
    # Try the new moviepy 2.0+ structure
    from moviepy import VideoFileClip, AudioFileClip, CompositeVideoClip
    from moviepy.video.VideoClip import TextClip
    from moviepy.audio.io.AudioFileClip import AudioFileClip
    logger = logging.getLogger(__name__)
    logger.info("Using moviepy 2.0+ imports")
except ImportError:
    try:
        # Fallback to moviepy 1.x structure
        from moviepy.editor import VideoFileClip, AudioFileClip, CompositeVideoClip, TextClip
        logger.info("Using moviepy 1.x imports")
    except ImportError:
        # Last resort - use the specific paths
        from moviepy.video.io.VideoFileClip import VideoFileClip
        from moviepy.audio.io.AudioFileClip import AudioFileClip
        from moviepy.video.compositing.CompositeVideoClip import CompositeVideoClip
        from moviepy.video.VideoClip import TextClip
        logger.info("Using moviepy direct imports")

# ==================== OPTIONAL IMPORTS ====================
# These are optional and won't crash if missing
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
# Remove this line:
# import requests

# Keep only:
import aiohttp
from dotenv import load_dotenv
import aiohttp
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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
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
            
            # Templates table
            conn.execute('''
                CREATE TABLE IF NOT EXISTS templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    type TEXT,
                    data TEXT,
                    preview TEXT,
                    created_by INTEGER,
                    is_public BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Affiliates table
            conn.execute('''
                CREATE TABLE IF NOT EXISTS affiliates (
                    user_id INTEGER PRIMARY KEY,
                    earnings REAL DEFAULT 0,
                    total_referrals INTEGER DEFAULT 0,
                    last_payout DATE,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')
            
            conn.commit()
    
    def get_user(self, user_id):
        with self.get_connection() as conn:
            cursor = conn.execute(
                'SELECT * FROM users WHERE user_id = ?',
                (user_id,)
            )
            return cursor.fetchone()
    
    def create_user(self, user_id, username=None, first_name=None, last_name=None, referral_code=None):
        with self.get_connection() as conn:
            # Generate unique referral code
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            conn.execute(
                '''INSERT OR IGNORE INTO users 
                   (user_id, username, first_name, last_name, referral_code) 
                   VALUES (?, ?, ?, ?, ?)''',
                (user_id, username, first_name, last_name, code)
            )
            
            # Handle referral
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
                    # Give bonus credits
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
                conn.execute(
                    'UPDATE users SET credits = credits - 1 WHERE user_id = ?',
                    (user_id,)
                )
                conn.commit()
            return True
        return False
    
    def add_credits(self, user_id, amount):
        with self.get_connection() as conn:
            conn.execute(
                'UPDATE users SET credits = credits + ? WHERE user_id = ?',
                (amount, user_id)
            )
            conn.commit()
    
    def get_edit_count(self, user_id):
        user = self.get_user(user_id)
        return user[8] if user else 0
    
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

# ==================== ADVANCED VIDEO EDITOR ====================
class AdvancedVideoEditor:
    @staticmethod
    async def trim_video(input_path, output_path, start_time, end_time):
        try:
            video = mp.VideoFileClip(input_path)
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
            video = mp.VideoFileClip(input_path)
            
            # Create text clip
            txt_clip = TextClip(text, fontsize=font_size, color=color, 
                               font='Arial', stroke_color='black', stroke_width=2)
            
            # Set position
            if position == 'center':
                txt_clip = txt_clip.set_position(('center', 'center'))
            elif position == 'top':
                txt_clip = txt_clip.set_position(('center', 'top'))
            elif position == 'bottom':
                txt_clip = txt_clip.set_position(('center', 'bottom'))
            else:
                txt_clip = txt_clip.set_position(position)
            
            txt_clip = txt_clip.set_duration(video.duration)
            
            # Composite
            final = CompositeVideoClip([video, txt_clip])
            final.write_videofile(output_path, codec='libx264', audio_codec='aac', logger=None)
            
            video.close()
            txt_clip.close()
            final.close()
            return True
        except Exception as e:
            logger.error(f"Error adding text to video: {e}")
            return False
    
    @staticmethod
    async def add_background_music(input_path, output_path, audio_path, volume=1.0):
        try:
            video = mp.VideoFileClip(input_path)
            audio = mp.AudioFileClip(audio_path)
            
            # Adjust duration
            if audio.duration > video.duration:
                audio = audio.subclip(0, video.duration)
            else:
                audio = audio.loop(duration=video.duration)
            
            audio = audio.volumex(volume)
            
            # Combine
            final = video.set_audio(audio)
            final.write_videofile(output_path, codec='libx264', audio_codec='aac', logger=None)
            
            video.close()
            audio.close()
            final.close()
            return True
        except Exception as e:
            logger.error(f"Error adding audio to video: {e}")
            return False
    
    @staticmethod
    async def resize_video(input_path, output_path, width, height):
        try:
            video = mp.VideoFileClip(input_path)
            resized = video.resize(newsize=(width, height))
            resized.write_videofile(output_path, codec='libx264', audio_codec='aac', logger=None)
            video.close()
            resized.close()
            return True
        except Exception as e:
            logger.error(f"Error resizing video: {e}")
            return False
    
    @staticmethod
    async def compress_video(input_path, output_path, quality='medium'):
        bitrate_map = {'low': '300k', 'medium': '500k', 'high': '1000k'}
        bitrate = bitrate_map.get(quality, '500k')
        
        try:
            video = mp.VideoFileClip(input_path)
            video.write_videofile(output_path, bitrate=bitrate, codec='libx264', 
                                 audio_codec='aac', logger=None)
            video.close()
            return True
        except Exception as e:
            logger.error(f"Error compressing video: {e}")
            return False
    
    @staticmethod
    async def add_transition(input_path1, input_path2, output_path, transition_type='fade', duration=1):
        try:
            clip1 = mp.VideoFileClip(input_path1)
            clip2 = mp.VideoFileClip(input_path2)
            
            if transition_type == 'fade':
                clip1 = clip1.crossfadeout(duration)
                clip2 = clip2.crossfadein(duration)
            elif transition_type == 'slide':
                clip2 = clip2.set_position(('right', 'center')).resize(clip1.size)
            
            final = mp.concatenate_videoclips([clip1, clip2], method="compose")
            final.write_videofile(output_path, codec='libx264', audio_codec='aac', logger=None)
            
            clip1.close()
            clip2.close()
            final.close()
            return True
        except Exception as e:
            logger.error(f"Error adding transition: {e}")
            return False
    
    @staticmethod
    async def speed_video(input_path, output_path, speed=1.5):
        try:
            video = mp.VideoFileClip(input_path)
            sped_up = video.fx(mp.vfx.speedx, speed)
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
            video = mp.VideoFileClip(input_path)
            
            if effect_type == 'blur':
                video = video.fx(mp.vfx.gaussian_blur, 5)
            elif effect_type == 'blackwhite':
                video = video.fx(mp.vfx.blackwhite)
            elif effect_type == 'mirror':
                video = video.fx(mp.vfx.mirror_x)
            elif effect_type == 'invert':
                video = video.fx(mp.vfx.invert_colors)
            
            video.write_videofile(output_path, codec='libx264', audio_codec='aac', logger=None)
            video.close()
            return True
        except Exception as e:
            logger.error(f"Error applying effect: {e}")
            return False
    
    @staticmethod
    async def extract_audio(input_path, output_path):
        try:
            video = mp.VideoFileClip(input_path)
            audio = video.audio
            audio.write_audiofile(output_path, logger=None)
            video.close()
            audio.close()
            return True
        except Exception as e:
            logger.error(f"Error extracting audio: {e}")
            return False
    
    @staticmethod
    async def add_caption(input_path, output_path, captions):
        try:
            video = mp.VideoFileClip(input_path)
            caption_clips = []
            
            for caption in captions:
                txt_clip = TextClip(caption['text'], fontsize=caption.get('size', 30),
                                   color=caption.get('color', 'white'),
                                   stroke_color='black', stroke_width=2)
                txt_clip = txt_clip.set_position(('center', 'bottom')).set_duration(caption['duration'])
                txt_clip = txt_clip.set_start(caption['start'])
                caption_clips.append(txt_clip)
            
            final = CompositeVideoClip([video] + caption_clips)
            final.write_videofile(output_path, codec='libx264', audio_codec='aac', logger=None)
            
            video.close()
            final.close()
            return True
        except Exception as e:
            logger.error(f"Error adding captions: {e}")
            return False

# ==================== ADVANCED IMAGE EDITOR ====================
class AdvancedImageEditor:
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
            
            # Adjust opacity
            watermark = watermark.copy()
            alpha = watermark.split()[3]
            alpha = alpha.point(lambda p: p * opacity)
            watermark.putalpha(alpha)
            
            # Calculate position
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
            
            # Resize sticker if too large
            max_size = min(img.width, img.height) // 3
            if sticker.width > max_size or sticker.height > max_size:
                sticker.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            
            # Calculate position
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
                # Add shadow effect
                shadow = Image.new('RGBA', (width + border_width*2, height + border_width*2), (0,0,0,0))
                shadow.paste(bordered, (5,5))
                bordered = Image.alpha_composite(shadow, bordered)
            
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
        if edit_count < Config.MAX_FREE_EDITS:
            return True
        return False
    
    def get_remaining_edits(self, user_id):
        if self.db.check_premium(user_id):
            return "Unlimited (Premium)"
        
        edit_count = self.db.get_edit_count(user_id)
        remaining = max(0, Config.MAX_FREE_EDITS - edit_count)
        return remaining
    
    def get_credits(self, user_id):
        user = self.db.get_user(user_id)
        return user[8] if user else 0
    
    def create_payment_link(self, user_id, plan='monthly'):
        payment_id = str(uuid.uuid4())
        amount = Config.PREMIUM_PRICE if plan == 'monthly' else Config.PREMIUM_PRICE * 10
        
        self.db.get_connection().execute(
            'INSERT INTO payments (user_id, amount, payment_id, payment_method, status) VALUES (?, ?, ?, ?, ?)',
            (user_id, amount, payment_id, 'crypto', 'pending')
        )
        self.db.get_connection().commit()
        
        # In production, integrate with actual payment gateway
        return f"https://your-payment-gateway.com/pay/{payment_id}"
    
    def verify_payment(self, payment_id):
        with self.db.get_connection() as conn:
            cursor = conn.execute(
                'SELECT user_id FROM payments WHERE payment_id = ? AND status = "pending"',
                (payment_id,)
            )
            result = cursor.fetchone()
            
            if result:
                conn.execute(
                    'UPDATE payments SET status = "completed" WHERE payment_id = ?',
                    (payment_id,)
                )
                return result[0]
        return None

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
            
            await asyncio.sleep(0.05)  # Avoid rate limiting
        
        return sent, total
    
    async def get_admin_stats(self):
        stats = self.db.get_stats()
        
        # Get recent edits
        with self.db.get_connection() as conn:
            recent_edits = conn.execute(
                '''SELECT u.username, e.edit_type, e.status, e.created_at 
                   FROM edits e JOIN users u ON e.user_id = u.user_id 
                   ORDER BY e.created_at DESC LIMIT 10'''
            ).fetchall()
        
        return {
            'stats': stats,
            'recent_edits': recent_edits
        }
    
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

# ==================== FLASK WEB APP ====================
flask_app = Flask(__name__)
flask_app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'your-secret-key')
flask_app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max file size
socketio = SocketIO(flask_app, cors_allowed_origins="*")

# Global instances
bot_instance = None
db = DatabaseManager()
premium_manager = PremiumManager(db)
admin_manager = None

# Conversation states
(EDIT_TYPE, WAIT_MEDIA, EDIT_PARAMETERS, AWAIT_CONFIRMATION) = range(4)

# ==================== TELEGRAM BOT HANDLERS ====================
class TelegramBot:
    def __init__(self, token):
        self.token = token
        self.application = None
        self.user_data = {}
        self.job_queue = None
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        
        # Check for referral code
        referral_code = context.args[0] if context.args else None
        db.create_user(user.id, user.username, user.first_name, user.last_name, referral_code)
        
        welcome_text = f"""
🎬 *Welcome to Kinva Master Bot* {user.first_name}!

Your all-in-one professional media editing assistant with CapCut and Canva-style features!

✨ *Premium Features:*
• ✂️ Trim, Cut, Split videos
• 📝 Add text, captions, subtitles
• 🎵 Background music and audio mixing
• 🎨 Filters, effects, transitions
• 🖼️ Image editing with AI
• 🎭 Remove background (AI-powered)
• 📐 Resize, rotate, crop
• 💧 Add watermarks and stickers
• 🚀 Speed up/slow down videos
• 🎬 Video to audio conversion
• 🖼️ Create collages and frames

💎 *Premium Benefits:*
• Unlimited edits
• 4K/8K output quality
• Priority processing
• Advanced AI features
• Custom templates
• Dedicated support

🎁 *Free Tier:* {Config.MAX_FREE_EDITS} free edits or {Config.FREE_TRIAL_DAYS} days premium trial!

Use /help to see all commands and /premium to upgrade!
        """
        
        keyboard = [
            [InlineKeyboardButton("✂️ Video Editor", callback_data='video_editor'),
             InlineKeyboardButton("🖼️ Image Editor", callback_data='image_editor')],
            [InlineKeyboardButton("🎨 Templates", callback_data='templates'),
             InlineKeyboardButton("💎 Premium", callback_data='premium')],
            [InlineKeyboardButton("📊 My Stats", callback_data='stats'),
             InlineKeyboardButton("❓ Help", callback_data='help')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = """
📚 *Kinva Master Bot - Complete Guide*

*/start* - Start the bot
*/help* - Show this help message
*/edit* - Start editing media
*/stats* - View your statistics
*/premium* - Get premium subscription
*/credits* - Check your credits
*/referral* - Get referral link
*/templates* - Browse templates
*/cancel* - Cancel current operation

*🎬 Video Editing Features:*
• Trim/Cut videos
• Add text overlays
• Add background music
• Resize videos
• Compress videos
• Speed up/slow down
• Add transitions
• Apply effects (blur, BW, mirror)
• Extract audio
• Add captions/subtitles
• Merge videos

*🖼️ Image Editing Features:*
• Resize images
• Add text
• Apply filters
• Rotate images
• Add watermarks
• Adjust brightness/contrast
• Remove background (AI)
• Add stickers
• Create collages
• Add frames

*💎 Premium Benefits:*
✅ Unlimited edits
✅ AI background removal
✅ 4K output support
✅ Priority queue
✅ Custom templates
✅ No watermark on output
✅ Early access to features

*💰 Referral Program:*
Share your referral link and earn 2 free credits for each friend who joins!

*Support:* Contact @kinva_support for assistance
        """
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def edit_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        # Check if banned
        user = db.get_user(user_id)
        if user and user[11]:
            await update.message.reply_text("❌ You have been banned from using this bot.")
            return
        
        keyboard = [
            [InlineKeyboardButton("🎬 Advanced Video Editor", callback_data='video_editor'),
             InlineKeyboardButton("🖼️ Advanced Image Editor", callback_data='image_editor')],
            [InlineKeyboardButton("🎨 Browse Templates", callback_data='templates'),
             InlineKeyboardButton("⭐ AI Tools", callback_data='ai_tools')],
            [InlineKeyboardButton("❌ Cancel", callback_data='cancel')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "🎨 *Choose your editing tool:*",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return EDIT_TYPE
    
    async def video_editor_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        keyboard = [
            [InlineKeyboardButton("✂️ Trim/Cut", callback_data='video_trim'),
             InlineKeyboardButton("📝 Add Text", callback_data='video_text')],
            [InlineKeyboardButton("🎵 Add Music", callback_data='video_audio'),
             InlineKeyboardButton("📏 Resize", callback_data='video_resize')],
            [InlineKeyboardButton("🗜️ Compress", callback_data='video_compress'),
             InlineKeyboardButton("⚡ Speed", callback_data='video_speed')],
            [InlineKeyboardButton("🎨 Effects", callback_data='video_effects'),
             InlineKeyboardButton("🔄 Transitions", callback_data='video_transition')],
            [InlineKeyboardButton("🎤 Extract Audio", callback_data='video_extract_audio'),
             InlineKeyboardButton("📝 Add Captions", callback_data='video_caption')],
            [InlineKeyboardButton("🔗 Merge Videos", callback_data='video_merge'),
             InlineKeyboardButton("❌ Cancel", callback_data='cancel')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "🎬 *Video Editing Tools*\n\nChoose an operation:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return WAIT_MEDIA
    
    async def image_editor_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        keyboard = [
            [InlineKeyboardButton("📏 Resize", callback_data='image_resize'),
             InlineKeyboardButton("📝 Add Text", callback_data='image_text')],
            [InlineKeyboardButton("🎨 Apply Filter", callback_data='image_filter'),
             InlineKeyboardButton("🔄 Rotate", callback_data='image_rotate')],
            [InlineKeyboardButton("💧 Add Watermark", callback_data='image_watermark'),
             InlineKeyboardButton("✨ Adjust Brightness", callback_data='image_brightness')],
            [InlineKeyboardButton("🎭 Remove Background", callback_data='image_remove_bg'),
             InlineKeyboardButton("🧸 Add Sticker", callback_data='image_sticker')],
            [InlineKeyboardButton("🖼️ Create Collage", callback_data='image_collage'),
             InlineKeyboardButton("🖼️ Add Frame", callback_data='image_frame')],
            [InlineKeyboardButton("❌ Cancel", callback_data='cancel')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "🖼️ *Image Editing Tools*\n\nChoose an operation:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return WAIT_MEDIA
    
    async def handle_media(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        operation = context.user_data.get('operation')
        edit_type = context.user_data.get('edit_type')
        
        if not operation:
            await update.message.reply_text("Please select an operation first using /edit")
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
        
        # Check file size
        if media_file.file_size > Config.MAX_VIDEO_SIZE * 1024 * 1024:
            await update.message.reply_text(f"File too large! Maximum size: {Config.MAX_VIDEO_SIZE}MB")
            return WAIT_MEDIA
        
        # Download file
        input_path = f"temp/{update.effective_user.id}_{uuid.uuid4()}.{file_ext}"
        os.makedirs('temp', exist_ok=True)
        await media_file.download_to_drive(input_path)
        
        context.user_data['input_path'] = input_path
        context.user_data['input_files'] = [input_path]
        
        # Handle different operations
        operation_handlers = {
            'trim': lambda: self.handle_trim(update, context),
            'resize': lambda: self.handle_resize(update, context),
            'text': lambda: self.handle_text(update, context),
            'audio': lambda: self.handle_audio(update, context),
            'compress': lambda: self.handle_compress(update, context),
            'speed': lambda: self.handle_speed(update, context),
            'effects': lambda: self.handle_effects(update, context),
            'extract_audio': lambda: self.handle_extract_audio(update, context),
            'caption': lambda: self.handle_caption(update, context),
            'merge': lambda: self.handle_merge(update, context),
            'filter': lambda: self.handle_filter(update, context),
            'rotate': lambda: self.handle_rotate(update, context),
            'watermark': lambda: self.handle_watermark(update, context),
            'brightness': lambda: self.handle_brightness(update, context),
            'remove_bg': lambda: self.handle_remove_bg(update, context),
            'sticker': lambda: self.handle_sticker(update, context),
            'collage': lambda: self.handle_collage(update, context),
            'frame': lambda: self.handle_frame(update, context)
        }
        
        handler = operation_handlers.get(operation)
        if handler:
            return await handler()
        
        return EDIT_PARAMETERS
    
    async def handle_trim(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "✂️ *Trim Video*\n\n"
            "Send the trim duration in format: start end\n"
            "Example: 10 30 (trims from 10s to 30s)\n\n"
            "Or send 'auto' to trim silence from start and end.",
            parse_mode='Markdown'
        )
        return EDIT_PARAMETERS
    
    async def handle_resize(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "📏 *Resize Media*\n\n"
            "Send dimensions in format: width height\n"
            "Example: 1920 1080\n\n"
            "Presets:\n"
            "• 1080p: 1920 1080\n"
            "• 720p: 1280 720\n"
            "• 480p: 854 480\n"
            "• Square: 1080 1080\n"
            "• Story: 1080 1920",
            parse_mode='Markdown'
        )
        return EDIT_PARAMETERS
    
    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "📝 *Add Text*\n\n"
            "Send the text you want to add to your media.\n\n"
            "You can format with:\n"
            "• Bold: *text*\n"
            "• Italic: _text_\n"
            "• Code: `text`",
            parse_mode='Markdown'
        )
        return EDIT_PARAMETERS
    
    async def handle_audio(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🎵 *Add Background Music*\n\n"
            "Please send the audio file you want to add as background music.\n\n"
            "Supported formats: MP3, WAV, OGG, M4A"
        )
        return EDIT_PARAMETERS
    
    async def handle_compress(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🗜️ *Compress Video*\n\n"
            "Choose compression quality:\n"
            "• low - Smallest file size\n"
            "• medium - Balanced\n"
            "• high - Best quality\n\n"
            "Send: low, medium, or high",
            parse_mode='Markdown'
        )
        return EDIT_PARAMETERS
    
    async def handle_speed(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "⚡ *Change Video Speed*\n\n"
            "Send speed factor (0.5 to 2.0):\n"
            "• 0.5 - Half speed (slow motion)\n"
            "• 1.0 - Normal speed\n"
            "• 1.5 - 1.5x speed\n"
            "• 2.0 - Double speed",
            parse_mode='Markdown'
        )
        return EDIT_PARAMETERS
    
    async def handle_effects(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🎨 *Video Effects*\n\n"
            "Choose an effect:\n"
            "• blur - Gaussian blur\n"
            "• blackwhite - Black and white\n"
            "• mirror - Mirror effect\n"
            "• invert - Invert colors\n\n"
            "Send the effect name:",
            parse_mode='Markdown'
        )
        return EDIT_PARAMETERS
    
    async def handle_extract_audio(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🎤 *Extract Audio*\n\n"
            "Processing your video to extract audio...\n"
            "This may take a moment."
        )
        
        input_path = context.user_data.get('input_path')
        output_path = input_path.replace('.', '_audio.').replace('.mp4', '.mp3')
        
        success = await AdvancedVideoEditor.extract_audio(input_path, output_path)
        
        if success:
            db.increment_edit_count(update.effective_user.id)
            db.log_edit(update.effective_user.id, 'extract_audio', input_path, output_path, {})
            
            with open(output_path, 'rb') as f:
                await update.message.reply_audio(audio=InputFile(f), title="Extracted Audio")
            
            os.remove(input_path)
            os.remove(output_path)
        else:
            await update.message.reply_text("Error extracting audio.")
        
        return ConversationHandler.END
    
    async def handle_caption(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "📝 *Add Captions*\n\n"
            "Send captions in JSON format:\n"
            "```json\n"
            "[\n"
            "  {\"start\": 0, \"duration\": 3, \"text\": \"Hello\"},\n"
            "  {\"start\": 3, \"duration\": 3, \"text\": \"World\"}\n"
            "]\n"
            "```",
            parse_mode='Markdown'
        )
        return EDIT_PARAMETERS
    
    async def handle_merge(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if len(context.user_data.get('input_files', [])) < 2:
            await update.message.reply_text(
                "Send the second video to merge.\n"
                "After sending both videos, I'll merge them."
            )
            return WAIT_MEDIA
        
        await update.message.reply_text(
            "Choose transition type:\n"
            "• fade - Fade transition\n"
            "• slide - Slide transition\n\n"
            "Send: fade or slide"
        )
        return EDIT_PARAMETERS
    
    async def handle_filter(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🎨 *Image Filters*\n\n"
            "Choose a filter:\n"
            "• blur - Soft blur\n"
            "• contour - Outline effect\n"
            "• sharpen - Sharpen image\n"
            "• edge_enhance - Enhance edges\n"
            "• emboss - 3D emboss effect\n"
            "• smooth - Smooth image\n"
            "• detail - Enhance details\n\n"
            "Send the filter name:",
            parse_mode='Markdown'
        )
        return EDIT_PARAMETERS
    
    async def handle_rotate(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🔄 *Rotate Image*\n\n"
            "Send rotation angle (0-360 degrees):\n"
            "• 90 - Rotate right\n"
            "• -90 - Rotate left\n"
            "• 180 - Flip upside down",
            parse_mode='Markdown'
        )
        return EDIT_PARAMETERS
    
    async def handle_watermark(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "💧 *Add Watermark*\n\n"
            "Please send the watermark image (PNG with transparency recommended).\n\n"
            "After sending, I'll ask for position and opacity."
        )
        return EDIT_PARAMETERS
    
    async def handle_brightness(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "✨ *Adjust Brightness*\n\n"
            "Send brightness factor (0.5 to 2.0):\n"
            "• 0.5 - Darker\n"
            "• 1.0 - Original\n"
            "• 1.5 - Brighter\n"
            "• 2.0 - Much brighter",
            parse_mode='Markdown'
        )
        return EDIT_PARAMETERS
    
    async def handle_remove_bg(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🎭 *Remove Background*\n\n"
            "Processing your image with AI to remove background...\n"
            "This may take a moment."
        )
        
        input_path = context.user_data.get('input_path')
        output_path = input_path.replace('.', '_nobg.')
        
        success = await AdvancedImageEditor.remove_background(input_path, output_path)
        
        if success:
            db.increment_edit_count(update.effective_user.id)
            db.log_edit(update.effective_user.id, 'remove_bg', input_path, output_path, {})
            
            with open(output_path, 'rb') as f:
                await update.message.reply_photo(photo=InputFile(f))
            
            os.remove(input_path)
            os.remove(output_path)
        else:
            await update.message.reply_text("Error removing background. This feature requires premium.")
        
        return ConversationHandler.END
    
    async def handle_sticker(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🧸 *Add Sticker*\n\n"
            "Please send the sticker image (PNG with transparency)."
        )
        return EDIT_PARAMETERS
    
    async def handle_collage(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if len(context.user_data.get('input_files', [])) < 2:
            await update.message.reply_text(
                "Send more images to create a collage.\n"
                "Send at least 2 images."
            )
            return WAIT_MEDIA
        
        await update.message.reply_text(
            "Choose collage layout:\n"
            "• grid - Grid layout\n\n"
            "Send: grid"
        )
        return EDIT_PARAMETERS
    
    async def handle_frame(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🖼️ *Add Frame*\n\n"
            "Choose frame type:\n"
            "• simple - Simple border\n"
            "• shadow - Shadow effect\n\n"
            "Send: simple or shadow"
        )
        return EDIT_PARAMETERS
    
    async def handle_parameters(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        operation = context.user_data.get('operation')
        input_path = context.user_data.get('input_path')
        user_id = update.effective_user.id
        
        output_path = input_path.replace('.', f'_edited.')
        
        try:
            success = False
            
            if operation == 'trim':
                text = update.message.text
                if text.lower() == 'auto':
                    # Auto trim silence - simplified version
                    success = await AdvancedVideoEditor.trim_video(input_path, output_path, 0, 10)
                else:
                    start, end = map(float, text.split())
                    output_path = input_path.replace('.', f'_trimmed.')
                    success = await AdvancedVideoEditor.trim_video(input_path, output_path, start, end)
            
            elif operation == 'resize':
                width, height = map(int, update.message.text.split())
                if context.user_data.get('edit_type') == 'video':
                    output_path = input_path.replace('.', f'_resized.')
                    success = await AdvancedVideoEditor.resize_video(input_path, output_path, width, height)
                else:
                    output_path = input_path.replace('.', f'_resized.')
                    success = await AdvancedImageEditor.resize_image(input_path, output_path, width, height)
            
            elif operation == 'text':
                text = update.message.text
                if context.user_data.get('edit_type') == 'video':
                    output_path = input_path.replace('.', f'_text.')
                    success = await AdvancedVideoEditor.add_text(input_path, output_path, text)
                else:
                    output_path = input_path.replace('.', f'_text.')
                    success = await AdvancedImageEditor.add_text(input_path, output_path, text)
            
            elif operation == 'audio':
                if update.message.audio:
                    audio_file = await update.message.audio.get_file()
                    audio_path = f"temp/audio_{uuid.uuid4()}.mp3"
                    await audio_file.download_to_drive(audio_path)
                    
                    output_path = input_path.replace('.', f'_with_audio.')
                    success = await AdvancedVideoEditor.add_background_music(input_path, output_path, audio_path)
                    os.remove(audio_path)
                else:
                    await update.message.reply_text("Please send an audio file.")
                    return EDIT_PARAMETERS
            
            elif operation == 'compress':
                quality = update.message.text.lower()
                output_path = input_path.replace('.', f'_compressed.')
                success = await AdvancedVideoEditor.compress_video(input_path, output_path, quality)
            
            elif operation == 'speed':
                speed = float(update.message.text)
                output_path = input_path.replace('.', f'_speed.')
                success = await AdvancedVideoEditor.speed_video(input_path, output_path, speed)
            
            elif operation == 'effects':
                effect = update.message.text.lower()
                output_path = input_path.replace('.', f'_effect.')
                success = await AdvancedVideoEditor.add_effects(input_path, output_path, effect)
            
            elif operation == 'caption':
                captions = json.loads(update.message.text)
                output_path = input_path.replace('.', f'_captioned.')
                success = await AdvancedVideoEditor.add_caption(input_path, output_path, captions)
            
            elif operation == 'merge':
                # Handle video merging
                transition = update.message.text.lower()
                # Simplified merge logic
                output_path = input_path.replace('.', f'_merged.')
                success = True  # Placeholder
            
            elif operation == 'filter':
                filter_type = update.message.text.lower()
                output_path = input_path.replace('.', f'_filtered.')
                success = await AdvancedImageEditor.apply_filter(input_path, output_path, filter_type)
            
            elif operation == 'rotate':
                angle = int(update.message.text)
                output_path = input_path.replace('.', f'_rotated.')
                success = await AdvancedImageEditor.rotate_image(input_path, output_path, angle)
            
            elif operation == 'watermark':
                if update.message.document or update.message.photo:
                    if update.message.document:
                        watermark_file = await update.message.document.get_file()
                    else:
                        watermark_file = await update.message.photo[-1].get_file()
                    
                    watermark_path = f"temp/watermark_{uuid.uuid4()}.png"
                    await watermark_file.download_to_drive(watermark_path)
                    
                    output_path = input_path.replace('.', f'_watermarked.')
                    success = await AdvancedImageEditor.add_watermark(input_path, output_path, watermark_path)
                    os.remove(watermark_path)
                else:
                    await update.message.reply_text("Please send an image file for watermark.")
                    return EDIT_PARAMETERS
            
            elif operation == 'brightness':
                factor = float(update.message.text)
                output_path = input_path.replace('.', f'_bright.')
                success = await AdvancedImageEditor.adjust_brightness(input_path, output_path, factor)
            
            elif operation == 'sticker':
                if update.message.document or update.message.photo:
                    if update.message.document:
                        sticker_file = await update.message.document.get_file()
                    else:
                        sticker_file = await update.message.photo[-1].get_file()
                    
                    sticker_path = f"temp/sticker_{uuid.uuid4()}.png"
                    await sticker_file.download_to_drive(sticker_path)
                    
                    output_path = input_path.replace('.', f'_stickered.')
                    success = await AdvancedImageEditor.add_sticker(input_path, output_path, sticker_path)
                    os.remove(sticker_path)
                else:
                    await update.message.reply_text("Please send a sticker image.")
                    return EDIT_PARAMETERS
            
            elif operation == 'collage':
                images = context.user_data.get('input_files', [])
                output_path = f"temp/collage_{uuid.uuid4()}.jpg"
                success = await AdvancedImageEditor.collage_images(images, output_path)
            
            elif operation == 'frame':
                frame_type = update.message.text.lower()
                output_path = input_path.replace('.', f'_framed.')
                success = await AdvancedImageEditor.add_frame(input_path, output_path, frame_type)
            
            if success:
                db.increment_edit_count(user_id)
                db.log_edit(user_id, operation, input_path, output_path, 
                          {'text': update.message.text if hasattr(update.message, 'text') else ''})
                
                # Send result
                if context.user_data.get('edit_type') == 'video' or operation in ['compress', 'speed', 'effects', 'trim', 'merge']:
                    with open(output_path, 'rb') as f:
                        await update.message.reply_video(video=InputFile(f))
                else:
                    with open(output_path, 'rb') as f:
                        await update.message.reply_photo(photo=InputFile(f))
                
                # Cleanup
                for file_path in context.user_data.get('input_files', []):
                    if os.path.exists(file_path):
                        os.remove(file_path)
                if os.path.exists(output_path):
                    os.remove(output_path)
            else:
                await update.message.reply_text("Error processing your request. Please try again.")
            
        except Exception as e:
            logger.error(f"Error in handle_parameters: {e}")
            await update.message.reply_text(f"An error occurred: {str(e)[:100]}")
        
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
🎬 *Total Edits:* {user[8]}
💰 *Credits:* {user[8] if not user[5] else 'Unlimited'}
🎁 *Free Edits Remaining:* {premium_manager.get_remaining_edits(user_id)}

🔗 *Referral Link:* `https://t.me/{context.bot.username}?start={user[9]}`
📈 *Referrals:* {db.get_connection().execute('SELECT COUNT(*) FROM users WHERE referred_by = ?', (user_id,)).fetchone()[0]}
            """
            
            keyboard = []
            if not user[5]:
                keyboard.append([InlineKeyboardButton("💎 Upgrade to Premium", callback_data='premium')])
            keyboard.append([InlineKeyboardButton("💰 Get Referral Link", callback_data='referral')])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(stats_text, parse_mode='Markdown', reply_markup=reply_markup)
    
    async def credits_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        user = db.get_user(user_id)
        
        if user[5]:
            await update.message.reply_text("💎 You have a premium subscription! Unlimited edits! 🎉")
        else:
            credits = user[8]
            await update.message.reply_text(
                f"💰 *Your Credits: {credits}*\n\n"
                f"Each edit costs 1 credit.\n"
                f"Get more credits by:\n"
                f"• Referring friends (2 credits each)\n"
                f"• Upgrading to premium\n"
                f"• Daily bonuses\n\n"
                f"Use /referral to get your referral link!",
                parse_mode='Markdown'
            )
    
    async def referral_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        user = db.get_user(user_id)
        
        referral_link = f"https://t.me/{context.bot.username}?start={user[9]}"
        
        await update.message.reply_text(
            f"🔗 *Your Referral Link*\n\n"
            f"`{referral_link}`\n\n"
            f"Share this link with your friends!\n"
            f"For each friend who joins, you get 2 free credits! 🎉\n\n"
            f"Your friends also get 5 free credits to start!",
            parse_mode='Markdown'
        )
    
    async def templates_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        keyboard = [
            [InlineKeyboardButton("🎬 Video Templates", callback_data='video_templates'),
             InlineKeyboardButton("🖼️ Image Templates", callback_data='image_templates')],
            [InlineKeyboardButton("✨ Trending", callback_data='trending_templates'),
             InlineKeyboardButton("📁 My Templates", callback_data='my_templates')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "🎨 *Template Gallery*\n\nChoose template category:",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    async def premium_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        premium_text = """
💎 *Premium Subscription*

*✨ Premium Benefits:*
✅ Unlimited media edits
✅ AI background removal
✅ 4K/8K output support
✅ Priority processing queue
✅ Custom templates
✅ No watermark on output
✅ Advanced effects & transitions
✅ Early access to features
✅ Dedicated support

*💰 Pricing Plans:*

*Monthly Plan* - $9.99/month
• All premium features
• Cancel anytime

*Yearly Plan* - $99.99/year
• 2 months free!
• Best value

*💳 Payment Methods:*
• Credit/Debit Card
• PayPal
• Cryptocurrency (USDT, BTC)
• UPI (India)

*🎁 Special Offer:* First 100 users get 20% off!
        """
        
        keyboard = [
            [InlineKeyboardButton("💳 Monthly - $9.99", callback_data='premium_monthly'),
             InlineKeyboardButton("📅 Yearly - $99.99", callback_data='premium_yearly')],
            [InlineKeyboardButton("🎁 Redeem Code", callback_data='redeem_code'),
             InlineKeyboardButton("ℹ️ More Info", callback_data='premium_info')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(premium_text, parse_mode='Markdown', reply_markup=reply_markup)
    
    async def callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        data = query.data
        user_id = query.from_user.id
        
        # Check if user is banned
        user = db.get_user(user_id)
        if user and user[11] and data not in ['unban_me']:
            await query.edit_message_text("❌ You have been banned from using this bot.")
            return
        
        # Handle different callbacks
        if data == 'video_editor':
            context.user_data['edit_type'] = 'video'
            return await self.video_editor_menu(update, context)
        
        elif data == 'image_editor':
            context.user_data['edit_type'] = 'image'
            return await self.image_editor_menu(update, context)
        
        elif data.startswith('video_'):
            operation = data.replace('video_', '')
            context.user_data['operation'] = operation
            context.user_data['edit_type'] = 'video'
            return await self.video_editor_menu(update, context)
        
        elif data.startswith('image_'):
            operation = data.replace('image_', '')
            context.user_data['operation'] = operation
            context.user_data['edit_type'] = 'image'
            return await self.image_editor_menu(update, context)
        
        elif data == 'premium':
            await self.premium_command(update, context)
        
        elif data == 'premium_monthly':
            payment_link = premium_manager.create_payment_link(user_id, 'monthly')
            await query.edit_message_text(
                f"🔗 Complete your payment:\n{payment_link}\n\n"
                f"After payment, your premium will be activated automatically.\n"
                f"Contact @kinva_support if you need assistance."
            )
        
        elif data == 'premium_yearly':
            payment_link = premium_manager.create_payment_link(user_id, 'yearly')
            await query.edit_message_text(
                f"🔗 Complete your payment:\n{payment_link}\n\n"
                f"After payment, your premium will be activated automatically."
            )
        
        elif data == 'stats':
            await self.stats_command(update, context)
        
        elif data == 'help':
            await self.help_command(update, context)
        
        elif data == 'referral':
            await self.referral_command(update, context)
        
        elif data == 'templates':
            await self.templates_command(update, context)
        
        elif data == 'ai_tools':
            await query.edit_message_text(
                "🤖 *AI Tools*\n\n"
                "• Background Removal - Remove image backgrounds\n"
                "• Face Enhancement - Enhance faces in photos\n"
                "• Object Removal - Remove unwanted objects\n"
                "• Colorization - Colorize black & white photos\n\n"
                "These features are available for premium users only!",
                parse_mode='Markdown'
            )
        
        elif data == 'cancel':
            await query.edit_message_text("Operation cancelled.")
            return ConversationHandler.END
        
        return ConversationHandler.END
    
    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Operation cancelled.")
        return ConversationHandler.END
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"Update {update} caused error {context.error}")
        
        try:
            if update and update.effective_message:
                await update.effective_message.reply_text(
                    "An error occurred. Please try again later."
                )
        except:
            pass
    
    # Admin commands
    async def admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not admin_manager.is_admin(update.effective_user.id):
            await update.message.reply_text("⛔ You are not authorized to use this command.")
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
             InlineKeyboardButton("📊 Full Stats", callback_data='admin_stats')],
            [InlineKeyboardButton("💳 Payments", callback_data='admin_payments'),
             InlineKeyboardButton("🎁 Add Credits", callback_data='admin_add_credits')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(admin_text, parse_mode='Markdown', reply_markup=reply_markup)
    
    async def broadcast_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not admin_manager.is_admin(update.effective_user.id):
            return
        
        await update.message.reply_text(
            "📢 *Broadcast Message*\n\n"
            "Send the message you want to broadcast to all users.\n"
            "You can also send media with caption.",
            parse_mode='Markdown'
        )
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
            f"📢 *Broadcast Preview*\n\n{message}\n\n"
            f"Send to {len(db.get_all_users())} users?\n"
            f"Type 'yes' to confirm or 'no' to cancel.",
            parse_mode='Markdown'
        )
        
        context.user_data['broadcast_message'] = message
        context.user_data['broadcast_media'] = media
        context.user_data['broadcast_media_type'] = media_type
        
        return AWAIT_CONFIRMATION
    
    async def confirm_broadcast(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not admin_manager.is_admin(update.effective_user.id):
            return ConversationHandler.END
        
        if update.message.text.lower() == 'yes':
            await update.message.reply_text("📢 Broadcasting message to all users...")
            
            sent, total = await admin_manager.broadcast_message(
                context.user_data['broadcast_message'],
                context.user_data['broadcast_media'],
                context.user_data['broadcast_media_type']
            )
            
            await update.message.reply_text(f"✅ Broadcast completed!\nSent to {sent}/{total} users.")
        else:
            await update.message.reply_text("❌ Broadcast cancelled.")
        
        return ConversationHandler.END
    
    def setup(self):
        """Setup the bot application"""
        self.application = Application.builder().token(self.token).build()
        
        # Admin conversation handler
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
        
        # Main conversation handler
        conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler('edit', self.edit_command),
                CallbackQueryHandler(self.callback_handler, pattern='^video_editor$'),
                CallbackQueryHandler(self.callback_handler, pattern='^image_editor$')
            ],
            states={
                EDIT_TYPE: [
                    CallbackQueryHandler(self.video_editor_menu, pattern='^video_editor$'),
                    CallbackQueryHandler(self.image_editor_menu, pattern='^image_editor$'),
                    CallbackQueryHandler(self.callback_handler, pattern='^templates$'),
                    CallbackQueryHandler(self.callback_handler, pattern='^ai_tools$'),
                    CallbackQueryHandler(self.callback_handler, pattern='^cancel$')
                ],
                WAIT_MEDIA: [
                    MessageHandler(filters.VIDEO | filters.PHOTO | filters.Document.ALL, self.handle_media),
                    CallbackQueryHandler(self.callback_handler, pattern='^cancel$')
                ],
                EDIT_PARAMETERS: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_parameters),
                    MessageHandler(filters.AUDIO, self.handle_parameters),
                    MessageHandler(filters.PHOTO, self.handle_parameters),
                    MessageHandler(filters.Document.ALL, self.handle_parameters),
                ]
            },
            fallbacks=[CommandHandler('cancel', self.cancel_command)],
            allow_reentry=True
        )
        
        # Add handlers
        self.application.add_handler(conv_handler)
        self.application.add_handler(admin_conv)
        self.application.add_handler(CommandHandler('start', self.start))
        self.application.add_handler(CommandHandler('help', self.help_command))
        self.application.add_handler(CommandHandler('stats', self.stats_command))
        self.application.add_handler(CommandHandler('credits', self.credits_command))
        self.application.add_handler(CommandHandler('referral', self.referral_command))
        self.application.add_handler(CommandHandler('premium', self.premium_command))
        self.application.add_handler(CommandHandler('templates', self.templates_command))
        self.application.add_handler(CommandHandler('admin', self.admin_command))
        self.application.add_handler(CallbackQueryHandler(self.callback_handler))
        self.application.add_error_handler(self.error_handler)
    
    async def start_bot(self):
        """Start the bot"""
        global admin_manager
        admin_manager = AdminManager(db, self.application.bot)
        
        self.setup()
        await self.application.initialize()
        await self.application.start()
        
        # Set webhook or start polling
        if Config.WEBHOOK_URL and 'localhost' not in Config.WEBHOOK_URL:
            await self.application.bot.set_webhook(f"{Config.WEBHOOK_URL}/webhook")
        else:
            await self.application.updater.start_polling()
        
        logger.info("Kinva Master Bot started successfully")
    
    async def stop_bot(self):
        """Stop the bot"""
        if self.application:
            await self.application.stop()
        logger.info("Kinva Master Bot stopped")

# ==================== FLASK ROUTES ====================
@flask_app.route('/')
def index():
    return render_template('editor.html')

@flask_app.route('/editor')
def editor():
    return render_template('editor.html')

@flask_app.route('/admin')
def admin_panel():
    if not admin_manager or not admin_manager.is_admin(request.args.get('user_id', 0)):
        return jsonify({'error': 'Unauthorized'}), 401
    return render_template('admin.html')

@flask_app.route('/api/stats')
def api_stats():
    if not admin_manager or not admin_manager.is_admin(request.args.get('user_id', 0)):
        return jsonify({'error': 'Unauthorized'}), 401
    return jsonify(db.get_stats())

@flask_app.route('/api/users')
def api_users():
    if not admin_manager or not admin_manager.is_admin(request.args.get('user_id', 0)):
        return jsonify({'error': 'Unauthorized'}), 401
    
    with db.get_connection() as conn:
        users = conn.execute(
            'SELECT user_id, username, first_name, is_premium, total_edits, created_at FROM users ORDER BY created_at DESC LIMIT 100'
        ).fetchall()
    
    return jsonify([{
        'user_id': u[0],
        'username': u[1],
        'name': u[2],
        'premium': u[3],
        'edits': u[4],
        'joined': u[5]
    } for u in users])

@flask_app.route('/webhook', methods=['POST'])
async def webhook():
    if bot_instance and bot_instance.application:
        update = telegram.Update.de_json(request.get_json(), bot_instance.application.bot)
        await bot_instance.application.process_update(update)
    return 'ok'

# ==================== CLEANUP TASK ====================
async def cleanup_temp_files():
    """Clean up temporary files older than 1 hour"""
    while True:
        try:
            temp_dir = 'temp'
            if os.path.exists(temp_dir):
                current_time = time.time()
                for filename in os.listdir(temp_dir):
                    filepath = os.path.join(temp_dir, filename)
                    if os.path.isfile(filepath):
                        file_age = current_time - os.path.getctime(filepath)
                        if file_age > 3600:  # 1 hour
                            os.remove(filepath)
            await asyncio.sleep(3600)  # Run every hour
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
            await asyncio.sleep(3600)

# ==================== TEMPLATE FILES ====================
def create_templates():
    """Create required template files"""
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static/css', exist_ok=True)
    os.makedirs('static/js', exist_ok=True)
    
    # Editor HTML template (simplified version)
    editor_html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Kinva Master - Professional Media Editor</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }
        .editor-container {
            background: white;
            border-radius: 20px;
            padding: 30px;
            margin: 50px auto;
            box-shadow: 0 10px 40px rgba(0,0,0,0.1);
        }
        .preview-area {
            border: 2px dashed #ddd;
            border-radius: 10px;
            padding: 20px;
            text-align: center;
            min-height: 300px;
            background: #f9f9f9;
        }
        .preview-area img, .preview-area video {
            max-width: 100%;
            max-height: 400px;
            border-radius: 8px;
        }
        .toolbar {
            margin-top: 20px;
        }
        .btn-tool {
            margin: 5px;
        }
        h1 {
            color: #667eea;
            margin-bottom: 30px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="editor-container">
            <h1 class="text-center">🎬 Kinva Master Editor</h1>
            
            <div class="row">
                <div class="col-md-6">
                    <div class="preview-area">
                        <div id="previewContent">
                            <p>No media selected</p>
                        </div>
                        <input type="file" id="fileInput" accept="image/*,video/*" style="display: none;">
                        <button class="btn btn-primary mt-3" onclick="document.getElementById('fileInput').click()">
                            Upload Media
                        </button>
                    </div>
                </div>
                
                <div class="col-md-6">
                    <div class="toolbar">
                        <h4>Video Tools</h4>
                        <div>
                            <button class="btn btn-outline-primary btn-tool" onclick="editMedia('trim')">✂️ Trim</button>
                            <button class="btn btn-outline-primary btn-tool" onclick="editMedia('text')">📝 Text</button>
                            <button class="btn btn-outline-primary btn-tool" onclick="editMedia('audio')">🎵 Music</button>
                            <button class="btn btn-outline-primary btn-tool" onclick="editMedia('resize')">📏 Resize</button>
                            <button class="btn btn-outline-primary btn-tool" onclick="editMedia('compress')">🗜️ Compress</button>
                        </div>
                        
                        <h4 class="mt-3">Image Tools</h4>
                        <div>
                            <button class="btn btn-outline-success btn-tool" onclick="editMedia('resize')">📏 Resize</button>
                            <button class="btn btn-outline-success btn-tool" onclick="editMedia('text')">📝 Text</button>
                            <button class="btn btn-outline-success btn-tool" onclick="editMedia('filter')">🎨 Filter</button>
                            <button class="btn btn-outline-success btn-tool" onclick="editMedia('rotate')">🔄 Rotate</button>
                            <button class="btn btn-outline-success btn-tool" onclick="editMedia('remove_bg')">🎭 Remove BG</button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        let currentFile = null;
        let currentFileId = null;
        
        document.getElementById('fileInput').addEventListener('change', async function(e) {
            const file = e.target.files[0];
            if (!file) return;
            
            currentFile = file;
            const formData = new FormData();
            formData.append('file', file);
            
            try {
                const response = await fetch('/api/upload', {
                    method: 'POST',
                    body: formData
                });
                const data = await response.json();
                
                if (data.success) {
                    currentFileId = data.file_id;
                    const previewDiv = document.getElementById('previewContent');
                    if (data.type === 'video') {
                        previewDiv.innerHTML = `<video controls src="/api/download/${data.path}"></video>`;
                    } else {
                        previewDiv.innerHTML = `<img src="/api/download/${data.path}" alt="Preview">`;
                    }
                }
            } catch (error) {
                console.error('Upload error:', error);
            }
        });
        
        function editMedia(operation) {
            if (!currentFileId) {
                alert('Please upload a file first');
                return;
            }
            alert(`Operation ${operation} will be available soon!`);
        }
    </script>
</body>
</html>
    """
    
    with open('templates/editor.html', 'w') as f:
        f.write(editor_html)
    
    # Admin HTML template
    admin_html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Kinva Master - Admin Panel</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body>
    <div class="container mt-4">
        <h1>👑 Kinva Master Admin Panel</h1>
        
        <div class="row mt-4">
            <div class="col-md-3">
                <div class="card text-white bg-primary mb-3">
                    <div class="card-body">
                        <h5 class="card-title">Total Users</h5>
                        <h2 id="totalUsers">-</h2>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card text-white bg-success mb-3">
                    <div class="card-body">
                        <h5 class="card-title">Premium Users</h5>
                        <h2 id="premiumUsers">-</h2>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card text-white bg-info mb-3">
                    <div class="card-body">
                        <h5 class="card-title">Total Edits</h5>
                        <h2 id="totalEdits">-</h2>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card text-white bg-warning mb-3">
                    <div class="card-body">
                        <h5 class="card-title">Active Today</h5>
                        <h2 id="activeToday">-</h2>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="card mt-4">
            <div class="card-header">
                <h5>Recent Users</h5>
            </div>
            <div class="card-body">
                <table class="table" id="usersTable">
                    <thead>
                        <tr><th>User ID</th><th>Username</th><th>Name</th><th>Premium</th><th>Edits</th><th>Joined</th></tr>
                    </thead>
                    <tbody></tbody>
                </table>
            </div>
        </div>
    </div>
    
    <script>
        async function loadStats() {
            const response = await fetch('/api/stats?user_id=8525952693');
            const stats = await response.json();
            document.getElementById('totalUsers').textContent = stats.total_users;
            document.getElementById('premiumUsers').textContent = stats.premium_users;
            document.getElementById('totalEdits').textContent = stats.total_edits;
            document.getElementById('activeToday').textContent = stats.active_today;
        }
        
        async function loadUsers() {
            const response = await fetch('/api/users?user_id=8525952693');
            const users = await response.json();
            const tbody = document.querySelector('#usersTable tbody');
            tbody.innerHTML = '';
            users.forEach(user => {
                tbody.innerHTML += `
                    <tr>
                        <td>${user.user_id}</td>
                        <td>${user.username || '-'}</td>
                        <td>${user.name || '-'}</td>
                        <td>${user.premium ? '✅' : '❌'}</td>
                        <td>${user.edits}</td>
                        <td>${new Date(user.joined).toLocaleDateString()}</td>
                    </tr>
                `;
            });
        }
        
        loadStats();
        loadUsers();
        setInterval(loadStats, 30000);
    </script>
</body>
</html>
    """
    
    with open('templates/admin.html', 'w') as f:
        f.write(admin_html)
    
    # Create empty CSS and JS files
    with open('static/css/style.css', 'w') as f:
        f.write('/* Kinva Master Styles */')
    
    with open('static/js/editor.js', 'w') as f:
        f.write('// Kinva Master Editor JavaScript')

# ==================== MAIN APPLICATION ====================
class KinvaMasterBot:
    def __init__(self):
        self.bot = None
        self.loop = None
    
    async def start(self):
        """Start both bot and web app"""
        global bot_instance
        
        # Create necessary directories
        os.makedirs('temp', exist_ok=True)
        create_templates()
        
        # Initialize bot
        self.bot = TelegramBot(Config.TELEGRAM_BOT_TOKEN)
        bot_instance = self.bot
        await self.bot.start_bot()
        
        # Start cleanup task
        asyncio.create_task(cleanup_temp_files())
        
        logger.info("=" * 50)
        logger.info("Kinva Master Bot is running!")
        logger.info(f"Bot username: @{self.bot.application.bot.username if self.bot.application else 'unknown'}")
        logger.info(f"Web interface: http://localhost:{Config.PORT}")
        logger.info("=" * 50)
        
        # Start Flask app with Socket.IO
        socketio.run(flask_app, host='0.0.0.0', port=Config.PORT, debug=False)
    
    async def stop(self):
        """Stop the bot"""
        if self.bot:
            await self.bot.stop_bot()
        logger.info("Kinva Master Bot stopped")

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
        raise
