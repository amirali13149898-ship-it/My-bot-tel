"""
لایه‌ی ارتباط با Supabase.
همه‌ی جدول‌ها و کوئری‌ها اینجاست تا bot.py تمیز بمونه.
"""

import os
from supabase import create_client, Client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
OWNER_ID = int(os.environ["OWNER_ID"])

# ادمین‌های ثابتی که مستقیم از Environment Variables رندر تنظیم می‌شن.
# تو تب Environment رندر یه متغیر به اسم ADMIN_IDS بساز و آیدی عددی
# ادمین‌ها رو با کاما جدا کن، مثلا: ADMIN_IDS=111111111,222222222
# نیازی به ری‌استارت دستی نیست؛ رندر با تغییر Environment Variable
# خودش سرویس رو دوباره دیپلوی می‌کنه.
def _parse_env_admin_ids() -> set:
    raw = os.environ.get("ADMIN_IDS", "")
    ids = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            pass
    return ids


ENV_ADMIN_IDS = _parse_env_admin_ids()

sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# ---------- ادمین‌ها ----------

def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID


def is_env_admin(user_id: int) -> bool:
    """ادمینی که فقط از طریق ADMIN_IDS تو Render تعریف شده (توی دیتابیس نیست)."""
    return user_id in ENV_ADMIN_IDS


def is_admin(user_id: int) -> bool:
    if is_owner(user_id) or is_env_admin(user_id):
        return True
    res = sb.table("admins").select("user_id").eq("user_id", user_id).execute()
    return len(res.data) > 0


def add_admin(user_id: int, added_by: int):
    sb.table("admins").upsert({"user_id": user_id, "level": "admin", "added_by": added_by}).execute()


def remove_admin(user_id: int):
    sb.table("admins").delete().eq("user_id", user_id).execute()


def list_admins():
    db_admins = sb.table("admins").select("*").execute().data
    env_admins = [
        {"user_id": uid, "level": "env (Render)", "added_by": None}
        for uid in ENV_ADMIN_IDS
    ]
    return env_admins + db_admins


# ---------- کاربران مجاز ----------

def is_allowed(user_id: int) -> bool:
    if is_admin(user_id):
        return True
    res = sb.table("allowed_users").select("user_id").eq("user_id", user_id).execute()
    return len(res.data) > 0


def allow_user(user_id: int, added_by: int):
    sb.table("allowed_users").upsert({"user_id": user_id, "added_by": added_by}).execute()


def disallow_user(user_id: int):
    sb.table("allowed_users").delete().eq("user_id", user_id).execute()


# ---------- عضویت اجباری ----------

def list_force_channels():
    return sb.table("force_channels").select("*").execute().data


def add_force_channel(chat_id: str, title: str = ""):
    sb.table("force_channels").insert({"chat_id": chat_id, "title": title}).execute()


def remove_force_channel(chat_id: str):
    sb.table("force_channels").delete().eq("chat_id", chat_id).execute()


# ---------- پست‌ها ----------

def create_post(creator_id: int, content_type: str, file_id: str, caption: str, buttons: list) -> int:
    res = sb.table("posts").insert({
        "creator_id": creator_id,
        "content_type": content_type,
        "file_id": file_id,
        "caption": caption,
        "buttons": buttons,
    }).execute()
    return res.data[0]["id"]


def get_post(post_id: int):
    res = sb.table("posts").select("*").eq("id", post_id).execute()
    return res.data[0] if res.data else None


def deactivate_post(post_id: int):
    sb.table("posts").update({"active": False}).eq("id", post_id).execute()


# ---------- رأی‌ها ----------

def has_voted(post_id: int, user_id: int) -> bool:
    res = sb.table("votes").select("user_id").eq("post_id", post_id).eq("user_id", user_id).execute()
    return len(res.data) > 0


def add_vote(post_id: int, user_id: int, button_index: int):
    sb.table("votes").insert({"post_id": post_id, "user_id": user_id, "button_index": button_index}).execute()


def vote_counts(post_id: int) -> dict:
    res = sb.table("votes").select("button_index").eq("post_id", post_id).execute()
    counts = {}
    for row in res.data:
        idx = row["button_index"]
        counts[idx] = counts.get(idx, 0) + 1
    return counts


# ---------- چنل‌های مبدا (برای گرفتن پست) ----------

def list_source_channels():
    return sb.table("source_channels").select("*").execute().data


def add_source_channel(chat_id: str, title: str = ""):
    sb.table("source_channels").insert({"chat_id": chat_id, "title": title}).execute()
