"""Tiny standard-library HTTP server for the Telegram Mini App.
Railway terminates public HTTPS; this process listens on its assigned internal PORT.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

from config import BOT_TOKEN
import games

logger = logging.getLogger("emerald_group_bot.miniapp")
WEB_ROOT = Path(__file__).resolve().parent / "webapp"
_MEMBERSHIP_CACHE = {}
_MEMBERSHIP_LOCK = threading.Lock()


def verify_group_membership(chat_id: int, user_id: int) -> bool:
    """Confirm that the signed group launch belongs to a current group member.

    Telegram guarantees getChatMember for other users when the bot is an admin.
    Results are cached briefly to avoid a Bot API request on every game poll.
    """
    now = time.time()
    key = (int(chat_id), int(user_id))
    with _MEMBERSHIP_LOCK:
        cached = _MEMBERSHIP_CACHE.get(key)
        if cached and cached[0] > now:
            return cached[1]
    try:
        query = urllib.parse.urlencode({"chat_id": int(chat_id), "user_id": int(user_id)})
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember?{query}"
        request = urllib.request.Request(url, headers={"User-Agent": "EmeraldGroupBot/4.0"})
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.loads(response.read(16_384).decode("utf-8"))
        member = payload.get("result") or {}
        status = member.get("status")
        allowed = status in ("creator", "administrator", "member") or (status == "restricted" and bool(member.get("is_member")))
    except Exception:
        logger.info("Mini App group membership check failed for chat=%s user=%s", chat_id, user_id)
        allowed = False
    with _MEMBERSHIP_LOCK:
        _MEMBERSHIP_CACHE[key] = (now + 45, allowed)
    return allowed


def validate_init_data(raw: str):
    if not raw or len(raw) > 8192:
        return None
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
        data = dict(pairs)
        received_hash = data.pop("hash", "")
        if not received_hash:
            return None
        check_string = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))
        secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(received_hash, expected):
            return None
        auth_date = int(data.get("auth_date", "0"))
        now = int(time.time())
        if auth_date > now + 60 or now - auth_date > 86400:
            return None
        user = json.loads(data.get("user", "{}"))
        user_id = int(user.get("id", 0))
        chat_id = games.parse_group_start_param(data.get("start_param", ""), BOT_TOKEN)
        if user_id <= 0 or chat_id is None or data.get("chat_type") not in ("group", "supergroup") or not data.get("chat_instance"):
            return None
        return {"user_id": user_id, "chat_id": chat_id, "user": user}
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


class Handler(BaseHTTPRequestHandler):
    server_version = "EmeraldMiniApp/1.0"

    def log_message(self, fmt, *args):
        logger.info("miniapp %s - %s", self.address_string(), fmt % args)

    def _send(self, status: int, body: bytes, content_type: str = "application/json; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data):
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 16_384:
            raise ValueError("invalid_body")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _origin_ok(self):
        origin = self.headers.get("Origin")
        if not origin:
            return True
        return urlparse(origin).netloc == self.headers.get("Host", "")

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/games", "/games/"):
            try:
                body = (WEB_ROOT / "index.html").read_bytes()
                self._send(200, body, "text/html; charset=utf-8")
            except OSError:
                self._json(500, {"ok": False, "error": "app_unavailable"})
            return
        if path == "/health":
            self._json(200, {"ok": True, "service": "emerald-miniapp"})
            return
        if path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
            return
        self._json(404, {"ok": False, "error": "not_found"})

    def do_POST(self):
        if not self._origin_ok():
            self._json(403, {"ok": False, "error": "origin_denied"})
            return
        try:
            payload = self._read_json()
            identity = validate_init_data(str(payload.get("init_data", "")))
            if not identity:
                self._json(401, {"ok": False, "error": "telegram_auth_failed"})
                return
            chat_id, user_id = identity["chat_id"], identity["user_id"]
            if not verify_group_membership(chat_id, user_id):
                self._json(403, {"ok": False, "error": "not_group_member"})
                return
            path = urlparse(self.path).path
            if path == "/api/bootstrap":
                profile = games.get_profile(chat_id, user_id)
                boards = {key: games.leaderboard(chat_id, key, 10) for key in sorted(games.GAME_KEYS)}
                self._json(200, {"ok": True, "profile": profile, "leaderboards": boards, "user": {"id": user_id, "name": str(identity["user"].get("first_name", "عضو"))[:60]}})
                return
            if path == "/api/session":
                game_key = str(payload.get("game", ""))
                token = games.create_session(chat_id, user_id, game_key)
                seed = games.get_session_seed(token, chat_id, user_id)
                self._json(200, {"ok": True, "session": token, "seed": seed})
                return
            if path == "/api/reaction/check":
                self._json(200, games.reaction_check(str(payload.get("session", "")), chat_id, user_id))
                return
            if path == "/api/reaction/finish":
                result = games.finish_reaction(str(payload.get("session", "")), chat_id, user_id)
                self._json(200 if result.get("ok") else 400, result)
                return
            if path == "/api/score":
                result = games.record_score(
                    str(payload.get("session", "")), chat_id, user_id,
                    str(payload.get("game", "")), payload.get("score"), payload.get("duration_ms"), str(payload.get("proof", "")),
                )
                self._json(200 if result.get("ok") else 400, result)
                return
            self._json(404, {"ok": False, "error": "not_found"})
        except (ValueError, TypeError, json.JSONDecodeError):
            self._json(400, {"ok": False, "error": "invalid_request"})
        except Exception:
            logger.exception("Mini App request failed")
            self._json(500, {"ok": False, "error": "server_error"})


def start_server():
    port = int(os.getenv("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, name="emerald-miniapp", daemon=True)
    thread.start()
    logger.info("Mini App HTTP server listening on port %s", port)
    return server
