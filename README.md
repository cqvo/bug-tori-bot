# bug-tori-bot

A small Slack bot with three independent behaviors:

- **Reactions** — randomly reacts to messages with a random custom emoji from the workspace.
- **Mock replies** — randomly replies in-thread with the last 1–3 sentences of the message in alternating case plus `:spongebob-mock:` (or attaches `spongebob-mock.jpg` when the bot has `files:write`).
- **Give-up replies** — when a message ends in a `?`, randomly replies in-thread by uploading `just-give-up.jpg`. Requires the `files:write` scope and the image file; otherwise this behavior is disabled.

All three behaviors fire by default for every human in invited channels at the global rates in `config.yaml`. Per-user overrides in `users.yaml` (gitignored) can raise or lower an individual's rate, or set it to `0.0` to opt them out entirely.

Each behavior has its own independent sampling rate. The same message can trigger any combination of the three, or none.

Runs locally as a long-running Python process over Slack Socket Mode — no public URL required.

## How it works

- Connects to Slack via Socket Mode using a bot token (`xoxb-…`) and app-level token (`xapp-…`).
- Subscribes to `message.*` events in every channel the bot has been invited to.
- On startup, fetches the workspace's custom emoji list via `emoji.list`.
- For each new top-level message in a public/private channel:
  - **Mock branch:** rolls against the author's effective `mock_percentage` (override from `users.yaml`, else the global default). A 0.0 rate skips. On a hit, takes the last 1–3 sentences of the message (count chosen at random) and posts a threaded reply: `aLtErNaTiNg cAsE :spongebob-mock:` (or uploads `spongebob-mock.jpg` if `files:write` is granted).
  - **Give-up branch:** only fires when the message ends in a `?` (ignoring trailing whitespace). Rolls against the author's effective `giveup_percentage`. A 0.0 rate skips. On a hit, uploads `just-give-up.jpg` as a threaded reply. Silently disabled if `files:write` or the image file is missing.
  - **Reaction branch:** rolls against the author's effective `reaction_percentage`. A 0.0 rate skips. On a hit, picks one custom emoji at random and adds it as a reaction.
- Skips DMs/group DMs, edits, joins, other message subtypes, and anything with a `bot_id` (catches messages from other installed apps and our own posts). Swallows `already_reacted` from Slack.
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
| `chat:write` | Post threaded mock replies. |
| `emoji:read` | Fetch the workspace's custom emoji list at startup. |
| `users:read` | Resolve overridden user IDs to display names for startup logging. |
| `files:write` | Optional for mock replies (uploads `spongebob-mock.jpg` instead of emoji text; falls back to emoji without it). **Required** to enable give-up replies (`just-give-up.jpg`), which have no fallback. |
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
cp users.example.yaml users.yaml
```

Edit `.env` with the two tokens:

```
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
```

Then edit `config.yaml` for global default rates that apply to **every** human in invited channels:

```yaml
reaction_percentage: 0.25     # 0.0–1.0; share of all users' messages to react to
mock_percentage: 0.1          # 0.0–1.0; share of all users' messages to mock-reply to
giveup_percentage: 0.25       # 0.0–1.0; share of messages ending in "?" to reply to with just-give-up.jpg
```

Then edit `users.yaml` (gitignored) for per-user overrides. Either field is optional; `0.0` opts that user out of that behavior entirely:

```yaml
users:
  U0985TXQZPF:
    name: Some User              # optional; only used in startup logs
    reaction_percentage: 1.0     # always react to this user
  U08SBTJ9N1W:
    name: Friend
    mock_percentage: 0.0         # never mock this user
