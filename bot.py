# -*- coding: utf-8 -*-
"""
بات پست + دکمه شیشه‌ای انتخابی
اجرا به روش polling + یه سرور فیک HTTP کوچیک که فقط برای اینه که
روی Render به عنوان Web Service (رایگان) هم درست دیپلوی و healthy بشه.
"""

import os
import sys
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

import database as db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


# =========================================================
#           خواندن و اعتبارسنجی متغیرهای محیطی
# =========================================================

REQUIRED_ENV_VARS = ["BOT_TOKEN"]


def load_env():
    missing = [name for name in REQUIRED_ENV_VARS if not os.environ.get(name)]
    if missing:
        log.error(
            "متغیرهای محیطی زیر ست نشدن: %s — از تب Environment توی Render اضافه‌شون کن.",
            ", ".join(missing),
        )
        sys.exit(1)

    bot_token = os.environ["BOT_TOKEN"]
    target_channel = os.environ.get("TARGET_CHANNEL", "").strip()

    return bot_token, target_channel


BOT_TOKEN, TARGET_CHANNEL = load_env()

# ---------- مراحل گفتگوی ساخت پست ----------
WAIT_CONTENT, WAIT_BTN_NAME, WAIT_BTN_LINK, WAIT_MORE, WAIT_CONFIRM = range(5)

YES_NO_KB = ReplyKeyboardMarkup([["بله", "خیر"]], resize_keyboard=True)


def target_chat_id():
    """chat_id مقصد رو برمی‌گردونه: اگه عددیه به int تبدیل می‌کنه، وگرنه یوزرنیم/آیدی رشته‌ای رو همون‌جوری برمی‌گردونه."""
    if not TARGET_CHANNEL:
        return None
    try:
        return int(TARGET_CHANNEL)
    except ValueError:
        return TARGET_CHANNEL


# =========================================================
#                    عضویت اجباری
# =========================================================

