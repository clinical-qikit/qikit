"""MkDocs hook: build guide pages from README sections, so the README stays the one copy.

A page line of the form

    <!-- readme: Across providers -->

is replaced by the README section whose heading starts with that text, up to the next
heading of the same or a higher level. The section's own heading is dropped (the page
has its title) and its subheadings move up so the first level under it becomes ##.
``<!-- readme: intro -->`` is the text between the title and the first ## heading, and
``<!-- file: CHANGELOG.md -->`` is a whole file from the repository root. A README line
ending in ``<!-- github-only -->`` (the link to this site) is left out.

Links in included text are written for GitHub, relative to the repository root. They
are rewritten for the site: docs/X.md becomes a site page, CHANGELOG.md the changelog
page, and anything else in the repository a link to it on GitHub.
"""

from __future__ import annotations

import posixpath
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GITHUB = "https://github.com/clinical-qikit/qikit/blob/main/"
DIRECTIVE = re.compile(r"^<!--\s*(readme|file):\s*(.+?)\s*-->[ \t]*$", re.MULTILINE)
LINK = re.compile(r"\[([^\]]*)\]\(([^)\s#]+)(#[^)\s]*)?\)")
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
FENCE = re.compile(r"^\s*(```|~~~)")


def _headings(lines: list[str]) -> list[tuple[int, int, str]]:
    """(line index, level, text) of each heading outside fenced code."""
    out, fenced = [], False
    for i, line in enumerate(lines):
        if FENCE.match(line):
            fenced = not fenced
            continue
        m = None if fenced else HEADING.match(line)
        if m:
            out.append((i, len(m.group(1)), m.group(2).strip()))
    return out


def readme_section(name: str, text: str) -> str:
    lines = text.splitlines()
    heads = _headings(lines)
    if name == "intro":
        start = heads[0][0] + 1 if heads and heads[0][1] == 1 else 0
        end = next((i for i, lvl, _ in heads if lvl == 2), len(lines))
        return "\n".join(lines[start:end]).strip()
    for k, (i, level, title) in enumerate(heads):
        if title.startswith(name):
            end = next((j for j, lvl, _ in heads[k + 1:] if lvl <= level), len(lines))
            body = lines[i + 1:end]
            shift = level - 1
            nested = {j - i - 1 for j, _, _ in heads[k + 1:] if j < end}
            for j in nested:
                body[j] = body[j][shift:]
            return "\n".join(body).strip()
    raise ValueError(f"no README heading starts with {name!r}")


def _title(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.name


def rewrite_links(text: str, docs_pages: set[str], page: str = "index.md") -> str:
    here = posixpath.dirname(page) or "."

    def rel(target: str) -> str:
        return posixpath.relpath(target, here)

    def fix(m: re.Match[str]) -> str:
        label, target, anchor = m.group(1), m.group(2), m.group(3) or ""
        if "://" in target or target.startswith("mailto:"):
            return m.group(0)
        if target.startswith("docs/") and target[5:] in docs_pages:
            if label == target:  # a bare path reads as the page's title on the site
                label = _title(ROOT / target)
            return f"[{label}]({rel(target[5:])}{anchor})"
        if target == "CHANGELOG.md":
            return f"[{label}]({rel('changelog.md')}{anchor})"
        kind = "tree/main/" if (ROOT / target).is_dir() else "blob/main/"
        return f"[{label}]({GITHUB.replace('blob/main/', kind)}{target}{anchor})"

    return LINK.sub(fix, text)


def _drop_github_only(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if not ln.rstrip().endswith("<!-- github-only -->"))


def expand(markdown: str, docs_pages: set[str], page: str = "index.md") -> str:
    def replace(m: re.Match[str]) -> str:
        kind, arg = m.group(1), m.group(2)
        if kind == "readme":
            body = readme_section(arg, (ROOT / "README.md").read_text(encoding="utf-8"))
        else:
            body = (ROOT / arg).read_text(encoding="utf-8")
        return rewrite_links(_drop_github_only(body), docs_pages, page)

    return DIRECTIVE.sub(replace, markdown)


def on_page_markdown(markdown, page, config, files):  # noqa: ARG001  (MkDocs hook)
    if "<!--" not in markdown:
        return markdown
    pages = {f.src_uri for f in files.documentation_pages()}
    return expand(markdown, pages, page.file.src_uri)
