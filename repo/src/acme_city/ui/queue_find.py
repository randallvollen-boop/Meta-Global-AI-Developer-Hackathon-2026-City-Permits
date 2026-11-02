"""Search and paging for the work queue and the review queue.

The search is a query-string value, so the page works with no JavaScript.
It runs on the full list and only then keeps one page, so a match that
would have sat past the first page is not hidden by the page.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlencode

#: How many rows one page of either queue shows. The seeded queues fit on
#: the first page. A longer list continues on the next page.
PAGE_SIZE = 25


def normalize_query(value: str | None) -> str:
    """Return the search text with the extra space removed.

    The words the person typed are kept, including their case, so the page
    can quote the search back. Only the surrounding and repeated space goes.
    """
    return " ".join(str(value or "").split())[:200]


def matches_query(reference: str, applicant: str, address: str, query: str) -> bool:
    """Return whether one case matches the search text.

    The match is case-insensitive. The readable reference matches in full
    (``SYN-APP-617``) or by the number alone (``617``), and the applicant
    name and the site address match the same way.
    """
    needle = normalize_query(query).casefold()
    if not needle:
        return True
    haystack = " ".join(part for part in (reference, applicant, address) if part)
    return needle in haystack.casefold()


def search_summary(count: int, query: str) -> str:
    """Return the line that says how the search came out."""
    shown = normalize_query(query)
    if count <= 0:
        return f"No match for {shown}."
    if count == 1:
        return f"1 match for {shown}"
    return f"{count} matches for {shown}"


def review_href(
    area: str = "",
    action: str = "",
    query: str = "",
    tag: str = "",
) -> str:
    """Return a review-queue address that keeps the area, the action, the search and the tag."""
    params: list[tuple[str, str]] = []
    if area:
        params.append(("area", area))
    if action:
        params.append(("next_action", action))
    text = normalize_query(query)
    if text:
        params.append(("q", text))
    if tag:
        params.append(("tag", tag))
    if not params:
        return "/queue/review"
    return "/queue/review?" + urlencode(params)


def work_href(
    *,
    focus: str = "all",
    view: str = "my",
    department: str = "",
    object_type: str = "",
    state: str = "",
    query: str = "",
    tag: str = "",
) -> str:
    """Return a work-queue address that keeps the filters and, when set, the search and the tag."""
    payload: dict[str, str] = {
        "focus": focus or "all",
        "view": view or "my",
        "department": department or "",
        "object_type": object_type or "",
        "state": state or "",
    }
    text = normalize_query(query)
    if text:
        payload["q"] = text
    if tag:
        payload["tag"] = tag
    return "/queue?" + urlencode(payload)


def with_page(url: str, page: int) -> str:
    """Return ``url`` on the given page. Page 1 keeps the address it already has."""
    if page <= 1:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}page={page}"


def paginate(
    rows: list[Any],
    page: int,
    page_size: int = PAGE_SIZE,
) -> tuple[list[Any], dict[str, Any]]:
    """Return one page of ``rows`` and where that page sits in the list.

    ``page`` is clamped into the real range. An empty list is one empty page.
    """
    total = len(rows)
    size = page_size if page_size > 0 else PAGE_SIZE
    pages = max((total + size - 1) // size, 1)
    try:
        current = int(page)
    except (TypeError, ValueError):
        current = 1
    if current < 1:
        current = 1
    if current > pages:
        current = pages
    start = (current - 1) * size
    return rows[start : start + size], {
        "page": current,
        "pages": pages,
        "total": total,
        "prev_href": "",
        "next_href": "",
    }


def paging_links(url: str, page: int, pages: int) -> dict[str, str]:
    """Return the previous and next addresses for one page of ``url``."""
    return {
        "prev_href": with_page(url, page - 1) if page > 1 else "",
        "next_href": with_page(url, page + 1) if page < pages else "",
    }


def sole_open(rows: list[dict[str, Any]], query: str, back: str) -> dict[str, str] | None:
    """Return the Open target when the search has exactly one application.

    ``back`` is the queue address the case link carries, so the case page
    can name the queue the person came from.
    """
    if not normalize_query(query) or len(rows) != 1:
        return None
    row = rows[0]
    if row.get("kind") not in (None, "application"):
        return None
    application_id = str(row.get("application_id") or row.get("id") or "")
    if not application_id:
        return None
    return {
        "reference": str(row.get("reference") or row.get("title") or ""),
        "applicant_name": str(row.get("applicant_name") or ""),
        "address": str(row.get("address") or ""),
        "href": f"/permits/{application_id}?from={quote(back, safe='')}",
    }


__all__ = [
    "PAGE_SIZE",
    "matches_query",
    "normalize_query",
    "paginate",
    "paging_links",
    "review_href",
    "search_summary",
    "sole_open",
    "with_page",
    "work_href",
]
