import json
import logging
import time

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatType
from telegram.error import TelegramError
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes,
    MessageHandler, filters,
)

from config import BOT_TOKEN, OWNER_ID, XP_PER_MESSAGE, XP_COOLDOWN_SECONDS, DEFAULT_ADMIN_LEVEL, validate_config
import database as db
from levels import level_from_xp, rank_for_level, automatic_badges, next_level_progress
import admin_panel as panel

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("emerald_group_bot")

# The owner can type a title or a custom point reason after choosing a button.
pending_input = {}

def is_owner(user_id):
    return user_id == OWNER_ID

def safe_name(user):
    return user.full_name or user.first_name or str(user.id)

async def is_group_admin(context, chat_id, user_id):
    """Return True only when the user is a Telegram admin of this group.

    The configured owner retains access to every registered group.
    """
    if is_owner(user_id):
        return True
    try:
        member = await context.bot.get_chat_member(chat_id=int(chat_id), user_id=int(user_id))
        return member.status in ("administrator", "creator")
    except (TelegramError, ValueError, TypeError):
        return False

async def groups_for_user(context, user_id):
    """Registered groups the user is allowed to administer."""
    groups = db.get_groups()
    if is_owner(user_id):
        return groups
    allowed = []
    for group in groups:
        if await is_group_admin(context, group["chat_id"], user_id):
            allowed.append(group)
    return allowed

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.effective_chat.type == ChatType.PRIVATE:
        if is_owner(user.id):
            await update.effective_message.reply_text(
                "💚 <b>پنل مدیریت زمرد</b>\n\n"
                "بات را به گروهت اضافه کن و در گروه یک پیام بفرست تا ثبت شود.\n"
                "سپس از دکمه زیر پنل مدیریت را باز کن.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ باز کردن پنل مدیریت", callback_data="home")]])
            )
        else:
            await update.effective_message.reply_text(
                "سلام! 💚\nبرای دیدن وضعیتت، در گروه دستور /me را بزن.\n"
                "اگر در گروهی مدیر تلگرام هستی، دستور /admin را برای پنل همان گروه امتحان کن."
            )
    else:
        db.register_group(update.effective_chat.id, update.effective_chat.title or "گروه")
        await update.effective_message.reply_text(
            "💚 بات مدیریت زمرد فعال شد!\nبرای پروفایل: /me\nبرای جدول رتبه‌ها: /top\nبرای درخواست بررسی ادمینی: /admin_request"
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "💚 <b>راهنمای بات</b>\n\n"
        "/me — پروفایل و لول تو\n"
        "/top — ۱۰ عضو برتر بر اساس XP\n"
        "/rank — نمایش رتبه و پیشرفت لول\n"
        "/rewards — نشان‌های خودکار و راهنمای امتیاز ویژه\n"
        "/admin_request — درخواست بررسی برای ادمین شدن\n"
        "/admin — باز کردن پنل مدیریت (فقط مدیر اصلی)"
    )
    await update.effective_message.reply_text(text, parse_mode="HTML")

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.effective_chat.type != ChatType.PRIVATE:
        await update.effective_message.reply_text("برای باز کردن پنل، در گفت‌وگوی خصوصی بات دستور /admin را بزن.")
        return
    groups = await groups_for_user(context, user.id)
    if not groups:
        await update.effective_message.reply_text(
            "گروهی برای مدیریت پیدا نشد. ابتدا بات را به گروهت اضافه کن و در آن یک پیام بفرست؛ "
            "سپس مطمئن شو در همان گروه مدیر تلگرام هستی و دوباره /admin را بزن."
        )
        return
    await update.effective_message.reply_text(
        "💚 <b>پنل مدیریت زمرد</b>\nگروهی را انتخاب کن که در آن مدیر تلگرام هستی:",
        parse_mode="HTML", reply_markup=panel.group_picker(groups)
    )

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await update.effective_message.reply_text("این دستور را داخل گروهی بزن که بات عضو آن است.")
        return
    db.register_group(chat.id, chat.title or "گروه")
    db.upsert_member(chat.id, user)
    m = db.get_member(chat.id, user.id)
    xp = m["xp"]
    level = level_from_xp(xp)
    rank, icon = rank_for_level(level)
    earned, required, pct = next_level_progress(xp, level)
    badges = automatic_badges(level)
    try:
        custom = json.loads(m["custom_badges"] or "[]")
    except json.JSONDecodeError:
        custom = []
    badge_text = " ".join(f"{b['emoji']} {b['name']}" for b in badges + custom) or "هنوز نشانی نگرفته‌ای"
    title = m["custom_title"] or rank
    await update.effective_message.reply_text(
        f"💚 <b>پروفایل {safe_name(user)}</b>\n\n"
        f"🏷 لقب: <b>{title}</b>\n"
        f"{icon} سطح: <b>{level}/100 · {rank}</b>\n"
        f"✨ XP: <b>{xp:,}</b>\n"
        f"📈 پیشرفت لول بعدی: <b>{pct}%</b> ({earned}/{required})\n"
        f"⭐ امتیاز ویژه: <b>{m['bonus_points']:,}</b>\n"
        f"🎖 نشان‌ها: {badge_text}",
        parse_mode="HTML"
    )

