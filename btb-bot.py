import logging
import os
import random
import re
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk.errors import SlackApiError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("bug-tori-bot")


def load_config(path: Path) -> dict:
    with path.open() as f:
        cfg = yaml.safe_load(f)
    for key in ("reaction_percentage", "mock_percentage", "giveup_percentage"):
        val = cfg.get(key)
        if val is None or not (0.0 <= float(val) <= 1.0):
            sys.exit(f"config.yaml {key} must be between 0.0 and 1.0")
    return cfg


def alternating_case(text: str) -> str:
    out = []
    i = 0
    for ch in text:
        if ch.isalpha():
            out.append(ch.lower() if i % 2 == 0 else ch.upper())
            i += 1
        else:
            out.append(ch)
    return "".join(out)


USER_ID_RE = re.compile(r"^[UW][A-Z0-9]+$")
USER_FIELDS = {"name", "mock_percentage", "reaction_percentage", "giveup_percentage"}

# Slack encodes user mentions as <@U012ABC> or <@U012ABC|label> in message text.
MENTION_RE = re.compile(r"<@([UW][A-Z0-9]+)(?:\|([^>]+))?>")


def load_users(path: Path) -> dict[str, dict]:
    if not path.is_file():
        return {}
    with path.open() as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        sys.exit(f"{path.name} must be a YAML mapping")
    users = raw.get("users") or {}
    if not isinstance(users, dict):
        sys.exit(f"{path.name} 'users' must be a mapping of user_id -> overrides")
    result: dict[str, dict] = {}
    for uid, entry in users.items():
        if not isinstance(uid, str) or not USER_ID_RE.match(uid):
            sys.exit(f"{path.name}: '{uid}' is not a valid Slack member ID")
        if entry is None:
            entry = {}
        if not isinstance(entry, dict):
            sys.exit(f"{path.name}: entry for {uid} must be a mapping")
        unknown = set(entry) - USER_FIELDS
        if unknown:
            sys.exit(f"{path.name}: unknown field(s) for {uid}: {sorted(unknown)}")
        for key in ("mock_percentage", "reaction_percentage", "giveup_percentage"):
            if key in entry and entry[key] is not None:
                try:
                    val = float(entry[key])
                except (TypeError, ValueError):
                    sys.exit(f"{path.name}: {uid}.{key} must be a number in [0.0, 1.0]")
                if not (0.0 <= val <= 1.0):
                    sys.exit(f"{path.name}: {uid}.{key} must be between 0.0 and 1.0")
                entry[key] = val
        result[uid] = entry
    return result


