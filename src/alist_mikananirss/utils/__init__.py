from .tmdb import TMDBClient


class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]


def is_video(s: str) -> bool:
    return s.lower().endswith((".mp4", ".mkv", ".avi", ".rmvb", ".wmv", ".flv"))
