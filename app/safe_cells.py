import re

_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")
_NUMBER = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")


def cell(value):
    if isinstance(value, str) and value.startswith(_TRIGGERS) and not _NUMBER.match(value):
        return "'" + value
    return value


def row(values):
    return [cell(v) for v in values]
