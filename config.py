import os

API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
BOT_OWNER_ID = int(os.environ.get("BOT_OWNER_ID", "0"))

SESSION_NAME_REPLY = os.environ.get("SESSION_NAME_REPLY", "reply_sync_session")
SESSION_NAME_CHECK = os.environ.get("SESSION_NAME_CHECK", "delete_checker_session")

MAIN_CHANNEL_ID = int(os.environ.get("MAIN_CHANNEL_ID", "0"))
TARGET_CHAT_IDS = list(map(int, os.environ.get("TARGET_CHAT_IDS", "").split(",")))

MAPPING_FILE = os.environ.get("MAPPING_FILE", "post_map.json")
LAST_UPDATE_ID_FILE = os.environ.get("LAST_UPDATE_ID_FILE", "last_update_id.txt")
TEXT_FORWARD_CONFIG = os.environ.get("TEXT_FORWARD_CONFIG", "text_forwarding_enabled.json")
