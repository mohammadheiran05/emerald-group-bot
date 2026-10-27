import json
from html import escape
from datetime import datetime, timezone
import logging
import time

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand,
    BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats, MenuButtonCommands,
)
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

# Telegram slash-command menus for groups and private chats.
GROUP_COMMANDS = [
    BotCommand("start", "فعال‌سازی و معرفی ربات"),
    BotCommand("help", "راهنمای همه دستورها"),
    BotCommand("me", "پروفایل، XP و لول من"),
    BotCommand("rank", "رتبه و پیشرفت لول من"),
    BotCommand("top", "۱۰ عضو برتر گروه"),
    BotCommand("rewards", "راهنمای نشان‌ها و پاداش‌ها"),
    BotCommand("league", "نمایش لیگ گروه"),
    BotCommand("missions", "مأموریت‌های روزانه و هفتگی"),
    BotCommand("shop", "فروشگاه خرید با XP"),
    BotCommand("inventory", "کلکسیون و فعال‌سازی خریدها"),
    BotCommand("transactions", "تاریخچه تغییرات XP"),
    BotCommand("achievements", "دستاوردهای من"),
    BotCommand("admin_request", "درخواست بررسی ادمینی"),
    BotCommand("admin", "راهنمای پنل مدیریت"),
]
PRIVATE_COMMANDS = [
    BotCommand("start", "شروع و معرفی ربات"),
    BotCommand("help", "راهنمای دستورها"),
    BotCommand("admin", "باز کردن پنل مدیریت گروه‌ها"),
]

async def setup_bot_commands(app: Application):
    """Publish slash-command suggestions in Telegram group and private chats."""
    try:
        await app.bot.set_my_commands(
            GROUP_COMMANDS, scope=BotCommandScopeAllGroupChats()
        )
        await app.bot.set_my_commands(
            PRIVATE_COMMANDS, scope=BotCommandScopeAllPrivateChats()
        )
        # Show Telegram's built-in command menu button in private chats.
        await app.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        logger.info("Telegram command menus configured for groups and private chats")
    except TelegramError:
        # A menu setup issue should be visible in logs, but must not crash the bot.
        logger.exception("Could not configure Telegram command menus")

# The owner can type a title or a custom point reason after choosing a button.
pending_input = {}

def is_owner(user_id):
    return user_id == OWNER_ID

