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
    pct = cfg.get("reaction_percentage")
    if pct is None or not (0.0 <= float(pct) <= 1.0):
        sys.exit("config.yaml reaction_percentage must be between 0.0 and 1.0")
    return cfg


def parse_target_user_ids(raw: str | None) -> set[str]:
    if not raw:
        sys.exit("TARGET_USER_IDS must be set in .env as a comma-separated list (see .env.example)")
    ids = {part.strip() for part in raw.split(",") if part.strip()}
    if not ids:
        sys.exit("TARGET_USER_IDS must contain at least one Slack member ID")
    return ids


def main() -> None:
    load_dotenv()
    bot_token = os.environ.get("SLACK_BOT_TOKEN")
    app_token = os.environ.get("SLACK_APP_TOKEN")
    if not bot_token or not app_token:
        sys.exit("SLACK_BOT_TOKEN and SLACK_APP_TOKEN must be set (see .env.example)")

    target_user_ids = parse_target_user_ids(os.environ.get("TARGET_USER_IDS"))
    cfg = load_config(Path(__file__).parent / "config.yaml")
    reaction_percentage: float = float(cfg["reaction_percentage"])

    app = App(token=bot_token)

    emoji_resp = app.client.emoji_list()
    custom_emojis: list[str] = list(emoji_resp.get("emoji", {}).keys())
    if not custom_emojis:
        sys.exit("workspace has no custom emojis to react with")

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
    log.info(
        "targets=%s percentage=%.2f custom_emojis=%d",
        targets_labeled, reaction_percentage, len(custom_emojis),
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

    @app.event("message")
    def on_message(event, client, logger):
        user = event.get("user")
        channel_id = event.get("channel")
        ts = event.get("ts")
        subtype = event.get("subtype")
        if subtype is not None:
            log.info("skip ts=%s channel=%s: subtype=%s", ts, channel_id, subtype)
            return
        if user not in target_user_ids:
            log.info("skip ts=%s channel=%s user=%s: not a target", ts, channel_id, user)
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
