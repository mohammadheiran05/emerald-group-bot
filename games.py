"""Lightweight, group-scoped mini-game records for Emerald Group Bot."""
from __future__ import annotations

import secrets
import time
from datetime import datetime, timezone

import database as db

GAME_KEYS = {"snake", "memory", "tictactoe", "reaction"}


def _rng_next(state: int) -> int:
    x = int(state) & 0xFFFFFFFF
    if x == 0:
        x = 1
    x ^= (x << 13) & 0xFFFFFFFF
    x ^= x >> 17
    x ^= (x << 5) & 0xFFFFFFFF
    return x & 0xFFFFFFFF


def memory_deck(seed: int):
    deck = [i % 8 for i in range(16)]
    state = int(seed) & 0xFFFFFFFF or 1
    for i in range(15, 0, -1):
        state = _rng_next(state)
        j = state % (i + 1)
        deck[i], deck[j] = deck[j], deck[i]
    return deck


def verify_memory_proof(seed: int, proof: str, score: int) -> bool:
    if not isinstance(proof, str) or not 16 <= len(proof) <= 400 or len(proof) % 2:
        return False
    deck = memory_deck(seed)
    matched = set()
    pending = None
    moves = 0
    for pos, char in enumerate(proof):
        try:
            index = int(char, 16)
        except ValueError:
            return False
        if index < 0 or index >= 16 or index in matched:
            return False
        if pending is None:
            pending = index
        else:
            if index == pending:
                return False
            moves += 1
            if deck[index] == deck[pending]:
                matched.update((pending, index))
            pending = None
            if len(matched) == 16 and pos != len(proof) - 1:
                return False
    return pending is None and len(matched) == 16 and moves == int(score)


def _ttt_result(cells):
    wins = ((0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6))
    for a,b,c in wins:
        if cells[a] and cells[a] == cells[b] == cells[c]:
            return cells[a]
    return "draw" if all(cells) else None


def _ttt_ai_move(cells):
    def winning_move(mark):
        for i in range(9):
            if cells[i] is None:
                cells[i] = mark
                won = _ttt_result(cells) == mark
                cells[i] = None
                if won:
                    return i
        return None
    choice = winning_move("O")
    if choice is None:
        choice = winning_move("X")
    if choice is None and cells[4] is None:
        choice = 4
    if choice is None:
        choice = next((i for i in (0,2,6,8) if cells[i] is None), None)
    if choice is None:
        choice = next((i for i in (1,3,5,7) if cells[i] is None), None)
    return choice


def verify_tictactoe_proof(proof: str, score: int) -> bool:
    if not isinstance(proof, str) or not 1 <= len(proof) <= 5:
        return False
    cells = [None] * 9
    outcome = None
    for pos, char in enumerate(proof):
        try:
            move = int(char, 16)
        except ValueError:
            return False
        if move < 0 or move > 8 or cells[move] is not None or outcome is not None:
            return False
        cells[move] = "X"
        outcome = _ttt_result(cells)
        if outcome is None:
            ai_move = _ttt_ai_move(cells)
            if ai_move is None:
                outcome = "draw"
            else:
                cells[ai_move] = "O"
                outcome = _ttt_result(cells)
        if outcome is not None and pos != len(proof) - 1:
            return False
    expected = {"X": 1, "draw": 0, "O": -1}.get(outcome)
    return expected is not None and expected == int(score)


def verify_snake_proof(seed: int, proof: str, score: int, duration_ms: int) -> bool:
    if not isinstance(proof, str) or not 1 <= len(proof) <= 4500:
        return False
    if duration_ms < max(1000, int(len(proof) * 70)):
        return False
    body = [(9,10),(8,10),(7,10)]
    direction = (1,0)
    state = int(seed) & 0xFFFFFFFF or 1
    def spawn_food(current_body, rng_state):
        while True:
            rng_state = _rng_next(rng_state); x = rng_state % 20
            rng_state = _rng_next(rng_state); y = rng_state % 20
            if (x,y) not in current_body:
                return (x,y), rng_state
    food, state = spawn_food(body, state)
    points = 0
    ended = False
    vectors = {"U":(0,-1),"D":(0,1),"L":(-1,0),"R":(1,0)}
    for pos, char in enumerate(proof):
        next_direction = vectors.get(char)
        if next_direction is None or next_direction == (-direction[0],-direction[1]):
            return False
        direction = next_direction
        head = (body[0][0] + direction[0], body[0][1] + direction[1])
        if head[0] < 0 or head[1] < 0 or head[0] >= 20 or head[1] >= 20 or head in body:
            ended = True
            if pos != len(proof) - 1:
                return False
            break
        body.insert(0, head)
        if head == food:
            points += 1
            food, state = spawn_food(body, state)
        else:
            body.pop()
    return ended and points == int(score)


