from telegram import Update
from telegram.ext import ContextTypes

async def get_id_pengguna(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler untuk command /id - menampilkan ID dan username user
    """
    user = update.effective_user
    
    # Membuat pesan sederhana dengan ID dan username
    username = f"@{user.username}" if user.username else "Tidak ada username"
    message_text = f"🆔 ID: `{user.id}`\n👤 Username: {username}"
    
    await update.message.reply_text(
        message_text, 
        parse_mode='Markdown'
    )