# QA Report — Emerald Group Bot 4.0.0

## Automated checks
- 18/18 unit tests passed.
- Python syntax compilation passed for bot, database, panel, configuration, levels, game logic, Mini App server and tests.
- Mini App JavaScript passed `node --check`.
- Local HTTP checks: `/health`, `/games` and `/` returned HTTP 200.
- Mini App API integration test: authenticated bootstrap, session creation and replay-verified score submission returned HTTP 200.
- Concurrency test: 40 synthetic players submitted verified Memory game records concurrently; 40/40 accepted; SQLite integrity remained `ok`.
- Version 3 to 4 database migration test preserved member XP, special points, delegated moderator access and a pre-existing shop item; new game tables and session seed column were added; `PRAGMA integrity_check` returned `ok`.
- Telegram callback payloads used by the tested admin, shop and inventory keyboards remained within Telegram's 64-byte limit.

## Not yet verified live
- No live Telegram group was used for end-to-end moderation or gameplay testing.
- The Mini App has not yet been opened in a real Telegram mobile/desktop client.
- Railway deployment and BotFather Main Mini App configuration are still manual steps.
- The 40-player concurrency test is synthetic and is not a measurement of Railway production capacity.

## Required configuration before enabling group games
1. Set `MINI_APP_URL` to the service's public HTTPS Railway domain.
2. Configure that URL as the bot's Main Mini App in BotFather.
3. Confirm the bot is an administrator in the group. The moderation commands need restriction permissions; the Mini App also checks group membership through `getChatMember`.
