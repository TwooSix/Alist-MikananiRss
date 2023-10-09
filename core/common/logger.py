import logging
import os
import time


class Log(object):
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    stream_handler: logging.StreamHandler = None
    file_handler: logging.StreamHandler = None

    @staticmethod
    def update_level(level: str):
        if level == "DEBUG":
            Log.stream_handler.setLevel(logging.DEBUG)
            Log.file_handler.setLevel(logging.DEBUG)
        elif level == "INFO":
            Log.stream_handler.setLevel(logging.INFO)
            Log.file_handler.setLevel(logging.INFO)
        elif level == "WARN":
            Log.stream_handler.setLevel(logging.WARN)
            Log.file_handler.setLevel(logging.WARN)
        elif level == "ERROR":
            Log.stream_handler.setLevel(logging.ERROR)
            Log.file_handler.setLevel(logging.ERROR)
        elif level == "CRITICAL":
            Log.stream_handler.setLevel(logging.CRITICAL)
            Log.file_handler.setLevel(logging.CRITICAL)
        else:
            Log.error(f"Unknown logging level: {level}")

    @staticmethod
    def init():
        formatter = logging.Formatter(
            "%(asctime)s - %(filename)s[line:%(lineno)d] - %(levelname)s: %(message)s"
        )
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(logging.DEBUG)
        stream_handler.setFormatter(formatter)
        Log.stream_handler = stream_handler
        Log.logger.addHandler(stream_handler)

        log_path = os.path.join(os.getcwd(), "log")
        if not os.path.isdir(log_path):
            os.makedirs(log_path)
        day_time = time.strftime("%Y%m%d", time.localtime(time.time()))
        log_filename = os.path.join(log_path, day_time + ".log")
        file_handler = logging.FileHandler(log_filename, mode="a", encoding="utf-8")
        Log.file_handler = file_handler
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        Log.logger.addHandler(file_handler)

        Log.debug = Log.logger.debug
        Log.info = Log.logger.info
        Log.warn = Log.logger.warning
        Log.error = Log.logger.error
        return

    @staticmethod
    def debug(es):
        Log.logger.debug(es)

    @staticmethod
    def info(es):
        Log.logger.info(es, exc_info=True)

    @staticmethod
    def warn(es):
        Log.logger.warning(es, exc_info=True)

    @staticmethod
    def error(es):
        Log.logger.error(es, exc_info=True)
