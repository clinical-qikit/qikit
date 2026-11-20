"""Griffe extension: turn qikit's plain-text docstrings into Markdown for the API pages.

The docstrings are written for help(): headings underlined with dashes and arguments as
``name : description`` with indented continuation lines. A numpy parser would read
each description as a type, so instead the docstring is rewritten as Markdown and
rendered as text (docstring_style is left unset in mkdocs.yml):

- an underlined heading becomes a level-4 heading;
- ``name : description`` at the start of a line becomes a list item, and its indented
  continuation lines stay with it.

Pipe tables and everything else pass through.
"""

from __future__ import annotations

import re

import griffe

UNDERLINE = re.compile(r"^-{3,}\s*$")
ENTRY = re.compile(r"^([A-Za-z_*][\w*, ]{0,40}?)\s+:\s+(.*)$")


def to_markdown(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    in_list = False
    fenced = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        if fenced:
            out.append(line)
            i += 1
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if line.strip() and "|" not in line and UNDERLINE.match(nxt):
            out += ["", f"#### {line.strip()}", ""]
            in_list = False
            i += 2
            continue
        m = ENTRY.match(line)
        if m:
            if not in_list:
                out.append("")
            names = ", ".join(f"`{n.strip()}`" for n in m.group(1).split(","))
            out.append(f"- {names}: {m.group(2)}")
            in_list = True
        elif in_list and line.startswith(" ") and line.strip():
            out.append("  " + line.strip())
        else:
            if in_list and line.strip():
                out.append("")
            in_list = False
            out.append(line)
        i += 1
    return "\n".join(out)


class QikitDocstrings(griffe.Extension):
    def on_instance(self, *, obj: griffe.Object, **kwargs: object) -> None:  # noqa: ARG002
        if obj.docstring is not None:
            obj.docstring.value = to_markdown(obj.docstring.value)
