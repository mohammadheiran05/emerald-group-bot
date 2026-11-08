# Emerald Group Bot 3.0.0-rc1

## Added
- Separate per-group delegated moderator access list, controlled only by the Telegram group creator.
- Persistent warning records and moderation audit trail in SQLite.
- `/ban`, `/unban`, `/mute`, `/unmute`, `/warn`, `/warnings`, `/clearwarns`.
- `/modadd`, `/modremove`, `/modlist` for Creator-managed delegation.
- A moderation guide entry in the group admin panel.

## Security model
- `OWNER_ID` remains the bot/system owner and retains the existing global bot-panel access.
- `OWNER_ID` alone does not authorize moderation actions in a group.
- Telegram group Creator can moderate and delegate moderation rights for that group.
- Delegated moderators can run moderation commands only in the group where they were added.
- The bot must have Telegram administrator rights with permission to restrict/ban members for ban/mute operations.

## Compatibility
- Database changes are additive. Existing SQLite tables and user progress are preserved.
- This source package intentionally excludes `.env`, `.venv`, and the live SQLite database.
- HTML5 mini-games are not included in this release candidate; they remain conditional on hosting/security/performance testing.

## Validation
- Python syntax compilation passed for all application modules.
- Isolated SQLite migration, moderator access, warning lifecycle, and audit-write tests passed.
- Telegram API calls were checked against the python-telegram-bot 22.8 package source bundled in the submitted project archive. A live Telegram integration test has not yet been run.
