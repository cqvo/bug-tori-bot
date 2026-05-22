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

The bot has **two independent behaviors**, each sampled separately per message:
- **Reactions** — gated to a small allowlist (`TARGET_USER_IDS`). On a hit, adds a random workspace custom emoji via `reactions_add`.
- **Mock replies** — applies to everyone in invited channels *except* `BLOCKED_USER_IDS`. On a hit, posts a threaded reply with the original text in alternating case. If the bot was granted `files:write` and `spongebob-mock.jpg` is present next to the script, it uploads the image via `files_upload_v2` with the alternating-case text as `initial_comment`; otherwise it falls back to `chat_postMessage` with `… :spongebob-mock:` appended. Scope is detected once at startup via `auth.test`'s `x-oauth-scopes` header.

Flow on each event:
1. Drop DMs (`channel_type` in `("im", "mpim")`), anything with a `subtype` (edits, joins, file-share, `bot_message`, etc.), and anything with a `bot_id` set (catches modern apps that post without a `subtype`, plus our own posts as a belt-and-suspenders self-mock guard). Only top-level human messages pass.
2. **Mock branch:** if `event["user"]` is not in `BLOCKED_USER_IDS`, roll `random.random() < mock_percentage`; on hit, post a threaded reply with `alternating_case(text) + " :spongebob-mock:"`.
3. **Reaction branch:** if `event["user"]` is in `TARGET_USER_IDS`, roll `random.random() < reaction_percentage`; on hit, pick a random custom emoji and call `reactions_add`.
4. Swallow `already_reacted` errors silently; log any other Slack error with a channel label resolved via `conversations_info`.

The two rolls are independent — the same message can be both mocked and reacted to, or neither.

The **custom emoji list is fetched once at startup** via `emoji.list` and cached for the process lifetime — restart to pick up newly added workspace emojis. If the workspace has zero custom emojis, the bot exits at startup rather than running as a no-op.

Config is split across two files on purpose:
- `.env` — secrets and identifiers we don't commit (`SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `TARGET_USER_IDS`, optional `BLOCKED_USER_IDS`, both comma-separated lists of Slack member IDs). Gitignored.
- `config.yaml` — non-secret behavior (`reaction_percentage`, `mock_percentage`, both floats 0.0–1.0). Validated at startup; bad values call `sys.exit`.

## Slack app requirements

Changes to scopes or event subscriptions require **reinstalling the app to the workspace** and re-copying the bot token. Required pieces (full table in README.md):

- Bot scopes: `reactions:write`, `chat:write` (mock replies), `emoji:read`, `users:read` (resolves target/blocked IDs to display names at startup), plus `*:history` for whichever channel types the bot should see (`channels`, `groups`, `im`, `mpim`). Optional: `files:write` to upload `spongebob-mock.jpg` as the mock reply instead of emoji text.
- App-level token scope: `connections:write`.
- Event subscriptions: `message.channels`, `message.groups`, `message.im`, `message.mpim`.
- Socket Mode must be enabled in the app config.

The bot only receives events for channels it has been `/invite`d to — adding channel coverage is an in-Slack action, not a code change.