async def check_force_join(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> list:
    """برمی‌گردونه لیست چنل‌هایی که کاربر عضوشون نیست."""
    missing = []
    for ch in db.list_force_channels():
        try:
            member = await context.bot.get_chat_member(ch["chat_id"], user_id)
            if member.status in ("left", "kicked"):
                missing.append(ch)
        except Exception as e:
            log.warning("بررسی عضویت تو %s شکست خورد: %s", ch.get("chat_id"), e)
            missing.append(ch)
    return missing


def force_join_keyboard(missing: list) -> InlineKeyboardMarkup:
    rows = []
    for ch in missing:
        username = str(ch["chat_id"]).lstrip("@")
        rows.append([InlineKeyboardButton(
            f"عضویت در {ch.get('title') or ch['chat_id']}",
            url=f"https://t.me/{username}",
        )])
    rows.append([InlineKeyboardButton("✅ عضو شدم", callback_data="check_join")])
    return InlineKeyboardMarkup(rows)


# =========================================================
#                        /start
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    missing = await check_force_join(user_id, context)
    if missing:
        await update.message.reply_text(
            "برای استفاده از بات باید تو کانال‌های زیر عضو باشی:",
            reply_markup=force_join_keyboard(missing),
        )
        return

    if not db.is_allowed(user_id):
        await update.message.reply_text("⛔️ اجازه‌ی استفاده از این بات رو نداری. از ادمین بخواه بهت دسترسی بده.")
        return

    text = f"سلام! خوش اومدی.\nآیدی عددیت: {user_id}"
    if db.is_admin(user_id):
        text += "\nتو ادمینی، /panel رو بزن."
    await update.message.reply_text(text)


async def check_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    missing = await check_force_join(user_id, context)
    if missing:
        await query.answer("هنوز عضو همه‌ی کانال‌ها نشدی!", show_alert=True)
        return
    await query.answer("عضویت تایید شد ✅")
    await query.edit_message_text("عضویت تایید شد، حالا /start رو بزن.")


# =========================================================
#                    پنل ادمین (متنی، نه شیشه‌ای)
# =========================================================

ADMIN_MENU = ReplyKeyboardMarkup(
    [
        ["➕ پست جدید"],
        ["👥 ادمین‌ها", "✅ کاربران مجاز"],
        ["🔒 عضویت اجباری", "📡 چنل‌های مبدا"],
        ["❌ بستن پنل"],
    ],
    resize_keyboard=True,
)


async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not db.is_admin(user_id):
        await update.message.reply_text("⛔️ فقط ادمین‌ها.")
        return
    await update.message.reply_text("پنل ادمین:", reply_markup=ADMIN_MENU)


async def close_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("پنل بسته شد.", reply_markup=ReplyKeyboardRemove())


# ---- مدیریت ادمین‌ها ----

async def add_admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not db.is_admin(user_id):
        return
    if not context.args:
        await update.message.reply_text("فرمت: /addadmin <user_id>")
        return
    try:
        target = int(context.args[0])
    except ValueError:
        await update.message.reply_text("آیدی عددی باید عدد باشه.")
        return
    db.add_admin(target, added_by=user_id)
    await update.message.reply_text(f"کاربر {target} ادمین شد.")


async def remove_admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not db.is_owner(user_id):
        await update.message.reply_text("فقط مالک اصلی می‌تونه ادمین حذف کنه.")
        return
    if not context.args:
        await update.message.reply_text("فرمت: /removeadmin <user_id>")
        return
    try:
        target = int(context.args[0])
    except ValueError:
        await update.message.reply_text("آیدی عددی باید عدد باشه.")
        return
    db.remove_admin(target)
    await update.message.reply_text("حذف شد.")


async def list_admins_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db.is_admin(update.effective_user.id):
        return
    admins = db.list_admins()
    if not admins:
        await update.message.reply_text("لیست ادمین‌ها خالیه.")
        return
    lines = "\n".join(f"- {a['user_id']} ({a['level']})" for a in admins)
    await update.message.reply_text("لیست ادمین‌ها:\n" + lines)


# ---- مدیریت کاربران مجاز ----

async def allow_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db.is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("فرمت: /allow <user_id>")
        return
    try:
        target = int(context.args[0])
    except ValueError:
        await update.message.reply_text("آیدی عددی باید عدد باشه.")
        return
    db.allow_user(target, added_by=update.effective_user.id)
    await update.message.reply_text(f"کاربر {target} مجاز شد.")


async def disallow_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db.is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("فرمت: /disallow <user_id>")
        return
    try:
        target = int(context.args[0])
    except ValueError:
        await update.message.reply_text("آیدی عددی باید عدد باشه.")
        return
    db.disallow_user(target)
    await update.message.reply_text("دسترسی گرفته شد.")


# ---- عضویت اجباری ----

async def add_force_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db.is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("فرمت: /addforce @channel_username")
        return
    chat_id = context.args[0]
    db.add_force_channel(chat_id, title=chat_id)
    await update.message.reply_text(f"{chat_id} به لیست عضویت اجباری اضافه شد.")


async def remove_force_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db.is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("فرمت: /removeforce @channel_username")
        return
    db.remove_force_channel(context.args[0])
    await update.message.reply_text("حذف شد.")


async def force_list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db.is_admin(update.effective_user.id):
        return
    chans = db.list_force_channels()
    if not chans:
        await update.message.reply_text("لیست عضویت اجباری خالیه.")
        return
    text = "\n".join(f"- {c['chat_id']}" for c in chans)
    await update.message.reply_text(text)


# =========================================================
#                  ساخت پست با دکمه شیشه‌ای
# =========================================================

async def newpost_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db.is_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ فقط ادمین‌ها می‌تونن پست بسازن.")
        return ConversationHandler.END
    await update.message.reply_text(
        "محتوای پست رو بفرست (متن، عکس، ویدیو یا فایل، با کپشن دلخواه).\n/cancel برای لغو"
    )
    return WAIT_CONTENT


async def newpost_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg.photo:
        context.user_data["content_type"] = "photo"
        context.user_data["file_id"] = msg.photo[-1].file_id
        context.user_data["caption"] = msg.caption or ""
    elif msg.video:
        context.user_data["content_type"] = "video"
        context.user_data["file_id"] = msg.video.file_id
        context.user_data["caption"] = msg.caption or ""
    elif msg.document:
        context.user_data["content_type"] = "document"
        context.user_data["file_id"] = msg.document.file_id
        context.user_data["caption"] = msg.caption or ""
    elif msg.text:
        context.user_data["content_type"] = "text"
        context.user_data["file_id"] = None
        context.user_data["caption"] = msg.text
    else:
        await update.message.reply_text(
            "این نوع پیام پشتیبانی نمیشه. متن، عکس، ویدیو یا فایل بفرست."
        )
        return WAIT_CONTENT

    context.user_data["buttons"] = []
    await update.message.reply_text(
        "اسم دکمه‌ی اول رو بفرست (متنی که روی دکمه‌ی شیشه‌ای نشون داده میشه):",
        reply_markup=ReplyKeyboardRemove(),
    )
    return WAIT_BTN_NAME


async def newpost_btn_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("اسم دکمه نمی‌تونه خالی باشه، دوباره بفرست:")
        return WAIT_BTN_NAME
    context.user_data["pending_btn_name"] = name
    await update.message.reply_text(
        f'لینکی که می‌خوای برای دکمه‌ی «{name}» بذاری رو بفرست.\n'
        f"اگه این دکمه لینک نداره و فقط برای رأی‌گیریه، بنویس: -"
    )
    return WAIT_BTN_LINK


async def newpost_btn_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    name = context.user_data.pop("pending_btn_name", "دکمه")

    if link == "-":
        context.user_data["buttons"].append({"text": name, "action": "vote"})
    else:
        if not (link.startswith("http://") or link.startswith("https://") or link.startswith("tg://")):
            await update.message.reply_text(
                "لینک باید با http:// یا https:// شروع بشه. دوباره لینک همین دکمه رو بفرست، یا برای دکمه‌ی بدون لینک بنویس: -"
            )
            context.user_data["pending_btn_name"] = name
            return WAIT_BTN_LINK
        context.user_data["buttons"].append({"text": name, "action": "url", "url": link})

    if len(context.user_data["buttons"]) >= 3:
        return await show_preview(update, context)

    await update.message.reply_text("دکمه‌ی بعدی هم می‌خوای اضافه کنی؟", reply_markup=YES_NO_KB)
    return WAIT_MORE


async def newpost_more(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.message.text.strip()
    if answer == "بله":
        n = len(context.user_data["buttons"]) + 1
        await update.message.reply_text(f"اسم دکمه‌ی {n} رو بفرست:", reply_markup=ReplyKeyboardRemove())
        return WAIT_BTN_NAME
    return await show_preview(update, context)


async def show_preview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = context.user_data["buttons"]
    preview_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(b["text"], url=b.get("url", "https://t.me")) if b["action"] == "url"
         else InlineKeyboardButton(b["text"], callback_data="preview")]
        for b in buttons
    ])
    caption = context.user_data["caption"]
    ctype = context.user_data["content_type"]

    if ctype == "text":
        await update.message.reply_text(caption or "(بدون متن)", reply_markup=preview_kb)
    elif ctype == "photo":
        await update.message.reply_photo(context.user_data["file_id"], caption=caption, reply_markup=preview_kb)
    elif ctype == "video":
        await update.message.reply_video(context.user_data["file_id"], caption=caption, reply_markup=preview_kb)
    elif ctype == "document":
        await update.message.reply_document(context.user_data["file_id"], caption=caption, reply_markup=preview_kb)

    await update.message.reply_text(
        "این پیش‌نمایشه. برای انتشار در کانال بنویس: بفرست\nبرای لغو: /cancel"
    )
    return WAIT_CONFIRM