```

To find a user's member ID: click their name in Slack → **View full profile** → **⋮** menu → **Copy member ID**.

### 3. Run

```bash
./start.sh          # activates .venv and runs the bot
# or, manually:
python btb-bot.py
```

By default (`LOG_MODE=normal`) the bot is silent at startup and only logs when it actually mocks or reacts. To see the connection handshake and per-message decisions during setup, run with `LOG_MODE=verbose ./start.sh`:

```
... DEBUG bug-tori-bot reaction_pct=0.25 mock_pct=0.10 giveup_pct=0.25 users_overridden=2 custom_emojis=N image_upload=False giveup=False
... DEBUG bug-tori-bot starting Socket Mode connection
```

Then `/invite @bug-tori-bot` to any channels you want it active in.

## Verifying it works

1. Temporarily set `reaction_percentage: 1.0`, `mock_percentage: 1.0`, and `giveup_percentage: 1.0` in `config.yaml` and restart.
2. From any account *not* listed in `users.yaml`, post a message ending in a `?` in an invited channel. The bot should react within ~1 second with a random custom emoji, post a mock reply in-thread, *and* (if `files:write` is granted) upload `just-give-up.jpg` in-thread.
3. Post a message that does *not* end in a `?`. You should get the reaction and mock reply but no give-up image — give-up only triggers on messages ending in `?`.
4. From an account listed with `mock_percentage: 0.0`, post a message. You should get only the reaction (and give-up, if `?`), no mock reply.
5. From an account listed with `reaction_percentage: 0.0`, post a message. You should get the mock reply (and give-up, if `?`), no reaction.
6. Lower the percentages to your real target values and restart.

## Configuration reference

### `.env`

| Var | Required | Description |
| --- | --- | --- |
| `SLACK_BOT_TOKEN` | yes | `xoxb-…` from *OAuth & Permissions* after installing the app. |
| `SLACK_APP_TOKEN` | yes | `xapp-…` app-level token with `connections:write` scope. |
| `LOG_MODE` | no | `normal` (default), `verbose`, or `debug`. `normal` only logs when the bot actually posts a mock reply or adds a reaction. `verbose` also logs skip/decision/startup lines. `debug` adds Slack SDK request/response logging. |

### `config.yaml`

| Key | Type | Description |
| --- | --- | --- |
| `reaction_percentage` | float | `0.0`–`1.0`. Default fraction of all users' messages to react to, sampled independently per message. Overridable per user in `users.yaml`. |
| `mock_percentage` | float | `0.0`–`1.0`. Default fraction of all users' messages to mock-reply to, sampled independently per message. Overridable per user in `users.yaml`. |
| `giveup_percentage` | float | `0.0`–`1.0`. Default fraction of messages **ending in a `?`** to reply to with `just-give-up.jpg`, sampled independently per message. Requires the `files:write` scope and the image file. Overridable per user in `users.yaml`. |

### `users.yaml` (gitignored; copy from `users.example.yaml`)

Top-level key `users:` maps Slack member ID → entry. Each entry takes:

| Key | Type | Description |
| --- | --- | --- |
| `name` | string | Optional, cosmetic. Shown in startup logs alongside the Slack-resolved display name. |
| `mock_percentage` | float | Optional override of the global `mock_percentage` for this user. `0.0` opts them out of mock replies entirely. |
| `reaction_percentage` | float | Optional override of the global `reaction_percentage` for this user. `0.0` opts them out of reactions entirely. |
| `giveup_percentage` | float | Optional override of the global `giveup_percentage` for this user. `0.0` opts them out of give-up replies entirely. Only applies to messages ending in `?`. |

Users not listed in `users.yaml` get the global defaults for all three behaviors.

## Troubleshooting

**`token is invalid (auth.test result: invalid_auth)`** — the bot token isn't set, is malformed, or hasn't been re-issued after reinstalling the app. Double-check the value in `.env`.

**Bot starts but doesn't react** — confirm:
- The bot is a member of the channel (`/invite @bug-tori-bot`).
- The poster doesn't have `reaction_percentage: 0.0` in `users.yaml`.
- `reaction_percentage` in `config.yaml` isn't too low to observe.

**Bot starts but doesn't mock-reply** — confirm:
- The bot is a member of the channel (`/invite @bug-tori-bot`).
- The poster doesn't have `mock_percentage: 0.0` in `users.yaml`.
- `mock_percentage` in `config.yaml` isn't too low to observe.
- The app has the `chat:write` bot scope (added after the initial install — you must reinstall).

**Bot starts but doesn't send give-up replies** — confirm:
- The message actually ends in a `?` (give-up only triggers on those, ignoring trailing whitespace).
- The app has the `files:write` scope and `just-give-up.jpg` sits next to `btb-bot.py`. If `files:write` is granted but the image is missing, a startup warning fires (`give-up replies disabled`) and the verbose startup dump shows `giveup=False`.
- The poster doesn't have `giveup_percentage: 0.0` in `users.yaml`.
- `giveup_percentage` in `config.yaml` isn't too low to observe.

**`reaction_percentage must be between 0.0 and 1.0`** / **`mock_percentage must be between 0.0 and 1.0`** / **`giveup_percentage must be between 0.0 and 1.0`** — `config.yaml` value is missing, non-numeric, or out of range.

**`workspace has no custom emojis to react with`** — the app's workspace has no custom emojis installed, or the bot lacks the `emoji:read` scope. Add some custom emojis (Slack → *Tools & settings* → *Customize workspace*) or grant the scope and reinstall the app.

## Files

```
btb-bot.py            # entrypoint
config.yaml           # global reaction_percentage, mock_percentage, giveup_percentage
users.example.yaml    # per-user override template; copy to users.yaml (gitignored)
spongebob-mock.jpg    # mock-reply image (optional; needs files:write)
just-give-up.jpg      # give-up reply image (needs files:write)
.env.example          # token template
pyproject.toml        # deps: slack-bolt, pyyaml, python-dotenv
```
