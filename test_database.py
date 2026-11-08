"""Isolated regression tests for Emerald Group Bot 4.0.0."""
import os
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

_TEST_DB_DIR = tempfile.TemporaryDirectory(prefix="emerald_bot_tests_")
os.environ["DATABASE_PATH"] = str(Path(_TEST_DB_DIR.name) / "test.db")
os.environ["OWNER_ID"] = "987654321"

import database as db  # noqa: E402
from levels import level_from_xp, xp_to_reach_level  # noqa: E402
import admin_panel  # noqa: E402
import bot  # noqa: E402
import asyncio  # noqa: E402
import games  # noqa: E402
import miniapp_server  # noqa: E402
import hashlib  # noqa: E402
import hmac  # noqa: E402
import threading  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402
from urllib.parse import urlencode  # noqa: E402
from urllib.request import Request, urlopen  # noqa: E402

CHAT_ID = -1001234567890
USER_ID = 123456789


def memory_proof_for_moves(seed, moves):
    deck = games.memory_deck(seed)
    pairs = {}
    for index, value in enumerate(deck):
        pairs.setdefault(value, []).append(index)
    values = list(pairs)
    mismatch = (pairs[values[0]][0], pairs[values[1]][0])
    proof = "".join(format(i, "x") for i in mismatch) * (moves - 8)
    for value in values:
        proof += "".join(format(i, "x") for i in pairs[value])
    return proof


class EmeraldDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.addClassCleanup(_TEST_DB_DIR.cleanup)
        db.init_db()
        db.register_group(CHAT_ID, "گروه آزمایشی")
        cls.user = SimpleNamespace(id=USER_ID, username="qa_user", full_name="QA <Member>")
        db.upsert_member(CHAT_ID, cls.user)

    def setUp(self):
        # Keep XP tests independent while preserving the shared schema.
        with db._connect() as conn:
            conn.execute("UPDATE members SET xp=0,bonus_points=0,xp_today=0,xp_day='',last_xp_at=0,last_message_hash='',last_message_hash_at=0 WHERE chat_id=? AND user_id=?", (CHAT_ID, USER_ID))
            conn.execute("UPDATE groups SET xp_per_message=10,xp_cooldown_seconds=0,daily_xp_cap=15 WHERE chat_id=?", (CHAT_ID,))
            conn.execute("DELETE FROM shop_inventory WHERE chat_id=? AND user_id=?", (CHAT_ID, USER_ID))
            conn.execute("DELETE FROM shop_items WHERE chat_id=?", (CHAT_ID,))
            conn.execute("DELETE FROM game_scores WHERE chat_id=?", (CHAT_ID,))
            conn.execute("DELETE FROM game_sessions WHERE chat_id=?", (CHAT_ID,))
            conn.execute("DELETE FROM game_profiles WHERE chat_id=?", (CHAT_ID,))

    def test_hard_curve_is_more_expensive_and_levels_are_bounded(self):
        self.assertGreater(xp_to_reach_level(100, "hard"), xp_to_reach_level(100, "normal"))
        for xp in (0, 1, 100, 1000, 10000, 100000):
            self.assertGreaterEqual(level_from_xp(xp, "hard"), 1)
            self.assertLessEqual(level_from_xp(xp, "hard"), 100)

    def test_duplicate_message_and_daily_xp_cap(self):
        first = db.upsert_member(CHAT_ID, self.user, award_xp=True, message_text="same message")
        duplicate = db.upsert_member(CHAT_ID, self.user, award_xp=True, message_text="same message")
        second = db.upsert_member(CHAT_ID, self.user, award_xp=True, message_text="different message")
        third = db.upsert_member(CHAT_ID, self.user, award_xp=True, message_text="third message")
        self.assertTrue(first["got_xp"])
        self.assertFalse(duplicate["got_xp"])
        self.assertEqual(second["xp"], 15)
        self.assertEqual(third["xp"], 15)

    def test_admin_xp_cannot_make_balance_negative(self):
        db.award_admin_xp(CHAT_ID, USER_ID, -999999, 987, "QA")
        self.assertEqual(db.get_member(CHAT_ID, USER_ID)["xp"], 0)

    def test_shop_points_purchase_is_atomic_and_xp_is_not_spent(self):
        db.change_bonus_points(CHAT_ID, USER_ID, 100, 987, "QA credit")
        item_id = db.add_shop_item(CHAT_ID, "badge", "نشان آزمایشی", "🏅", 1, 987, 25)
        result = db.buy_shop_item(CHAT_ID, USER_ID, item_id, "points")
        self.assertTrue(result["ok"])
        self.assertEqual(result["points_balance"], 75)
        self.assertEqual(db.get_member(CHAT_ID, USER_ID)["xp"], 0)
        self.assertEqual(db.buy_shop_item(CHAT_ID, USER_ID, item_id, "points")["reason"], "owned")
        self.assertTrue(db.equip_shop_item(CHAT_ID, USER_ID, item_id)["ok"])

    def test_only_creator_can_manage_delegated_moderators(self):
        class FakeMessage:
            def __init__(self, text=""):
                self.text = text
                self.reply_to_message = None
                self.replies = []
            async def reply_text(self, text, **kwargs):
                self.replies.append(text)

        class FakeBot:
            async def get_chat_member(self, chat_id, user_id):
                status = "creator" if user_id == 444 else "administrator"
                return SimpleNamespace(status=status, user=SimpleNamespace(is_bot=False))

        context = SimpleNamespace(bot=FakeBot())
        delegated = SimpleNamespace(id=333)
        message = FakeMessage("/modadd 555")
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=CHAT_ID, type="supergroup"),
            effective_user=delegated,
            effective_message=message,
        )
        self.assertFalse(asyncio.run(bot._moderation_access(update, context, creator_only=True)))
        self.assertTrue(message.replies)
        self.assertFalse(db.is_group_moderator(CHAT_ID, 555))

        owner = SimpleNamespace(id=444)
        owner_update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=CHAT_ID, type="supergroup"),
            effective_user=owner,
            effective_message=FakeMessage("/modremove 555"),
        )
        db.add_group_moderator(CHAT_ID, 555, 444)
        context.args = ["555"]
        asyncio.run(bot.moderation_command(owner_update, context))
        self.assertFalse(db.is_group_moderator(CHAT_ID, 555))

    def test_moderators_are_group_scoped_and_warnings_can_be_cleared(self):
        self.assertTrue(db.add_group_moderator(CHAT_ID, 555, USER_ID))
        self.assertTrue(db.is_group_moderator(CHAT_ID, 555))
        self.assertFalse(db.is_group_moderator(CHAT_ID - 1, 555))
        warning_id = db.add_moderation_warning(CHAT_ID, USER_ID, 555, "QA warning")
        self.assertGreater(warning_id, 0)
        self.assertEqual(len(db.get_moderation_warnings(CHAT_ID, USER_ID)), 1)
        self.assertEqual(db.clear_moderation_warnings(CHAT_ID, USER_ID), 1)
        self.assertEqual(len(db.get_moderation_warnings(CHAT_ID, USER_ID)), 0)
        self.assertTrue(db.remove_group_moderator(CHAT_ID, 555))

    def test_member_card_escapes_html_and_tolerates_bad_badge_json(self):
        member = db.get_member(CHAT_ID, USER_ID)
        member["custom_badges"] = '["not-a-dict", {"emoji": 7, "name": null}]'
        body, keyboard = admin_panel.member_card(CHAT_ID, member)
        self.assertIn("QA &lt;Member&gt;", body)
        self.assertNotIn("QA <Member>", body)
        self.assertIsNotNone(keyboard)

    def test_game_xp_is_separate_and_session_is_one_time(self):
        token = games.create_session(CHAT_ID, USER_ID, "memory")
        seed = games.get_session_seed(token, CHAT_ID, USER_ID)
        proof = memory_proof_for_moves(seed, 8)
        result = games.record_score(token, CHAT_ID, USER_ID, "memory", 8, 10000, proof)
        self.assertTrue(result["ok"])
        self.assertEqual(result["game_xp"], 40)
        self.assertEqual(db.get_member(CHAT_ID, USER_ID)["xp"], 0)
        self.assertEqual(games.get_profile(CHAT_ID, USER_ID)["game_xp"], 40)
        self.assertEqual(games.record_score(token, CHAT_ID, USER_ID, "memory", 8, 10000, proof)["reason"], "session_expired")
        self.assertEqual(games.leaderboard(CHAT_ID, "memory")[0]["best"], 8)
        self.assertEqual(games.leaderboard(CHAT_ID - 1, "memory"), [])

    def test_memory_leaderboard_rewards_fewer_moves(self):
        # Clear this test's scores and profile, then record two members.
        other = 22334455
        db.upsert_member(CHAT_ID, SimpleNamespace(id=other, username="fast", full_name="Fast Member"))
        with db._connect() as conn:
            conn.execute("DELETE FROM game_scores WHERE chat_id=? AND game_key='memory'", (CHAT_ID,))
            conn.execute("DELETE FROM game_profiles WHERE chat_id=? AND user_id IN (?,?)", (CHAT_ID, USER_ID, other))
            conn.execute("DELETE FROM game_sessions WHERE chat_id=?", (CHAT_ID,))
        slow_token = games.create_session(CHAT_ID, USER_ID, "memory")
        slow_seed = games.get_session_seed(slow_token, CHAT_ID, USER_ID)
        self.assertTrue(games.record_score(slow_token, CHAT_ID, USER_ID, "memory", 24, 20000, memory_proof_for_moves(slow_seed, 24))["ok"])
        # Cooldown is per-user, so another user can submit immediately.
        fast_token = games.create_session(CHAT_ID, other, "memory")
        fast_seed = games.get_session_seed(fast_token, CHAT_ID, other)
        self.assertTrue(games.record_score(fast_token, CHAT_ID, other, "memory", 10, 15000, memory_proof_for_moves(fast_seed, 10))["ok"])
        rows = games.leaderboard(CHAT_ID, "memory")
        self.assertEqual(rows[0]["user_id"], other)
        self.assertEqual(rows[0]["best"], 10)

    def test_game_score_limits_and_cooldown(self):
        bad = games.create_session(CHAT_ID, USER_ID, "snake")
        self.assertEqual(games.record_score(bad, CHAT_ID, USER_ID, "snake", 999, 10000)["reason"], "invalid_score")
        good = games.create_session(CHAT_ID, USER_ID, "memory")
        good_seed = games.get_session_seed(good, CHAT_ID, USER_ID)
        first = games.record_score(good, CHAT_ID, USER_ID, "memory", 8, 20000, memory_proof_for_moves(good_seed, 8))
        self.assertTrue(first["ok"])
        next_token = games.create_session(CHAT_ID, USER_ID, "memory")
        next_seed = games.get_session_seed(next_token, CHAT_ID, USER_ID)
        self.assertEqual(games.record_score(next_token, CHAT_ID, USER_ID, "memory", 8, 20000, memory_proof_for_moves(next_seed, 8))["reason"], "cooldown")

    def test_client_game_scores_require_valid_replay_proofs(self):
        snake_token = games.create_session(CHAT_ID, USER_ID, "snake")
        self.assertEqual(games.record_score(snake_token, CHAT_ID, USER_ID, "snake", 10, 10000, "R" * 10)["reason"], "invalid_proof")
        # With a known test seed, eleven straight steps end at the wall without food.
        with db._connect() as conn:
            conn.execute("UPDATE game_sessions SET seed=1 WHERE token=?", (snake_token,))
        snake_result = games.record_score(snake_token, CHAT_ID, USER_ID, "snake", 0, 1500, "R" * 11)
        self.assertTrue(snake_result["ok"])
        ttt_token = games.create_session(CHAT_ID, USER_ID, "tictactoe")
        self.assertTrue(games.record_score(ttt_token, CHAT_ID, USER_ID, "tictactoe", -1, 5000, "013")["ok"])
        self.assertFalse(games.verify_memory_proof(12345, "0000000000000000", 8))
        self.assertFalse(games.verify_tictactoe_proof("000", 1))

    def test_reaction_timer_is_server_measured(self):
        token = games.create_session(CHAT_ID, USER_ID, "reaction")
        with db._connect() as conn:
            conn.execute("UPDATE game_sessions SET reaction_ready_at=? WHERE token=?", (int(__import__('time').time()*1000)-1, token))
        self.assertTrue(games.reaction_check(token, CHAT_ID, USER_ID)["ready"])
        __import__('time').sleep(0.12)
        result = games.finish_reaction(token, CHAT_ID, USER_ID)
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["score"], 100)

    def test_signed_group_launch_payload(self):
        token = "123456:TEST_TOKEN"
        payload = games.make_group_start_param(CHAT_ID, token)
        self.assertEqual(games.parse_group_start_param(payload, token), CHAT_ID)
        self.assertIsNone(games.parse_group_start_param(payload, token + "x"))

    def test_miniapp_init_data_hmac_validation(self):
        token = "123456:TEST_TOKEN"
        miniapp_server.BOT_TOKEN = token
        launch = games.make_group_start_param(CHAT_ID, token)
        fields = {
            "auth_date": str(int(__import__('time').time())),
            "chat_instance": "9876543210123456789",
            "chat_type": "supergroup",
            "start_param": launch,
            "user": json.dumps({"id": USER_ID, "first_name": "QA"}, separators=(",", ":")),
        }
        check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
        secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        raw = urlencode(fields)
        self.assertEqual(miniapp_server.validate_init_data(raw)["chat_id"], CHAT_ID)
        fields["hash"] = "0" * 64
        self.assertIsNone(miniapp_server.validate_init_data(urlencode(fields)))

    def test_miniapp_http_api_bootstrap_and_score_submission(self):
        token = "123456:API_TEST_TOKEN"
        miniapp_server.BOT_TOKEN = token
        original_membership_check = miniapp_server.verify_group_membership
        miniapp_server.verify_group_membership = lambda chat_id, user_id: True
        fields = {
            "auth_date": str(int(__import__('time').time())),
            "chat_instance": "9876543210123456789",
            "chat_type": "supergroup",
            "start_param": games.make_group_start_param(CHAT_ID, token),
            "user": json.dumps({"id": USER_ID, "first_name": "QA"}, separators=(",", ":")),
        }
        check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
        secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        init_data = urlencode(fields)
        server = ThreadingHTTPServer(("127.0.0.1", 0), miniapp_server.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        def post(path, payload):
            body = json.dumps({**payload, "init_data": init_data}).encode()
            request = Request(base + path, data=body, headers={"Content-Type": "application/json"}, method="POST")
            with urlopen(request, timeout=5) as response:
                return json.loads(response.read().decode())
        try:
            bootstrap = post("/api/bootstrap", {})
            self.assertTrue(bootstrap["ok"])
            self.assertEqual(bootstrap["profile"]["game_level"], 1)
            session_data = post("/api/session", {"game": "memory"})
            session = session_data["session"]
            proof = memory_proof_for_moves(session_data["seed"], 8)
            score = post("/api/score", {"game": "memory", "session": session, "score": 8, "duration_ms": 10000, "proof": proof})
            self.assertTrue(score["ok"])
            self.assertEqual(score["game_xp"], 40)
        finally:
            server.shutdown()
            server.server_close()
            miniapp_server.verify_group_membership = original_membership_check

    def test_sqlite_integrity(self):
        with db._connect() as conn:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_non_owner_group_admin_cannot_finally_promote_admin_request(self):
        class FakeMessage:
            def __init__(self):
                self.replies = []
            async def reply_text(self, text):
                self.replies.append(text)

        class FakeQuery:
            def __init__(self):
                self.from_user = SimpleNamespace(id=222)
                self.data = f"request_approve:{CHAT_ID}:{USER_ID}"
                self.message = FakeMessage()
                self.answer_count = 0
            async def answer(self, *args, **kwargs):
                self.answer_count += 1

        class FakeBot:
            def __init__(self):
                self.promote_called = False
            async def get_chat_member(self, chat_id, user_id):
                return SimpleNamespace(status="administrator")
            async def promote_chat_member(self, **kwargs):
                self.promote_called = True

        query = FakeQuery()
        fake_bot = FakeBot()
        update = SimpleNamespace(callback_query=query)
        context = SimpleNamespace(bot=fake_bot)
        asyncio.run(bot.callback_handler(update, context))
        self.assertFalse(fake_bot.promote_called)
        self.assertEqual(query.answer_count, 1)
        self.assertTrue(any("مدیر اصلی" in message for message in query.message.replies))

    def test_all_admin_panel_callback_payloads_fit_telegram_limit(self):
        member = db.get_member(CHAT_ID, USER_ID)
        group = {"chat_id": CHAT_ID, "title": "گروه آزمایشی"}
        keyboards = [
            admin_panel.group_picker([group]),
            admin_panel.members_keyboard(CHAT_ID, 0, [member], 1),
            admin_panel.member_card(CHAT_ID, member)[1],
            admin_panel.badge_keyboard(CHAT_ID, USER_ID, []),
            admin_panel.settings_keyboard(CHAT_ID, 70, True),
            admin_panel.shop_admin_keyboard(CHAT_ID, db.get_shop_items(CHAT_ID, active_only=False)),
            admin_panel.shop_keyboard(CHAT_ID, db.get_shop_items(CHAT_ID), USER_ID),
            admin_panel.group_home_keyboard(CHAT_ID),
            admin_panel.progress_keyboard(CHAT_ID, 70, True),
            admin_panel.economy_keyboard(CHAT_ID),
            admin_panel.shop_admin_keyboard(CHAT_ID, db.get_shop_items(CHAT_ID, active_only=False), 0),
            admin_panel.shop_keyboard(CHAT_ID, db.get_shop_items(CHAT_ID), USER_ID, 0),
            bot.inventory_keyboard(CHAT_ID, USER_ID, db.get_inventory(CHAT_ID, USER_ID), 0)[0],
        ]
        for keyboard in keyboards:
            for row in keyboard.inline_keyboard:
                for button in row:
                    if button.callback_data is not None:
                        self.assertLessEqual(len(button.callback_data.encode("utf-8")), 64, button.callback_data)


if __name__ == "__main__":
    unittest.main()