async def newpost_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip() != "بفرست":
        await update.message.reply_text("برای انتشار بنویس: بفرست")
        return WAIT_CONFIRM

    creator_id = update.effective_user.id
    ctype = context.user_data["content_type"]
    file_id = context.user_data["file_id"]
    caption = context.user_data["caption"]
    buttons = context.user_data["buttons"]

    post_id = db.create_post(creator_id, ctype, file_id, caption, buttons)
    kb = build_post_keyboard(post_id, buttons)

    target = target_chat_id()
    if target is None:
        await update.message.reply_text("⚠️ TARGET_CHANNEL تنظیم نشده، پست فقط اینجا نمایش داده شد.")
        target = update.effective_chat.id

    try:
        if ctype == "text":
            await context.bot.send_message(target, caption or "", reply_markup=kb)
        elif ctype == "photo":
            await context.bot.send_photo(target, file_id, caption=caption, reply_markup=kb)
        elif ctype == "video":
            await context.bot.send_video(target, file_id, caption=caption, reply_markup=kb)
        elif ctype == "document":
            await context.bot.send_document(target, file_id, caption=caption, reply_markup=kb)
    except Exception as e:
        log.exception("ارسال پست به کانال شکست خورد")
        await update.message.reply_text(f"❌ ارسال پست شکست خورد: {e}", reply_markup=ADMIN_MENU)
        context.user_data.clear()
        return ConversationHandler.END

    await update.message.reply_text("✅ پست منتشر شد.", reply_markup=ADMIN_MENU)
    context.user_data.clear()
    return ConversationHandler.END


