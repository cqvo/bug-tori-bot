# bug-tori-bot

A small Slack bot that watches messages from one or more specific users and randomly reacts to a configurable percentage of them with a random custom emoji from the workspace.

Runs locally as a long-running Python process over Slack Socket Mode — no public URL required.

## How it works

- Connects to Slack via Socket Mode using a bot token (`xoxb-…`) and app-level token (`xapp-…`).
- Subscribes to `message.*` events in every channel the bot has been invited to.
- On startup, fetches the workspace's custom emoji list via `emoji.list`.
- For each new top-level message, if the author is in `target_user_ids`, rolls a random number against `reaction_percentage`. On a hit, picks one custom emoji at random and adds it as a reaction.
- Skips edits, joins, and other message subtypes. Swallows `already_reacted` from Slack.
- The custom emoji list is fetched once at startup. Restart the bot to pick up newly added workspace emojis.

The bot only sees messages in channels it has been explicitly invited to. To expand its reach, `/invite @bug-tori-bot` in more channels.

## Setup

This assumes the Slack app already exists in your workspace. You'll need two tokens from it:

- **Bot User OAuth Token** (`xoxb-…`) — copied from *OAuth & Permissions* after installing the app.
- **App-Level Token** (`xapp-…`) — generated under *Basic Information → App-Level Tokens*. Socket Mode must also be enabled under *Socket Mode*.

#### Required bot scopes

Configured under *OAuth & Permissions → Scopes → Bot Token Scopes*:

| Scope | Why |
| --- | --- |
| `reactions:write` | Add emoji reactions to messages. |
| `emoji:read` | Fetch the workspace's custom emoji list at startup. |
| `users:read` | Resolve target user IDs to display names for startup logging. |
| `channels:history` | Read messages in public channels the bot is invited to. |
| `groups:history` | Read messages in private channels the bot is invited to. |
| `im:history` | Read DMs sent to the bot. |
| `mpim:history` | Read group DMs the bot is part of. |

#### Required app-level token scope

Configured when generating the `xapp-…` token under *Basic Information → App-Level Tokens*:

| Scope | Why |
| --- | --- |
| `connections:write` | Authenticate the Socket Mode WebSocket connection. |

#### Required event subscriptions

Configured under *Event Subscriptions → Subscribe to bot events*:

| Event | Why |
| --- | --- |
| `message.channels` | Messages posted in public channels. |
| `message.groups` | Messages posted in private channels. |
| `message.im` | Messages sent in DMs with the bot. |
| `message.mpim` | Messages posted in group DMs. |

If you change scopes after installing the app, you must reinstall it to the workspace and re-copy the bot token.

### 1. Install dependencies

Requires Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. Configure

```bash
cp .env.example .env
```

Edit `.env` and paste the two tokens:

```
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
```

Then edit `config.yaml`:

```yaml
target_user_ids:              # one or more Slack member IDs to watch
  - U0985TXQZPF
reaction_percentage: 0.25     # 0.0–1.0; share of their messages to react to
```

To find a user's member ID: click their name in Slack → **View full profile** → **⋮** menu → **Copy member ID**. Add as many IDs as you like under `target_user_ids`.

### 3. Run

```bash
python btb-bot.py
```

You should see:

```
... INFO bug-tori-bot targets=['U0985TXQZPF'] percentage=0.25 custom_emojis=N
... INFO bug-tori-bot starting Socket Mode connection
```

Then `/invite @bug-tori-bot` to any channels you want it active in.

## Verifying it works

1. Temporarily set `reaction_percentage: 1.0` in `config.yaml` and restart.
2. From any account whose ID is in `target_user_ids`, post a message in an invited channel.
3. The bot should react within ~1 second with a random custom emoji from the workspace.
4. Lower the percentage to your real target value and restart.

## Configuration reference

### `.env`

| Var | Required | Description |
| --- | --- | --- |
| `SLACK_BOT_TOKEN` | yes | `xoxb-…` from *OAuth & Permissions* after installing the app. |
| `SLACK_APP_TOKEN` | yes | `xapp-…` app-level token with `connections:write` scope. |

### `config.yaml`

| Key | Type | Description |
| --- | --- | --- |
| `target_user_ids` | list of strings | Slack member IDs (e.g. `U0985TXQZPF`). Messages from any user in the list trigger reactions. |
| `reaction_percentage` | float | `0.0`–`1.0`. Fraction of qualifying messages to react to, sampled independently per message. |

## Troubleshooting

**`token is invalid (auth.test result: invalid_auth)`** — the bot token isn't set, is malformed, or hasn't been re-issued after reinstalling the app. Double-check the value in `.env`.

**Bot starts but doesn't react** — confirm:
- The bot is a member of the channel (`/invite @bug-tori-bot`).
- The poster's member ID is in `target_user_ids` (try adding your own ID for a self-test).
- `reaction_percentage` isn't too low to observe.

**`reaction_percentage must be between 0.0 and 1.0`** — `config.yaml` value is missing, non-numeric, or out of range.

**`workspace has no custom emojis to react with`** — the app's workspace has no custom emojis installed, or the bot lacks the `emoji:read` scope. Add some custom emojis (Slack → *Tools & settings* → *Customize workspace*) or grant the scope and reinstall the app.

## Files

```
btb-bot.py      # entrypoint
config.yaml     # target user, percentage, emoji list
.env.example    # token template
pyproject.toml  # deps: slack-bolt, pyyaml, python-dotenv
```
