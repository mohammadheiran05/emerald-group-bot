import json
from html import escape
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from levels import level_from_xp, rank_for_level, automatic_badges, next_level_progress
import database as db

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 مدیریت اعضا", callback_data="members:0"),
         InlineKeyboardButton("🏆 درخواست‌های ادمینی", callback_data="requests")],
        [InlineKeyboardButton("⚙️ تنظیمات گروه", callback_data="settings"),
         InlineKeyboardButton("📊 راهنما", callback_data="help")],
    ])

def group_picker(groups, action="open"):
    rows = [[InlineKeyboardButton(f"💚 {g['title'][:45]}", callback_data=f"group:{g['chat_id']}:{action}")]
            for g in groups]
    rows.append([InlineKeyboardButton("↩️ بازگشت", callback_data="home")])
    return InlineKeyboardMarkup(rows)

def members_keyboard(chat_id, offset, members, total):
    rows = []
    for m in members:
        name = escape((m["full_name"] or str(m["user_id"]))[:32])
        rows.append([InlineKeyboardButton(f"👤 {name} · لول {level_from_xp(m['xp'])}", callback_data=f"member:{chat_id}:{m['user_id']}")])
    nav = []
    if offset > 0:
        nav.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"members:{chat_id}:{max(0, offset-10)}"))
    if offset + 10 < total:
        nav.append(InlineKeyboardButton("بعدی ➡️", callback_data=f"members:{chat_id}:{offset+10}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("↩️ منوی اصلی", callback_data="home")])
    return InlineKeyboardMarkup(rows)

def member_card(chat_id, member):
    xp = int(member["xp"])
    level = level_from_xp(xp)
    rank_name, rank_icon = rank_for_level(level)
    earned, required, pct = next_level_progress(xp, level)
    custom_title = escape(str(member["custom_title"] or "بدون لقب اختصاصی"))
    try:
        custom_badges = json.loads(member["custom_badges"] or "[]")
    except json.JSONDecodeError:
        custom_badges = []
    auto = automatic_badges(level)
    badge_text = escape(" ".join(f"{b.get('emoji','🏅')} {b.get('name','نشان')}" for b in auto + custom_badges))
    if not badge_text:
        badge_text = "هنوز نشانی ندارد"
    text = (
        f"👤 <b>{escape(str(member['full_name'] or member['user_id']))}</b>\n"
        f"🆔 <code>{member['user_id']}</code>\n"
        f"{rank_icon} لول: <b>{level}/100 · {rank_name}</b>\n"
        f"✨ XP: <b>{xp:,}</b>  |  پیشرفت لول: {pct}% ({earned}/{required})\n"
        f"⭐ امتیاز ویژه: <b>{member['bonus_points']:,}</b>\n"
        f"🏷 لقب: <b>{custom_title}</b>\n"
        f"🎖 نشان‌ها: {badge_text}"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("+100 XP", callback_data=f"xp:{chat_id}:{member['user_id']}:100"),
         InlineKeyboardButton("−100 XP", callback_data=f"xp:{chat_id}:{member['user_id']}:-100")],
        [InlineKeyboardButton("+10 ⭐", callback_data=f"points:{chat_id}:{member['user_id']}:10"),
         InlineKeyboardButton("+50 ⭐", callback_data=f"points:{chat_id}:{member['user_id']}:50"),
         InlineKeyboardButton("+100 ⭐", callback_data=f"points:{chat_id}:{member['user_id']}:100")],
        [InlineKeyboardButton("−10 ⭐", callback_data=f"points:{chat_id}:{member['user_id']}:-10"),
         InlineKeyboardButton("−50 ⭐", callback_data=f"points:{chat_id}:{member['user_id']}:-50")],
        [InlineKeyboardButton("🏷 تعیین لقب", callback_data=f"title:{chat_id}:{member['user_id']}")],
        [InlineKeyboardButton("🎖 اختصاص نشان", callback_data=f"badges:{chat_id}:{member['user_id']}")],
        [InlineKeyboardButton("📜 تاریخچه امتیاز", callback_data=f"history:{chat_id}:{member['user_id']}")],
        [InlineKeyboardButton("⬅️ فهرست اعضا", callback_data=f"members:{chat_id}:0"),
         InlineKeyboardButton("🏠 منوی اصلی", callback_data="home")],
    ])
    return text, kb

BADGE_OPTIONS = [("🌟", "ستاره‌دار"), ("💚", "یار وفادار"), ("🏆", "قهرمان"), ("🛡️", "عضو قابل اعتماد"), ("🎯", "ماموریت‌انجام‌ده")]

def badge_keyboard(chat_id, user_id, existing):
    rows = []
    for index, (emoji, name) in enumerate(BADGE_OPTIONS):
        has = any(b.get("emoji") == emoji and b.get("name") == name for b in existing)
        label = ("✅ " if has else "➕ ") + emoji + " " + name
        # Keep callback_data short: Telegram limits it to 64 bytes.
        rows.append([InlineKeyboardButton(label, callback_data=f"badge_toggle:{chat_id}:{user_id}:{index}")])
    rows.append([InlineKeyboardButton("🧹 پاک کردن نشان‌های دستی", callback_data=f"badge_clear:{chat_id}:{user_id}")])
    rows.append([InlineKeyboardButton("⬅️ بازگشت به عضو", callback_data=f"member:{chat_id}:{user_id}")])
    return InlineKeyboardMarkup(rows)

def settings_keyboard(chat_id, admin_level, announcements):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🎯 لول ادمینی: {admin_level}", callback_data=f"levelset:{chat_id}")],
        [InlineKeyboardButton("🔔 پیام ارتقای لول: روشن" if announcements else "🔕 پیام ارتقای لول: خاموش",
                              callback_data=f"announce:{chat_id}")],
        [InlineKeyboardButton("🛡️ تنظیمات XP و ضداسپم", callback_data=f"xpset:{chat_id}")],
        [InlineKeyboardButton("↩️ منوی اصلی", callback_data="home")],
    ])
