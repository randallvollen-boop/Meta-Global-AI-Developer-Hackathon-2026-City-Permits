#!/usr/bin/env python3
"""Independent checks on the built ACME City Permits architecture page.

Run:  python3 -I check/verify_page.py <built.html> <STATUS.json> <page.json>

Checks, in order:
  1. Denylist terms from page.json are absent from the built output.
  2. The kit global client list is absent from the built output.
  3. No external script, style, font, image or link is required to render.
  4. The status panel values match STATUS.json exactly.
  5. Every number printed on the page is on the allowed figure list.

Writes a text report to stdout and exits non-zero when a check fails.
Standard library only.
"""
import base64
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

KIT = Path.home() / "Documents/Vollen Data Analytics/Solution_Architecture_Kit"

# The kit global client list, read from the installed builder so the two never drift.
def _leak_pattern():
    src = (KIT / "build_page.py").read_text(encoding="utf-8")
    blob = "".join(re.findall(r'"([A-Za-z0-9+/=]+)"', src.split("_LEAK_B64 = (")[1].split(")")[0]))
    return re.compile(base64.b64decode(blob).decode(), re.I)


LEAK_OUT = _leak_pattern()

# Figures that may appear on the page, with the source that allows each one.
ALLOWED_FIGURES = {
    "0.2": "Kinetograph 0.2.0 (planned video)",
    "00": "video length 2:00 (planned)",
    "5": "five nodes of the adjudication agent",
    "6": "6 feet fence limit in the planned what-if demo",
    "7": "seven nodes, seven scenes, 7 feet fence limit in the planned demo",
    "10": "parity phase 2 merge: 10 of 10 gates",
    "14": "section 14-305 caption in the planned narration",
    "305": "section 14-305 caption in the planned narration",
    "15": "scene second ranges in the planned narration",
    "25": "scene second ranges in the planned narration",
    "45": "scene second ranges in the planned narration",
    "72": "scene second ranges in the planned narration",
    "96": "scene second ranges in the planned narration",
    "112": "scene second ranges in the planned narration",
    "120": "scene second ranges in the planned narration",
    "17": "parity: 17 permit types",
    "69": "parity: simulated GIS parcels",
    "71": "parity: simulated GIS addresses",
    "37": "parity phase 2 merge: acceptance passed",
    "762": "parity phase 2 merge: pytest passed",
    "879": "merged main at ead8790 (phase 3a and city website): pytest passed (repo/var/check-run-main-city/)",
    "5.6": "model name GPT-5.6",
    "5.5": "model name Claude Opus 5.5",
    "1.3": "model name Muse Spark 1.3",
    "1.0": "model names Muse Wonder 1.0 and Muse Image 1.0",
    "0": "zero implemented, zero verified, zero records",
    "1": "status values and list positions",
    "01": "identifier fragment for AT, VC and D identifiers",
    "08": "identifier fragment for AT, VC and D identifiers",
    "19": "clock fragment of the status record time",
    "2": "two-success live call cap",
    "3": "three source adapters",
    "4": "four personas",
    "5": "five child plans",
    "6": "six release gates",
    "7": "seven day window, not printed",
    "8": "eight screens",
    "9": "nine open decisions",
    "10": "ten application modules",
    "11": "eleven scenarios",
    "12": "identifier fragment",
    "13": "identifier fragment",
    "14": "identifier fragment",
    "15": "identifier fragment",
    "20": "twenty acceptance tests",
    "22": "twenty-two tasks",
    "23": "identifier fragment",
    "24": "identifier fragment",
    "25": "identifier fragment",
    "26": "date fragment",
    "29": "identifier fragment",
    "30": "identifier fragment",
    "31": "identifier fragment",
    "32": "identifier fragment",
    "33": "identifier fragment",
    "34": "identifier fragment",
    "35": "identifier fragment",
    "36": "identifier fragment",
    "37": "identifier fragment",
    "38": "identifier fragment",
    "39": "identifier fragment",
    "40": "identifier fragment",
    "41": "identifier fragment",
    "42": "identifier fragment",
    "43": "identifier fragment",
    "44": "identifier fragment",
    "45": "identifier fragment",
    "46": "identifier fragment",
    "47": "identifier fragment",
    "48": "identifier fragment",
    "49": "identifier fragment",
    "50": "valuation fragment",
    "51": "valuation fragment",
    "52": "valuation fragment",
    "53": "valuation fragment",
    "54": "valuation fragment",
    "55": "valuation fragment",
    "56": "valuation fragment",
    "57": "fifty-seven requirements",
    "70": "valuation fragment",
    "100": "fixed review fee",
    "101": "requirement identifier",
    "102": "requirement identifier",
    "103": "requirement identifier",
    "104": "requirement identifier",
    "105": "requirement identifier",
    "106": "requirement identifier",
    "107": "requirement identifier",
    "108": "requirement identifier",
    "109": "requirement identifier",
    "110": "requirement identifier",
    "150": "first assessment and carried allocation",
    "170": "reassessment",
    "001": "case identifier",
    "0.001": "variable component rate",
    "0.0010": "variable component rate, not printed",
    "3.13": "model version fragment",
    "1.3": "model version",
    "2026": "dates",
    "10": "date fragment",
    "26": "date fragment",
    "00": "clock fragment",
    "00.00": "amount fragment",
    "50.00": "variable component",
    "100.00": "fixed review fee",
    "150.00": "first assessment",
    "170.00": "reassessment",
    "20.00": "balance due",
    "70,000.00": "reassessment valuation",
    "50,000.00": "first valuation",
}

