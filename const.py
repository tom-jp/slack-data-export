import logging
import os


class ConstMeta(type):

    def __setattr__(self, name, value):
        if name in self.__dict__:
            raise TypeError(f"Can't rebind const ({name})")
        else:
            self.__setattr__(name, value)


class Const(metaclass=ConstMeta):
    # Slack App OAuth Tokens
    USER_TOKEN = os.environ["SLACK_USER_TOKEN"] # Get USER_TOKEN from OS Environment Variable
#    USER_TOKEN = "xoxp-xxxxxx"  # Your User Token
#    BOT_TOKEN = "xoxb-xxxxxx"  # Your Bot Token

    CHANNEL_TYPES = "im" # public_channel,private_channel,mpim,im
    # Wait time (sec) for an API call or a file download.
    # If change this value, check the rate limits of Slack APIs.
    ACCESS_WAIT = 1.2
    # Export Directory path.
    EXPORT_BASE_PATH = "./export"
    # Logging level for the logging module.
    LOG_LEVEL = logging.INFO
    # Connect and read timeouts (sec) for the requests module.
    REQUESTS_CONNECT_TIMEOUT = 3.05
    REQUESTS_READ_TIMEOUT = 60
    # Whether or not to use the User Token.
    USE_USER_TOKEN = True
    # Whether or not.to split message files by day.
    # If split, message files are saved in a format similar to official
    # functions.
    SPLIT_MESSAGE_FILES = True
