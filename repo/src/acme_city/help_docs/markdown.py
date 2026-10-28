"""A small Markdown renderer that cannot pass raw HTML through.

Every character of the source is escaped before any markup is added, so a
``<script>`` tag in a document appears as visible text.  The renderer adds only
a fixed set of tags: headings, paragraphs, lists, tables, block quotes, code,
emphasis and links.  A link keeps its address only when it is an ``http`` or
``https`` address; any other target (a relative path, ``javascript:``, ``data:``)
is shown as plain text.
"""
# REQUIRES: SEC-01
# Rendered documents are escaped text with a fixed set of tags; no script runs.

from __future__ import annotations

import html
import re

#: Documents larger than this are cut, with a plain notice.
MAX_CHARS = 1_000_000

_FENCE = re.compile(r"^\s*(```|~~~)\s*([A-Za-z0-9_+-]*)\s*$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_RULE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_ITEM = re.compile(r"^(\s*)([-*+]|\d{1,3}[.)])\s+(.*)$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")
_CODE = re.compile(r"`([^`\n]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])")
_LINK = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)")
_AUTOLINK = re.compile(r"&lt;(https?://[^\s&]+)&gt;")


def _anchor(text: str, escaped_target: str) -> str:
    target = html.unescape(escaped_target)
    if re.match(r"^https?://", target, re.IGNORECASE):
        return (
            f'<a href="{html.escape(target, quote=True)}" rel="noopener noreferrer nofollow">'
            f"{text}</a>"
        )
    return text


def _link(match: re.Match[str]) -> str:
    return _anchor(match.group(1), match.group(2))


def inline(source: str) -> str:
    """Return one line of Markdown as safe HTML."""
    escaped = html.escape(source, quote=True)
    pieces: list[str] = []

    def keep_code(match: re.Match[str]) -> str:
        pieces.append(f"<code>{match.group(1)}</code>")
        return f"\x00{len(pieces) - 1}\x00"

    text = _CODE.sub(keep_code, escaped)
    text = _AUTOLINK.sub(lambda m: _anchor(m.group(1), m.group(1)), text)
    text = _LINK.sub(_link, text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: pieces[int(m.group(1))], text)


def _slug(text: str, used: dict[str, int]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", re.sub(r"<[^>]+>|&\w+;", "", text).lower()).strip("-") or "section"
    count = used.get(base, 0)
    used[base] = count + 1
    return base if count == 0 else f"{base}-{count}"


def _cells(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", body)]


def _list(lines: list[str], start: int) -> tuple[str, int]:
    """Render the list that starts at ``start``; return the HTML and the next index."""
    first = _ITEM.match(lines[start])
    assert first is not None
    base = len(first.group(1).expandtabs(4))
    ordered = first.group(2)[0].isdigit()
    tag = "ol" if ordered else "ul"
    out = [f"<{tag}>"]
    i = start
    while i < len(lines):
        match = _ITEM.match(lines[i])
        if match is None or len(match.group(1).expandtabs(4)) < base:
            break
        indent = len(match.group(1).expandtabs(4))
        if indent > base:
            break
        text = [match.group(3)]
        i += 1
        nested = ""
        while i < len(lines):
            nxt = lines[i]
            if not nxt.strip():
                break
            sub = _ITEM.match(nxt)
            if sub is not None:
                if len(sub.group(1).expandtabs(4)) > base:
                    nested, i = _list(lines, i)
                    continue
                break
            if nxt.startswith(" ") and not _FENCE.match(nxt):
                text.append(nxt.strip())
                i += 1
                continue
            break
        out.append(f"<li>{inline(' '.join(text))}{nested}</li>")
        # A blank line between items of the same list does not end it.
        if i < len(lines) and not lines[i].strip() and i + 1 < len(lines):
            following = _ITEM.match(lines[i + 1])
            if following is not None and len(following.group(1).expandtabs(4)) == base:
                i += 1
    out.append(f"</{tag}>")
    return "".join(out), i


def render(source: str) -> str:
    """Return the Markdown ``source`` as safe HTML."""
    cut = len(source) > MAX_CHARS
    lines = source[:MAX_CHARS].replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    used: dict[str, int] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        fence = _FENCE.match(line)
        if fence:
            marker = fence.group(1)
            body: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(marker):
                body.append(lines[i])
                i += 1
            i += 1
            language = html.escape(fence.group(2))
            cls = f' class="language-{language}"' if language else ""
            out.append(f"<pre><code{cls}>{html.escape(chr(10).join(body))}</code></pre>")
            continue
        heading = _HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            text = inline(heading.group(2))
            out.append(f'<h{level} id="{_slug(text, used)}">{text}</h{level}>')
            i += 1
            continue
        if _RULE.match(line):
            out.append("<hr>")
            i += 1
            continue
        if "|" in line and i + 1 < len(lines) and _TABLE_SEP.match(lines[i + 1]) and "-" in lines[i + 1]:
            head = _cells(line)
            i += 2
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].strip() and "|" in lines[i]:
                rows.append(_cells(lines[i]))
                i += 1
            table = ["<div class=\"help-table\"><table><thead><tr>"]
            table += [f'<th scope="col">{inline(c)}</th>' for c in head]
            table.append("</tr></thead><tbody>")
            for row in rows:
                table.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>")
            table.append("</tbody></table></div>")
            out.append("".join(table))
            continue
        if line.lstrip().startswith(">"):
            quote: list[str] = []
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                quote.append(lines[i].lstrip()[1:].strip())
                i += 1
            out.append(f"<blockquote><p>{inline(' '.join(quote))}</p></blockquote>")
            continue
        if _ITEM.match(line):
            block, i = _list(lines, i)
            out.append(block)
            continue
        paragraph = [line.strip()]
        i += 1
        while i < len(lines) and lines[i].strip():
            nxt = lines[i]
            if _FENCE.match(nxt) or _HEADING.match(nxt) or _ITEM.match(nxt) or nxt.lstrip().startswith(">"):
                break
            paragraph.append(nxt.strip())
            i += 1
        out.append(f"<p>{inline(' '.join(paragraph))}</p>")
    if cut:
        out.append("<p><em>The rest of this document is not shown because it is very long.</em></p>")
    return "\n".join(out)


__all__ = ["inline", "render"]
