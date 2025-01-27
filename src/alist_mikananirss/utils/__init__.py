from collections import OrderedDict

from .tmdb import TMDBClient


class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]

    def destroy_instance(cls):
        if cls in cls._instances:
            cls._instances.pop(cls)


class FixedSizeSet:
    def __init__(self, maxsize=10000):
        self.maxsize = maxsize
        self._set = OrderedDict()

    def add(self, item):
        self._set[item] = None
        if len(self._set) > self.maxsize:
            self._set.popitem(last=False)

    def __contains__(self, item):
        return item in self._set


def is_video(s: str) -> bool:
    return s.lower().endswith((".mp4", ".mkv", ".avi", ".rmvb", ".wmv", ".flv"))
