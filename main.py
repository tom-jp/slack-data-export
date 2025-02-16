import json
import os
import requests
import urllib3
import shutil
from datetime import datetime
from logging import basicConfig, getLogger
from time import sleep
from slack_sdk import WebClient

# このライブラリはうまくインポートできてないみたい
from slack_sdk.errors import SlackApiError

'''
SSL errorを出さないための小細工
'''
import ssl
import certifi
import os
os.environ['CURL_CA_BUNDLE'] = ''

# Cert Warningを出さないための小細工
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 保存フォルダ名に乱数文字を含めるため
import random, string

# windowsのファイル名に使用できない文字を置換するため
import re

from const import Const

# Initialize logger.
basicConfig(format="%(asctime)s %(name)s:%(lineno)s [%(levelname)s]: " +
            "%(message)s (%(funcName)s)")
logger = getLogger(__name__)
logger.setLevel(Const.LOG_LEVEL)


def main():
    logger.info("---- Start Slack Data Export ----")

    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger.info("  - Initializing webclient-")
    client = init_webclient()
    logger.info("  - getting user list-")
    users = get_users(client)
    logger.info("  - getting accessible channels-")
    channels = get_accessible_channels(client, users)

    logger.info("  - saving users -")
    save_users(users, now)
    logger.info("  - saving channels -")
    save_channels(channels, now)

    total_channels = len(channels)

    for index, channel in enumerate(channels, start=1):
        logger.info(f"Processing Channel {index}/{total_channels}: {channel['name']}")
        messages = get_messages(client, channel["id"])
        messages = sort_messages(messages)
        logger.info("  -  saving messages -")
        channel['name'] = shorten_filename(channel["name"])
        #channel["name"] = channel["name"][0:49]+'_'+random_name
        save_messages(messages, channel["name"], now)
        logger.info("  -  saving files -")
        save_files(messages, channel["name"], now)

    archive_data(now)

    logger.info("---- End Slack Data Export ----")

    return None


def init_webclient():
    client = None

    # 証明書エラーを出さないための小細工
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    if Const.USE_USER_TOKEN:
        logger.info("Use USER TOKEN")
        client = WebClient(token=Const.USER_TOKEN,ssl=ssl_context)
    else:
        logger.info("Use BOT TOKEN")
        client = WebClient(token=Const.BOT_TOKEN,ssl=ssl_context)

    return client


def get_users(client):
    users = []

    try:
        logger.debug("Call users_list (Slack API)")
        users = client.users_list()["members"]
        logger.debug(users)
        sleep(Const.ACCESS_WAIT)

    except SlackApiError as e:
        logger.error(e)
        sleep(Const.ACCESS_WAIT)

    return users


def get_accessible_channels(client, users):
    channels = []
    channels_raw = []
    cursor = None

    try:
        while True:
            logger.debug("Call conversations_list (Slack API)")
            conversations_list = client.conversations_list(
                types=Const.CHANNEL_TYPES,
                cursor=cursor,
                limit=200)
            logger.debug(conversations_list)

            channels_raw.extend(conversations_list["channels"])
            sleep(Const.ACCESS_WAIT)

            cursor = fetch_next_cursor(conversations_list)
            if not cursor:
                break
            else:
                logger.debug("  next cursor: " + cursor)

        # In the case a im (Direct Messages), "name" dose't exist in "channel",
        # so takes and appends "real_name" from users_list as "name".
        # And append "@" to the beginning of "name" in the case a im, to
        # distinguish from channel names.
        channels = [{
            **x,
            **{
                "name": "@" + next(
                (y.get("real_name", "Unknown") for y in users if y["id"] == x["user"]),
                "Unknown")
            }
        } if x["is_im"] else x for x in channels_raw]

    except SlackApiError as e:
        logger.error(e)
        sleep(Const.ACCESS_WAIT)

    return channels