async def top_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await update.effective_message.reply_text("این دستور را داخل گروه بزن.")
        return
    members = db.get_members(chat.id, limit=10)
    if not members:
        await update.effective_message.reply_text("هنوز عضوی ثبت نشده؛ چند پیام در گروه بفرستید.")
        return
    lines = ["🏆 <b>۱۰ عضو برتر گروه</b>", ""]
    for i, m in enumerate(members, 1):
        level = level_from_xp(m["xp"])
        rank, icon = rank_for_level(level)
        lines.append(f"{i}. {icon} {m['full_name']} — لول {level} · {m['xp']:,} XP")
    await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")

async def rewards_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = [
        "🎖 <b>نشان‌های خودکار</b>",
        "🌟 لول ۵ — عضو پرتلاش",
        "💬 لول ۱۰ — فعال گروه",
        "⚡ لول ۲۵ — حرفه‌ای",
        "💚 لول ۵۰ — زمردی",
        "🛡️ لول ۷۵ — نخبه",
        "👑 لول ۱۰۰ — اسطوره",
        "",
        "⭐ امتیاز ویژه فقط توسط مدیر از پنل داده می‌شود و روی XP یا لول اثر ندارد.",
    ]
    await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")

async def admin_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await update.effective_message.reply_text("این دستور را داخل گروه بزن.")
        return
    db.register_group(chat.id, chat.title or "گروه")
    db.upsert_member(chat.id, user)
    m = db.get_member(chat.id, user.id)
    group = db.get_group(chat.id)
    level = level_from_xp(m["xp"])
    required = int(group["admin_level"]) if group else DEFAULT_ADMIN_LEVEL
    if level < required:
        await update.effective_message.reply_text(f"هنوز به لول لازم نرسیدی. لول فعلی: {level}؛ لول لازم: {required}.")
        return
    db.add_admin_request(chat.id, user.id)
    await update.effective_message.reply_text("درخواستت ثبت شد 💚 یکی از مدیران گروه می‌تواند آن را از پنل بررسی کند.")

async def group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not user or user.is_bot or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    # Ignore commands and service messages for XP.
    if msg.text and msg.text.startswith("/"):
        db.register_group(chat.id, chat.title or "گروه")
        db.upsert_member(chat.id, user)
        return
    db.register_group(chat.id, chat.title or "گروه")
    result = db.upsert_member(chat.id, user, XP_PER_MESSAGE, award_xp=True, cooldown_seconds=XP_COOLDOWN_SECONDS)
    if result["got_xp"] and result["level"] > result["old_level"]:
        group = db.get_group(chat.id)
        if group and group["rankup_announcements"]:
            rank, icon = rank_for_level(result["level"])
            try:
                await msg.reply_text(
                    f"💚 تبریک {safe_name(user)}!\n{icon} به لول {result['level']} رسیدی؛ رتبه: {rank}."
                )
            except TelegramError:
                pass