def main() -> None:
    load_dotenv()

    log_mode = os.environ.get("LOG_MODE", "normal").lower()
    if log_mode not in ("normal", "verbose", "debug"):
        sys.exit("LOG_MODE must be one of: normal, verbose, debug")
    log.setLevel(logging.DEBUG if log_mode in ("verbose", "debug") else logging.INFO)
    if log_mode == "debug":
        logging.getLogger("slack_bolt").setLevel(logging.DEBUG)
        logging.getLogger("slack_sdk").setLevel(logging.DEBUG)

    bot_token = os.environ.get("SLACK_BOT_TOKEN")
    app_token = os.environ.get("SLACK_APP_TOKEN")
    if not bot_token or not app_token:
        sys.exit("SLACK_BOT_TOKEN and SLACK_APP_TOKEN must be set (see .env.example)")

    here = Path(__file__).parent
    cfg = load_config(here / "config.yaml")
    reaction_percentage: float = float(cfg["reaction_percentage"])
    mock_percentage: float = float(cfg["mock_percentage"])
    giveup_percentage: float = float(cfg["giveup_percentage"])
    users = load_users(here / "users.yaml")

    def effective_mock_pct(uid: str) -> float:
        override = users.get(uid, {}).get("mock_percentage")
        return mock_percentage if override is None else override

    def effective_reaction_pct(uid: str) -> float:
        override = users.get(uid, {}).get("reaction_percentage")
        return reaction_percentage if override is None else override

    def effective_giveup_pct(uid: str) -> float:
        override = users.get(uid, {}).get("giveup_percentage")
        return giveup_percentage if override is None else override

    app = App(token=bot_token)

    emoji_resp = app.client.emoji_list()
    custom_emojis: list[str] = list(emoji_resp.get("emoji", {}).keys())
    if not custom_emojis:
        sys.exit("workspace has no custom emojis to react with")

    mock_image_path = here / "spongebob-mock.jpg"
    giveup_image_path = here / "just-give-up.jpg"
    can_upload_image = False
    can_giveup = False
    try:
        auth_resp = app.client.auth_test()
        scopes_header = auth_resp.headers.get("x-oauth-scopes", "")
        granted_scopes = {s.strip() for s in scopes_header.split(",") if s.strip()}
        has_files_write = "files:write" in granted_scopes
        can_upload_image = has_files_write and mock_image_path.is_file()
        can_giveup = has_files_write and giveup_image_path.is_file()
        if has_files_write and not mock_image_path.is_file():
            log.warning(
                "files:write granted but %s not found; falling back to emoji",
                mock_image_path,
            )
        if has_files_write and not giveup_image_path.is_file():
            log.warning(
                "files:write granted but %s not found; give-up replies disabled",
                giveup_image_path,
            )
    except SlackApiError as e:
        log.warning("auth.test failed: %s", e.response.get("error"))

    user_name_cache: dict[str, str] = {}

    def display_name(user_id: str) -> str:
        cached = user_name_cache.get(user_id)
        if cached is not None:
            return cached
        name = user_id
        try:
            info = app.client.users_info(user=user_id)
            user = info["user"]
            name = (
                user.get("profile", {}).get("display_name")
                or user.get("profile", {}).get("real_name")
                or user.get("real_name")
                or user.get("name")
                or user_id
            )
        except SlackApiError as e:
            log.warning(
                "users_info failed for %s: %s", user_id, e.response.get("error")
            )
        user_name_cache[user_id] = name
        return name

    def user_label(user_id: str) -> str:
        name = display_name(user_id)
        return f"{name} ({user_id})" if name != user_id else user_id

    def render_mentions(text: str) -> str:
        # Turn <@U…> mentions into literal "@name" text so the mock reply
        # neither pings the target nor echoes a broken, lower-cased user ID.
        def repl(m: re.Match) -> str:
            label = m.group(2)
            return f"@{label}" if label else f"@{display_name(m.group(1))}"

        return MENTION_RE.sub(repl, text)

    log.debug(
        "reaction_pct=%.2f mock_pct=%.2f giveup_pct=%.2f users_overridden=%d "
        "custom_emojis=%d image_upload=%s giveup=%s",
        reaction_percentage,
        mock_percentage,
        giveup_percentage,
        len(users),
        len(custom_emojis),
        can_upload_image,
        can_giveup,
    )
    for uid in sorted(users):
        entry = users[uid]
        log.debug(
            "  user %s: name=%r mock_pct=%s reaction_pct=%s giveup_pct=%s",
            user_label(uid),
            entry.get("name"),
            entry.get("mock_percentage"),
            entry.get("reaction_percentage"),
            entry.get("giveup_percentage"),
        )

    def channel_label(channel_id: str) -> str:
        try:
            info = app.client.conversations_info(channel=channel_id)
            name = info["channel"].get("name")
            if name:
                return f"#{name} ({channel_id})"
        except SlackApiError:
            pass
        return channel_id

    channel_member_cache: dict[str, bool] = {}

    def bot_in_channel(channel_id: str) -> bool:
        cached = channel_member_cache.get(channel_id)
        if cached is not None:
            return cached
        try:
            info = app.client.conversations_info(channel=channel_id)
            is_member = bool(info["channel"].get("is_member"))
        except SlackApiError as e:
            log.warning(
                "conversations_info failed for %s: %s; assuming bot is in channel",
                channel_id,
                e.response.get("error"),
            )
            is_member = True
        channel_member_cache[channel_id] = is_member
        return is_member

    @app.event("message")
    def on_message(event, client, logger):
        user = event.get("user")
        channel_id = event.get("channel")
        ts = event.get("ts")
        subtype = event.get("subtype")
        channel_type = event.get("channel_type")
        if channel_type in ("im", "mpim"):
            return
        if subtype is not None:
            log.debug("skip ts=%s channel=%s: subtype=%s", ts, channel_id, subtype)
            return
        if event.get("bot_id"):
            log.debug(
                "skip ts=%s channel=%s: bot_id=%s app_id=%s",
                ts,
                channel_id,
                event.get("bot_id"),
                event.get("app_id"),
            )
            return
        if not user:
            return
        if not bot_in_channel(channel_id):
            log.debug("skip ts=%s channel=%s: bot not in channel", ts, channel_id)
            return

        text = event.get("text") or ""
        mock_pct = effective_mock_pct(user)
        if mock_pct == 0.0:
            log.debug(
                "skip-mock ts=%s channel=%s user=%s: rate=0", ts, channel_id, user
            )
        else:
            mock_roll = random.random()
            if mock_roll < mock_pct and text.strip():
                mocked_text = alternating_case(render_mentions(text))
                log.info(
                    "mock ts=%s channel=%s user=%s: roll %.3f < %.3f mode=%s",
                    ts,
                    channel_id,
                    user,
                    mock_roll,
                    mock_pct,
                    "image" if can_upload_image else "emoji",
                )
                try:
                    if can_upload_image:
                        client.files_upload_v2(
                            channel=channel_id,
                            thread_ts=ts,
                            file=str(mock_image_path),
                            initial_comment=mocked_text,
                        )
                    else:
                        client.chat_postMessage(
                            channel=channel_id,
                            thread_ts=ts,
                            text=f":spongebob-mock: {mocked_text} :spongebob-mock:",
                        )
                except SlackApiError as e:
                    err = e.response.get("error")
                    if err == "not_in_channel":
                        channel_member_cache.pop(channel_id, None)
                    logger.warning(
                        "mock post failed in %s: %s",
                        channel_label(channel_id),
                        err,
                    )
            else:
                log.debug(
                    "skip-mock ts=%s channel=%s user=%s: roll %.3f >= %.3f",
                    ts,
                    channel_id,
                    user,
                    mock_roll,
                    mock_pct,
                )

        giveup_pct = effective_giveup_pct(user)
        if not can_giveup:
            log.debug(
                "skip-giveup ts=%s channel=%s user=%s: disabled (no files:write or image)",
                ts,
                channel_id,
                user,
            )
        elif giveup_pct == 0.0:
            log.debug(
                "skip-giveup ts=%s channel=%s user=%s: rate=0", ts, channel_id, user
            )
        elif "?" not in text:
            log.debug(
                "skip-giveup ts=%s channel=%s user=%s: no '?' in text",
                ts,
                channel_id,
                user,
            )
        else:
            giveup_roll = random.random()
            if giveup_roll < giveup_pct:
                log.info(
                    "giveup ts=%s channel=%s user=%s: roll %.3f < %.3f",
                    ts,
                    channel_id,
                    user,
                    giveup_roll,
                    giveup_pct,
                )
                try:
                    client.files_upload_v2(
                        channel=channel_id,
                        thread_ts=ts,
                        file=str(giveup_image_path),
                    )
                except SlackApiError as e:
                    err = e.response.get("error")
                    if err == "not_in_channel":
                        channel_member_cache.pop(channel_id, None)
                    logger.warning(
                        "giveup post failed in %s: %s",
                        channel_label(channel_id),
                        err,
                    )
            else:
                log.debug(
                    "skip-giveup ts=%s channel=%s user=%s: roll %.3f >= %.3f",
                    ts,
                    channel_id,
                    user,
                    giveup_roll,
                    giveup_pct,
                )

        reaction_pct = effective_reaction_pct(user)
        if reaction_pct == 0.0:
            log.debug("skip ts=%s channel=%s user=%s: rate=0", ts, channel_id, user)
            return
        roll = random.random()
        if roll >= reaction_pct:
            log.debug(
                "skip ts=%s channel=%s user=%s: roll %.3f >= %.3f",
                ts,
                channel_id,
                user,
                roll,
                reaction_pct,
            )
            return
        log.info(
            "react ts=%s channel=%s user=%s: roll %.3f < %.3f",
            ts,
            channel_id,
            user,
            roll,
            reaction_pct,
        )
        emoji = random.choice(custom_emojis)
        try:
            client.reactions_add(
                channel=channel_id,
                timestamp=ts,
                name=emoji,
            )
            log.info("reacted with :%s: in %s", emoji, channel_label(channel_id))
        except SlackApiError as e:
            err = e.response.get("error")
            if err == "already_reacted":
                return
            logger.warning(
                "reactions_add failed in %s: %s", channel_label(channel_id), err
            )

    log.debug("starting Socket Mode connection")
    SocketModeHandler(app, app_token).start()


if __name__ == "__main__":
    main()
