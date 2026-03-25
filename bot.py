"""
Kinva Master Bot - Complete Single File Implementation
Telegram bot with video/image editing, web interface, and premium features
"""

import os
import logging
import sqlite3
import asyncio
import json
import uuid
import shutil
import subprocess
import datetime
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from functools import wraps
import threading
import queue
import time

# Web framework imports
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_socketio import SocketIO, emit

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
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import moviepy as mp
from moviepy.video.fx import resize, rotate, crop
import imageio

# Utilities
import requests
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

# Configuration
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

# Database Manager
class DatabaseManager:
    def __init__(self, db_path='kinva_master.db'):
        self.db_path = db_path
        self.init_db()
    
    def get_connection(self):
        return sqlite3.connect(self.db_path)
    
    def init_db(self):
        with self.get_connection() as conn:
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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
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
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    amount REAL,
                    payment_id TEXT,
                    status TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
    
    def create_user(self, user_id, username=None, first_name=None, last_name=None):
        with self.get_connection() as conn:
            conn.execute(
                '''INSERT OR IGNORE INTO users 
                   (user_id, username, first_name, last_name) 
                   VALUES (?, ?, ?, ?)''',
                (user_id, username, first_name, last_name)
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
        if user and user[5]:  # is_premium
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

# Video Editor
class VideoEditor:
    @staticmethod
    async def trim_video(input_path, output_path, start_time, end_time):
        try:
            video = mp.VideoFileClip(input_path)
            trimmed = video.subclip(start_time, end_time)
            trimmed.write_videofile(output_path, codec='libx264', audio_codec='aac')
            video.close()
            trimmed.close()
            return True
        except Exception as e:
            logger.error(f"Error trimming video: {e}")
            return False
    
    @staticmethod
    async def add_text(input_path, output_path, text, position='center', font_size=30):
        try:
            video = mp.VideoFileClip(input_path)
            
            def make_text(txt):
                txt_clip = mp.TextClip(txt, fontsize=font_size, color='white', 
                                       font='Arial', stroke_color='black', stroke_width=2)
                return txt_clip.set_position(position).set_duration(video.duration)
            
            text_clip = make_text(text)
            final = mp.CompositeVideoClip([video, text_clip])
            final.write_videofile(output_path, codec='libx264', audio_codec='aac')
            
            video.close()
            text_clip.close()
            final.close()
            return True
        except Exception as e:
            logger.error(f"Error adding text to video: {e}")
            return False
    
    @staticmethod
    async def add_audio(input_path, output_path, audio_path, volume=1.0):
        try:
            video = mp.VideoFileClip(input_path)
            audio = mp.AudioFileClip(audio_path)
            
            # Adjust audio duration to match video
            if audio.duration > video.duration:
                audio = audio.subclip(0, video.duration)
            else:
                audio = audio.loop(duration=video.duration)
            
            # Set volume
            audio = audio.volumex(volume)
            
            # Combine
            final = video.set_audio(audio)
            final.write_videofile(output_path, codec='libx264', audio_codec='aac')
            
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
            resized.write_videofile(output_path, codec='libx264', audio_codec='aac')
            video.close()
            resized.close()
            return True
        except Exception as e:
            logger.error(f"Error resizing video: {e}")
            return False
    
    @staticmethod
    async def compress_video(input_path, output_path, bitrate='500k'):
        try:
            video = mp.VideoFileClip(input_path)
            video.write_videofile(output_path, bitrate=bitrate, codec='libx264', audio_codec='aac')
            video.close()
            return True
        except Exception as e:
            logger.error(f"Error compressing video: {e}")
            return False

# Image Editor
class ImageEditor:
    @staticmethod
    async def resize_image(input_path, output_path, width, height):
        try:
            img = Image.open(input_path)
            img_resized = img.resize((width, height), Image.Resampling.LANCZOS)
            img_resized.save(output_path)
            img.close()
            return True
        except Exception as e:
            logger.error(f"Error resizing image: {e}")
            return False
    
    @staticmethod
    async def add_text(input_path, output_path, text, position=(10, 10), font_size=20):
        try:
            img = Image.open(input_path)
            draw = ImageDraw.Draw(img)
            
            # Try to load a font, fallback to default
            try:
                font = ImageFont.truetype("arial.ttf", font_size)
            except:
                font = ImageFont.load_default()
            
            draw.text(position, text, fill="white", font=font)
            img.save(output_path)
            img.close()
            return True
        except Exception as e:
            logger.error(f"Error adding text to image: {e}")
            return False
    
    @staticmethod
    async def apply_filter(input_path, output_path, filter_type):
        try:
            img = Image.open(input_path)
            
            if filter_type == 'blur':
                img = img.filter(ImageFilter.BLUR)
            elif filter_type == 'contour':
                img = img.filter(ImageFilter.CONTOUR)
            elif filter_type == 'sharpen':
                img = img.filter(ImageFilter.SHARPEN)
            elif filter_type == 'edge_enhance':
                img = img.filter(ImageFilter.EDGE_ENHANCE)
            elif filter_type == 'emboss':
                img = img.filter(ImageFilter.EMBOSS)
            
            img.save(output_path)
            img.close()
            return True
        except Exception as e:
            logger.error(f"Error applying filter to image: {e}")
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
    async def add_watermark(input_path, output_path, watermark_path, position='bottom-right'):
        try:
            img = Image.open(input_path)
            watermark = Image.open(watermark_path)
            
            # Calculate position
            if position == 'bottom-right':
                x = img.width - watermark.width - 10
                y = img.height - watermark.height - 10
            elif position == 'bottom-left':
                x = 10
                y = img.height - watermark.height - 10
            elif position == 'top-right':
                x = img.width - watermark.width - 10
                y = 10
            elif position == 'top-left':
                x = 10
                y = 10
            
            img.paste(watermark, (x, y), watermark if watermark.mode == 'RGBA' else None)
            img.save(output_path)
            img.close()
            watermark.close()
            return True
        except Exception as e:
            logger.error(f"Error adding watermark: {e}")
            return False

# Premium Manager
class PremiumManager:
    def __init__(self, db):
        self.db = db
    
    def check_edit_limit(self, user_id):
        if self.db.check_premium(user_id):
            return True  # Premium users have no limit
        
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
    
    def create_premium_invoice(self, user_id, days=30):
        # This would integrate with payment gateway (Stripe, PayPal, etc.)
        # For demo purposes, return a dummy payment link
        payment_id = str(uuid.uuid4())
        amount = Config.PREMIUM_PRICE
        
        self.db.get_connection().execute(
            'INSERT INTO payments (user_id, amount, payment_id, status) VALUES (?, ?, ?, ?)',
            (user_id, amount, payment_id, 'pending')
        )
        self.db.get_connection().commit()
        
        # Return payment link (in production, integrate with actual payment provider)
        return f"https://your-payment-gateway.com/pay/{payment_id}"
    
    def verify_payment(self, payment_id):
        # Verify payment with payment provider
        # For demo, just return success
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

# Error Handler
class ErrorHandler:
    @staticmethod
    def handle_error(error, context=None):
        logger.error(f"Error occurred: {error}")
        if context:
            logger.error(f"Context: {context}")
        
        # Send alert to admin if needed
        if Config.ADMIN_IDS:
            # Would send Telegram message to admin
            pass

# Flask Web Application
flask_app = Flask(__name__)
flask_app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'your-secret-key')
socketio = SocketIO(flask_app, cors_allowed_origins="*")

