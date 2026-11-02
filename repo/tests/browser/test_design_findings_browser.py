"""The design findings of the Hallmark checker of 2026-11-02 are fixed.

The checker named sixty things on the judge-facing pages.  This browser
walk measures the nineteen places of low contrast it named, the width of the
same pages on a phone, and the smaller findings it named: the disabled
controls, the labels in capitals, the footer of the City website, the
description of the link preview, the bar of the tour and the straight
quotes in the prose.

The contrast is measured the way a reader sees it: the colour of the text
against the background the stylesheet paints behind it.
"""
# REQUIRES: UX-01, UX-02, UX-03

from __future__ import annotations

import pytest

from conftest import BrowserServer, assert_no_horizontal_overflow

#: The pages the checker walked: the staff frame and the City website.
STAFF_PAGES = ("/select", "/walkthrough", "/lifecycle")
CITY_PAGES = ("/city/", "/city/community", "/city/permits")
JUDGE_PAGES = STAFF_PAGES + CITY_PAGES

#: The nineteen places of low contrast the checker named, as the selector
#: and the markup that carries it.  The markup repeats the structure the
#: selector needs (a state of a node, a heading of a card), so the browser
#: measures the rule and not the page it happened to stand on.
CONTRAST_PROBES: tuple[tuple[str, str], ...] = (
    (".ui-drawer-refused", '<p class="ui-drawer-refused">refused</p>'),
    (".case-confirmation", '<p class="case-confirmation">confirmed</p>'),
    (
        ".agent-dag-node.warn .st",
        '<div class="agent-dag-node warn"><span class="st">w</span></div>',
    ),
    (".rnode.ok .st", '<div class="rnode ok"><div class="h"><span class="st">o</span></div></div>'),
    (".guide-step-n", '<span class="guide-step-n">1</span>'),
    (
        ".agent-dag-node.block .st",
        '<div class="agent-dag-node block"><span class="st">b</span></div>',
    ),
    (
        ".agent-dag-node.idle .st",
        '<div class="agent-dag-node idle"><span class="st">i</span></div>',
    ),
    (".rnode .h .st", '<div class="rnode"><div class="h"><span class="st">s</span></div></div>'),
    (".search", '<div class="search"><input type="text"></div>'),
    (".step .ic", '<div class="step"><span class="ic">i</span></div>'),
    (".tl-dot", '<span class="tl-dot">t</span>'),
    (".type-ic.line", '<span class="type-ic line">l</span>'),
    (".icon-preview", '<div class="icon-preview">p</div>'),
)

#: The labels the checker named as capitals with wide spacing: the page
#: that carries the stylesheet of the rule, the selector, the markup that
#: carries it and the size the label now has (one step below the size it
#: had, in the pixels of the browser).
CAPITAL_LABELS = (
    ("/select", ".admin-b .admin-b-change-kind",
     '<div class="admin-b"><p class="admin-b-change-kind">kind</p></div>', "11.52px"),
    ("/select", ".agent-dag-state", '<p class="agent-dag-state">Clear</p>', "10.56px"),
    ("/city/", ".city-wordmark small",
     '<span class="city-wordmark"><small>Permit Services</small></span>', "11.2px"),
    ("/select", ".data-table thead th",
     '<table class="data-table"><thead><tr><th>Rule</th></tr></thead></table>', "10.56px"),
    ("/select", ".eyebrow", '<p class="eyebrow">Permit workspace</p>', "11.52px"),
    ("/select", ".fact .k", '<div class="fact"><span class="k">Reference</span></div>', "10.56px"),
    ("/select", ".feedback-detail dt",
     '<dl class="feedback-detail"><div><dt>Destination</dt><dd>x</dd></div></dl>', "12.16px"),
    ("/select", ".responsibility-grid dt",
     '<dl class="responsibility-grid"><div><dt>Role</dt><dd>x</dd></div></dl>', "12.16px"),
    ("/select", ".pair-list dt",
     '<dl class="pair-list"><div><dt>Outcome</dt><dd>x</dd></div></dl>', "12.16px"),
    ("/select", ".guide-k", '<span class="guide-k">Do</span>', "12.16px"),
    ("/select", ".issue .fix b",
     '<div class="issue"><div class="fix"><b>Next</b> text</div></div>', "10.24px"),
    ("/select", ".kpi .k", '<div class="kpi"><span class="k">Open cases</span></div>', "10.88px"),
    ("/select", ".nav-label", '<div class="nav-label">Workspace</div>', "10.24px"),
    ("/select", ".nav-more-summary",
     '<summary class="nav-more-summary">More tools</summary>', "10.24px"),
    ("/select", ".ops-figure .k",
     '<div class="ops-figure"><span class="k">Cases</span></div>', "11.2px"),
    ("/select", ".tour-count", '<p class="tour-count">Step 1 of 4</p>', "12.16px"),
    ("/select", "th", '<table><thead><tr><th>Rule</th></tr></thead></table>', "10.56px"),
)

