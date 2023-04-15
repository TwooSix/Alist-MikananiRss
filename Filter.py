
Filter = {
    '简体': r'(简体)|(简中)|(简日)|(CHS)',
    '繁体': r'(繁体)|(繁中)|(繁日)|(CHT)',
    '1080': r'(1080[pP])',
    '非合集': r'^((?!合集).)*$'
}

def addFilter(self, name:str, regex):
    Filter[name] = regex
