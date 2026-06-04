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

The bot has **three independent behaviors**, each sampled separately per message:
- **Reactions** — every human in an invited channel is eligible by default (opt-out via `users.yaml`). On a hit, adds a random workspace custom emoji via `reactions_add`.
- **Mock replies** — every human in an invited channel is eligible by default. On a hit, posts a threaded reply with the original text in alternating case. User mentions (`<@U…>`) in the source text are first rewritten to literal `@name` strings (resolved via `users_info`, cached) so the reply neither re-pings the target nor echoes a broken lower-cased user ID. If the bot was granted `files:write` and `spongebob-mock.jpg` is present next to the script, it uploads the image via `files_upload_v2` with the alternating-case text as `initial_comment`; otherwise it falls back to `chat_postMessage` with `… :spongebob-mock:` appended. Scope is detected once at startup via `auth.test`'s `x-oauth-scopes` header.
- **Give-up replies** — only fire when the message text ends in a `?` (after `rstrip()`, so trailing whitespace is ignored). On a hit, uploads `just-give-up.jpg` via `files_upload_v2` as a threaded reply (no caption). Image-only: gated on a startup `can_giveup` flag (`files:write` granted **and** `just-give-up.jpg` present, reusing the same `auth.test` scope detection as the mock image). When the flag is false the branch is disabled — there is no emoji/text fallback because no `:just-give-up:` emoji exists.

Per-user rate overrides live in `users.yaml` (see Config section). Effective rate per user per behavior = the user's override if set, else the global default from `config.yaml`. A rate of `0.0` opts that user out of the behavior.

Flow on each event:
1. Drop DMs (`channel_type` in `("im", "mpim")`), anything with a `subtype` (edits, joins, file-share, `bot_message`, etc.), and anything with a `bot_id` set (catches modern apps that post without a `subtype`, plus our own posts as a belt-and-suspenders self-mock guard). Only top-level human messages pass.
2. **Mock branch:** compute `effective_mock_pct(user)`. If 0, skip. Otherwise roll `random.random() < pct`; on hit, post a threaded reply with `alternating_case(text)` (with image or `:spongebob-mock:` per scope).
3. **Give-up branch:** compute `effective_giveup_pct(user)`. Skip if `can_giveup` is false, if the rate is 0, or if `text.rstrip()` does not end in `?`. Otherwise roll `random.random() < pct`; on hit, upload `just-give-up.jpg` as a threaded reply.
4. **Reaction branch:** compute `effective_reaction_pct(user)`. If 0, skip. Otherwise roll `random.random() < pct`; on hit, pick a random custom emoji and call `reactions_add`.
5. Swallow `already_reacted` errors silently; log any other Slack error with a channel label resolved via `conversations_info`.

The three rolls are independent — the same message can be mocked, given up on, and reacted to in any combination, or none.

The **custom emoji list is fetched once at startup** via `emoji.list` and cached for the process lifetime — restart to pick up newly added workspace emojis. If the workspace has zero custom emojis, the bot exits at startup rather than running as a no-op.

Config is split across three files on purpose:
- `.env` — secrets and the optional `LOG_MODE` operational toggle (`SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `LOG_MODE`). Gitignored.
- `config.yaml` — non-secret global defaults (`reaction_percentage`, `mock_percentage`, `giveup_percentage`, all floats 0.0–1.0). Committed. Validated at startup; bad/missing values call `sys.exit`.
- `users.yaml` — per-user overrides (`name`, `mock_percentage`, `reaction_percentage`, `giveup_percentage` keyed by Slack member ID). Gitignored. Missing file is fine and means "no overrides" (everyone gets the global defaults). `users.example.yaml` documents the schema and is committed. Validated at startup: unknown fields, malformed IDs (must match `^[UW][A-Z0-9]+$`), and out-of-range percentages all `sys.exit`.

`LOG_MODE` has three values, validated at startup:
- `normal` (default) — `log.info` fires only when the bot actually acts (`mock …`, `giveup …`, `react …`, `reacted with :emoji: …`). Warnings still fire. Skips, roll-misses, and startup config dumps are at `log.debug` and suppressed.
- `verbose` — sets the `bug-tori-bot` logger to `DEBUG`, exposing all of the above skip/decision/startup lines. Slack SDK loggers stay at their defaults.
- `debug` — verbose plus `slack_bolt` and `slack_sdk` loggers set to `DEBUG` (raw API request/response noise).

## Slack app requirements

Changes to scopes or event subscriptions require **reinstalling the app to the workspace** and re-copying the bot token. Required pieces (full table in README.md):

- Bot scopes: `reactions:write`, `chat:write` (mock replies), `emoji:read`, `users:read` (resolves overridden user IDs to display names in startup logs), plus `*:history` for whichever channel types the bot should see (`channels`, `groups`, `im`, `mpim`). `files:write` is optional for mock replies (uploads `spongebob-mock.jpg` instead of emoji text) but **required** for give-up replies (uploads `just-give-up.jpg`, which has no fallback).
- App-level token scope: `connections:write`.
- Event subscriptions: `message.channels`, `message.groups`, `message.im`, `message.mpim`.
- Socket Mode must be enabled in the app config.

The bot only receives events for channels it has been `/invite`d to — adding channel coverage is an in-Slack action, not a code change.
