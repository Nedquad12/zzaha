import json
import os

USER_ROLE_PATH = "/home/ec2-user/package/admin/user_roles.json"
USER_ROLES = {}  # Format: {user_id: ["whitelist", "vip"]}
PUBLIC_GROUP_ID = -1002344730976

AUTHORIZED_ADMINS = {
    "superman": "kuncirahem",
}

def load_roles():
    global USER_ROLES
    if os.path.exists(USER_ROLE_PATH):
        with open(USER_ROLE_PATH, "r") as f:
            USER_ROLES = json.load(f)
            # Pastikan keys jadi int
            USER_ROLES = {int(k): v for k, v in USER_ROLES.items()}
    else:
        USER_ROLES = {}

def save_roles():
    with open(USER_ROLE_PATH, "w") as f:
        json.dump(USER_ROLES, f)

def check_admin_credentials(username, password):
    return AUTHORIZED_ADMINS.get(username) == password

def add_user(user_id, role):
    if user_id not in USER_ROLES:
        USER_ROLES[user_id] = []
    if role not in USER_ROLES[user_id]:
        USER_ROLES[user_id].append(role)
    save_roles()

def remove_user(user_id):
    if user_id in USER_ROLES:
        del USER_ROLES[user_id]
        save_roles()

def promote_user(user_id):
    if user_id in USER_ROLES and "vip" not in USER_ROLES[user_id]:
        USER_ROLES[user_id].append("vip")
        save_roles()

def is_authorized_user(user_id):
    return "whitelist" in USER_ROLES.get(user_id, [])

def is_vip_user(user_id):
    return "vip" in USER_ROLES.get(user_id, [])

def list_users():
    return USER_ROLES

def is_active_admin(user_id: int, active_admins: set) -> bool:
    """
    Cek apakah user adalah admin yang sudah login via /admin.
    active_admins di-pass dari admin_command.py untuk menghindari circular import.
    """
    return user_id in active_admins


async def check_public_group_access(update, active_admins: set) -> bool:
    """
    Guard khusus untuk grup PUBLIC_GROUP_ID (-1002344730976).

    Aturan:
      - Bukan di grup ini          → return True  (logika normal berlaku)
      - Admin aktif (sudah login)  → return True  (boleh akses)
      - User VIP                   → kirim pesan peringatan, return False
      - User lain                  → diam/cuekin, return False

    Cara pakai di handler:
        from admin.auth import check_public_group_access
        from admin.admin_command import active_admins

        async def cmd_skor(update, context):
            if not await check_public_group_access(update, active_admins):
                return
            # ... logika normal
    """
    chat_id = update.effective_chat.id

    # Bukan di grup target → tidak perlu pengecekan khusus
    if chat_id != PUBLIC_GROUP_ID:
        return True

    uid = update.effective_user.id

    # Admin aktif → izinkan
    if is_active_admin(uid, active_admins):
        return True

    # VIP → tolak dengan pesan
    if is_vip_user(uid):
        await update.message.reply_text(
            "Untuk klien VIP, akses bot hanya di grup VIP."
        )
        return False

    # Bukan siapa-siapa → cuekin
    return False