#: The contrast a reader needs of the text of the interface.
MINIMUM_CONTRAST = 4.5

#: Measure the colour of an element against the background behind it.
MEASURE = """([selector, markup]) => {
  const host = document.createElement('div');
  host.style.cssText = 'position:absolute;left:-9999px;top:0;';
  host.innerHTML = markup;
  document.body.appendChild(host);
  const element = host.querySelector(selector);
  if (!element) { host.remove(); return {selector: selector, missing: true}; }
  const style = getComputedStyle(element);
  const parse = (value) => {
    const numbers = value.match(/[\\d.]+/g).map(Number);
    return {
      r: numbers[0], g: numbers[1], b: numbers[2],
      a: numbers.length > 3 ? numbers[3] : 1,
    };
  };
  const channel = (value) => {
    const c = value / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  };
  const luminance = (colour) =>
    0.2126 * channel(colour.r) + 0.7152 * channel(colour.g) + 0.0722 * channel(colour.b);
  const over = (top, bottom) => ({
    r: top.r * top.a + bottom.r * (1 - top.a),
    g: top.g * top.a + bottom.g * (1 - top.a),
    b: top.b * top.a + bottom.b * (1 - top.a),
    a: 1,
  });
  const foreground = parse(style.color);
  let background = parse(style.backgroundColor);
  let node = element;
  while (background.a === 0 && node.parentElement) {
    node = node.parentElement;
    background = parse(getComputedStyle(node).backgroundColor);
  }
  const painted = foreground.a < 1 ? over(foreground, background) : foreground;
  const one = luminance(painted);
  const other = luminance(background);
  const ratio = (Math.max(one, other) + 0.05) / (Math.min(one, other) + 0.05);
  /* The values are read before the probe leaves the page: a computed style
     of an element that is gone is empty. */
  const found = {
    selector: selector,
    ratio: Math.round(ratio * 100) / 100,
    color: style.color,
    background: style.backgroundColor,
    transform: style.textTransform,
    spacing: style.letterSpacing,
    size: style.fontSize,
  };
  host.remove();
  return found;
}"""

#: The straight quotes of the prose of a page.
PROSE = """() => {
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const found = [];
  let node = walker.nextNode();
  while (node) {
    const text = node.nodeValue || '';
    if (text.includes("'") || text.includes('"')) found.push(text.trim().slice(0, 60));
    node = walker.nextNode();
  }
  return found;
}"""


def contrast_of(page, selector: str, markup: str) -> dict:
    """Return the measured contrast of one selector on the open page."""
    return page.evaluate(MEASURE, [selector, markup])


@pytest.mark.parametrize("path", STAFF_PAGES)
def test_the_staff_pages_read_in_the_light_theme(page, server, path: str) -> None:
    """The nineteen places of the staff pages read in the light theme."""
    page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
    for selector, markup in CONTRAST_PROBES:
        measured = contrast_of(page, selector, markup)
        assert not measured.get("missing"), f"{path}: {selector} is not in the page"
        assert measured["ratio"] >= MINIMUM_CONTRAST, (
            f"{path}: {selector} reads at {measured['ratio']}:1 "
            f"({measured['color']} on {measured['background']})"
        )


@pytest.mark.parametrize("path", STAFF_PAGES)
def test_the_staff_pages_read_in_the_dark_theme(page, server, path: str) -> None:
    """The same nineteen places read in the dark theme of the staff frame."""
    page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
    page.evaluate("() => document.documentElement.setAttribute('data-theme', 'dark')")
    for selector, markup in CONTRAST_PROBES:
        measured = contrast_of(page, selector, markup)
        assert not measured.get("missing"), f"{path}: {selector} is not in the page"
        assert measured["ratio"] >= MINIMUM_CONTRAST, (
            f"{path}: {selector} reads at {measured['ratio']}:1 in the dark theme "
            f"({measured['color']} on {measured['background']})"
        )