def safe_name(user):
    return escape(user.full_name or user.first_name or str(user.id))

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
        "/league — لیگ فعلی\n"
        "/missions — مأموریت روزانه و هفتگی\n"
        "/shop — فروشگاه XP گروه\n"
        "/inventory — کلکسیون و فعال‌سازی محصولات\n"
        "/transactions — تاریخچه تغییرات XP\n"
        "/achievements — دستاوردهای دائمی\n"
        "/admin_request — درخواست بررسی برای ادمین شدن\n"
        "/admin — باز کردن پنل گروه‌هایی که مدیر تلگرامشان هستی"
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
    mode = db.get_level_mode(chat.id)
    level = level_from_xp(xp, mode, db.get_level_costs(chat.id))
    rank, icon = rank_for_level(level)
    earned, required, pct = next_level_progress(xp, level, mode, db.get_level_costs(chat.id))
    badges = automatic_badges(level)
    try:
        custom = json.loads(m["custom_badges"] or "[]")
    except json.JSONDecodeError:
        custom = []
    badge_text = escape(" ".join(f"{b.get('emoji', '🏅')} {b.get('name', 'نشان')}" for b in badges + custom)) or "هنوز نشانی نگرفته‌ای"
    title = m.get("active_shop_title") or m["custom_title"] or rank
    shop_badge = escape(str(m.get("active_shop_badge") or ""))
    shop_frame = escape(str(m.get("active_shop_frame") or ""))
    await update.effective_message.reply_text(
        f"💚 <b>پروفایل {safe_name(user)}</b>\n\n"
        f"🏷 لقب: <b>{escape(str(title))}</b>\n"
        f"{icon} سطح: <b>{level}/100 · {rank}</b>\n"
        f"✨ XP: <b>{xp:,}</b>\n"
        f"📈 پیشرفت لول بعدی: <b>{pct}%</b> ({earned}/{required})\n"
        f"⭐ امتیاز ویژه: <b>{m['bonus_points']:,}</b>\n"
        f"🎖 نشان‌ها: {badge_text}\n"
        f"🛍 نشان فعال: {shop_badge or 'ندارد'}\n"
        f"🖼 قاب پروفایل: {shop_frame or 'ندارد'}",
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
        level = level_from_xp(m["xp"], db.get_level_mode(chat.id), db.get_level_costs(chat.id))
        rank, icon = rank_for_level(level)
        lines.append(f"{i}. {icon} {escape(str(m['full_name'] or m['user_id']))} — لول {level} · {m['xp']:,} XP")
    await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")

async def league_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat=update.effective_chat
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await update.effective_message.reply_text("این دستور را داخل گروه بزن."); return
    m=db.get_member(chat.id,update.effective_user.id)
    if not m:
        await update.effective_message.reply_text("هنوز اطلاعاتی ثبت نشده؛ چند پیام بفرست."); return
    level=level_from_xp(m["xp"], db.get_level_mode(chat.id), db.get_level_costs(chat.id))
    leagues=[(1,"🥉 برنز"),(11,"🥈 نقره"),(26,"🥇 طلا"),(46,"💎 الماس"),(66,"💚 زمرد")]
    league=max((label for threshold,label in leagues if level>=threshold),default="🥉 برنز")
    await update.effective_message.reply_text(f"🏆 لیگ فعلی: {league}\nلول: {level}/100\nXP: {m['xp']:,}\nرتبه‌بندی هر گروه مستقل است.")

async def missions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat=update.effective_chat; user=update.effective_user
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await update.effective_message.reply_text("این دستور را داخل گروه بزن."); return
    db.register_group(chat.id, chat.title or "گروه")
    m=db.get_member(chat.id,user.id)
    if not m:
        await update.effective_message.reply_text("برای شروع مأموریت‌ها چند پیام در گروه بفرست."); return
    group=db.get_group(chat.id) or {}
    today=datetime.now(timezone.utc).date(); day=today.isoformat(); iso=today.isocalendar(); week_key=f"{iso.year}-W{iso.week:02d}"
    daily=int(m.get("xp_today",0)) if m.get("xp_day")==day else 0
    weekly=int(m.get("xp_week",0)) if m.get("xp_week_key")==week_key else 0
    dt=int(group.get("daily_mission_target",100)); dr=int(group.get("daily_mission_reward",25))
    wt=int(group.get("weekly_mission_target",500)); wr=int(group.get("weekly_mission_reward",100))
    msg_target=int(group.get("daily_message_target",20)); msg_reward=int(group.get("daily_message_reward",20))
    messages_today=int(m.get("messages_today",0)) if m.get("messages_day")==day else 0
    messages=[f"🎯 <b>مأموریت XP روزانه</b>: {daily:,}/{dt:,} XP",f"🎁 پاداش: {dr:,} XP", "", f"💬 <b>مأموریت فعالیت روزانه</b>: {messages_today:,}/{msg_target:,} پیام",f"🎁 پاداش: {msg_reward:,} XP", "", f"🗓️ <b>مأموریت XP هفتگی</b>: {weekly:,}/{wt:,} XP",f"🎁 پاداش: {wr:,} XP"]
    reward_text=[]
    if daily>=dt:
        if db.claim_mission(chat.id,user.id,"daily_custom",day):
            db.award_admin_xp(chat.id,user.id,dr,0,"پاداش مأموریت روزانه"); reward_text.append(f"روزانه +{dr} XP")
        else: messages.append("\n✅ پاداش روزانه این دوره قبلاً دریافت شده است.")
    if weekly>=wt:
        if db.claim_mission(chat.id,user.id,"weekly_custom",week_key):
            db.award_admin_xp(chat.id,user.id,wr,0,"پاداش مأموریت هفتگی"); reward_text.append(f"هفتگی +{wr} XP")
        else: messages.append("\n✅ پاداش هفتگی این دوره قبلاً دریافت شده است.")
    if messages_today>=msg_target:
        if db.claim_mission(chat.id,user.id,"daily_messages",day):
            db.award_admin_xp(chat.id,user.id,msg_reward,0,"پاداش مأموریت تعداد پیام روزانه"); reward_text.append(f"فعالیت روزانه +{msg_reward} XP")
        else: messages.append("\n✅ پاداش فعالیت روزانه این دوره قبلاً دریافت شده است.")
    if reward_text: messages.append("\n🏆 پاداش دریافت شد: "+"؛ ".join(reward_text))
    elif daily<dt and weekly<wt and messages_today<msg_target: messages.append("\nبا فعالیت طبیعی و پیام‌های غیرتکراری پیشرفت کن؛ پاداش هر مأموریت در هر دوره فقط یک‌بار پرداخت می‌شود.")
    await update.effective_message.reply_text("\n".join(messages),parse_mode="HTML")

async def achievements_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat=update.effective_chat; user=update.effective_user
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await update.effective_message.reply_text("این دستور را داخل گروه بزن."); return
    m=db.get_member(chat.id,user.id)
    if not m:
        await update.effective_message.reply_text("هنوز اطلاعاتی ثبت نشده."); return
    thresholds=[(100,"اولین صد XP"),(1000,"هزار XP"),(5000,"پنج هزار XP"),(10000,"ده هزار XP")]
    earned=[]
    for threshold,label in thresholds:
        if int(m["xp"])>=threshold and db.earn_achievement(chat.id,user.id,str(threshold)):
            earned.append(label)
    existing=db.get_achievements(chat.id,user.id)
    labels={str(t):name for t,name in thresholds}
    lines=["🏅 <b>دستاوردهای دائمی</b>"]
    lines += ["✅ "+labels.get(a["achievement_key"],a["achievement_key"]) for a in existing]
    lines += ["هنوز دستاوردی نگرفته‌ای."] if not existing else []
    if earned: lines.append("\nتازه دریافت شد: "+"، ".join(earned))
    await update.effective_message.reply_text("\n".join(lines),parse_mode="HTML")

async def shop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat=update.effective_chat; user=update.effective_user
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await update.effective_message.reply_text("برای خرید، دستور /shop را داخل گروه بزن."); return
    db.register_group(chat.id,chat.title or "گروه"); db.upsert_member(chat.id,user)
    items=db.get_shop_items(chat.id)
    if not items:
        await update.effective_message.reply_text("🛍 فروشگاه این گروه هنوز محصولی ندارد. از مدیر گروه بخواه فروشگاه را در پنل تنظیم کند."); return
    m=db.get_member(chat.id,user.id)
    await update.effective_message.reply_text(f"💚 <b>فروشگاه زمرد</b>\nموجودی تو: <b>{m['xp']:,} XP</b>\nبرای خرید، محصول را انتخاب کن:",parse_mode="HTML",reply_markup=panel.shop_keyboard(chat.id,items,user.id))

async def transactions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat=update.effective_chat; user=update.effective_user
    if chat.type not in (ChatType.GROUP,ChatType.SUPERGROUP):
        await update.effective_message.reply_text("این دستور را داخل گروه بزن."); return
    rows=db.xp_transaction_history(chat.id,user.id,10)
    if not rows:
        await update.effective_message.reply_text("هنوز تراکنش XP ثبت نشده است."); return
    lines=["🧾 <b>تاریخچه XP تو</b>"]
    for row in rows:
        amount=int(row["amount"]); sign="+" if amount>0 else ""
        desc=escape(str(row["description"] or row["kind"]))
        stamp=datetime.fromtimestamp(int(row["created_at"]),timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines.append(f"{sign}{amount:,} XP · موجودی {int(row['balance_after']):,} · {desc}\n<code>{stamp}</code>")
    await update.effective_message.reply_text("\n\n".join(lines),parse_mode="HTML")

async def inventory_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat=update.effective_chat; user=update.effective_user
    if chat.type not in (ChatType.GROUP,ChatType.SUPERGROUP):
        await update.effective_message.reply_text("این دستور را داخل گروه بزن."); return
    inv=db.get_inventory(chat.id,user.id)
    if not inv:
        await update.effective_message.reply_text("🎒 کلکسیونت هنوز خالی است. برای دیدن فروشگاه /shop را بزن."); return
    rows=[]
    for item in inv[:30]:
        rows.append([InlineKeyboardButton(f"{item['emoji']} {item['name'][:25]} · فعال‌سازی",callback_data=f"equip:{chat.id}:{item['item_id']}")])
    await update.effective_message.reply_text("🎒 <b>کلکسیون تو</b>\nروی محصولی بزن تا آن را در پروفایلت فعال کنی:",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(rows))

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
    required = int(group["admin_level"]) if group else DEFAULT_ADMIN_LEVEL
    level = level_from_xp(m["xp"], db.get_level_mode(chat.id), db.get_level_costs(chat.id))
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
    result = db.upsert_member(chat.id, user, XP_PER_MESSAGE, award_xp=True, cooldown_seconds=XP_COOLDOWN_SECONDS, message_text=(msg.text or msg.caption or ""), track_activity=True)
    if result["got_xp"] and result["level"] > result["old_level"]:
        group = db.get_group(chat.id)
        if group and group["rankup_announcements"]:
            rank, icon = rank_for_level(result["level"])
            try:
                await msg.reply_text(
                    f"💚 تبریک {safe_name(user)}!\n{icon} به لول {result['level']} رسیدی؛ رتبه: {escape(str(rank))}."
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
    elif state["kind"] == "xp_reason":
        result=db.award_admin_xp(state["chat_id"],state["user_id"],state["amount"],user.id,text[:200])
        if not result:
            await update.effective_message.reply_text("عضو پیدا نشد؛ ممکن است از دیتابیس حذف شده باشد."); return
        await update.effective_message.reply_text(f"✅ XP تغییر کرد: {result['old_xp']:,} ← {result['xp']:,}\nلول: {result['old_level']} ← {result['level']}")
        m=db.get_member(state["chat_id"],state["user_id"])
        if m:
            body,markup=panel.member_card(state["chat_id"],m)
            await update.effective_message.reply_text(body,parse_mode="HTML",reply_markup=markup)
    elif state["kind"] == "reason":
        amount = state["amount"]
        value = db.change_bonus_points(state["chat_id"], state["user_id"], amount, user.id, text[:200])
        await update.effective_message.reply_text(f"✅ امتیاز ویژه به‌روزرسانی شد. موجودی فعلی: {value}")
    elif state["kind"] == "xp_settings":
        try:
            values=[int(x) for x in text.split()]
            if len(values)!=3 or not 1<=values[0]<=100 or not 5<=values[1]<=3600 or not 50<=values[2]<=10000: raise ValueError
        except ValueError:
            await update.effective_message.reply_text("فرمت نامعتبر است. سه عدد بفرست؛ مثال: 10 60 300. محدوده‌ها: XP=1..100، فاصله=5..3600، سقف روزانه=50..10000."); return
        db.set_xp_settings(state["chat_id"],*values)
        await update.effective_message.reply_text("✅ تنظیمات XP همین گروه ذخیره شد. XP و سابقه قبلی اعضا تغییر نکرد.")
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
    elif state["kind"] == "shop_price":
        try:
            price=int(text)
            if not 0<=price<=10000000: raise ValueError
            ok=db.update_shop_item_price(state["chat_id"],state["item_id"],price)
            await update.effective_message.reply_text("✅ قیمت محصول به‌روزرسانی شد." if ok else "محصول پیدا نشد.")
        except ValueError:
            pending_input[user.id]=state
            await update.effective_message.reply_text("قیمت باید عدد صحیح بین ۰ تا ۱۰٬۰۰۰٬۰۰۰ باشد. دوباره بفرست.")
    elif state["kind"] == "shop_add":
        try:
            parts=[x.strip() for x in text.split("|")]
            if len(parts)!=4: raise ValueError
            name,kind,price_raw,emoji=parts; kind_map={"لقب":"title","title":"title","نشان":"badge","badge":"badge","قاب":"frame","frame":"frame"}
            item_type=kind_map.get(kind.lower()); price=int(price_raw)
            if not item_type or not name or not 0<=price<=10000000: raise ValueError
            item_id=db.add_shop_item(state["chat_id"],item_type,name,emoji or "🎁",price,user.id)
            await update.effective_message.reply_text(f"✅ محصول #{item_id} به فروشگاه این گروه اضافه شد.")
        except (ValueError, Exception) as exc:
            logger.info("Shop item creation rejected: %s",exc)
            pending_input[user.id]=state
            await update.effective_message.reply_text("فرمت درست نیست یا این نام از قبل وجود دارد. این‌طور بفرست: نام محصول | نوع (لقب/نشان/قاب) | قیمت XP | ایموجی\nمثال: لقب زمردی | لقب | 500 | 💚")
    elif state["kind"] == "level_costs":
        try:
            costs={}
            for pair in text.replace(","," ").split():
                if "=" not in pair: raise ValueError
                level_raw,xp_raw=pair.split("=",1); level=int(level_raw); amount=int(xp_raw)
                if not 2<=level<=100 or not 1<=amount<=1000000: raise ValueError
                costs[level]=amount
            db.set_level_costs(state["chat_id"],costs)
            await update.effective_message.reply_text(f"✅ {len(costs)} سطح سفارشی ذخیره شد. فقط هزینه XP رسیدن به لول‌های واردشده تغییر می‌کند؛ لول‌های دیگر از فرمول حالت انتخابی استفاده می‌کنند. برای پاک کردن تنظیمات اختصاصی بنویس: پاک کردن")
        except ValueError:
            if text in ("پاک کردن","حذف","clear"):
                db.set_level_costs(state["chat_id"],{})
                await update.effective_message.reply_text("✅ هزینه‌های سفارشی پاک شدند و فرمول حالت انتخابی اعمال می‌شود.")
            else:
                pending_input[user.id]=state
                await update.effective_message.reply_text("فرمت: لول=XP و بین هر مورد فاصله بگذار. مثال: 2=80 3=120 4=180 10=500. لول باید ۲ تا ۱۰۰ و XP بین ۱ تا ۱٬۰۰۰٬۰۰۰ باشد. دوباره بفرست.")
    elif state["kind"] == "mission_settings":
        try:
            vals=[int(x) for x in text.split()]
            if len(vals) not in (4,6) or not 10<=vals[0]<=100000 or not 0<=vals[1]<=10000 or not vals[0]<=vals[2]<=1000000 or not 0<=vals[3]<=100000: raise ValueError
            if len(vals)==6 and (not 1<=vals[4]<=1000 or not 0<=vals[5]<=10000): raise ValueError
            db.set_mission_settings(state["chat_id"],*vals)
            await update.effective_message.reply_text("✅ تنظیم مأموریت‌ها ذخیره شد؛ هدف و پاداش XP روزانه/هفتگی و در صورت واردکردن دو عدد اضافه، مأموریت تعداد پیام روزانه به‌روزرسانی شدند.")
        except ValueError:
            pending_input[user.id]=state
            await update.effective_message.reply_text("چهار یا شش عدد بفرست: هدف XP روزانه، پاداش روزانه، هدف XP هفتگی، پاداش هفتگی [هدف تعداد پیام روزانه، پاداش آن]. مثال کامل: 100 25 500 100 20 20")
    elif state["kind"] == "search":
        groups = db.get_groups()
        if not groups:
            await update.effective_message.reply_text("هنوز گروهی ثبت نشده.")
            return
        chat_id = state["chat_id"]
        found = db.search_members(chat_id, text, limit=20)
        if not found:
            await update.effective_message.reply_text("عضوی با این مشخصات پیدا نشد. نام، نام کاربری یا شناسه را بررسی کن.")
            return
        rows = [[InlineKeyboardButton(f"👤 {escape(str(m['full_name'] or m['user_id']))[:30]}", callback_data=f"member:{chat_id}:{m['user_id']}")] for m in found[:20]]
        rows.append([InlineKeyboardButton("↩️ منوی اصلی", callback_data="home")])
        await update.effective_message.reply_text("نتایج جست‌وجو:", reply_markup=InlineKeyboardMarkup(rows))

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    data = query.data or ""
    # Member-facing shop actions: purchase is atomic and does not require admin rights.
    if data.startswith("shopbuy:"):
        try:
            parts=data.split(":")
            _, chat_raw, item_raw = parts[:3]
            currency = parts[3] if len(parts) > 3 else "xp"
            chat_id=int(chat_raw); item_id=int(item_raw)
            result=db.buy_shop_item(chat_id,user.id,item_id,currency)
            if not result["ok"]:
                reason=result.get("reason")
                messages={
                    "unavailable":"این محصول دیگر در دسترس نیست.",
                    "member_missing":"ابتدا در گروه چند پیام بفرست و دوباره تلاش کن.",
                    "owned":"این محصول را قبلاً خریده‌ای.",
                    "funds":f"XP کافی نداری. موجودی: {result.get('balance',0):,}؛ قیمت: {result.get('price',0):,} XP.",
                    "points_funds":f"امتیاز ویژه کافی نداری. موجودی: {result.get('balance',0):,}؛ قیمت: {result.get('price',0):,} ⭐.",
                    "bad_currency":"روش پرداخت معتبر نیست.",
                }
                await query.answer(messages.get(reason,"خرید انجام نشد."),show_alert=True); return
            item=result["item"]
            await query.answer(f"خرید موفق! {item['emoji']} {item['name']}",show_alert=True)
            items=db.get_shop_items(chat_id)
            await query.edit_message_text(
                f"💚 <b>فروشگاه زمرد</b>\nخریدت ثبت شد: {item['emoji']} <b>{escape(item['name'])}</b>\n"
                f"موجودی XP: <b>{result['balance']:,}</b> (بدون کسر)\n"
                f"امتیاز ویژه: <b>{result['points_balance']:,} ⭐</b>\n"
                "برای فعال‌سازی محصول، کلکسیونت را باز کن.",
                parse_mode="HTML",reply_markup=panel.shop_keyboard(chat_id,items,user.id))
        except Exception as exc:
            logger.exception("Shop purchase failed: %s",exc); await query.answer("خطا در خرید؛ موجودی را بررسی کن و دوباره تلاش کن.",show_alert=True)
        return
    if data.startswith("shopowned:"):
        await query.answer("این محصول را قبلاً خریده‌ای.",show_alert=True)
        return
    if data.startswith("shopinfo:"):
        await query.answer("روش پرداخت را انتخاب کن: XP (بدون کسر) یا ⭐ امتیاز ویژه (از موجودی کم می‌شود).",show_alert=True)
        return
    if data.startswith("inventory:"):
        try:
            _,chat_raw,target_raw=data.split(":"); chat_id=int(chat_raw); target_id=int(target_raw)
            if target_id!=user.id: await query.answer("این کلکسیون متعلق به کاربر دیگری است.",show_alert=True); return
            inv=db.get_inventory(chat_id,user.id); rows=[]
            for item in inv[:30]: rows.append([InlineKeyboardButton(f"{item['emoji']} {item['name'][:25]} · فعال‌سازی",callback_data=f"equip:{chat_id}:{item['item_id']}")])
            rows.append([InlineKeyboardButton("⬅️ بازگشت به فروشگاه",callback_data=f"shopopen:{chat_id}")])
            await query.answer()
            body = "🎒 <b>کلکسیون تو</b>\nمحصولی را برای نمایش در پروفایل فعال کن:" if inv else "🎒 <b>کلکسیون تو خالی است.</b>\nاول از فروشگاه یک محصول بخر."
            await query.edit_message_text(body,parse_mode="HTML",reply_markup=InlineKeyboardMarkup(rows)); return
        except Exception as exc:
            logger.exception("Inventory callback failed: %s",exc); await query.answer("کلکسیون در دسترس نیست.",show_alert=True); return
    if data.startswith("equip:"):
        try:
            _,chat_raw,item_raw=data.split(":"); chat_id=int(chat_raw); item_id=int(item_raw)
            result=db.equip_shop_item(chat_id,user.id,item_id)
            if not result["ok"]: await query.answer("این محصول در کلکسیونت نیست.",show_alert=True); return
            await query.answer("در پروفایلت فعال شد!",show_alert=True)
            inv=db.get_inventory(chat_id,user.id); rows=[]
            for item in inv[:30]: rows.append([InlineKeyboardButton(f"{item['emoji']} {item['name'][:25]} · فعال‌سازی",callback_data=f"equip:{chat_id}:{item['item_id']}")])
            await query.edit_message_text("🎒 <b>کلکسیون تو</b>\nمحصول انتخاب‌شده در پروفایلت فعال شد.",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(rows or [[InlineKeyboardButton("🛍 فروشگاه",callback_data=f"shopopen:{chat_id}")]])); return
        except Exception as exc:
            logger.exception("Equip callback failed: %s",exc); await query.answer("فعال‌سازی انجام نشد.",show_alert=True); return
    if data.startswith("shopopen:"):
        try:
            chat_id=int(data.split(":")[1]); items=db.get_shop_items(chat_id); m=db.get_member(chat_id,user.id)
            await query.answer(); await query.edit_message_text(f"💚 <b>فروشگاه زمرد</b>\nموجودی: <b>{int((m or {}).get('xp',0)):,} XP</b>",parse_mode="HTML",reply_markup=panel.shop_keyboard(chat_id,items,user.id)); return
        except Exception: await query.answer("فروشگاه در دسترس نیست.",show_alert=True); return
    if data == "shopclose":
        await query.answer(); await query.edit_message_text("فروشگاه بسته شد."); return
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
                    "badge_toggle", "badge_clear", "history", "settings", "levelset", "xp",
                    "announce", "search", "requests", "request_view",
                    "request_reject", "request_approve", "xpset", "audit", "dashboard", "levelmode", "levelmode_set", "levelcustom", "missionset", "shopadmin", "shopadd", "shoptoggle", "shopprice", "xphistory"}
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
                    f"💚 <b>{escape(str(group['title']))}</b>\n\n"
                    f"👥 اعضای ثبت‌شده: {db.member_count(chat_id)}\n"
                    f"🎯 لول درخواست ادمینی: {group['admin_level']}\n\nیک بخش را انتخاب کن:",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("👥 مدیریت اعضا", callback_data=f"members:{chat_id}:0")],
                        [InlineKeyboardButton("🔎 جست‌وجوی عضو", callback_data=f"search:{chat_id}")],
                        [InlineKeyboardButton("🏆 درخواست‌های ادمینی", callback_data=f"requests:{chat_id}")],
                        [InlineKeyboardButton("🛍 مدیریت فروشگاه", callback_data=f"shopadmin:{chat_id}"), InlineKeyboardButton("📊 داشبورد", callback_data=f"dashboard:{chat_id}")],
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
        if data.startswith("xp:"):
            _, chat_raw, target_raw, amount_raw = data.split(":")
            chat_id, target_id, amount = int(chat_raw), int(target_raw), int(amount_raw)
            pending_input[user.id] = {"kind":"xp_reason", "chat_id":chat_id, "user_id":target_id, "amount":amount}
            await query.message.reply_text(f"برای تغییر {amount:+d} XP، دلیل را در یک پیام بفرست. تغییر با ثبت سابقه مدیریتی انجام می‌شود.")
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
        if data.startswith("xphistory:"):
            _,chat_raw,target_raw=data.split(":"); chat_id=int(chat_raw); target_id=int(target_raw)
            rows=db.xp_transaction_history(chat_id,target_id,10)
            if rows:
                lines=["🧾 <b>تاریخچه XP عضو</b>"]
                for row in rows:
                    amount=int(row["amount"]); sign="+" if amount>0 else ""; desc=escape(str(row["description"] or row["kind"]))
                    lines.append(f"{sign}{amount:,} XP · موجودی {int(row['balance_after']):,} · {desc}")
                body="\n".join(lines)
            else: body="هنوز تراکنش XP برای این عضو ثبت نشده است."
            await query.edit_message_text(body,parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ بازگشت به عضو",callback_data=f"member:{chat_id}:{target_id}")]])); return
        if data.startswith("dashboard:"):
            chat_id=int(data.split(":")[1]); d=db.group_dashboard(chat_id); g=db.get_group(chat_id) or {}
            mode=db.get_level_mode(chat_id); mode_label={"easy":"آسان","normal":"استاندارد","hard":"سخت"}.get(mode,"استاندارد")
            body=(f"📊 <b>داشبورد زمرد V2</b>\n\n👥 اعضای ثبت‌شده: <b>{d['members']:,}</b>\n"
                  f"✨ مجموع XP اعضا: <b>{d['xp_total']:,}</b>\n📅 اعضای فعال ۷ روز اخیر: <b>{d['active_7d']:,}</b>\n"
                  f"🛍 محصولات فعال فروشگاه: <b>{d['shop_items']}</b>\n🧾 خریدهای ثبت‌شده: <b>{d['purchases']}</b>\n"
                  f"📈 سختی لول: <b>{mode_label}</b>\n🎯 XP هر پیام: <b>{g.get('xp_per_message',10)}</b>\n"
                  f"🛡 فاصله XP: <b>{g.get('xp_cooldown_seconds',60)} ثانیه</b> · سقف روزانه: <b>{g.get('daily_xp_cap',300)}</b>")
            await query.edit_message_text(body,parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛍 مدیریت فروشگاه",callback_data=f"shopadmin:{chat_id}")],[InlineKeyboardButton("⚙️ تنظیمات",callback_data=f"settings:{chat_id}")],[InlineKeyboardButton("↩️ منوی گروه",callback_data=f"group:{chat_id}:open")]])); return
        if data.startswith("levelmode:"):
            chat_id=int(data.split(":")[1]); mode=db.get_level_mode(chat_id); labels={"easy":"آسان","normal":"استاندارد","hard":"سخت"}
            await query.edit_message_text(f"📈 <b>سیستم لول‌بندی این گروه</b>\nحالت فعلی: <b>{labels.get(mode,'استاندارد')}</b>\n\nتغییر حالت، XP اعضا را پاک یا تغییر نمی‌دهد؛ فقط محاسبه لول را عوض می‌کند.",parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🟢 آسان",callback_data=f"levelmode_set:{chat_id}:easy"),InlineKeyboardButton("⚖️ استاندارد",callback_data=f"levelmode_set:{chat_id}:normal")],[InlineKeyboardButton("🔥 سخت",callback_data=f"levelmode_set:{chat_id}:hard")],[InlineKeyboardButton("🧮 تعیین XP لول‌های مشخص",callback_data=f"levelcustom:{chat_id}")],[InlineKeyboardButton("⬅️ تنظیمات",callback_data=f"settings:{chat_id}")]])); return
        if data.startswith("levelmode_set:"):
            _,chat_raw,mode=data.split(":"); chat_id=int(chat_raw); db.set_level_mode(chat_id,mode)
            mode_name={"easy":"آسان","normal":"استاندارد","hard":"سخت"}[mode]
            await query.edit_message_text(f"✅ حالت لول‌بندی روی «{mode_name}» تنظیم شد. XP اعضا دست‌نخورده باقی مانده است.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ تنظیمات گروه",callback_data=f"settings:{chat_id}")]])); return
        if data.startswith("levelcustom:"):
            chat_id=int(data.split(":")[1]); pending_input[user.id]={"kind":"level_costs","chat_id":chat_id}
            await query.message.reply_text("🧮 هزینه XP برای لول‌های مشخص\nهر مورد را به شکل لول=XP بفرست و بین موارد فاصله بگذار. مثال: 2=80 3=120 4=180 10=500\nاین مقدار، XP لازم برای رسیدن از لول قبلی به همان لول است. فقط لول‌هایی که وارد می‌کنی سفارشی می‌شوند. برای پاک کردن همه موارد سفارشی بنویس: پاک کردن")
            return
        if data.startswith("missionset:"):
            chat_id=int(data.split(":")[1]); g=db.get_group(chat_id) or {}
            pending_input[user.id]={"kind":"mission_settings","chat_id":chat_id}
            await query.message.reply_text(f"🎯 تنظیم مأموریت‌ها\nXP روزانه: هدف {g.get('daily_mission_target',100)} / پاداش {g.get('daily_mission_reward',25)}؛ XP هفتگی: هدف {g.get('weekly_mission_target',500)} / پاداش {g.get('weekly_mission_reward',100)}؛ تعداد پیام روزانه: هدف {g.get('daily_message_target',20)} / پاداش {g.get('daily_message_reward',20)}.\nچهار عدد یا شش عدد بفرست. مثال کامل: 100 25 500 100 20 20")
            return
        if data.startswith("shopadmin:"):
            chat_id=int(data.split(":")[1]); items=db.get_shop_items(chat_id,active_only=False)
            await query.edit_message_text("🛍 <b>مدیریت فروشگاه گروه</b>\nروی محصول بزن تا فعال/غیرفعال شود. افزودن محصول با قالب ساده انجام می‌شود. محصولات و خریدها بین گروه‌ها جدا هستند.",parse_mode="HTML",reply_markup=panel.shop_admin_keyboard(chat_id,items)); return
        if data.startswith("shopadd:"):
            chat_id=int(data.split(":")[1]); pending_input[user.id]={"kind":"shop_add","chat_id":chat_id}
            await query.message.reply_text("نام محصول | نوع (لقب/نشان/قاب) | قیمت XP | ایموجی\nمثال: لقب زمردی | لقب | 500 | 💚\nقیمت باید عدد صحیح باشد؛ نام محصول در همان گروه یکتا است.")
            return
        if data.startswith("shopprice:"):
            _,chat_raw,item_raw=data.split(":"); chat_id=int(chat_raw); item_id=int(item_raw)
            pending_input[user.id]={"kind":"shop_price","chat_id":chat_id,"item_id":item_id}
            await query.message.reply_text("قیمت جدید محصول را فقط به شکل عدد بفرست (۰ تا ۱۰٬۰۰۰٬۰۰۰ XP).")
            return
        if data.startswith("shoptoggle:"):
            _,chat_raw,item_raw=data.split(":"); chat_id=int(chat_raw); item_id=int(item_raw); active=db.toggle_shop_item(chat_id,item_id)
            if active is None: await query.answer("محصول پیدا نشد.",show_alert=True); return
            items=db.get_shop_items(chat_id,active_only=False)
            await query.edit_message_text("وضعیت محصول به‌روزرسانی شد.",reply_markup=panel.shop_admin_keyboard(chat_id,items)); return
        if data.startswith("settings:"):
            chat_id = int(data.split(":")[1])
            g = db.get_group(chat_id)
            await query.edit_message_text("⚙️ <b>تنظیمات گروه</b>", parse_mode="HTML",
                                          reply_markup=panel.settings_keyboard(chat_id, g["admin_level"], g["rankup_announcements"]))
            return
        if data.startswith("xpset:"):
            chat_id=int(data.split(":")[1]); pending_input[user.id]={"kind":"xp_settings","chat_id":chat_id}
            await query.message.reply_text("تنظیمات را به شکل سه عدد بفرست: XP هر پیام، فاصله ثانیه‌ای، سقف XP روزانه. مثال: 10 60 300")
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
                name = escape(str(m["full_name"] if m else r["user_id"]))
                rows.append([InlineKeyboardButton(f"👤 {name[:25]} · تأیید/رد", callback_data=f"request_view:{chat_id}:{r['user_id']}")])
            rows.append([InlineKeyboardButton("↩️ منوی گروه", callback_data=f"group:{chat_id}:open")])
            await query.edit_message_text("🏆 <b>درخواست‌های ادمینی</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows))
            return
        if data.startswith("request_view:"):
            _, chat_raw, target_raw = data.split(":")
            chat_id, target_id = int(chat_raw), int(target_raw)
            m = db.get_member(chat_id, target_id)
            name = escape(str(m["full_name"] if m else target_id))
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
    app = Application.builder().token(BOT_TOKEN).post_init(setup_bot_commands).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("me", profile))
    app.add_handler(CommandHandler("rank", profile))
    app.add_handler(CommandHandler("top", top_command))
    app.add_handler(CommandHandler("rewards", rewards_command))
    app.add_handler(CommandHandler("league", league_command))
    app.add_handler(CommandHandler("missions", missions_command))
    app.add_handler(CommandHandler("shop", shop_command))
    app.add_handler(CommandHandler("inventory", inventory_command))
    app.add_handler(CommandHandler("transactions", transactions_command))
    app.add_handler(CommandHandler("achievements", achievements_command))
    app.add_handler(CommandHandler("admin_request", admin_request))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, handle_text_input))
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & ~filters.COMMAND, group_message))
    app.add_handler(CommandHandler("unknown", unknown_command))
    print("Emerald Group Bot is running. Stop with Ctrl+C.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
