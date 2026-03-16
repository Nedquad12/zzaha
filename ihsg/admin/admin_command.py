from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters
from admin.auth import check_admin_credentials, add_user, promote_user, remove_user, list_users
import asyncio

ASK_USERNAME, ASK_PASSWORD, ADMIN_MENU, BROADCAST_TARGET, BROADCAST_MESSAGE = range(5)

active_admins = set()

async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🛡 Masukkan ID admin:")
    return ASK_USERNAME

async def ask_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['admin_username'] = update.message.text
    await update.message.reply_text("🔒 Masukkan password:")
    return ASK_PASSWORD

async def admin_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = context.user_data['admin_username']
    password = update.message.text

    if check_admin_credentials(username, password):
        active_admins.add(update.effective_user.id)
        await update.message.reply_text("""✅ Login berhasil.

📋 **MENU ADMIN:**

👥 **User Management:**
- `tambah <id> whitelist` - Tambah user whitelist
- `tambah <id> vip` - Tambah user VIP
- `naikkan <id>` - Promote user ke VIP
- `hapus <id>` - Hapus user
- `daftar` - Lihat daftar semua user

🔄 **Data:**
- `reload` - Hapus JSON lama & muat ulang dari XLSX

📢 **Broadcast:**
- `broadcast all` - Broadcast ke semua user
- `broadcast vip` - Broadcast ke semua user VIP
- `broadcast whitelist` - Broadcast ke semua user whitelist
- `broadcast <id>` - Broadcast ke user tertentu""", parse_mode="Markdown")
        return ADMIN_MENU
    else:
        await update.message.reply_text("❌ ID atau Password salah.")
        return ConversationHandler.END


async def admin_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in active_admins:
        await update.message.reply_text("⛔ Kamu belum login sebagai admin.")
        return ConversationHandler.END

    text  = update.message.text.lower().strip()
    parts = text.split()

    # ── Reload ────────────────────────────────────────────────────────────────
    if text == "reload":
        msg = await update.message.reply_text("⏳ Memproses reload, mohon tunggu…")
        try:
            from main import do_reload_and_screen
            result_text = await do_reload_and_screen(context)
        except Exception as e:
            result_text = f"❌ Error saat reload: {e}"
        await msg.edit_text(result_text, parse_mode="Markdown")

    # ── User management ───────────────────────────────────────────────────────
    elif text.startswith("tambah") and len(parts) == 3:
        try:
            user_id, role = int(parts[1]), parts[2]
            if role not in ("whitelist", "vip"):
                await update.message.reply_text("⚠️ Role harus `whitelist` atau `vip`", parse_mode="Markdown")
            else:
                add_user(user_id, role)
                await update.message.reply_text(f"✅ User `{user_id}` ditambahkan sebagai `{role}`", parse_mode="Markdown")
        except:
            await update.message.reply_text("⚠️ Format salah. Gunakan: `tambah <id> whitelist/vip`", parse_mode="Markdown")

    elif text.startswith("naikkan") and len(parts) == 2:
        try:
            user_id = int(parts[1])
            promote_user(user_id)
            await update.message.reply_text(f"⬆️ User `{user_id}` dinaikkan menjadi VIP", parse_mode="Markdown")
        except:
            await update.message.reply_text("⚠️ Format salah. Gunakan: `naikkan <id>`", parse_mode="Markdown")

    elif text.startswith("hapus") and len(parts) == 2:
        try:
            user_id = int(parts[1])
            remove_user(user_id)
            await update.message.reply_text(f"🗑 User `{user_id}` dihapus dari daftar", parse_mode="Markdown")
        except:
            await update.message.reply_text("⚠️ Format salah. Gunakan: `hapus <id>`", parse_mode="Markdown")

    elif text.startswith("daftar"):
        data = list_users()
        if not data:
            await update.message.reply_text("📭 Tidak ada user terdaftar.")
        else:
            msg_text = "\n".join([f"{uid}: {', '.join(roles)}" for uid, roles in data.items()])
            await update.message.reply_text(f"📋 Daftar user:\n```\n{msg_text}\n```", parse_mode="Markdown")

    # ── Broadcast ─────────────────────────────────────────────────────────────
    elif text.startswith("broadcast"):
        if len(parts) < 2:
            await update.message.reply_text("⚠️ Format: `broadcast all/vip/whitelist/<user_id>`", parse_mode="Markdown")
            return ADMIN_MENU

        target = parts[1]
        context.user_data['broadcast_target'] = target
        data   = list_users()

        if target == "all":
            await update.message.reply_text("📢 Broadcast ke *SEMUA USER*\n\n💬 Ketik pesan yang ingin dikirim:", parse_mode="Markdown")
        elif target == "vip":
            await update.message.reply_text("📢 Broadcast ke *SEMUA USER VIP*\n\n💬 Ketik pesan yang ingin dikirim:", parse_mode="Markdown")
        elif target == "whitelist":
            await update.message.reply_text("📢 Broadcast ke *SEMUA USER WHITELIST*\n\n💬 Ketik pesan yang ingin dikirim:", parse_mode="Markdown")
        elif target.isdigit():
            user_id = int(target)
            if user_id in data:
                roles = ", ".join(data[user_id])
                await update.message.reply_text(f"📢 Broadcast ke *USER {user_id}* ({roles})\n\n💬 Ketik pesan yang ingin dikirim:", parse_mode="Markdown")
            else:
                await update.message.reply_text("❌ User ID tidak ditemukan dalam database.")
                return ADMIN_MENU
        else:
            await update.message.reply_text("⚠️ Target tidak valid. Gunakan: `all`, `vip`, `whitelist`, atau `<user_id>`", parse_mode="Markdown")
            return ADMIN_MENU

        return BROADCAST_MESSAGE

    else:
        await update.message.reply_text("❓ Perintah tidak dikenal. Ketik `reload`, `tambah`, `hapus`, `naikkan`, `daftar`, atau `broadcast`.")

    return ADMIN_MENU


