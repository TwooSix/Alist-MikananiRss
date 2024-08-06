import re


class RegexFilter:
    _default_patterns = {
        "简体": r"(简体|简中|简日|CHS)",
        "繁体": r"(繁体|繁中|繁日|CHT|Baha)",
        "1080p": r"(X1080|1080P)",
        "非合集": r"^(?!.*(\d{2}-\d{2}|合集)).*",
    }

    def __init__(self, patterns_name: list = None):
        self.patterns = []
        if patterns_name is not None:
            for pattern in patterns_name:
                self.add_pattern(pattern)

    def update_regex(self, regex_pattern: dict) -> None:
        if regex_pattern is not None:
            self._default_patterns.update(regex_pattern)

    def add_pattern(self, pattern_name: str) -> None:
        """Add regex pattern to filter"""
        try:
            tmp_pattern = self._default_patterns[pattern_name]
        except KeyError:
            raise KeyError(f"Can't find the filter <{pattern_name}>")
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
