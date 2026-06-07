from __future__ import annotations

import re


CONTROL_CHARS_EXCEPT_TAB = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")


def sanitize_control_chars(value: object) -> str:
    return CONTROL_CHARS_EXCEPT_TAB.sub("", str(value))