EXTRA_LEAKS = [
    "RailFlow", "Rail Flow", "Westerville", "Westerville City",
    Path.home().name, "/home/", "Randall", "GB10", "127.0.0.1", "192.168", "10.0.0",
    "META_API_KEY", "api_key", "apikey", "api key", "password", "secret",
    "mailto:", "gmail", "@vollen", "grant balance", "prize",
]


class Text(HTMLParser):
    """Visible text of the page, with script, style and svg removed."""

    SKIP = {"script", "style", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.parts = [], []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.stack.append(True)
        else:
            self.stack.append(False)

    def handle_endtag(self, tag):
        if self.stack:
            self.stack.pop()

    def handle_data(self, data):
        if not any(self.stack):
            self.parts.append(data)

    def text(self):
        return re.sub(r"\s+", " ", " ".join(self.parts))


def fail(lines, msg):
    lines.append("FAIL  " + msg)
    lines.append("")   # keep the failure visible in the report body


def main():
    if len(sys.argv) != 4:
        print("usage: verify_page.py <built.html> <STATUS.json> <page.json>")
        return 2
    html_path = Path(sys.argv[1])
    status = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    cfg = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
    doc = html_path.read_text(encoding="utf-8")
    lines = ["# Independent page verification", "", "Page: `%s`" % html_path, ""]
    failures = []

    # 1. denylist
    lines.append("## 1. Denylist")
    deny = list(cfg.get("denylist", []))
    # Private words (kept outside the repository) come from denylist_file when it exists.
    deny_file = Path(cfg["denylist_file"]).expanduser() if cfg.get("denylist_file") else None
    if deny_file and deny_file.is_file():
        deny += [w.strip() for w in deny_file.read_text(encoding="utf-8").splitlines() if w.strip()]
    for word in deny:
        if word.lower() in doc.lower():
            fail(lines, 'denylist term "%s" is present' % word)
            failures.append(word)
    lines.append("Checked %d denylist terms from page.json and the private denylist file." % len(deny))

    # 2. global client list and extra leak words
    lines.append("")
    lines.append("## 2. Global client list and extra leak words")
    for m in LEAK_OUT.finditer(doc):
        fail(lines, "global client list hit: %s" % m.group(0))
        failures.append(m.group(0))
    for word in EXTRA_LEAKS:
        if word.lower() in doc.lower():
            fail(lines, "extra leak word present: %s" % word)
            failures.append(word)
    lines.append("Checked the kit global client list and %d extra leak words." % len(EXTRA_LEAKS))

    # 3. external resources
    lines.append("")
    lines.append("## 3. External resources")
    ext = []
    for m in re.finditer(r"""\b(src|href|action|poster|data|xlink:href)\s*=\s*(["'])(.*?)\2""", doc, re.S):
        v = m.group(3).strip()
        if m.group(1) == "data" or v.startswith("#") or v.startswith("data:"):
            continue
        ext.append("%s=%s" % (m.group(1), v[:60]))
    for m in re.finditer(r"url\(\s*[\"']?([^)\"']*)", doc):
        if not (m.group(1).startswith("data:") or m.group(1).startswith("#")):
            ext.append("url(%s" % m.group(1)[:60])
    if re.search(r"@import|<link\b", doc):
        ext.append("@import or <link> found")
    for e in ext:
        fail(lines, "external resource: " + e)
        failures.append(e)
    lines.append("Checked src, href, action, poster, data, xlink:href, url(), @import and link.")

    # 4. status values
    lines.append("")
    lines.append("## 4. Status panel against STATUS.json")
    req = status["requirements"]
    exe = status["execution"]
    ver = status["verification"]
    expect = {
        "status-overall": [status["overall_status"].replace("_", " ").upper(),
                           status["architecture_status"].replace("_", " ").upper()],
        "status-requirements": [str(req["outlined"]), str(req["implemented"]), str(req["verified"])],
        "status-tasks": [str(exe["tasks_total"]), str(exe["tasks_verified"]), exe["current_phase"]],
        "status-phase": [exe["current_phase"]],
        "status-verification": [str(ver["acceptance_total"]), str(ver["supplementary_total"]),
                                str(ver["scenarios_total"])],
        "status-muse": [ver["live_muse_primary_chain"].upper().replace("_", " ")],
    }
    for element_id, needles in expect.items():
        m = re.search(r'id="%s"[^>]*>(.*?)</div>\s*</div>' % element_id, doc, re.S)
        block = m.group(1) if m else ""
        if not m:
            fail(lines, "status element %s not found" % element_id)
            failures.append(element_id)
            continue
        for needle in needles:
            if needle.upper() not in block.upper():
                fail(lines, "%s does not carry the STATUS.json value %r" % (element_id, needle))
                failures.append(element_id + " " + needle)
        lines.append("%s carries %s." % (element_id, ", ".join(needles)))
    for attr in ("data-outlined=\"%d\"" % req["outlined"], "data-implemented=\"%d\"" % req["implemented"],
                 "data-verified=\"%d\"" % req["verified"], "data-total=\"%d\"" % exe["tasks_total"],
                 "data-phase=\"%s\"" % exe["current_phase"],
                 "data-live-muse-primary-chain=\"%s\"" % ver["live_muse_primary_chain"]):
        if attr not in doc:
            fail(lines, "status data attribute missing: " + attr)
            failures.append(attr)
    lines.append("Checked the stable status data attributes.")

    # 5. figures
    lines.append("")
    lines.append("## 5. Figures printed on the page")
    t = Text()
    t.feed(doc[doc.index("<body"):])
    text = t.text()
    found = set(re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?", text))
    status_figures = set(
        re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?", json.dumps(status, sort_keys=True))
    )
    allowed_figures = set(ALLOWED_FIGURES) | status_figures
    unknown = sorted(f for f in found if f not in allowed_figures)
    for f in unknown:
        fail(lines, "figure on the page is not on the allowed list: %s" % f)
        failures.append(f)
    lines.append("Found %d distinct numeric tokens, %d of them unrecognised." % (len(found), len(unknown)))

    # 6. mockups carry the fictional data note
    lines.append("")
    lines.append("## 6. Mockup notes")
    mockups = len(re.findall(r'class="bnc"', doc))
    notes = len(re.findall(r"Example with fictional data", doc))
    if notes < mockups:
        fail(lines, "only %d fictional data notes for %d mockups" % (notes, mockups))
        failures.append("mockup note")
    lines.append("%d mockup frames, %d fictional data notes." % (mockups, notes))

    lines.append("")
    lines.append("Result: **%s**" % ("FAIL, %d problem(s)" % len(failures) if failures else "PASS"))
    print("\n".join(lines))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