def game_level(xp: int) -> int:
    """A separate progression curve; game XP never changes normal group XP."""
    xp = max(0, int(xp))
    level = 1
    remaining = xp
    while level < 100:
        cost = 80 + (level - 1) * 35
        if remaining < cost:
            break
        remaining -= cost
        level += 1
    return level


def _game_xp(game_key: str, score: int) -> int:
    if game_key == "snake":
        return min(40, 5 + max(0, score) * 2)
    if game_key == "memory":
        # score is the number of moves; lower is better.
        return max(5, min(40, 48 - max(0, score - 8) // 2))
    if game_key == "tictactoe":
        return {1: 35, 0: 18, -1: 8}.get(score, 0)
    if game_key == "reaction":
        # score is reaction time in milliseconds; lower is better.
        return max(5, min(40, 45 - max(0, score - 150) // 50))
    return 0


def create_session(chat_id: int, user_id: int, game_key: str) -> str:
    if game_key not in GAME_KEYS:
        raise ValueError("invalid_game")
    token = secrets.token_urlsafe(24)
    now = int(time.time())
    reaction_ready_at = now + 2 + secrets.randbelow(26) / 10 if game_key == "reaction" else 0
    seed = secrets.randbits(32) or 1
    with db._connect() as conn:
        conn.execute("DELETE FROM game_sessions WHERE expires_at < ? OR (used=1 AND started_at < ?)", (now, now - 3600))
        # A player can have only one active game session per group; a restart invalidates the old one.
        conn.execute("UPDATE game_sessions SET used=1 WHERE chat_id=? AND user_id=? AND used=0", (int(chat_id), int(user_id)))
        conn.execute(
            "INSERT INTO game_sessions(token,chat_id,user_id,game_key,started_at,expires_at,reaction_ready_at,seed) VALUES(?,?,?,?,?,?,?,?)",
            (token, int(chat_id), int(user_id), game_key, now, now + 900, int(reaction_ready_at * 1000) if game_key == "reaction" else 0, seed),
        )
    return token


def get_session_seed(token: str, chat_id: int, user_id: int):
    with db._connect() as conn:
        row = conn.execute("SELECT seed FROM game_sessions WHERE token=? AND chat_id=? AND user_id=? AND used=0", (token, chat_id, user_id)).fetchone()
    if not row:
        raise ValueError("session_expired")
    return int(row["seed"])


def record_score(token: str, chat_id: int, user_id: int, game_key: str, score: int, duration_ms: int, proof: str = ""):
    if game_key not in GAME_KEYS:
        return {"ok": False, "reason": "invalid_game"}
    try:
        score, duration_ms = int(score), int(duration_ms)
    except (TypeError, ValueError):
        return {"ok": False, "reason": "invalid_score"}
    if not 0 <= duration_ms <= 600_000:
        return {"ok": False, "reason": "invalid_duration"}
    if game_key == "snake" and not 0 <= score <= 100:
        return {"ok": False, "reason": "invalid_score"}
    if game_key == "memory" and not 8 <= score <= 200:
        return {"ok": False, "reason": "invalid_score"}
    if game_key == "tictactoe" and score not in (-1, 0, 1):
        return {"ok": False, "reason": "invalid_score"}
    if game_key == "reaction" and not 100 <= score <= 5000:
        return {"ok": False, "reason": "invalid_score"}

    minimum_ms = {"snake": 1000, "memory": 5000, "tictactoe": 3000, "reaction": 1000}[game_key]
    if duration_ms < minimum_ms:
        return {"ok": False, "reason": "too_fast"}
    if game_key == "snake" and score > (duration_ms // 250) + 1:
        return {"ok": False, "reason": "implausible"}

    now = int(time.time())
    xp = _game_xp(game_key, score)
    day_start = int(datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    best_col = {"snake": "best_snake", "memory": "best_memory", "tictactoe": "best_tictactoe", "reaction": "best_reaction_ms"}[game_key]
    with db._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        session = conn.execute("SELECT * FROM game_sessions WHERE token=?", (token,)).fetchone()
        if not session or session["used"] or session["expires_at"] < now:
            return {"ok": False, "reason": "session_expired"}
        if (int(session["chat_id"]), int(session["user_id"]), session["game_key"]) != (int(chat_id), int(user_id), game_key):
            return {"ok": False, "reason": "session_mismatch"}
        seed = int(session["seed"] or 1)
        if game_key == "snake" and not verify_snake_proof(seed, proof, score, duration_ms):
            return {"ok": False, "reason": "invalid_proof"}
        if game_key == "memory" and not verify_memory_proof(seed, proof, score):
            return {"ok": False, "reason": "invalid_proof"}
        if game_key == "tictactoe" and not verify_tictactoe_proof(proof, score):
            return {"ok": False, "reason": "invalid_proof"}
        last = conn.execute(
            "SELECT created_at FROM game_scores WHERE chat_id=? AND user_id=? AND game_key=? ORDER BY id DESC LIMIT 1",
            (chat_id, user_id, game_key),
        ).fetchone()
        if last and now - int(last["created_at"]) < 10:
            return {"ok": False, "reason": "cooldown"}
        daily_xp = conn.execute(
            "SELECT COALESCE(SUM(game_xp),0) FROM game_scores WHERE chat_id=? AND user_id=? AND created_at>=?",
            (chat_id, user_id, day_start),
        ).fetchone()[0]
        xp = min(xp, max(0, 150 - int(daily_xp)))
        consumed = conn.execute("UPDATE game_sessions SET used=1 WHERE token=? AND used=0 AND expires_at>=?", (token, now))
        if consumed.rowcount != 1:
            return {"ok": False, "reason": "session_expired"}
        conn.execute(
            "INSERT INTO game_profiles(chat_id,user_id,updated_at) VALUES(?,?,?) ON CONFLICT(chat_id,user_id) DO NOTHING",
            (chat_id, user_id, now),
        )
        conn.execute(
            "INSERT INTO game_scores(chat_id,user_id,game_key,score,game_xp,duration_ms,created_at) VALUES(?,?,?,?,?,?,?)",
            (chat_id, user_id, game_key, score, xp, duration_ms, now),
        )
        profile = conn.execute("SELECT * FROM game_profiles WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()
        if game_key in ("reaction", "memory"):
            old_best = profile[best_col]
            has_old = old_best is not None and int(old_best) > 0
            is_better = not has_old or score < int(old_best)
            new_best = score if is_better else old_best
        else:
            old_best = int(profile[best_col] if profile[best_col] is not None else (-2 if game_key == "tictactoe" else 0))
            is_better = score > old_best
            new_best = max(old_best, score)
        conn.execute(
            f"UPDATE game_profiles SET game_xp=game_xp+?,games_played=games_played+1,{best_col}=?,updated_at=? WHERE chat_id=? AND user_id=?",
            (xp, new_best, now, chat_id, user_id),
        )
        updated = conn.execute("SELECT game_xp,games_played FROM game_profiles WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()
        return {"ok": True, "game_xp": xp, "game_xp_total": int(updated["game_xp"]), "game_level": game_level(updated["game_xp"]), "games_played": int(updated["games_played"]), "new_best": bool(is_better)}


def reaction_check(token: str, chat_id: int, user_id: int):
    now_ms = int(time.time() * 1000)
    with db._connect() as conn:
        row = conn.execute("SELECT * FROM game_sessions WHERE token=?", (token,)).fetchone()
        if not row or row["used"] or row["expires_at"] < now_ms // 1000:
            return {"ok": False, "reason": "session_expired"}
        if (int(row["chat_id"]), int(row["user_id"]), row["game_key"]) != (int(chat_id), int(user_id), "reaction"):
            return {"ok": False, "reason": "session_mismatch"}
        if now_ms >= int(row["reaction_ready_at"]):
            if not row["reaction_shown_at"]:
                conn.execute("UPDATE game_sessions SET reaction_shown_at=? WHERE token=?", (now_ms, token))
            return {"ok": True, "ready": True}
        return {"ok": True, "ready": False}


def finish_reaction(token: str, chat_id: int, user_id: int):
    now_ms = int(time.time() * 1000)
    with db._connect() as conn:
        row = conn.execute("SELECT * FROM game_sessions WHERE token=?", (token,)).fetchone()
        if not row or row["used"] or row["expires_at"] < now_ms // 1000:
            return {"ok": False, "reason": "session_expired"}
        if (int(row["chat_id"]), int(row["user_id"]), row["game_key"]) != (int(chat_id), int(user_id), "reaction"):
            return {"ok": False, "reason": "session_mismatch"}
        shown_at = int(row["reaction_shown_at"] or 0)
        if not shown_at:
            return {"ok": False, "reason": "too_early"}
        reaction_ms = now_ms - shown_at
        started_ms = int(row["started_at"]) * 1000
    result = record_score(token, chat_id, user_id, "reaction", reaction_ms, max(1000, now_ms - started_ms))
    if result.get("ok"):
        result["score"] = reaction_ms
    return result


def get_profile(chat_id: int, user_id: int):
    with db._connect() as conn:
        row = conn.execute("SELECT * FROM game_profiles WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()
    data = dict(row) if row else {"game_xp": 0, "games_played": 0, "best_snake": 0, "best_memory": 0, "best_tictactoe": -2, "best_reaction_ms": None}
    data["game_level"] = game_level(data["game_xp"])
    return data


def leaderboard(chat_id: int, game_key: str, limit: int = 10):
    if game_key not in GAME_KEYS:
        return []
    aggregate = "MIN" if game_key in ("reaction", "memory") else "MAX"
    direction = "ASC" if game_key in ("reaction", "memory") else "DESC"
    with db._connect() as conn:
        rows = conn.execute(
            f"""SELECT s.user_id, {aggregate}(s.score) AS best,
                       m.full_name, p.game_xp
                FROM game_scores s
                LEFT JOIN members m ON m.chat_id=s.chat_id AND m.user_id=s.user_id
                LEFT JOIN game_profiles p ON p.chat_id=s.chat_id AND p.user_id=s.user_id
                WHERE s.chat_id=? AND s.game_key=?
                GROUP BY s.user_id ORDER BY best {direction} LIMIT ?""",
            (int(chat_id), game_key, max(1, min(20, int(limit)))),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["game_level"] = game_level(item.get("game_xp") or 0)
        result.append(item)
    return result


def make_group_start_param(chat_id: int, bot_token: str) -> str:
    import hashlib
    import hmac
    raw = str(int(chat_id))
    signature = hmac.new(bot_token.encode(), f"emerald-games:{raw}".encode(), hashlib.sha256).hexdigest()[:20]
    return f"g{raw}_{signature}"


def parse_group_start_param(value: str, bot_token: str):
    import hashlib
    import hmac
    import re
    match = re.fullmatch(r"g(-?\d{5,20})_([a-f0-9]{20})", value or "")
    if not match:
        return None
    raw, supplied = match.groups()
    expected = hmac.new(bot_token.encode(), f"emerald-games:{raw}".encode(), hashlib.sha256).hexdigest()[:20]
    if not hmac.compare_digest(supplied, expected):
        return None
    return int(raw)


def xp_leaderboard(chat_id: int, limit: int = 10):
    with db._connect() as conn:
        rows = conn.execute(
            """SELECT p.user_id,p.game_xp,p.games_played,m.full_name
               FROM game_profiles p LEFT JOIN members m
               ON m.chat_id=p.chat_id AND m.user_id=p.user_id
               WHERE p.chat_id=? ORDER BY p.game_xp DESC,p.games_played DESC LIMIT ?""",
            (int(chat_id), max(1, min(20, int(limit)))),
        ).fetchall()
    result = [dict(row) for row in rows]
    for row in result:
        row["game_level"] = game_level(row["game_xp"])
    return result
