import re


class RegexFilter:
    def __init__(self, regex_patterns: list = None):
        self.patterns = regex_patterns if regex_patterns else []

    def add_pattern(self, pattern: str) -> None:
        """Add regex pattern to filter"""
        self.patterns.append(pattern)

    def filt_single(self, string) -> bool:
        """Filter single string using regex"""
        match_result = True
        for pattern in self.patterns:
            match_result = match_result and re.search(pattern, string)
        return match_result

    def filt_list(self, string_list: list[str]) -> list[int]:
        """Filter list of string using regex

        Args:
            string_list (list[str]): list of string to be filtered

        Returns:
            list[int]: index of string that match the regex pattern
        """
        return [i for i, string in enumerate(string_list) if self.filt_single(string)]
