import logging
import os
import random
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
    for key in ("reaction_percentage", "mock_percentage"):
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


def parse_target_user_ids(raw: str | None) -> set[str]:
    if not raw:
        sys.exit("TARGET_USER_IDS must be set in .env as a comma-separated list (see .env.example)")
    ids = {part.strip() for part in raw.split(",") if part.strip()}
    if not ids:
        sys.exit("TARGET_USER_IDS must contain at least one Slack member ID")
    return ids


def parse_blocked_user_ids(raw: str | None) -> set[str]:
    if not raw:
        return set()
    return {part.strip() for part in raw.split(",") if part.strip()}


def main() -> None:
    load_dotenv()
    bot_token = os.environ.get("SLACK_BOT_TOKEN")
    app_token = os.environ.get("SLACK_APP_TOKEN")
    if not bot_token or not app_token:
        sys.exit("SLACK_BOT_TOKEN and SLACK_APP_TOKEN must be set (see .env.example)")

    target_user_ids = parse_target_user_ids(os.environ.get("TARGET_USER_IDS"))
    blocked_user_ids = parse_blocked_user_ids(os.environ.get("BLOCKED_USER_IDS"))
    cfg = load_config(Path(__file__).parent / "config.yaml")
    reaction_percentage: float = float(cfg["reaction_percentage"])
    mock_percentage: float = float(cfg["mock_percentage"])

    app = App(token=bot_token)

    emoji_resp = app.client.emoji_list()
    custom_emojis: list[str] = list(emoji_resp.get("emoji", {}).keys())
    if not custom_emojis:
        sys.exit("workspace has no custom emojis to react with")

    mock_image_path = Path(__file__).parent / "spongebob-mock.jpg"
    can_upload_image = False
    try:
        auth_resp = app.client.auth_test()
        scopes_header = auth_resp.headers.get("x-oauth-scopes", "")
        granted_scopes = {s.strip() for s in scopes_header.split(",") if s.strip()}
        can_upload_image = "files:write" in granted_scopes and mock_image_path.is_file()
        if "files:write" in granted_scopes and not mock_image_path.is_file():
            log.warning("files:write granted but %s not found; falling back to emoji", mock_image_path)
    except SlackApiError as e:
        log.warning("auth.test failed: %s", e.response.get("error"))

    def user_label(user_id: str) -> str:
        try:
            info = app.client.users_info(user=user_id)
            user = info["user"]
            name = (
                user.get("profile", {}).get("display_name")
                or user.get("profile", {}).get("real_name")
                or user.get("real_name")
                or user.get("name")
            )
            if name:
                return f"{name} ({user_id})"
        except SlackApiError as e:
            log.warning("users_info failed for %s: %s", user_id, e.response.get("error"))
        return user_id

    targets_labeled = [user_label(uid) for uid in sorted(target_user_ids)]
    blocked_labeled = [user_label(uid) for uid in sorted(blocked_user_ids)]
    log.info(
        "targets=%s blocked=%s reaction_pct=%.2f mock_pct=%.2f custom_emojis=%d image_upload=%s",
        targets_labeled, blocked_labeled, reaction_percentage, mock_percentage, len(custom_emojis), can_upload_image,
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
            log.warning("conversations_info failed for %s: %s", channel_id, e.response.get("error"))
            return False
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
            log.info("skip ts=%s channel=%s: subtype=%s", ts, channel_id, subtype)
            return
        if event.get("bot_id"):
            log.info(
                "skip ts=%s channel=%s: bot_id=%s app_id=%s",
                ts, channel_id, event.get("bot_id"), event.get("app_id"),
            )
            return
        if not user:
            return

        text = event.get("text") or ""
        if user in blocked_user_ids:
            log.info("skip-mock ts=%s channel=%s user=%s: blocked", ts, channel_id, user)
        elif not bot_in_channel(channel_id):
            log.info("skip-mock ts=%s channel=%s: bot not in channel", ts, channel_id)
        else:
            mock_roll = random.random()
            if mock_roll < mock_percentage and text.strip():
                mocked_text = alternating_case(text)
                log.info(
                    "mock ts=%s channel=%s user=%s: roll %.3f < %.3f mode=%s",
                    ts, channel_id, user, mock_roll, mock_percentage,
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
                            text=f"{mocked_text} :spongebob-mock:",
                        )
                except SlackApiError as e:
                    err = e.response.get("error")
                    if err == "not_in_channel":
                        channel_member_cache.pop(channel_id, None)
                    logger.warning(
                        "mock post failed in %s: %s",
                        channel_label(channel_id), err,
                    )
            else:
                log.info(
                    "skip-mock ts=%s channel=%s user=%s: roll %.3f >= %.3f",
                    ts, channel_id, user, mock_roll, mock_percentage,
                )

        if user not in target_user_ids:
            return
        roll = random.random()
        if roll >= reaction_percentage:
            log.info(
                "skip ts=%s channel=%s user=%s: roll %.3f >= %.3f",
                ts, channel_id, user, roll, reaction_percentage,
            )
            return
        log.info(
            "react ts=%s channel=%s user=%s: roll %.3f < %.3f",
            ts, channel_id, user, roll, reaction_percentage,
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
            logger.warning("reactions_add failed in %s: %s", channel_label(channel_id), err)

    log.info("starting Socket Mode connection")
    SocketModeHandler(app, app_token).start()


if __name__ == "__main__":
    main()