async def handle_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in active_admins:
        await update.message.reply_text("⛔ Kamu belum login sebagai admin.")
        return ConversationHandler.END

    target  = context.user_data.get('broadcast_target')
    message = update.message.text
    data    = list_users()

    if target == "all":
        target_users = list(data.keys())
        target_desc  = "SEMUA USER"
    elif target == "vip":
        target_users = [uid for uid, roles in data.items() if "vip" in roles]
        target_desc  = "SEMUA USER VIP"
    elif target == "whitelist":
        target_users = [uid for uid, roles in data.items() if "whitelist" in roles and "vip" not in roles]
        target_desc  = "SEMUA USER WHITELIST"
    elif target and target.isdigit():
        user_id = int(target)
        if user_id in data:
            target_users = [user_id]
            target_desc  = f"USER {user_id}"
        else:
            await update.message.reply_text("❌ User ID tidak ditemukan.")
            return ADMIN_MENU
    else:
        await update.message.reply_text("❌ Error target broadcast.")
        return ADMIN_MENU

    if not target_users:
        await update.message.reply_text(f"📭 Tidak ada user untuk target: {target}")
        return ADMIN_MENU

    await update.message.reply_text(
        f"📢 *KONFIRMASI BROADCAST*\n\n"
        f"🎯 *Target:* {target_desc}\n"
        f"👥 *Jumlah:* {len(target_users)} user\n"
        f"💬 *Pesan:*\n{message}\n\n"
        f"✅ Ketik `ya` untuk mengirim\n"
        f"❌ Ketik `tidak` untuk batal",
        parse_mode="Markdown"
    )

    context.user_data['broadcast_message'] = message
    context.user_data['target_users']      = target_users
    context.user_data['target_desc']       = target_desc
    return BROADCAST_TARGET


async def handle_broadcast_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in active_admins:
        await update.message.reply_text("⛔ Kamu belum login sebagai admin.")
        return ConversationHandler.END

    response = update.message.text.lower().strip()

    if response == "ya":
        target_users = context.user_data.get('target_users', [])
        message      = context.user_data.get('broadcast_message', '')
        target_desc  = context.user_data.get('target_desc', '')

        broadcast_msg = f"📢 *BROADCAST ADMIN*\n\n{message}\n\n---\n_Pesan ini dikirim oleh admin_"

        success_count = 0
        failed_count  = 0
        status_msg    = await update.message.reply_text("📤 Mengirim broadcast…")

        for user_id in target_users:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=broadcast_msg,
                    parse_mode="Markdown"
                )
                success_count += 1
                await asyncio.sleep(0.1)
            except Exception as e:
                failed_count += 1
                print(f"Failed to send to {user_id}: {e}")

        await status_msg.edit_text(
            f"✅ *BROADCAST SELESAI*\n\n"
            f"🎯 Target: {target_desc}\n"
            f"✅ Berhasil: {success_count}\n"
            f"❌ Gagal: {failed_count}\n"
            f"📊 Total: {len(target_users)}",
            parse_mode="Markdown"
        )

    elif response == "tidak":
        await update.message.reply_text("❌ Broadcast dibatalkan.")
    else:
        await update.message.reply_text("⚠️ Ketik `ya` untuk mengirim atau `tidak` untuk batal.")
        return BROADCAST_TARGET

    context.user_data.pop('broadcast_target', None)
    context.user_data.pop('broadcast_message', None)
    context.user_data.pop('target_users', None)
    context.user_data.pop('target_desc', None)

    return ADMIN_MENU


async def cancel_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    active_admins.discard(update.effective_user.id)
    await update.message.reply_text("🚪 Keluar dari mode admin.")
    return ConversationHandler.END


def get_admin_conversation_handler():
    return ConversationHandler(
        entry_points=[CommandHandler("admin", admin_start)],
        states={
            ASK_USERNAME:      [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_password)],
            ASK_PASSWORD:      [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_login)],
            ADMIN_MENU:        [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_command_handler)],
            BROADCAST_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_broadcast_message)],
            BROADCAST_TARGET:  [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_broadcast_confirmation)],
        },
        fallbacks=[CommandHandler("cancel", cancel_admin)],
        allow_reentry=True
    )
