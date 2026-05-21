# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Run / install

```bash
./start.sh                # activates .venv and runs the bot
# or, manually:
source .venv/bin/activate
pip install -e .          # one-time, after dependency changes
python btb-bot.py         # long-running foreground process
```

Python 3.11+. There is no test suite, linter, or build step configured.

## Architecture

Single-file Slack bot (`btb-bot.py`) running over **Socket Mode** — no inbound HTTP, no public URL. Connects out to Slack with a bot token (`xoxb-…`) plus an app-level token (`xapp-…`) and listens for `message` events.

Flow on each event:
1. Drop anything with a `subtype` (edits, joins, channel-join, file-share, etc. — only top-level human messages pass).
2. Drop if `event["user"]` is not in `TARGET_USER_IDS` (loaded from `.env`).
3. Roll `random.random() < reaction_percentage`; on hit, pick a random custom emoji and call `reactions_add`.
4. Swallow `already_reacted` errors silently; log any other Slack error with a channel label resolved via `conversations_info`.

The **custom emoji list is fetched once at startup** via `emoji.list` and cached for the process lifetime — restart to pick up newly added workspace emojis. If the workspace has zero custom emojis, the bot exits at startup rather than running as a no-op.

Config is split across two files on purpose:
- `.env` — secrets and identifiers we don't commit (`SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `TARGET_USER_IDS` as a comma-separated list of Slack member IDs). Gitignored.
- `config.yaml` — non-secret behavior (`reaction_percentage` float 0.0–1.0). Validated at startup; bad values call `sys.exit`.

## Slack app requirements

Changes to scopes or event subscriptions require **reinstalling the app to the workspace** and re-copying the bot token. Required pieces (full table in README.md):

- Bot scopes: `reactions:write`, `emoji:read`, `users:read` (resolves target IDs to display names at startup), plus `*:history` for whichever channel types the bot should see (`channels`, `groups`, `im`, `mpim`).
- App-level token scope: `connections:write`.
- Event subscriptions: `message.channels`, `message.groups`, `message.im`, `message.mpim`.
- Socket Mode must be enabled in the app config.

The bot only receives events for channels it has been `/invite`d to — adding channel coverage is an in-Slack action, not a code change.