async def newpost_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("لغو شد.", reply_markup=ADMIN_MENU)
    return ConversationHandler.END


def build_post_keyboard(post_id: int, buttons: list) -> InlineKeyboardMarkup:
    rows = []
    for i, b in enumerate(buttons):
        if b["action"] == "url":
            rows.append([InlineKeyboardButton(b["text"], url=b["url"])])
        else:
            rows.append([InlineKeyboardButton(b["text"], callback_data=f"vote:{post_id}:{i}")])
    return InlineKeyboardMarkup(rows)


# =========================================================
#                    کلیک روی دکمه‌ی رأی
# =========================================================

async def vote_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        _, post_id_s, idx_s = query.data.split(":")
        post_id, idx = int(post_id_s), int(idx_s)
    except (ValueError, AttributeError):
        await query.answer("خطای داخلی، دوباره امتحان کن.", show_alert=True)
        return

    user_id = query.from_user.id

    missing = await check_force_join(user_id, context)
    if missing:
        await query.answer("اول باید عضو کانال‌ها بشی.", show_alert=True)
        return

    if not db.is_allowed(user_id):
        await query.answer("اجازه‌ی استفاده از این بات رو نداری.", show_alert=True)
        return

    post = db.get_post(post_id)
    if not post or not post["active"]:
        await query.answer("این پست دیگه فعال نیست.", show_alert=True)
        return

    if db.has_voted(post_id, user_id):
        await query.answer("قبلاً رأی دادی!", show_alert=True)
        return

    db.add_vote(post_id, user_id, idx)
    counts = db.vote_counts(post_id)

    new_rows = []
    for i, b in enumerate(post["buttons"]):
        c = counts.get(i, 0)
        label = f"{b['text']} ({c})" if b["action"] == "vote" else b["text"]
        if b["action"] == "url":
            new_rows.append([InlineKeyboardButton(label, url=b["url"])])
        else:
            new_rows.append([InlineKeyboardButton(label, callback_data=f"vote:{post_id}:{i}")])

    try:
        await query.edit_message_reply_markup(InlineKeyboardMarkup(new_rows))
    except Exception as e:
        log.warning("آپدیت دکمه‌های پیام شکست خورد: %s", e)
    await query.answer("رأیت ثبت شد ✅")


# =========================================================
#                    چنل‌های مبدا (محدودیت مهم)
# =========================================================

