"""Terminal output that survives a non-UTF-8 console.

Windows consoles still default to a legacy code page, so printing a case note containing an
en dash raises ``UnicodeEncodeError`` on a machine that is otherwise working fine. That is a
miserable first impression for someone who has just cloned the project, and it is entirely
avoidable.

Two layers of defence, because either alone is insufficient:

* Rule rationales and stage rationales are held to ASCII, enforced by a test. They are the
  strings printed most often, and degrading a dash is a smaller cost than a crash.
* Everything else, case notes, docstrings, this project's own prose, keeps real typography,
  and the output stream is reconfigured to UTF-8 with replacement so it cannot fail.
"""

from __future__ import annotations

import sys
from io import TextIOBase


def configure_stdout() -> None:
    """Make stdout and stderr UTF-8 tolerant. Safe to call more than once."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            # A stream that refuses reconfiguration (a pipe already in binary mode, a
            # captured buffer under test) is not a reason to fail.
            continue


def supports_unicode(stream: TextIOBase | None = None) -> bool:
    """Whether a stream can represent the box-drawing characters used in trees."""
    target = stream or sys.stdout
    encoding = getattr(target, "encoding", None) or "ascii"
    try:
        "─│└".encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True
