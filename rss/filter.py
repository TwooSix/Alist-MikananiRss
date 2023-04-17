import config


class Filter:
    __filter = config.rssFilter

    def __init__(self) -> None:
        pass

    @staticmethod
    def addFilter(name: str, regex):
        Filter.__filter[name] = regex

    @staticmethod
    def getFilter(name: str):
        return Filter.__filter[name]