@pytest.mark.parametrize("path", CITY_PAGES)
def test_the_city_pages_read(page, server, path: str) -> None:
    """The same nineteen places read on the City website."""
    page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
    for selector, markup in CONTRAST_PROBES:
        measured = contrast_of(page, selector, markup)
        assert not measured.get("missing"), f"{path}: {selector} is not in the page"
        assert measured["ratio"] >= MINIMUM_CONTRAST, (
            f"{path}: {selector} reads at {measured['ratio']}:1 "
            f"({measured['color']} on {measured['background']})"
        )


@pytest.mark.parametrize("path", JUDGE_PAGES)
def test_every_judge_page_carries_a_description(page, server, path: str) -> None:
    """The link preview of every judge page has one plain sentence."""
    page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
    description = page.locator('meta[name="description"]').get_attribute("content")
    assert description, f"{path} has no description"
    assert "City of Acme" in description, description
    assert description.count(".") == 1, description
    assert "fictional" in description, description


@pytest.mark.parametrize("path", JUDGE_PAGES)
def test_the_prose_of_the_judge_pages_has_no_straight_quote(page, server, path: str) -> None:
    """The prose uses typographic quotes, not the straight ones."""
    page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
    straight = [text for text in page.evaluate(PROSE) if text]
    assert straight == [], f"{path} still holds straight quotes: {straight}"


def test_the_disabled_control_says_so_with_a_fill_and_a_cursor(page, server, login) -> None:
    """A control that cannot be used now is not a faded copy of a live one."""
    login("persona_permit_reviewer")
    page.goto(f"{server.base_url}/permits/app_synth_001", wait_until="domcontentloaded")
    disabled = page.locator("button[disabled]").first
    assert disabled.count() > 0, "the case offers a disabled control"
    style = disabled.evaluate(
        """element => {
          const style = getComputedStyle(element);
          /* The same button without the attribute shows what a live
             control of that kind looks like. */
          const live = document.createElement('button');
          live.className = element.className;
          document.body.appendChild(live);
          const liveStyle = getComputedStyle(live);
          const found = {
            cursor: style.cursor,
            opacity: style.opacity,
            background: style.backgroundColor,
            color: style.color,
            liveBackground: liveStyle.backgroundColor,
            liveColor: liveStyle.color,
          };
          live.remove();
          return found;
        }"""
    )
    assert style["cursor"] == "not-allowed", style
    assert float(style["opacity"]) == 1.0, style
    assert style["background"] != style["liveBackground"], style
    assert style["color"] != style["liveColor"], style
    # The reason stays beside the control that cannot be used.
    described = disabled.get_attribute("aria-describedby")
    assert described, "the disabled control names its reason"
    assert page.locator(f"#{described}").count() == 1, described


def test_the_labels_of_the_interface_are_in_sentence_case(page, server) -> None:
    """The labels are sentence case, without wide spacing, one size smaller."""
    for path, selector, markup, size in CAPITAL_LABELS:
        page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
        style = page.evaluate(MEASURE, [selector, markup])
        assert not style.get("missing"), f"{selector} is not in the page"
        assert style["transform"] == "none", f"{selector} still shouts: {style}"
        assert style["spacing"] in ("normal", "0px"), f"{selector} is still tracked: {style}"
        assert style["size"] == size, f"{selector} is not one size smaller: {style}"


def test_the_footer_of_the_city_website_is_a_list(page, server) -> None:
    """The links of the footer are a list, not one line joined by dots."""
    page.goto(f"{server.base_url}/city/", wait_until="domcontentloaded")
    footer = page.locator('[data-testid="city-footer-links"]')
    assert footer.evaluate("element => element.tagName") == "UL"
    assert footer.locator("li").count() >= 4
    assert "·" not in footer.inner_text()


