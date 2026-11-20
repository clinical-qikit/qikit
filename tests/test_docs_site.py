"""The documentation site's README hook (scripts/mkdocs_hooks.py)."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("mkdocs_hooks", ROOT / "scripts" / "mkdocs_hooks.py")
assert spec and spec.loader
hooks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hooks)


def test_every_guide_directive_finds_its_readme_section():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    pages = [p for p in (ROOT / "docs").rglob("*.md") if "archive" not in p.parts]
    names = [m.group(2) for p in pages for m in hooks.DIRECTIVE.finditer(p.read_text()) if m.group(1) == "readme"]
    assert names
    for name in names:
        assert hooks.readme_section(name, readme).strip(), name


def test_section_ignores_comments_in_code_and_promotes_subheadings():
    text = "# T\n\nintro\n\n## A\n\n```python\n# not a heading\n```\n\n### Sub\n\nbody\n\n## B\n\nother\n"
    section = hooks.readme_section("A", text)
    assert "# not a heading" in section and "## Sub" in section and "### Sub" not in section
    assert "other" not in section
    assert hooks.readme_section("intro", text) == "intro"


def test_links_point_at_site_pages_or_github():
    pages = {"methods.md"}
    out = hooks.rewrite_links(
        "[docs/methods.md](docs/methods.md) [§4](docs/methods.md#x) [log](CHANGELOG.md) "
        "[a](src/qikit/AGENTS.md) [w](https://e.org)",
        pages,
        "guide/funnel.md",
    )
    assert "[Methods: funnel plots and over-dispersion](../methods.md)" in out
    assert "[§4](../methods.md#x)" in out
    assert "[log](../changelog.md)" in out
    assert "[a](https://github.com/clinical-qikit/qikit/blob/main/src/qikit/AGENTS.md)" in out
    assert "[w](https://e.org)" in out
