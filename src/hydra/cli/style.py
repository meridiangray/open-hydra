"""style.py — how hydra-ctl prints a command's result, its warnings and its errors.

One line, git style, saying what happened:

    Initialized empty Hydra archive in /home/me/cases/htest
    Built htest: 244 records, 227 entities, 54 open questions (0.4s)
    hydra: no row 'nope' in the last build

In a terminal the verb is bold green, names bold, paths cyan, asides dim;
`hydra:` is red on errors and yellow on warnings. Plain text when the stream is
not a terminal, when NO_COLOR is set or TERM is dumb; FORCE_COLOR turns it on.

Data views (tree, claims, node find, sources, todo) use the same few, and only
for color: record names bold, types, tree lines and asides dim, positions,
relationship labels, property names and links cyan, what moved or disagrees
yellow, headers bold. Without color their text is exactly the same."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _on(stream) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return bool(getattr(stream, "isatty", None) and stream.isatty()) and os.environ.get("TERM") != "dumb"


def _sgr(code: str, text, stream) -> str:
    return f"\033[{code}m{text}\033[0m" if str(text) and _on(stream) else str(text)


def verb(text: str, stream=None) -> str:
    return _sgr("1;32", text, stream or sys.stdout)


def name(text, stream=None) -> str:
    return _sgr("1", text, stream or sys.stdout)


def path(p, stream=None) -> str:
    return _sgr("36", Path(p).resolve(), stream or sys.stdout)


def aside(text: str, stream=None) -> str:
    return _sgr("2", text, stream or sys.stdout)


def accent(text, stream=None) -> str:
    """Cyan: a position, a relationship label, a property name, a link."""
    return _sgr("36", text, stream or sys.stdout)


def note(text, stream=None) -> str:
    """Yellow: what moved, or disagrees."""
    return _sgr("33", text, stream or sys.stdout)


def styled(parts, stream=None) -> str:
    """[(text, kind)] -> one string; kind is name, aside, accent, note or "" (plain)."""
    fn = {"name": name, "aside": aside, "accent": accent, "note": note}
    return "".join(fn[k](t, stream) if k in fn and t else str(t) for t, k in parts)


def across(header: list[str], values: list[str], stream=None) -> list[str]:
    """One row of values under its header (numbers right-aligned): the counts
    a command ends with, e.g. under `Exported …`."""
    w = [max(len(h), len(v)) for h, v in zip(header, values)]
    num = lambda v: v.replace(",", "").replace(".", "").isdigit()
    cell = lambda xs: "  " + "   ".join(f"{x:>{w[i]}}" if num(values[i]) else f"{x:<{w[i]}}" for i, x in enumerate(xs))
    return [aside(cell(header).rstrip(), stream), cell(values).rstrip()]


def plural(n: int, word: str, many: str = "") -> str:
    return f"{n:,} {word if n == 1 else many or word + 's'}"


def warn(msg: str) -> None:
    print(f"{_sgr('1;33', 'hydra:', sys.stderr)} {msg}", file=sys.stderr)


def error(msg: str) -> None:
    print(f"{_sgr('1;31', 'hydra:', sys.stderr)} {msg}", file=sys.stderr)


def usage(text: str):
    """A command used wrongly: its usage on stderr, exit status 2 (as argparse does)."""
    print(text, file=sys.stderr)
    raise SystemExit(2)