async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    if not user or chat.type != ChatType.PRIVATE:
        return
    state = pending_input.get(user.id)
    if not state:
        return
    if not await is_group_admin(context, state.get("chat_id"), user.id):
        pending_input.pop(user.id, None)
        await update.effective_message.reply_text("⛔ دیگر مجوز مدیریت این گروه را نداری؛ دوباره /admin را بزن.")
        return
    pending_input.pop(user.id, None)
    text = (update.effective_message.text or "").strip()
    if state["kind"] == "title":
        db.set_custom_title(state["chat_id"], state["user_id"], "" if text in ("-", "پاک کردن", "حذف") else text[:60])
        await update.effective_message.reply_text("✅ لقب به‌روزرسانی شد.")
        m = db.get_member(state["chat_id"], state["user_id"])
        body, markup = panel.member_card(state["chat_id"], m)
        await update.effective_message.reply_text(body, parse_mode="HTML", reply_markup=markup)
    elif state["kind"] == "reason":
        amount = state["amount"]
        value = db.change_bonus_points(state["chat_id"], state["user_id"], amount, user.id, text[:200])
        await update.effective_message.reply_text(f"✅ امتیاز ویژه به‌روزرسانی شد. موجودی فعلی: {value}")
    elif state["kind"] == "admin_level":
        try:
            level = int(text)
            if not 1 <= level <= 100:
                raise ValueError
        except ValueError:
            await update.effective_message.reply_text("عدد باید بین ۱ تا ۱۰۰ باشد. دوباره از /admin وارد شو.")
            return
        db.set_admin_level(state["chat_id"], level)
        await update.effective_message.reply_text(f"✅ لول لازم برای درخواست ادمینی روی {level} تنظیم شد.")
    elif state["kind"] == "search":
        groups = db.get_groups()
        if not groups:
            await update.effective_message.reply_text("هنوز گروهی ثبت نشده.")
            return
        chat_id = state["chat_id"]
        members = db.get_members(chat_id, limit=100)
        query = text.casefold().lstrip("@")
        found = [m for m in members if query in (m["full_name"] or "").casefold() or query in (m["username"] or "").casefold() or query == str(m["user_id"])]
        if not found:
            await update.effective_message.reply_text("عضوی با این مشخصات در ۱۰۰ عضو اول پیدا نشد. از فهرست اعضا استفاده کن.")
            return
        rows = [[InlineKeyboardButton(f"👤 {m['full_name'][:30]}", callback_data=f"member:{chat_id}:{m['user_id']}")] for m in found[:20]]
        rows.append([InlineKeyboardButton("↩️ منوی اصلی", callback_data="home")])
        await update.effective_message.reply_text("نتایج جست‌وجو:", reply_markup=InlineKeyboardMarkup(rows))

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    data = query.data or ""
    if data == "home":
        groups = await groups_for_user(context, user.id)
        if not groups:
            await query.answer("گروه قابل مدیریتی پیدا نشد.", show_alert=True)
            return
        await query.answer()
        await query.edit_message_text("💚 <b>پنل مدیریت زمرد</b>\nگروهی را انتخاب کن که در آن مدیر تلگرام هستی:", parse_mode="HTML", reply_markup=panel.group_picker(groups))
        return

    # Validate authorization for every callback that targets a specific group.
    # Callback data is user-editable in principle, so never trust a chat_id alone.
    group_scoped = {"group", "members", "member", "points", "title", "badges",
                    "badge_toggle", "badge_clear", "history", "settings", "levelset",
                    "announce", "search", "requests", "request_view",
                    "request_reject", "request_approve"}
    prefix = data.split(":", 1)[0]
    if prefix in group_scoped:
        parts_for_auth = data.split(":")
        try:
            if prefix == "members" and len(parts_for_auth) == 2:
                # Old single-group pagination callback; resolve only among allowed groups.
                allowed = await groups_for_user(context, user.id)
                if len(allowed) != 1:
                    await query.answer("ابتدا گروه را از /admin انتخاب کن.", show_alert=True)
                    return
                authorized_chat_id = allowed[0]["chat_id"]
            else:
                authorized_chat_id = int(parts_for_auth[1])
        except (ValueError, IndexError):
            await query.answer("دکمه نامعتبر است. دوباره /admin را بزن.", show_alert=True)
            return
        if not await is_group_admin(context, authorized_chat_id, user.id):
            await query.answer("⛔ فقط مدیر همان گروه می‌تواند این بخش را مدیریت کند.", show_alert=True)
            return
    elif prefix not in ("help",):
        await query.answer("دکمه نامعتبر است.", show_alert=True)
        return

    await query.answer()
    try:
        if data.startswith("group:"):
            _, chat_id_raw, action = data.split(":")
            chat_id = int(chat_id_raw)
            group = db.get_group(chat_id)
            if not group:
                await query.edit_message_text("گروه پیدا نشد. /admin را دوباره بزن.")
                return
            if action == "open":
                await query.edit_message_text(
                    f"💚 <b>{group['title']}</b>\n\n"
                    f"👥 اعضای ثبت‌شده: {db.member_count(chat_id)}\n"
                    f"🎯 لول درخواست ادمینی: {group['admin_level']}\n\nیک بخش را انتخاب کن:",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("👥 مدیریت اعضا", callback_data=f"members:{chat_id}:0")],
                        [InlineKeyboardButton("🔎 جست‌وجوی عضو", callback_data=f"search:{chat_id}")],
                        [InlineKeyboardButton("🏆 درخواست‌های ادمینی", callback_data=f"requests:{chat_id}")],
                        [InlineKeyboardButton("⚙️ تنظیمات گروه", callback_data=f"settings:{chat_id}")],
                        [InlineKeyboardButton("↩️ انتخاب گروه", callback_data="home")],
                    ])
                )
            return
        if data.startswith("members:"):
            parts = data.split(":")
            groups = await groups_for_user(context, user.id)
            if not groups:
                await query.edit_message_text("گروهی برای مدیریت پیدا نشد.")
                return
            if len(parts) == 3:
                chat_id, offset = int(parts[1]), int(parts[2])
            else:
                offset = int(parts[1])
                if len(groups) > 1:
                    await query.edit_message_text("ابتدا گروه را انتخاب کن:", reply_markup=panel.group_picker(groups))
                    return
                chat_id = groups[0]["chat_id"]
            if not db.get_group(chat_id):
                await query.edit_message_text("گروه پیدا نشد. /admin را دوباره بزن.")
                return
            members = db.get_members(chat_id, limit=10, offset=offset)
            total = db.member_count(chat_id)
            await query.edit_message_text(
                f"👥 <b>اعضای ثبت‌شده</b> ({min(offset+1,total) if total else 0}–{min(offset+len(members),total)} از {total})",
                parse_mode="HTML", reply_markup=panel.members_keyboard(chat_id, offset, members, total)
            )
            return
        if data.startswith("member:"):
            _, chat_raw, user_raw = data.split(":")
            chat_id, target_id = int(chat_raw), int(user_raw)
            m = db.get_member(chat_id, target_id)
            if not m:
                await query.edit_message_text("عضو پیدا نشد.")
                return
            body, markup = panel.member_card(chat_id, m)
            await query.edit_message_text(body, parse_mode="HTML", reply_markup=markup)
            return
        if data.startswith("points:"):
            _, chat_raw, target_raw, amount_raw = data.split(":")
            chat_id, target_id, amount = int(chat_raw), int(target_raw), int(amount_raw)
            pending_input[user.id] = {"kind": "reason", "chat_id": chat_id, "user_id": target_id, "amount": amount}
            await query.message.reply_text(
                f"برای ثبت {amount:+d} امتیاز ویژه، دلیل را در یک پیام بفرست.\n"
                "برای دلیل کوتاه هم می‌توانی بنویسی: پاداش فعالیت"
            )
            return
        if data.startswith("title:"):
            _, chat_raw, target_raw = data.split(":")
            pending_input[user.id] = {"kind": "title", "chat_id": int(chat_raw), "user_id": int(target_raw)}
            await query.message.reply_text("لقب جدید را بفرست (حداکثر ۶۰ نویسه). برای حذف لقب بنویس: حذف")
            return
        if data.startswith("badges:"):
            _, chat_raw, target_raw = data.split(":")
            chat_id, target_id = int(chat_raw), int(target_raw)
            m = db.get_member(chat_id, target_id)
            try:
                existing = json.loads(m["custom_badges"] or "[]")
            except (TypeError, json.JSONDecodeError):
                existing = []
            await query.edit_message_text("🎖 نشان‌های دستی عضو را انتخاب کن:", reply_markup=panel.badge_keyboard(chat_id, target_id, existing))
            return
        if data.startswith("badge_toggle:"):
            _, chat_raw, target_raw, index_raw = data.split(":")
            chat_id, target_id, badge_index = int(chat_raw), int(target_raw), int(index_raw)
            if badge_index < 0 or badge_index >= len(panel.BADGE_OPTIONS):
                await query.answer("این نشان معتبر نیست.", show_alert=True)
                return
            m = db.get_member(chat_id, target_id)
            if not m:
                await query.answer("عضو پیدا نشد.", show_alert=True)
                return
            try:
                existing = json.loads(m["custom_badges"] or "[]")
            except (TypeError, json.JSONDecodeError):
                existing = []
            emoji, name = panel.BADGE_OPTIONS[badge_index]
            item = {"emoji": emoji, "name": name}
            if item in existing:
                existing.remove(item)
            else:
                existing.append(item)
            db.set_custom_badges(chat_id, target_id, existing)
            await query.edit_message_reply_markup(reply_markup=panel.badge_keyboard(chat_id, target_id, existing))
            return
        if data.startswith("badge_clear:"):
            _, chat_raw, target_raw = data.split(":")
            chat_id, target_id = int(chat_raw), int(target_raw)
            db.set_custom_badges(chat_id, target_id, [])
            await query.edit_message_text("نشان‌های دستی پاک شدند.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ بازگشت به عضو", callback_data=f"member:{chat_id}:{target_id}")]]))
            return
        if data.startswith("history:"):
            _, chat_raw, target_raw = data.split(":")
            chat_id, target_id = int(chat_raw), int(target_raw)
            rows = db.history_for_member(chat_id, target_id)
            if rows:
                lines = ["📜 <b>تاریخچه امتیاز ویژه</b>"]
                for r in rows:
                    sign = "+" if r["amount"] > 0 else ""
                    reason = (r["reason"] or "بدون دلیل").replace("<", "‹").replace(">", "›")
                    lines.append(f"{sign}{r['amount']} ⭐ — {reason}")
                text = "\n".join(lines)
            else:
                text = "هنوز تاریخچه‌ای برای این عضو ثبت نشده."
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ بازگشت به عضو", callback_data=f"member:{chat_id}:{target_id}")]]))
            return
        if data.startswith("settings:"):
            chat_id = int(data.split(":")[1])
            g = db.get_group(chat_id)
            await query.edit_message_text("⚙️ <b>تنظیمات گروه</b>", parse_mode="HTML",
                                          reply_markup=panel.settings_keyboard(chat_id, g["admin_level"], g["rankup_announcements"]))
            return
        if data.startswith("levelset:"):
            chat_id = int(data.split(":")[1])
            pending_input[user.id] = {"kind": "admin_level", "chat_id": chat_id}
            await query.message.reply_text("لول لازم برای درخواست ادمینی را به‌صورت عدد ۱ تا ۱۰۰ بفرست.")
            return
        if data.startswith("announce:"):
            chat_id = int(data.split(":")[1])
            g = db.get_group(chat_id)
            db.set_announcements(chat_id, not bool(g["rankup_announcements"]))
            g = db.get_group(chat_id)
            await query.edit_message_reply_markup(reply_markup=panel.settings_keyboard(chat_id, g["admin_level"], g["rankup_announcements"]))
            return
        if data.startswith("search:"):
            chat_id = int(data.split(":")[1])
            pending_input[user.id] = {"kind": "search", "chat_id": chat_id}
            await query.message.reply_text("نام، نام کاربری (بدون @) یا شناسه عددی عضو را بفرست.")
            return
        if data.startswith("requests:"):
            chat_id = int(data.split(":")[1])
            requests = db.get_admin_requests(chat_id)
            if not requests:
                await query.edit_message_text("درخواست در انتظار بررسی وجود ندارد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ منوی گروه", callback_data=f"group:{chat_id}:open")]]))
                return
            rows = []
            for r in requests[:30]:
                m = db.get_member(chat_id, r["user_id"])
                name = m["full_name"] if m else str(r["user_id"])
                rows.append([InlineKeyboardButton(f"👤 {name[:25]} · تأیید/رد", callback_data=f"request_view:{chat_id}:{r['user_id']}")])
            rows.append([InlineKeyboardButton("↩️ منوی گروه", callback_data=f"group:{chat_id}:open")])
            await query.edit_message_text("🏆 <b>درخواست‌های ادمینی</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows))
            return
        if data.startswith("request_view:"):
            _, chat_raw, target_raw = data.split(":")
            chat_id, target_id = int(chat_raw), int(target_raw)
            m = db.get_member(chat_id, target_id)
            name = m["full_name"] if m else str(target_id)
            await query.edit_message_text(f"درخواست ادمینی برای <b>{name}</b> · <code>{target_id}</code>", parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ تأیید و ارتقا در تلگرام", callback_data=f"request_approve:{chat_id}:{target_id}")],
                    [InlineKeyboardButton("❌ رد درخواست", callback_data=f"request_reject:{chat_id}:{target_id}")],
                    [InlineKeyboardButton("⬅️ درخواست‌ها", callback_data=f"requests:{chat_id}")],
                ]))
            return
        if data.startswith("request_reject:"):
            _, chat_raw, target_raw = data.split(":")
            chat_id, target_id = int(chat_raw), int(target_raw)
            db.set_admin_request_status(chat_id, target_id, "rejected")
            await query.edit_message_text("درخواست رد شد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ درخواست‌ها", callback_data=f"requests:{chat_id}")]]))
            return
        if data.startswith("request_approve:"):
            _, chat_raw, target_raw = data.split(":")
            chat_id, target_id = int(chat_raw), int(target_raw)
            try:
                await context.bot.promote_chat_member(
                    chat_id=chat_id, user_id=target_id,
                    can_manage_chat=True, can_delete_messages=True, can_manage_video_chats=True,
                    can_restrict_members=True, can_promote_members=False, can_change_info=False,
                    can_invite_users=True, can_pin_messages=True,
                )
                db.set_admin_request_status(chat_id, target_id, "approved")
                await query.edit_message_text("✅ درخواست تأیید شد و عضو ارتقا یافت.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ درخواست‌ها", callback_data=f"requests:{chat_id}")]]))
            except TelegramError as exc:
                logger.warning("Promote failed for %s in %s: %s", target_id, chat_id, exc)
                await query.edit_message_text(
                    "❌ تلگرام اجازه ارتقا نداد.\n"
                    "مطمئن شو بات در گروه ادمین است و مجوز افزودن/ارتقای ادمین‌ها را دارد. ممکن است سطح دسترسی بات برای این کار کافی نباشد.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ درخواست‌ها", callback_data=f"requests:{chat_id}")]])
                )
            return
        if data == "help":
            await query.edit_message_text(
                "📌 <b>راهنما</b>\n"
                "• XP از پیام‌های واجد شرایط به دست می‌آید.\n"
                "• امتیاز ویژه فقط از پنل داده می‌شود و روی لول اثر ندارد.\n"
                "• لقب و نشان‌های دستی از پروفایل عضو قابل مدیریت‌اند.\n"
                "• درخواست ادمینی پس از رسیدن به لول تعیین‌شده بررسی می‌شود.",
                parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ بازگشت", callback_data="home")]])
            )
    except (ValueError, KeyError, TypeError) as exc:
        logger.exception("Invalid callback %s: %s", data, exc)
        try:
            await query.message.reply_text("یک خطا رخ داد. دوباره از /admin وارد پنل شو.")
        except TelegramError:
            pass

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat and update.effective_chat.type == ChatType.PRIVATE:
        await update.effective_message.reply_text("دستور ناشناخته است. برای راهنما /help و برای پنل گروه‌هایی که مدیرشان هستی /admin را بزن.")

def main():
    errors = validate_config()
    if errors:
        print("تنظیمات ناقص است:")
        for err in errors:
            print(f"- {err}")
        raise SystemExit(1)
    db.init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("me", profile))
    app.add_handler(CommandHandler("rank", profile))
    app.add_handler(CommandHandler("top", top_command))
    app.add_handler(CommandHandler("rewards", rewards_command))
    app.add_handler(CommandHandler("admin_request", admin_request))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, handle_text_input))
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & ~filters.COMMAND, group_message))
    app.add_handler(CommandHandler("unknown", unknown_command))
    print("Emerald Group Bot is running. Stop with Ctrl+C.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
