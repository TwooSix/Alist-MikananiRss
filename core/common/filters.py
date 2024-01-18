import re


class RegexFilter:
    def __init__(self, patterns: list = None):
        self.patterns = []
        if patterns is not None:
            for pattern in patterns:
                self.add_pattern(pattern)

    def add_pattern(self, tmp_pattern: str) -> None:
        """Add regex pattern to filter"""
        pattern = re.compile(tmp_pattern, re.IGNORECASE)
        self.patterns.append(pattern)

    def filt_single(self, string) -> bool:
        """Filter single string using regex"""
        match_result = True
        for pattern in self.patterns:
            match_result = match_result and bool(re.search(pattern, string))
        return match_result

    def filt_list(self, string_list: list[str]) -> list[int]:
        """Filter list of string using regex

        Args:
            string_list (list[str]): list of string to be filtered

        Returns:
            list[int]: index of string that match the regex pattern
        """
        return [i for i, string in enumerate(string_list) if self.filt_single(string)]