def test_the_bar_of_the_tour_grows_by_a_scale(page, server) -> None:
    """The progress bar of the tour animates a transform, not a width."""
    page.goto(f"{server.base_url}/select", wait_until="domcontentloaded")
    page.locator('[data-testid="tour-start-landing"]').click()
    page.wait_for_selector('[data-testid="tour-progress-fill"]', state="attached")
    style = page.evaluate(
        "() => { const s = getComputedStyle(document.querySelector"
        "('[data-testid=\"tour-progress-fill\"]'));"
        " return {transition: s.transitionProperty, width: s.width,"
        " transform: s.transform}; }"
    )
    assert "transform" in style["transition"], style
    assert "width" not in style["transition"], style


def test_the_persona_page_holds_one_card_level(page, server) -> None:
    """The persona cards and the path cards are not cards inside a card."""
    page.goto(f"{server.base_url}/select", wait_until="domcontentloaded")
    nested = page.evaluate(
        """() => {
          const cards = [...document.querySelectorAll('[data-testid="persona-card"]')];
          const paths = [...document.querySelectorAll('[data-testid="landing-path"]')];
          const cardOf = (card) => {
            let node = card.parentElement;
            while (node) {
              const style = getComputedStyle(node);
              const bordered = style.borderTopWidth !== '0px'
                && style.borderTopStyle !== 'none';
              if (bordered && style.backgroundColor !== 'rgba(0, 0, 0, 0)') {
                return node.className;
              }
              node = node.parentElement;
            }
            return null;
          };
          return {
            personas: cards.map(cardOf),
            paths: paths.map(cardOf),
          };
        }"""
    )
    assert nested["personas"] == [None] * 5, nested
    assert nested["paths"] == [None] * len(nested["paths"]), nested


@pytest.mark.parametrize("path", JUDGE_PAGES)
def test_no_judge_page_scrolls_sideways_on_a_phone(page, server, viewport_390, path: str) -> None:
    """None of the judge pages is wider than the phone that shows it."""
    page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
    assert_no_horizontal_overflow(page)


def test_the_drawer_of_a_staff_page_fits_a_phone(page, server, viewport_390, login) -> None:
    """The drawer of the staff frame opens on a phone without a sideways scroll."""
    login("persona_permit_reviewer")
    page.goto(f"{server.base_url}/walkthrough?detail=help:walkthrough", wait_until="domcontentloaded")
    drawer = page.locator('[data-testid="ui-drawer"]')
    assert drawer.is_visible(), "the drawer did not open"
    assert_no_horizontal_overflow(page)


def test_the_persona_menu_fits_a_phone(page, server, viewport_390, login) -> None:
    """The menu of the persona chip opens on a phone without a sideways scroll."""
    login("persona_permit_reviewer")
    page.goto(f"{server.base_url}/queue", wait_until="domcontentloaded")
    page.locator('[data-testid="persona-trigger"]').click()
    panel = page.locator(".account-panel")
    assert panel.is_visible(), "the menu did not open"
    assert_no_horizontal_overflow(page)


def test_the_help_sheet_fits_a_phone(page, server, viewport_390, login) -> None:
    """The assistant of the applicant opens on a phone without a sideways scroll."""
    login("persona_applicant")
    page.goto(f"{server.base_url}/apply", wait_until="domcontentloaded")
    page.locator('[data-testid="help-chat-launcher"]').click()
    sheet = page.locator('[data-testid="help-panel-sheet"]')
    sheet.wait_for(state="visible")
    assert_no_horizontal_overflow(page)


def test_the_drawer_of_a_city_page_fits_a_phone(page, server, viewport_390, login) -> None:
    """The drawer of the City website opens on a phone without a sideways scroll."""
    login("persona_applicant")
    page.goto(f"{server.base_url}/city/permits", wait_until="domcontentloaded")
    page.locator('[data-testid="ui-help"]').first.click()
    drawer = page.locator('[data-testid="ui-drawer"]')
    drawer.wait_for(state="visible")
    assert_no_horizontal_overflow(page)


def test_the_panel_of_the_tour_fits_a_phone(page, server, viewport_390) -> None:
    """The panel of the tour opens on a phone without a sideways scroll."""
    page.goto(f"{server.base_url}/select", wait_until="domcontentloaded")
    page.locator('[data-testid="tour-start-landing"]').click()
    panel = page.locator('[data-testid="tour-panel"]')
    panel.wait_for(state="attached")
    assert_no_horizontal_overflow(page)
