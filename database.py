import json
import hashlib
import os
import sqlite3
import time
from pathlib import Path
from config import DATABASE_PATH, DEFAULT_ADMIN_LEVEL
from levels import level_from_xp

def _connect():
    Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    with _connect() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS groups (
            chat_id INTEGER PRIMARY KEY,
            title TEXT NOT NULL DEFAULT 'گروه',
            admin_level INTEGER NOT NULL DEFAULT 70,
            rankup_announcements INTEGER NOT NULL DEFAULT 1,
            created_at INTEGER NOT NULL,
            xp_per_message INTEGER NOT NULL DEFAULT 10,
            xp_cooldown_seconds INTEGER NOT NULL DEFAULT 60,
            daily_xp_cap INTEGER NOT NULL DEFAULT 300
        );
        CREATE TABLE IF NOT EXISTS members (
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL DEFAULT '',
            full_name TEXT NOT NULL DEFAULT '',
            xp INTEGER NOT NULL DEFAULT 0,
            bonus_points INTEGER NOT NULL DEFAULT 0,
            custom_title TEXT NOT NULL DEFAULT '',
            custom_badges TEXT NOT NULL DEFAULT '[]',
            last_xp_at INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL,
            xp_day TEXT NOT NULL DEFAULT '',
            xp_today INTEGER NOT NULL DEFAULT 0,
            last_message_hash TEXT NOT NULL DEFAULT '',
            last_message_hash_at INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (chat_id, user_id),
            FOREIGN KEY(chat_id) REFERENCES groups(chat_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_members_rank ON members(chat_id, xp DESC);
        CREATE TABLE IF NOT EXISTS admin_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,
            target_user_id INTEGER NOT NULL, actor_user_id INTEGER NOT NULL,
            action TEXT NOT NULL, old_value TEXT NOT NULL DEFAULT '',
            new_value TEXT NOT NULL DEFAULT '', reason TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_admin_audit_member ON admin_audit(chat_id,target_user_id,id DESC);
        CREATE TABLE IF NOT EXISTS mission_claims (
            chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL, mission_key TEXT NOT NULL,
            period_key TEXT NOT NULL, claimed_at INTEGER NOT NULL,
            PRIMARY KEY(chat_id,user_id,mission_key,period_key)
        );
        CREATE TABLE IF NOT EXISTS achievements (
            chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL, achievement_key TEXT NOT NULL,
            earned_at INTEGER NOT NULL, PRIMARY KEY(chat_id,user_id,achievement_key)
        );
        CREATE TABLE IF NOT EXISTS point_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            actor_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS admin_requests (
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at INTEGER NOT NULL,
            reviewed_at INTEGER,
            PRIMARY KEY (chat_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS shop_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            item_type TEXT NOT NULL CHECK(item_type IN ('title','badge','frame')),
            name TEXT NOT NULL,
            emoji TEXT NOT NULL DEFAULT '🎁',
            price INTEGER NOT NULL CHECK(price >= 0),
            active INTEGER NOT NULL DEFAULT 1,
            created_by INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL,
            UNIQUE(chat_id,item_type,name)
        );
        CREATE INDEX IF NOT EXISTS idx_shop_items_group ON shop_items(chat_id,active,id);
        CREATE TABLE IF NOT EXISTS shop_inventory (
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            item_id INTEGER NOT NULL,
            purchased_at INTEGER NOT NULL,
            PRIMARY KEY(chat_id,user_id,item_id),
            FOREIGN KEY(item_id) REFERENCES shop_items(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS xp_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            balance_after INTEGER NOT NULL,
            kind TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_xp_transactions_member ON xp_transactions(chat_id,user_id,id DESC);
        """)
        conn.execute("UPDATE groups SET admin_level=? WHERE admin_level IS NULL", (DEFAULT_ADMIN_LEVEL,))
        # Safe additive migrations for databases created by earlier bot versions.
        for table, columns in {
            "groups": {"xp_per_message": "INTEGER NOT NULL DEFAULT 10", "xp_cooldown_seconds": "INTEGER NOT NULL DEFAULT 60", "daily_xp_cap": "INTEGER NOT NULL DEFAULT 300", "level_mode": "TEXT NOT NULL DEFAULT 'normal'", "level_costs": "TEXT NOT NULL DEFAULT '{}'", "daily_mission_target": "INTEGER NOT NULL DEFAULT 100", "daily_mission_reward": "INTEGER NOT NULL DEFAULT 25", "weekly_mission_target": "INTEGER NOT NULL DEFAULT 500", "weekly_mission_reward": "INTEGER NOT NULL DEFAULT 100", "daily_message_target": "INTEGER NOT NULL DEFAULT 20", "daily_message_reward": "INTEGER NOT NULL DEFAULT 20"},
            "members": {"xp_day": "TEXT NOT NULL DEFAULT ''", "xp_today": "INTEGER NOT NULL DEFAULT 0", "xp_week_key": "TEXT NOT NULL DEFAULT ''", "xp_week": "INTEGER NOT NULL DEFAULT 0", "messages_day": "TEXT NOT NULL DEFAULT ''", "messages_today": "INTEGER NOT NULL DEFAULT 0", "last_message_hash": "TEXT NOT NULL DEFAULT ''", "last_message_hash_at": "INTEGER NOT NULL DEFAULT 0", "active_shop_title": "TEXT NOT NULL DEFAULT ''", "active_shop_badge": "TEXT NOT NULL DEFAULT ''", "active_shop_frame": "TEXT NOT NULL DEFAULT ''"},
        }.items():
            present = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            for col, definition in columns.items():
                if col not in present:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")

def register_group(chat_id: int, title: str):
    now = int(time.time())
    with _connect() as conn:
        conn.execute(
            """INSERT INTO groups(chat_id,title,admin_level,created_at) VALUES(?,?,?,?)
               ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title""",
            (chat_id, title or "گروه", DEFAULT_ADMIN_LEVEL, now),
        )
        # Seed a starter catalogue once so the shop is usable immediately after V2.
        has_items=conn.execute("SELECT 1 FROM shop_items WHERE chat_id=? LIMIT 1",(chat_id,)).fetchone()
        if not has_items:
            starter=[("title","عضو فعال","🏷️",250),("title","زمردی","💚",800),
                     ("badge","ستاره‌دار","🌟",400),("badge","قهرمان","🏆",1200),
                     ("frame","قاب زمردی","💚",600),("frame","قاب افسانه‌ای","👑",1500)]
            conn.executemany("INSERT OR IGNORE INTO shop_items(chat_id,item_type,name,emoji,price,active,created_by,created_at) VALUES(?,?,?,?,?,1,0,?)",
                             [(chat_id,kind,name,emoji,price,now) for kind,name,emoji,price in starter])

def get_groups():
    with _connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM groups ORDER BY title COLLATE NOCASE")]

def get_group(chat_id: int):
    with _connect() as conn:
        row = conn.execute("SELECT * FROM groups WHERE chat_id=?", (chat_id,)).fetchone()
        return dict(row) if row else None

def set_admin_level(chat_id: int, level: int):
    level = max(1, min(100, int(level)))
    with _connect() as conn:
        conn.execute("UPDATE groups SET admin_level=? WHERE chat_id=?", (level, chat_id))

def set_announcements(chat_id: int, enabled: bool):
    with _connect() as conn:
        conn.execute("UPDATE groups SET rankup_announcements=? WHERE chat_id=?", (int(enabled), chat_id))

def upsert_member(chat_id: int, user, xp_delta=0, award_xp=False, cooldown_seconds=60, message_text="", track_activity=False):
    now = int(time.time())
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date()
    day = today.isoformat()
    iso = today.isocalendar()
    week_key = f"{iso.year}-W{iso.week:02d}"
    username = user.username or ""
    full_name = user.full_name or user.first_name or "عضو"
    digest = hashlib.sha256((message_text or "").strip().casefold().encode("utf-8")).hexdigest() if message_text else ""
    with _connect() as conn:
        conn.execute("""INSERT INTO members(chat_id,user_id,username,full_name,updated_at)
            VALUES(?,?,?,?,?) ON CONFLICT(chat_id,user_id) DO UPDATE SET
            username=excluded.username,full_name=excluded.full_name,updated_at=excluded.updated_at""",
            (chat_id, user.id, username, full_name, now))
        row = conn.execute("SELECT * FROM members WHERE chat_id=? AND user_id=?", (chat_id, user.id)).fetchone()
        group = conn.execute("SELECT xp_per_message,xp_cooldown_seconds,daily_xp_cap FROM groups WHERE chat_id=?", (chat_id,)).fetchone()
        group_config=conn.execute("SELECT level_mode,level_costs FROM groups WHERE chat_id=?", (chat_id,)).fetchone() or {"level_mode":"normal","level_costs":"{}"}
        mode=str(group_config["level_mode"]); costs=json.loads(group_config["level_costs"] or "{}")
        old_xp = int(row["xp"]); old_level = level_from_xp(old_xp, mode, costs); new_xp = old_xp; got_xp = False
        xp_day = row["xp_day"] or ""; xp_today = int(row["xp_today"] or 0)
        xp_week_key = row["xp_week_key"] or ""; xp_week = int(row["xp_week"] or 0)
        messages_day=row["messages_day"] or ""; messages_today=int(row["messages_today"] or 0)
        if xp_day != day: xp_day, xp_today = day, 0
        if xp_week_key != week_key: xp_week_key, xp_week = week_key, 0
        if messages_day != day: messages_day, messages_today = day, 0
        if track_activity: messages_today += 1
        cooldown = max(0, int(group["xp_cooldown_seconds"] if group else cooldown_seconds))
        reward = max(0, int(group["xp_per_message"] if group else xp_delta))
        cap = max(0, int(group["daily_xp_cap"] if group else 300))
        repeated = bool(digest and digest == row["last_message_hash"] and now-int(row["last_message_hash_at"] or 0) < 300)
        if award_xp and now-int(row["last_xp_at"] or 0) >= cooldown and not repeated and xp_today < cap and reward > 0:
            reward = min(reward, cap-xp_today)
            new_xp = old_xp + reward; xp_today += reward; xp_week += reward; got_xp = reward > 0
            conn.execute("""UPDATE members SET xp=?,last_xp_at=?,updated_at=?,xp_day=?,xp_today=?,xp_week_key=?,xp_week=?,messages_day=?,messages_today=?,
                last_message_hash=?,last_message_hash_at=? WHERE chat_id=? AND user_id=?""",
                (new_xp,now,now,xp_day,xp_today,xp_week_key,xp_week,messages_day,messages_today,digest,now,chat_id,user.id))
            conn.execute("INSERT INTO xp_transactions(chat_id,user_id,amount,balance_after,kind,description,created_at) VALUES(?,?,?,?,?,?,?)",
                         (chat_id,user.id,reward,new_xp,"message_reward","پاداش پیام واجد شرایط",now))
        else:
            conn.execute("UPDATE members SET xp_day=?,xp_today=?,xp_week_key=?,xp_week=?,messages_day=?,messages_today=?,last_message_hash=CASE WHEN ?<>'' THEN ? ELSE last_message_hash END,last_message_hash_at=CASE WHEN ?<>'' THEN ? ELSE last_message_hash_at END WHERE chat_id=? AND user_id=?",
                (xp_day,xp_today,xp_week_key,xp_week,messages_day,messages_today,digest,digest,digest,now,chat_id,user.id))
        return {"old_xp":old_xp,"xp":new_xp,"old_level":old_level,"level":level_from_xp(new_xp, mode, costs),"got_xp":got_xp}


def set_xp_settings(chat_id: int, xp_per_message: int, cooldown_seconds: int, daily_cap: int):
    with _connect() as conn:
        conn.execute("UPDATE groups SET xp_per_message=?,xp_cooldown_seconds=?,daily_xp_cap=? WHERE chat_id=?",
                     (max(1,min(100,int(xp_per_message))),max(5,min(3600,int(cooldown_seconds))),max(50,min(10000,int(daily_cap))),chat_id))


def award_admin_xp(chat_id: int, user_id: int, amount: int, actor_id: int, reason: str):
    amount=max(-1000000,min(1000000,int(amount))); now=int(time.time())
    with _connect() as conn:
        row=conn.execute("SELECT xp FROM members WHERE chat_id=? AND user_id=?",(chat_id,user_id)).fetchone()
        if not row: return None
        old=int(row["xp"]); new=max(0,old+amount); actual=new-old
        gr=conn.execute("SELECT level_mode,level_costs FROM groups WHERE chat_id=?",(chat_id,)).fetchone(); mode=(gr["level_mode"] if gr else "normal"); costs=json.loads((gr["level_costs"] if gr else "{}") or "{}")
        conn.execute("UPDATE members SET xp=?,updated_at=? WHERE chat_id=? AND user_id=?",(new,now,chat_id,user_id))
        conn.execute("INSERT INTO admin_audit(chat_id,target_user_id,actor_user_id,action,old_value,new_value,reason,created_at) VALUES(?,?,?,?,?,?,?,?)",
                     (chat_id,user_id,actor_id,"xp",str(old),str(new),reason[:200],now))
        if actual:
            kind="mission_reward" if actor_id == 0 else "admin_adjustment"
            conn.execute("INSERT INTO xp_transactions(chat_id,user_id,amount,balance_after,kind,description,created_at) VALUES(?,?,?,?,?,?,?)",
                         (chat_id,user_id,actual,new,kind,(reason or "تغییر XP")[:200],now))
        return {"old_xp":old,"xp":new,"level":level_from_xp(new, mode, costs),"old_level":level_from_xp(old, mode, costs)}


def audit_for_member(chat_id: int, user_id: int, limit=10):
    with _connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM admin_audit WHERE chat_id=? AND target_user_id=? ORDER BY id DESC LIMIT ?",(chat_id,user_id,limit))]


def claim_mission(chat_id: int, user_id: int, mission_key: str, period_key: str):
    with _connect() as conn:
        cur=conn.execute("INSERT OR IGNORE INTO mission_claims(chat_id,user_id,mission_key,period_key,claimed_at) VALUES(?,?,?,?,?)",
                         (chat_id,user_id,mission_key,period_key,int(time.time())))
        return cur.rowcount == 1


def earn_achievement(chat_id: int, user_id: int, key: str):
    with _connect() as conn:
        cur=conn.execute("INSERT OR IGNORE INTO achievements(chat_id,user_id,achievement_key,earned_at) VALUES(?,?,?,?)",
                         (chat_id,user_id,key,int(time.time())))
        return cur.rowcount == 1


def get_achievements(chat_id: int, user_id: int):
    with _connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM achievements WHERE chat_id=? AND user_id=? ORDER BY earned_at",(chat_id,user_id))]

def get_member(chat_id: int, user_id: int):
    with _connect() as conn:
        row = conn.execute("SELECT * FROM members WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()
        return dict(row) if row else None

def get_members(chat_id: int, limit=30, offset=0):
    with _connect() as conn:
        rows = conn.execute(
            """SELECT * FROM members WHERE chat_id=?
               ORDER BY xp DESC, bonus_points DESC, full_name COLLATE NOCASE
               LIMIT ? OFFSET ?""", (chat_id, limit, offset)
        ).fetchall()
        return [dict(r) for r in rows]

def search_members(chat_id: int, query: str, limit=20):
    query=(query or "").strip().lstrip("@").casefold()
    if not query: return []
    with _connect() as conn:
        rows=conn.execute("SELECT * FROM members WHERE chat_id=? AND (instr(lower(full_name),?)>0 OR instr(lower(username),?)>0 OR CAST(user_id AS TEXT)=?) ORDER BY xp DESC LIMIT ?",
                          (chat_id,query,query,query,max(1,min(50,int(limit))))).fetchall()
        return [dict(r) for r in rows]

def member_count(chat_id: int):
    with _connect() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM members WHERE chat_id=?", (chat_id,)).fetchone()[0])

def change_bonus_points(chat_id: int, user_id: int, amount: int, actor_id: int, reason: str):
    now = int(time.time())
    with _connect() as conn:
        row = conn.execute("SELECT bonus_points FROM members WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()
        if not row:
            return None
        new_value = max(0, int(row["bonus_points"]) + int(amount))
        actual_change = new_value - int(row["bonus_points"])
        conn.execute("UPDATE members SET bonus_points=?,updated_at=? WHERE chat_id=? AND user_id=?",
                     (new_value, now, chat_id, user_id))
        conn.execute("INSERT INTO point_history(chat_id,user_id,actor_id,amount,reason,created_at) VALUES(?,?,?,?,?,?)",
                     (chat_id, user_id, actor_id, actual_change, reason, now))
        return new_value

def set_custom_title(chat_id: int, user_id: int, title: str):
    with _connect() as conn:
        conn.execute("UPDATE members SET custom_title=?,updated_at=? WHERE chat_id=? AND user_id=?",
                     (title[:60], int(time.time()), chat_id, user_id))

def set_custom_badges(chat_id: int, user_id: int, badges):
    with _connect() as conn:
        conn.execute("UPDATE members SET custom_badges=?,updated_at=? WHERE chat_id=? AND user_id=?",
                     (json.dumps(badges, ensure_ascii=False), int(time.time()), chat_id, user_id))

def add_admin_request(chat_id: int, user_id: int):
    now = int(time.time())
    with _connect() as conn:
        conn.execute("""INSERT INTO admin_requests(chat_id,user_id,status,created_at,reviewed_at)
                        VALUES(?,?,'pending',?,NULL)
                        ON CONFLICT(chat_id,user_id) DO UPDATE SET status='pending',created_at=excluded.created_at,reviewed_at=NULL""",
                     (chat_id, user_id, now))

def get_admin_requests(chat_id: int, status="pending"):
    with _connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM admin_requests WHERE chat_id=? AND status=? ORDER BY created_at",
            (chat_id, status)
        )]

def set_admin_request_status(chat_id: int, user_id: int, status: str):
    with _connect() as conn:
        conn.execute("UPDATE admin_requests SET status=?,reviewed_at=? WHERE chat_id=? AND user_id=?",
                     (status, int(time.time()), chat_id, user_id))

def history_for_member(chat_id: int, user_id: int, limit=8):
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM point_history WHERE chat_id=? AND user_id=? ORDER BY id DESC LIMIT ?",
            (chat_id, user_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]


# ---- Emerald V2: group shop, XP ledger, level/missions configuration ----
def get_level_mode(chat_id: int) -> str:
    group = get_group(chat_id) or {}
    mode = str(group.get("level_mode", "normal"))
    return mode if mode in ("easy", "normal", "hard") else "normal"

def get_level_costs(chat_id: int) -> dict:
    group=get_group(chat_id) or {}
    try:
        data=json.loads(group.get("level_costs") or "{}")
        return {int(k):int(v) for k,v in data.items() if 2 <= int(k) <= 100 and 1 <= int(v) <= 1000000}
    except (ValueError,TypeError,json.JSONDecodeError):
        return {}

def set_level_costs(chat_id: int, costs: dict):
    clean={}
    for key,value in costs.items():
        level=int(key); amount=int(value)
        if not 2 <= level <= 100 or not 1 <= amount <= 1000000: raise ValueError("level cost out of range")
        clean[str(level)]=amount
    with _connect() as conn:
        conn.execute("UPDATE groups SET level_costs=? WHERE chat_id=?",(json.dumps(clean,ensure_ascii=False),chat_id))

def set_level_mode(chat_id: int, mode: str):
    if mode not in ("easy", "normal", "hard"):
        raise ValueError("invalid level mode")
    with _connect() as conn:
        conn.execute("UPDATE groups SET level_mode=? WHERE chat_id=?", (mode, chat_id))

def set_mission_settings(chat_id: int, daily_target: int, daily_reward: int, weekly_target: int, weekly_reward: int, daily_message_target=20, daily_message_reward=20):
    daily_target=max(10,min(100000,int(daily_target))); daily_reward=max(0,min(10000,int(daily_reward)))
    weekly_target=max(daily_target,min(1000000,int(weekly_target))); weekly_reward=max(0,min(100000,int(weekly_reward)))
    daily_message_target=max(1,min(1000,int(daily_message_target))); daily_message_reward=max(0,min(10000,int(daily_message_reward)))
    with _connect() as conn:
        conn.execute("UPDATE groups SET daily_mission_target=?,daily_mission_reward=?,weekly_mission_target=?,weekly_mission_reward=?,daily_message_target=?,daily_message_reward=? WHERE chat_id=?",
                     (daily_target,daily_reward,weekly_target,weekly_reward,daily_message_target,daily_message_reward,chat_id))

def get_shop_items(chat_id: int, active_only=True):
    with _connect() as conn:
        sql="SELECT * FROM shop_items WHERE chat_id=?" + (" AND active=1" if active_only else "") + " ORDER BY price,id"
        return [dict(r) for r in conn.execute(sql,(chat_id,))]

def add_shop_item(chat_id: int, item_type: str, name: str, emoji: str, price: int, actor_id: int):
    if item_type not in ("title","badge","frame"): raise ValueError("نوع محصول نامعتبر است")
    name=(name or "").strip()[:50]; emoji=(emoji or "🎁").strip()[:8]; price=int(price)
    if not name or price < 0 or price > 10_000_000: raise ValueError("نام یا قیمت نامعتبر است")
    with _connect() as conn:
        cur=conn.execute("INSERT INTO shop_items(chat_id,item_type,name,emoji,price,active,created_by,created_at) VALUES(?,?,?,?,?,1,?,?)",
                         (chat_id,item_type,name,emoji,price,actor_id,int(time.time())))
        return int(cur.lastrowid)

def toggle_shop_item(chat_id: int, item_id: int):
    with _connect() as conn:
        row=conn.execute("SELECT active FROM shop_items WHERE id=? AND chat_id=?",(item_id,chat_id)).fetchone()
        if not row: return None
        active=0 if row["active"] else 1
        conn.execute("UPDATE shop_items SET active=? WHERE id=? AND chat_id=?",(active,item_id,chat_id))
        return active

def delete_shop_item(chat_id: int, item_id: int):
    with _connect() as conn:
        # Preserve past transaction records; deleting removes the catalogue item and its inventory.
        cur=conn.execute("DELETE FROM shop_items WHERE id=? AND chat_id=?",(item_id,chat_id))
        return cur.rowcount > 0

def buy_shop_item(chat_id: int, user_id: int, item_id: int):
    now=int(time.time())
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        item=conn.execute("SELECT * FROM shop_items WHERE id=? AND chat_id=? AND active=1",(item_id,chat_id)).fetchone()
        member=conn.execute("SELECT xp FROM members WHERE chat_id=? AND user_id=?",(chat_id,user_id)).fetchone()
        if not item: return {"ok":False,"reason":"unavailable"}
        if not member: return {"ok":False,"reason":"member_missing"}
        owned=conn.execute("SELECT 1 FROM shop_inventory WHERE chat_id=? AND user_id=? AND item_id=?",(chat_id,user_id,item_id)).fetchone()
        if owned: return {"ok":False,"reason":"owned"}
        balance=int(member["xp"]); price=int(item["price"])
        if balance < price: return {"ok":False,"reason":"funds","balance":balance,"price":price}
        new_balance=balance-price
        conn.execute("UPDATE members SET xp=?,updated_at=? WHERE chat_id=? AND user_id=?",(new_balance,now,chat_id,user_id))
        conn.execute("INSERT INTO shop_inventory(chat_id,user_id,item_id,purchased_at) VALUES(?,?,?,?)",(chat_id,user_id,item_id,now))
        conn.execute("INSERT INTO xp_transactions(chat_id,user_id,amount,balance_after,kind,description,created_at) VALUES(?,?,?,?,?,?,?)",
                     (chat_id,user_id,-price,new_balance,"shop_purchase",f"خرید {item['emoji']} {item['name']}",now))
        return {"ok":True,"item":dict(item),"balance":new_balance}

def get_inventory(chat_id: int, user_id: int):
    with _connect() as conn:
        return [dict(r) for r in conn.execute("SELECT i.*,s.item_type,s.name,s.emoji,s.price,s.active FROM shop_inventory i JOIN shop_items s ON s.id=i.item_id WHERE i.chat_id=? AND i.user_id=? ORDER BY i.purchased_at DESC",(chat_id,user_id))]

def equip_shop_item(chat_id: int, user_id: int, item_id: int):
    with _connect() as conn:
        row=conn.execute("SELECT s.* FROM shop_inventory i JOIN shop_items s ON s.id=i.item_id WHERE i.chat_id=? AND i.user_id=? AND i.item_id=?",(chat_id,user_id,item_id)).fetchone()
        if not row: return {"ok":False,"reason":"not_owned"}
        col={"title":"active_shop_title","badge":"active_shop_badge","frame":"active_shop_frame"}.get(row["item_type"])
        if not col: return {"ok":False,"reason":"bad_type"}
        conn.execute(f"UPDATE members SET {col}=?,updated_at=? WHERE chat_id=? AND user_id=?",(f"{row['emoji']} {row['name']}",int(time.time()),chat_id,user_id))
        return {"ok":True,"item":dict(row)}

def xp_transaction_history(chat_id: int, user_id: int, limit=10):
    with _connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM xp_transactions WHERE chat_id=? AND user_id=? ORDER BY id DESC LIMIT ?",(chat_id,user_id,max(1,min(50,int(limit))))) ]

def group_dashboard(chat_id: int):
    with _connect() as conn:
        total=conn.execute("SELECT COUNT(*) FROM members WHERE chat_id=?",(chat_id,)).fetchone()[0]
        xp_total=conn.execute("SELECT COALESCE(SUM(xp),0) FROM members WHERE chat_id=?",(chat_id,)).fetchone()[0]
        active_7d=conn.execute("SELECT COUNT(*) FROM members WHERE chat_id=? AND updated_at>=?",(chat_id,int(time.time())-7*86400)).fetchone()[0]
        items=conn.execute("SELECT COUNT(*) FROM shop_items WHERE chat_id=? AND active=1",(chat_id,)).fetchone()[0]
        purchases=conn.execute("SELECT COUNT(*) FROM xp_transactions WHERE chat_id=? AND kind='shop_purchase'",(chat_id,)).fetchone()[0]
        return {"members":int(total),"xp_total":int(xp_total),"active_7d":int(active_7d),"shop_items":int(items),"purchases":int(purchases)}


def update_shop_item_price(chat_id: int, item_id: int, price: int):
    price=max(0,min(10000000,int(price)))
    with _connect() as conn:
        cur=conn.execute("UPDATE shop_items SET price=? WHERE id=? AND chat_id=?",(price,item_id,chat_id))
        return cur.rowcount > 0