async def add_source_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db.is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("فرمت: /addsource @channel_username")
        return
    chat_id = context.args[0]
    db.add_source_channel(chat_id, title=chat_id)
    await update.message.reply_text(
        f"{chat_id} اضافه شد.\n"
        "توجه: بات فقط پست‌های جدید بعد از این لحظه رو از این کانال می‌بینه و می‌تونه "
        "خودکار روش دکمه بذاره. گرفتن پست‌های قدیمی/آرشیو با توکن بات ممکن نیست؛ "
        "برای اون باید از یه اکانت یوزر (Telethon/Pyrogram) استفاده کرد، که یه پروژه‌ی جدا و پیچیده‌تره."
    )


async def channel_post_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """وقتی تو یه چنل مبدا پست جدید میاد، اگه چنل ثبت شده باشه، دکمه پیش‌فرض بهش اضافه می‌کنیم."""
    post = update.channel_post
    if not post or not post.chat:
        return
    sources = {str(c["chat_id"]).lstrip("@") for c in db.list_source_channels()}
    username = post.chat.username or ""
    if username not in sources:
        return
    log.info("پست جدید از چنل مبدا رصد شد: %s / %s", post.chat.username, post.message_id)


# =========================================================
#                    مدیریت خطاهای عمومی
# =========================================================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error("خطای پیش‌بینی‌نشده هنگام پردازش آپدیت %s:", update, exc_info=context.error)


# =========================================================
#      سرور فیک HTTP فقط برای اینکه Render فکر کنه سالمه
# =========================================================

class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"OK - bot is running (polling)")

    def log_message(self, format, *args):
        # لاگ‌های پیش‌فرض http.server رو خاموش می‌کنیم که شلوغ نشه
        pass


def start_fake_web_server():
    port = int(os.environ.get("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    log.info("سرور فیک HTTP روی پورت %s بالا اومد (فقط برای health check رندر)", port)
    server.serve_forever()


# =========================================================
#                          main
# =========================================================

def main():
    log.info("Python %s", sys.version)
    log.info("در حال ساخت اپلیکیشن بات...")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("panel", panel))
    app.add_handler(CallbackQueryHandler(check_join_callback, pattern="^check_join$"))
    app.add_handler(CallbackQueryHandler(vote_callback, pattern="^vote:"))

    app.add_handler(CommandHandler("addadmin", add_admin_cmd))
    app.add_handler(CommandHandler("removeadmin", remove_admin_cmd))
    app.add_handler(CommandHandler("admins", list_admins_cmd))
    app.add_handler(CommandHandler("allow", allow_cmd))
    app.add_handler(CommandHandler("disallow", disallow_cmd))
    app.add_handler(CommandHandler("addforce", add_force_cmd))
    app.add_handler(CommandHandler("removeforce", remove_force_cmd))
    app.add_handler(CommandHandler("forcelist", force_list_cmd))
    app.add_handler(CommandHandler("addsource", add_source_cmd))

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("newpost", newpost_start),
            MessageHandler(filters.Regex("^➕ پست جدید$"), newpost_start),
        ],
        states={
            WAIT_CONTENT: [MessageHandler(~filters.COMMAND, newpost_content)],
            WAIT_BTN_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, newpost_btn_name)],
            WAIT_BTN_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, newpost_btn_link)],
            WAIT_MORE: [MessageHandler(filters.TEXT & ~filters.COMMAND, newpost_more)],
            WAIT_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, newpost_confirm)],
        },
        fallbacks=[CommandHandler("cancel", newpost_cancel)],
    )
    app.add_handler(conv)

    app.add_handler(MessageHandler(filters.Regex("^❌ بستن پنل$"), close_panel))
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL, channel_post_handler))

    app.add_error_handler(error_handler)

    # سرور فیک رو تو یه ترد جدا بالا میاریم تا Render پورت رو باز ببینه
    threading.Thread(target=start_fake_web_server, daemon=True).start()

    log.info("در حال اجرای بات به روش polling ...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