def save_users(users, now):
    export_path = os.path.join(*[Const.EXPORT_BASE_PATH, now])
    os.makedirs(export_path, exist_ok=True)

    logger.info("Save Users")
    logger.debug("users export path : " + export_path)

    file_path = os.path.join(*[export_path, "users.json"])
    with open(file_path, mode="wt", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

    return None


def save_channels(channels, now):
    export_path = os.path.join(*[Const.EXPORT_BASE_PATH, now])
    os.makedirs(export_path, exist_ok=True)

    logger.info("Save Channels")
    logger.debug("channels export path : " + export_path)

    file_path = os.path.join(*[export_path, "channels.json"])
    with open(file_path, mode="wt", encoding="utf-8") as f:
        json.dump(channels, f, ensure_ascii=False, indent=2)

    return None


def get_messages(client, channel_id):
    messages = []
    cursor = None

    try:
        logger.info("Get Messages of " + channel_id)

        # Stores channel's messages (other than thread's).
        while True:
            logger.debug("Call conversations_history (Slack API)")
            conversations_history = client.conversations_history(
                channel=channel_id, cursor=cursor, limit=200)
            logger.debug(conversations_history)

            messages.extend(conversations_history["messages"])
            sleep(Const.ACCESS_WAIT)

            cursor = fetch_next_cursor(conversations_history)
            if not cursor:
                break
            else:
                logger.debug("  next cursor: " + cursor)

        # Stores thread's messages.
        # Extracts messages whose has "thread_ts" is equal to "ts".
        for parent_message in (
                x for x in messages
                if "thread_ts" in x and x["thread_ts"] == x["ts"]):

            while True:
                logger.debug("Call conversations_replies (Slack API): " +
                             parent_message["ts"])
                conversations_replies = client.conversations_replies(
                    channel=channel_id,
                    ts=parent_message["thread_ts"],
                    cursor=cursor,
                    limit=200,
                )
                logger.debug(conversations_replies)

                # Since parent messages are also returned, excepts them.
                messages.extend([
                    x for x in conversations_replies["messages"]
                    if x["ts"] != x["thread_ts"]
                ])
                sleep(Const.ACCESS_WAIT)

                cursor = fetch_next_cursor(conversations_history)
                if not cursor:
                    break
                else:
                    logger.debug("  next cursor: " + cursor)

    except SlackApiError as e:
        logger.error(e)
        sleep(Const.ACCESS_WAIT)

    return messages


def fetch_next_cursor(api_response):
    if ("response_metadata" in api_response
            and "next_cursor" in api_response["response_metadata"]
            and api_response["response_metadata"]["next_cursor"]):

        return api_response["response_metadata"]["next_cursor"]
    else:
        return None


def sort_messages(org_messages):
    sort_messages = sorted(org_messages, key=lambda x: x["ts"])
    return sort_messages


def save_messages(messages, channel_name, now):
    export_path = os.path.join(*[Const.EXPORT_BASE_PATH, now, channel_name])
    os.makedirs(export_path)

    logger.info("Save Messages of " + channel_name)
    logger.debug("messages export path : " + export_path)

    if Const.SPLIT_MESSAGE_FILES:
        # Get a list of timestamps (Format YY-MM-DD) by excluding duplicate
        # timestamps in messages.
        for day_ts in {
                format_ts(x["ts"]): format_ts(x["ts"])
                for x in messages
        }.values():
            # Extract messages of "day_ts".
            day_messages = [
                x for x in messages if format_ts(x["ts"]) == day_ts
            ]

            file_path = os.path.join(
                *[export_path, "".join([day_ts, ".json"])])
            with open(file_path, mode="at", encoding="utf-8") as f:
                json.dump(day_messages, f, ensure_ascii=False, indent=2)
    else:
        file_path = os.path.join(*[export_path, "messages.json"])
        with open(file_path, mode="wt", encoding="utf-8") as f:
            json.dump(messages, f, ensure_ascii=False, indent=2)

    return None


def format_ts(unix_time_str):
    return datetime.fromtimestamp(float(unix_time_str)).strftime("%Y-%m-%d")

# Windowsでファイル名に使用できない文字を変換するためのテーブル。但し / と \ は除く。
INVALID_CHAR_MAP = {
    '<': '＜', '>': '＞', ':': '：', '"': '”',
    '|': '｜', '?': '？', '*': '＊'
}


def sanitize_filename(filename):
    """ファイル名に使用できない文字を全角に置換する"""
    return re.sub(r'[<>:"/\\|?*]', lambda x: INVALID_CHAR_MAP[x.group()], filename)

def shorten_filename(filename, max_length=50, random_length=10):
    """長いファイル名を max_length + ランダム random_length に短縮し、拡張子を保持"""
    name, ext = os.path.splitext(filename)  # 拡張子を分離
    
    if len(name) > max_length:  # ファイル名が50文字以上の場合
        random_suffix = ''.join(random.choices(string.ascii_letters + string.digits, k=random_length))  # ランダム10文字
        name = name[:max_length] + "_" + random_suffix  # 50文字 + "_" + ランダム10文字
    
    return name + ext  # 拡張子をつけて戻す

def save_files(messages, channel_name, now):
    export_path = os.path.join(
        *[Const.EXPORT_BASE_PATH, now, channel_name, "files"])
    os.makedirs(export_path)

    logger.info("Save Files of " + channel_name)
    logger.debug("files export path : " + export_path)

    token = Const.USER_TOKEN if Const.USE_USER_TOKEN else Const.BOT_TOKEN

    for files in (x["files"] for x in messages if "files" in x):
        # Downloads files except deleted.
        for fi in (x for x in files if x["mode"] != "tombstone"):
            logger.debug("  * Download " + fi["name"])

            try:
                response = requests.get(
                    fi["url_private"],
                    headers={"Authorization": "Bearer " + token},
                    timeout=(Const.REQUESTS_CONNECT_TIMEOUT,
                             Const.REQUESTS_READ_TIMEOUT),verify=False)
                sleep(Const.ACCESS_WAIT)

                # If the token's scope doesn't include "files:read", this
                # request should be redirected.
                if len(response.history) != 0:
                    logger.warning("File downloads may fail.")
                    logger.warning(
                        "Check if the list of scopes includes 'files:read'.")

                # NOTE: Content-Type is often set to "binary/octet-stream"
                #       regardless of the file type, so don't "continues" even
                #       if Content-Type and mimetype mismatch.
                # if fi["mimetype"] != response.headers["Content-Type"]:
                #     logger.debug("        mimetype    : " + fi["mimetype"])
                #     logger.debug("        content-type: " +
                #                  response.headers["Content-Type"])
                #     continue

                sanitized_file_name = shorten_filename(sanitize_filename(fi["id"] + "_" + fi["name"]))
                file_path = os.path.join(export_path,sanitized_file_name)

                with open(file_path, mode="wb") as f:
                    f.write(response.content)

            except (requests.exceptions.Timeout,
                    requests.exceptions.RequestException) as e:
                logger.error(e)
                logger.error("url_private : " + fi["url_private"])
                sleep(Const.ACCESS_WAIT)

    return None


def archive_data(now):
    root_path = os.path.join(*[Const.EXPORT_BASE_PATH, now])

    logger.info("Archive data")

    shutil.make_archive(root_path, format='zip', root_dir=root_path)
    shutil.rmtree(root_path)

    return None


if __name__ == "__main__":
    main()