# Global bot instance (will be initialized later)
bot_instance = None
db = DatabaseManager()
premium_manager = PremiumManager(db)

# Conversation states
(EDIT_TYPE, WAIT_MEDIA, EDIT_PARAMETERS) = range(3)

# Telegram Bot Handlers
class TelegramBot:
    def __init__(self, token):
        self.token = token
        self.application = None
        self.user_data = {}
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        db.create_user(user.id, user.username, user.first_name, user.last_name)
        
        welcome_text = f"""
🎬 Welcome to Kinva Master Bot, {user.first_name}!

I'm your all-in-one media editing assistant. I can help you edit videos and images with powerful tools.

✨ Features:
• Trim videos
• Add text to videos/images
• Add background music to videos
• Resize videos/images
• Apply filters to images
• Add watermarks
• Compress videos
• And much more!

💎 Premium Features:
• Unlimited edits
• Advanced effects
• Priority processing
• High-quality output

🎁 Free trial: {Config.FREE_TRIAL_DAYS} days premium or {Config.MAX_FREE_EDITS} free edits!

Use /help to see all commands.
        """
        
        keyboard = [
            [InlineKeyboardButton("✂️ Edit Video", callback_data='edit_video'),
             InlineKeyboardButton("🖼️ Edit Image", callback_data='edit_image')],
            [InlineKeyboardButton("💎 Premium", callback_data='premium'),
             InlineKeyboardButton("📊 Stats", callback_data='stats')],
            [InlineKeyboardButton("❓ Help", callback_data='help')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(welcome_text, reply_markup=reply_markup)
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = """
📚 *Available Commands:*

/start - Start the bot
/help - Show this help message
/edit - Start editing media
/stats - View your usage statistics
/premium - Get premium subscription
/cancel - Cancel current operation

*Editing Features:*
• *Video Editing*
  - Trim videos
  - Add text overlay
  - Add background music
  - Resize videos
  - Compress videos

• *Image Editing*
  - Resize images
  - Add text
  - Apply filters
  - Rotate images
  - Add watermarks

*Premium Benefits:*
✅ Unlimited edits
✅ Advanced effects
✅ Priority queue
✅ 4K output support
✅ Custom watermark removal

*Support:* Contact @kinva_support for assistance
        """
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def edit_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        # Check edit limit
        if not premium_manager.check_edit_limit(update.effective_user.id):
            remaining = premium_manager.get_remaining_edits(update.effective_user.id)
            await update.message.reply_text(
                f"⚠️ You've used all your free edits ({remaining} remaining).\n"
                f"Upgrade to premium for unlimited edits! Use /premium"
            )
            return
        
        keyboard = [
            [InlineKeyboardButton("🎬 Video", callback_data='edit_type_video'),
             InlineKeyboardButton("🖼️ Image", callback_data='edit_type_image')],
            [InlineKeyboardButton("❌ Cancel", callback_data='cancel')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "What would you like to edit?",
            reply_markup=reply_markup
        )
        return EDIT_TYPE
    
    async def edit_type_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        if query.data == 'edit_type_video':
            context.user_data['edit_type'] = 'video'
            keyboard = [
                [InlineKeyboardButton("✂️ Trim", callback_data='video_trim'),
                 InlineKeyboardButton("📝 Add Text", callback_data='video_text')],
                [InlineKeyboardButton("🎵 Add Audio", callback_data='video_audio'),
                 InlineKeyboardButton("📏 Resize", callback_data='video_resize')],
                [InlineKeyboardButton("🗜️ Compress", callback_data='video_compress'),
                 InlineKeyboardButton("❌ Cancel", callback_data='cancel')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "Choose video editing operation:",
                reply_markup=reply_markup
            )
        elif query.data == 'edit_type_image':
            context.user_data['edit_type'] = 'image'
            keyboard = [
                [InlineKeyboardButton("📏 Resize", callback_data='image_resize'),
                 InlineKeyboardButton("📝 Add Text", callback_data='image_text')],
                [InlineKeyboardButton("🎨 Apply Filter", callback_data='image_filter'),
                 InlineKeyboardButton("🔄 Rotate", callback_data='image_rotate')],
                [InlineKeyboardButton("💧 Add Watermark", callback_data='image_watermark'),
                 InlineKeyboardButton("❌ Cancel", callback_data='cancel')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "Choose image editing operation:",
                reply_markup=reply_markup
            )
        
        return WAIT_MEDIA
    
    async def handle_media(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        # Get the operation type
        operation = context.user_data.get('operation')
        
        if not operation:
            await update.message.reply_text("Please select an operation first using /edit")
            return ConversationHandler.END
        
        # Check if media is provided
        if update.message.video:
            media_file = await update.message.video.get_file()
            file_ext = 'mp4'
        elif update.message.document:
            media_file = await update.message.document.get_file()
            file_ext = update.message.document.file_name.split('.')[-1]
        elif update.message.photo:
            # Get the largest photo
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
        
        # Process based on operation
        if operation == 'trim':
            await update.message.reply_text(
                "Send the trim duration in format: start end\n"
                "Example: 10 30 (trims from 10s to 30s)"
            )
            return EDIT_PARAMETERS
        
        elif operation == 'resize':
            await update.message.reply_text(
                "Send the new dimensions in format: width height\n"
                "Example: 1920 1080"
            )
            return EDIT_PARAMETERS
        
        elif operation == 'text':
            await update.message.reply_text(
                "Send the text you want to add to your media:"
            )
            return EDIT_PARAMETERS
        
        elif operation == 'audio':
            await update.message.reply_text(
                "Please send the audio file you want to add as background music:"
            )
            return EDIT_PARAMETERS
        
        elif operation == 'filter':
            await update.message.reply_text(
                "Choose a filter:\n"
                "• blur\n"
                "• contour\n"
                "• sharpen\n"
                "• edge_enhance\n"
                "• emboss"
            )
            return EDIT_PARAMETERS
        
        elif operation == 'rotate':
            await update.message.reply_text(
                "Send the rotation angle in degrees (0-360):"
            )
            return EDIT_PARAMETERS
        
        elif operation == 'watermark':
            await update.message.reply_text(
                "Please send the watermark image:"
            )
            return EDIT_PARAMETERS
        
        elif operation == 'compress':
            await update.message.reply_text(
                "Processing compression... (this may take a moment)"
            )
            # Process compression directly
            output_path = input_path.replace(f".{file_ext}", f"_compressed.{file_ext}")
            success = await VideoEditor.compress_video(input_path, output_path)
            
            if success:
                db.increment_edit_count(update.effective_user.id)
                db.log_edit(update.effective_user.id, 'compress', input_path, output_path, {})
                
                with open(output_path, 'rb') as f:
                    await update.message.reply_video(video=InputFile(f))
                
                # Cleanup
                os.remove(input_path)
                os.remove(output_path)
            else:
                await update.message.reply_text("Error compressing video.")
            
            return ConversationHandler.END
        
        return EDIT_PARAMETERS
    
    async def handle_parameters(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        operation = context.user_data.get('operation')
        input_path = context.user_data.get('input_path')
        user_id = update.effective_user.id
        
        output_path = input_path.replace('.', f'_edited.')
        
        try:
            if operation == 'trim':
                start, end = map(float, update.message.text.split())
                output_path = input_path.replace('.', f'_trimmed.')
                success = await VideoEditor.trim_video(input_path, output_path, start, end)
                
            elif operation == 'resize':
                width, height = map(int, update.message.text.split())
                if context.user_data['edit_type'] == 'video':
                    output_path = input_path.replace('.', f'_resized.')
                    success = await VideoEditor.resize_video(input_path, output_path, width, height)
                else:
                    output_path = input_path.replace('.', f'_resized.')
                    success = await ImageEditor.resize_image(input_path, output_path, width, height)
            
            elif operation == 'text':
                text = update.message.text
                if context.user_data['edit_type'] == 'video':
                    output_path = input_path.replace('.', f'_text.')
                    success = await VideoEditor.add_text(input_path, output_path, text)
                else:
                    output_path = input_path.replace('.', f'_text.')
                    success = await ImageEditor.add_text(input_path, output_path, text)
            
            elif operation == 'audio':
                # Handle audio file
                if update.message.audio:
                    audio_file = await update.message.audio.get_file()
                    audio_path = f"temp/audio_{uuid.uuid4()}.mp3"
                    await audio_file.download_to_drive(audio_path)
                    
                    output_path = input_path.replace('.', f'_with_audio.')
                    success = await VideoEditor.add_audio(input_path, output_path, audio_path)
                    os.remove(audio_path)
                else:
                    await update.message.reply_text("Please send an audio file.")
                    return EDIT_PARAMETERS
            
            elif operation == 'filter':
                filter_type = update.message.text.lower()
                output_path = input_path.replace('.', f'_filtered.')
                success = await ImageEditor.apply_filter(input_path, output_path, filter_type)
            
            elif operation == 'rotate':
                angle = int(update.message.text)
                output_path = input_path.replace('.', f'_rotated.')
                success = await ImageEditor.rotate_image(input_path, output_path, angle)
            
            elif operation == 'watermark':
                # Handle watermark image
                if update.message.document or update.message.photo:
                    if update.message.document:
                        watermark_file = await update.message.document.get_file()
                    else:
                        watermark_file = await update.message.photo[-1].get_file()
                    
                    watermark_path = f"temp/watermark_{uuid.uuid4()}.png"
                    await watermark_file.download_to_drive(watermark_path)
                    
                    output_path = input_path.replace('.', f'_watermarked.')
                    success = await ImageEditor.add_watermark(input_path, output_path, watermark_path)
                    os.remove(watermark_path)
                else:
                    await update.message.reply_text("Please send an image file for watermark.")
                    return EDIT_PARAMETERS
            
            else:
                await update.message.reply_text("Invalid operation.")
                return ConversationHandler.END
            
            if success:
                db.increment_edit_count(user_id)
                db.log_edit(user_id, operation, input_path, output_path, {'text': update.message.text})
                
                # Send result
                if context.user_data['edit_type'] == 'video':
                    with open(output_path, 'rb') as f:
                        await update.message.reply_video(video=InputFile(f))
                else:
                    with open(output_path, 'rb') as f:
                        await update.message.reply_photo(photo=InputFile(f))
                
                # Cleanup
                os.remove(input_path)
                os.remove(output_path)
            else:
                await update.message.reply_text("Error processing your request. Please try again.")
            
        except Exception as e:
            logger.error(f"Error in handle_parameters: {e}")
            await update.message.reply_text("An error occurred. Please try again.")
        
        return ConversationHandler.END
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        user = db.get_user(user_id)
        
        if user:
            stats_text = f"""
📊 *Your Statistics*

👤 User: {user[2] or user[1] or user_id}
💎 Premium: {'✅ Yes' if user[5] else '❌ No'}
📅 Premium Expiry: {user[6] if user[6] else 'N/A'}
🎬 Total Edits: {user[8]}
📈 Free Edits Remaining: {premium_manager.get_remaining_edits(user_id)}
            """
            
            keyboard = []
            if not user[5]:
                keyboard.append([InlineKeyboardButton("💎 Upgrade to Premium", callback_data='premium')])
            
            if keyboard:
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text(stats_text, parse_mode='Markdown', reply_markup=reply_markup)
            else:
                await update.message.reply_text(stats_text, parse_mode='Markdown')
    
    async def premium_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        premium_text = """
💎 *Premium Subscription*

*Benefits:*
✅ Unlimited media edits
✅ Advanced editing effects
✅ Priority processing queue
✅ 4K/8K output support
✅ Custom watermark removal
✅ Early access to new features
✅ Dedicated support

*Pricing:*
• Monthly: $9.99
• Yearly: $99.99 (Save 17%)

*Payment Methods:*
• Credit/Debit Card
• PayPal
• Cryptocurrency

Click the button below to upgrade!
        """
        
        keyboard = [
            [InlineKeyboardButton("💳 Upgrade Now", callback_data='upgrade_premium')],
            [InlineKeyboardButton("❓ More Info", callback_data='premium_info')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(premium_text, parse_mode='Markdown', reply_markup=reply_markup)
    
    async def callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        data = query.data
        user_id = query.from_user.id
        
        if data == 'edit_video' or data == 'edit_image':
            context.user_data['edit_type'] = 'video' if data == 'edit_video' else 'image'
            await self.edit_type_handler(update, context)
        
        elif data.startswith('video_'):
            operation = data.replace('video_', '')
            context.user_data['operation'] = operation
            
            if operation == 'trim':
                await query.edit_message_text(
                    "Send me a video to trim.\n"
                    "After sending, I'll ask for the trim duration."
                )
            elif operation == 'text':
                await query.edit_message_text(
                    "Send me a video to add text to.\n"
                    "After sending, I'll ask for the text."
                )
            elif operation == 'audio':
                await query.edit_message_text(
                    "Send me a video to add audio to.\n"
                    "After sending, I'll ask for the audio file."
                )
            elif operation == 'resize':
                await query.edit_message_text(
                    "Send me a video to resize.\n"
                    "After sending, I'll ask for the dimensions."
                )
            elif operation == 'compress':
                await query.edit_message_text(
                    "Send me a video to compress.\n"
                    "I'll process it and send back the compressed version."
                )
            return WAIT_MEDIA
        
        elif data.startswith('image_'):
            operation = data.replace('image_', '')
            context.user_data['operation'] = operation
            
            if operation == 'resize':
                await query.edit_message_text(
                    "Send me an image to resize.\n"
                    "After sending, I'll ask for the dimensions."
                )
            elif operation == 'text':
                await query.edit_message_text(
                    "Send me an image to add text to.\n"
                    "After sending, I'll ask for the text."
                )
            elif operation == 'filter':
                await query.edit_message_text(
                    "Send me an image to apply filter to.\n"
                    "After sending, I'll ask for the filter type."
                )
            elif operation == 'rotate':
                await query.edit_message_text(
                    "Send me an image to rotate.\n"
                    "After sending, I'll ask for the angle."
                )
            elif operation == 'watermark':
                await query.edit_message_text(
                    "Send me an image to add watermark to.\n"
                    "After sending, I'll ask for the watermark image."
                )
            return WAIT_MEDIA
        
        elif data == 'premium':
            await self.premium_command(update, context)
        
        elif data == 'upgrade_premium':
            payment_link = premium_manager.create_premium_invoice(user_id)
            await query.edit_message_text(
                f"🔗 Complete your payment here:\n{payment_link}\n\n"
                f"After payment, your premium will be activated automatically."
            )
        
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
        
        try:
            if update and update.effective_message:
                await update.effective_message.reply_text(
                    "An error occurred. Please try again later."
                )
        except:
            pass
    
    def setup(self):
        """Setup the bot application"""
        self.application = Application.builder().token(self.token).build()
        
        # Add handlers
        conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler('edit', self.edit_command),
                CallbackQueryHandler(self.callback_handler, pattern='^edit_video$'),
                CallbackQueryHandler(self.callback_handler, pattern='^edit_image$')
            ],
            states={
                EDIT_TYPE: [
                    CallbackQueryHandler(self.edit_type_handler, pattern='^edit_type_'),
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
        
        self.application.add_handler(conv_handler)
        self.application.add_handler(CommandHandler('start', self.start))
        self.application.add_handler(CommandHandler('help', self.help_command))
        self.application.add_handler(CommandHandler('stats', self.stats_command))
        self.application.add_handler(CommandHandler('premium', self.premium_command))
        self.application.add_handler(CallbackQueryHandler(self.callback_handler))
        self.application.add_error_handler(self.error_handler)
    
    async def start_bot(self):
        """Start the bot"""
        self.setup()
        await self.application.initialize()
        await self.application.start()
        
        if Config.WEBHOOK_URL:
            await self.application.bot.set_webhook(f"{Config.WEBHOOK_URL}/webhook")
        else:
            await self.application.updater.start_polling()
    
    async def stop_bot(self):
        """Stop the bot"""
        if self.application:
            await self.application.stop()

# Flask Routes
@flask_app.route('/')
def index():
    return render_template('editor.html')

@flask_app.route('/editor')
def editor():
    return render_template('editor.html')

@flask_app.route('/stream')
def stream():
    return render_template('stream.html')

@flask_app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    # Save file temporarily
    file_id = str(uuid.uuid4())
    file_ext = file.filename.rsplit('.', 1)[1].lower()
    file_path = f"temp/{file_id}.{file_ext}"
    file.save(file_path)
    
    return jsonify({
        'success': True,
        'file_id': file_id,
        'path': file_path,
        'type': 'video' if file_ext in ['mp4', 'mov', 'avi', 'mkv'] else 'image'
    })

@flask_app.route('/api/edit', methods=['POST'])
def edit_media():
    data = request.json
    file_id = data.get('file_id')
    operation = data.get('operation')
    params = data.get('params', {})
    
    input_path = f"temp/{file_id}"
    output_path = f"temp/{file_id}_edited"
    
    # Determine if video or image based on file extension
    is_video = any(input_path.endswith(ext) for ext in ['.mp4', '.mov', '.avi', '.mkv'])
    
    # Process based on operation
    try:
        if is_video:
            if operation == 'trim':
                start = float(params.get('start', 0))
                end = float(params.get('end', 10))
                output_path = f"temp/{file_id}_trimmed.mp4"
                success = asyncio.run(VideoEditor.trim_video(input_path, output_path, start, end))
            
            elif operation == 'text':
                text = params.get('text', '')
                output_path = f"temp/{file_id}_text.mp4"
                success = asyncio.run(VideoEditor.add_text(input_path, output_path, text))
            
            elif operation == 'resize':
                width = int(params.get('width', 640))
                height = int(params.get('height', 480))
                output_path = f"temp/{file_id}_resized.mp4"
                success = asyncio.run(VideoEditor.resize_video(input_path, output_path, width, height))
            
            elif operation == 'compress':
                output_path = f"temp/{file_id}_compressed.mp4"
                success = asyncio.run(VideoEditor.compress_video(input_path, output_path))
        
        else:  # Image
            if operation == 'resize':
                width = int(params.get('width', 800))
                height = int(params.get('height', 600))
                output_path = f"temp/{file_id}_resized.jpg"
                success = asyncio.run(ImageEditor.resize_image(input_path, output_path, width, height))
            
            elif operation == 'text':
                text = params.get('text', '')
                output_path = f"temp/{file_id}_text.jpg"
                success = asyncio.run(ImageEditor.add_text(input_path, output_path, text))
            
            elif operation == 'filter':
                filter_type = params.get('filter', 'blur')
                output_path = f"temp/{file_id}_filtered.jpg"
                success = asyncio.run(ImageEditor.apply_filter(input_path, output_path, filter_type))
            
            elif operation == 'rotate':
                angle = int(params.get('angle', 0))
                output_path = f"temp/{file_id}_rotated.jpg"
                success = asyncio.run(ImageEditor.rotate_image(input_path, output_path, angle))
        
        if success:
            return jsonify({
                'success': True,
                'output_path': output_path,
                'message': 'Edit completed successfully'
            })
        else:
            return jsonify({'error': 'Edit failed'}), 500
    
    except Exception as e:
        logger.error(f"Edit error: {e}")
        return jsonify({'error': str(e)}), 500

@flask_app.route('/api/download/<path:file_path>')
def download_file(file_path):
    from flask import send_file
    try:
        return send_file(file_path, as_attachment=True)
    except:
        return jsonify({'error': 'File not found'}), 404

@socketio.on('connect')
def handle_connect():
    logger.info('Client connected')
    emit('connected', {'message': 'Connected to Kinva Master'})

@socketio.on('process_media')
def handle_process_media(data):
    # Handle real-time processing
    file_id = data.get('file_id')
    operation = data.get('operation')
    
    # Emit progress updates
    emit('progress', {'percent': 25, 'message': 'Processing started...'})
    
    # Simulate processing
    time.sleep(1)
    emit('progress', {'percent': 50, 'message': 'Analyzing media...'})
    
    time.sleep(1)
    emit('progress', {'percent': 75, 'message': 'Applying edits...'})
    
    time.sleep(1)
    emit('progress', {'percent': 100, 'message': 'Complete!'})
    
    emit('result', {'success': True, 'message': 'Processing complete'})

# Webhook handler for Telegram
@flask_app.route('/webhook', methods=['POST'])
async def webhook():
    if bot_instance and bot_instance.application:
        update = telegram.Update.de_json(request.get_json(), bot_instance.application.bot)
        await bot_instance.application.process_update(update)
    return 'ok'

# Cleanup task
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

# Main application runner
class KinvaMasterBot:
    def __init__(self):
        self.bot = None
        self.loop = None
    
    async def start(self):
        """Start both bot and web app"""
        global bot_instance
        
        # Create temp directory
        os.makedirs('temp', exist_ok=True)
        
        # Initialize bot
        self.bot = TelegramBot(Config.TELEGRAM_BOT_TOKEN)
        bot_instance = self.bot
        await self.bot.start_bot()
        
        # Start cleanup task
        asyncio.create_task(cleanup_temp_files())
        
        logger.info("Kinva Master Bot started successfully")
        
        # Start Flask app with Socket.IO
        socketio.run(flask_app, host='0.0.0.0', port=Config.PORT)
    
    async def stop(self):
        """Stop the bot"""
        if self.bot:
            await self.bot.stop_bot()
        logger.info("Kinva Master Bot stopped")

# Create templates directory and HTML files
def create_templates():
    """Create required template files"""
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static/css', exist_ok=True)
    os.makedirs('static/js', exist_ok=True)
    
    # Editor HTML template
    editor_html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Kinva Master - Media Editor</title>
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
        .progress-bar {
            transition: width 0.3s ease;
        }
        .status {
            margin-top: 20px;
            padding: 10px;
            border-radius: 5px;
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
                        <div class="mb-3">
                            <button class="btn btn-outline-primary btn-tool" onclick="editMedia('trim')">✂️ Trim</button>
                            <button class="btn btn-outline-primary btn-tool" onclick="editMedia('text')">📝 Add Text</button>
                            <button class="btn btn-outline-primary btn-tool" onclick="editMedia('audio')">🎵 Add Audio</button>
                            <button class="btn btn-outline-primary btn-tool" onclick="editMedia('resize')">📏 Resize</button>
                            <button class="btn btn-outline-primary btn-tool" onclick="editMedia('compress')">🗜️ Compress</button>
                        </div>
                        
                        <h4>Image Tools</h4>
                        <div class="mb-3">
                            <button class="btn btn-outline-success btn-tool" onclick="editMedia('resize')">📏 Resize</button>
                            <button class="btn btn-outline-success btn-tool" onclick="editMedia('text')">📝 Add Text</button>
                            <button class="btn btn-outline-success btn-tool" onclick="editMedia('filter')">🎨 Filter</button>
                            <button class="btn btn-outline-success btn-tool" onclick="editMedia('rotate')">🔄 Rotate</button>
                            <button class="btn btn-outline-success btn-tool" onclick="editMedia('watermark')">💧 Watermark</button>
                        </div>
                        
                        <div id="paramsPanel" style="display: none;">
                            <hr>
                            <h5>Parameters</h5>
                            <div id="paramsForm"></div>
                            <button class="btn btn-primary mt-2" onclick="applyEdit()">Apply</button>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="progress mt-3" style="display: none;">
                <div class="progress-bar" role="progressbar" style="width: 0%"></div>
            </div>
            
            <div id="status" class="status"></div>
        </div>
    </div>
    
    <script src="https://cdn.socket.io/4.5.0/socket.io.min.js"></script>
    <script>
        let currentFile = null;
        let currentFileId = null;
        let currentOperation = null;
        let socket = io();
        
        socket.on('connect', function() {
            console.log('Connected to server');
        });
        
        socket.on('progress', function(data) {
            const progressBar = document.querySelector('.progress');
            const progress = document.querySelector('.progress-bar');
            if (progressBar) {
                progressBar.style.display = 'block';
                progress.style.width = data.percent + '%';
                progress.textContent = data.message;
            }
            document.getElementById('status').innerHTML = `<div class="alert alert-info">${data.message}</div>`;
        });
        
        socket.on('result', function(data) {
            const progressBar = document.querySelector('.progress');
            if (progressBar) progressBar.style.display = 'none';
            if (data.success) {
                document.getElementById('status').innerHTML = '<div class="alert alert-success">Edit completed! Downloading...</div>';
                setTimeout(() => {
                    window.location.reload();
                }, 2000);
            } else {
                document.getElementById('status').innerHTML = `<div class="alert alert-danger">Error: ${data.message}</div>`;
            }
        });
        
        document.getElementById('fileInput').addEventListener('change', async function(e) {
            const file = e.target.files[0];
            if (!file) return;
            
            currentFile = file;
            const formData = new FormData();
            formData.append('file', file);
            
            document.getElementById('status').innerHTML = '<div class="alert alert-info">Uploading...</div>';
            
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
                    document.getElementById('status').innerHTML = '<div class="alert alert-success">File uploaded successfully!</div>';
                }
            } catch (error) {
                console.error('Upload error:', error);
                document.getElementById('status').innerHTML = '<div class="alert alert-danger">Upload failed</div>';
            }
        });
        
        function editMedia(operation) {
            if (!currentFileId) {
                alert('Please upload a file first');
                return;
            }
            
            currentOperation = operation;
            const paramsPanel = document.getElementById('paramsPanel');
            const paramsForm = document.getElementById('paramsForm');
            
            let html = '';
            switch(operation) {
                case 'trim':
                    html = `
                        <label>Start (seconds):</label>
                        <input type="number" id="start" class="form-control" value="0">
                        <label class="mt-2">End (seconds):</label>
                        <input type="number" id="end" class="form-control" value="10">
                    `;
                    break;
                case 'resize':
                    html = `
                        <label>Width:</label>
                        <input type="number" id="width" class="form-control" value="800">
                        <label class="mt-2">Height:</label>
                        <input type="number" id="height" class="form-control" value="600">
                    `;
                    break;
                case 'text':
                    html = `
                        <label>Text:</label>
                        <input type="text" id="text" class="form-control" placeholder="Enter text">
                    `;
                    break;
                case 'filter':
                    html = `
                        <label>Filter Type:</label>
                        <select id="filter" class="form-control">
                            <option value="blur">Blur</option>
                            <option value="contour">Contour</option>
                            <option value="sharpen">Sharpen</option>
                            <option value="edge_enhance">Edge Enhance</option>
                            <option value="emboss">Emboss</option>
                        </select>
                    `;
                    break;
                case 'rotate':
                    html = `
                        <label>Angle (degrees):</label>
                        <input type="number" id="angle" class="form-control" value="90">
                    `;
                    break;
                default:
                    html = '<p>No parameters needed</p>';
            }
            
            paramsForm.innerHTML = html;
            paramsPanel.style.display = 'block';
        }
        
        async function applyEdit() {
            if (!currentFileId || !currentOperation) {
                alert('Please select an operation');
                return;
            }
            
            const params = {};
            switch(currentOperation) {
                case 'trim':
                    params.start = parseFloat(document.getElementById('start').value);
                    params.end = parseFloat(document.getElementById('end').value);
                    break;
                case 'resize':
                    params.width = parseInt(document.getElementById('width').value);
                    params.height = parseInt(document.getElementById('height').value);
                    break;
                case 'text':
                    params.text = document.getElementById('text').value;
                    break;
                case 'filter':
                    params.filter = document.getElementById('filter').value;
                    break;
                case 'rotate':
                    params.angle = parseInt(document.getElementById('angle').value);
                    break;
            }
            
            socket.emit('process_media', {
                file_id: currentFileId,
                operation: currentOperation,
                params: params
            });
            
            document.getElementById('paramsPanel').style.display = 'none';
        }
    </script>
</body>
</html>
    """
    
    with open('templates/editor.html', 'w') as f:
        f.write(editor_html)
    
    # Stream HTML template
    stream_html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Kinva Master - Live Stream</title>
    <style>
        body {
            margin: 0;
            padding: 0;
            background: #000;
            color: #fff;
            font-family: Arial, sans-serif;
        }
        #videoContainer {
            position: relative;
            width: 100vw;
            height: 100vh;
            overflow: hidden;
        }
        video {
            width: 100%;
            height: 100%;
            object-fit: contain;
        }
        .controls {
            position: fixed;
            bottom: 20px;
            left: 50%;
            transform: translateX(-50%);
            background: rgba(0,0,0,0.7);
            padding: 10px 20px;
            border-radius: 10px;
            z-index: 1000;
        }
        button {
            background: #667eea;
            color: white;
            border: none;
            padding: 10px 20px;
            margin: 0 5px;
            border-radius: 5px;
            cursor: pointer;
        }
        button:hover {
            background: #764ba2;
        }
    </style>
</head>
<body>
    <div id="videoContainer">
        <video id="videoPlayer" autoplay muted></video>
    </div>
    <div class="controls">
        <button onclick="startStream()">Start Stream</button>
        <button onclick="stopStream()">Stop Stream</button>
        <button onclick="applyFilter()">Apply Filter</button>
        <button onclick="addOverlay()">Add Overlay</button>
    </div>
    
    <script>
        let stream = null;
        let mediaRecorder = null;
        let socket = null;
        let videoElement = document.getElementById('videoPlayer');
        
        async function startStream() {
            try {
                stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
                videoElement.srcObject = stream;
                videoElement.play();
                
                // Connect to WebSocket for streaming
                socket = io();
                mediaRecorder = new MediaRecorder(stream);
                
                mediaRecorder.ondataavailable = (event) => {
                    if (event.data.size > 0 && socket) {
                        socket.emit('stream_data', event.data);
                    }
                };
                
                mediaRecorder.start(1000); // Send data every second
                
                socket.on('processed_frame', (data) => {
                    // Receive processed video frame
                    const blob = new Blob([data], { type: 'video/webm' });
                    const url = URL.createObjectURL(blob);
                    videoElement.src = url;
                });
                
            } catch (error) {
                console.error('Error accessing camera:', error);
                alert('Could not access camera');
            }
        }
        
        function stopStream() {
            if (mediaRecorder && mediaRecorder.state !== 'inactive') {
                mediaRecorder.stop();
            }
            if (stream) {
                stream.getTracks().forEach(track => track.stop());
            }
            if (socket) {
                socket.disconnect();
            }
            videoElement.srcObject = null;
        }
        
        function applyFilter() {
            if (socket) {
                socket.emit('apply_filter', { filter: 'blur' });
            }
        }
        
        function addOverlay() {
            if (socket) {
                socket.emit('add_overlay', { text: 'Kinva Master Live' });
            }
        }
    </script>
</body>
</html>
    """
    
    with open('templates/stream.html', 'w') as f:
        f.write(stream_html)
    
    # Create empty CSS and JS files
    with open('static/css/style.css', 'w') as f:
        f.write('/* Kinva Master Styles */')
    
    with open('static/js/editor.js', 'w') as f:
        f.write('// Kinva Master Editor JavaScript')

# Main entry point
if __name__ == '__main__':
    # Create necessary directories and files
    os.makedirs('temp', exist_ok=True)
    create_templates()
    
    # Run the application
    bot_app = KinvaMasterBot()
    
    try:
        asyncio.run(bot_app.start())
    except KeyboardInterrupt:
        print("Shutting down...")
        asyncio.run(bot_app.stop())
    except Exception as e:
        logger.error(f"Fatal error: {e}")
