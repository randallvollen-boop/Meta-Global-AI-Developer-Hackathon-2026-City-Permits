# ACME City Permits architecture page, project note

Date: 2026-10-27 (parity phases 1 and 2 added; originally 2026-10-26). Status: PLANNED, in implementation. Internal draft.

## Revision 2026-10-28

The diagram now shows the parts built through repo commit `4ea0497`. See the revision section at the end of `BUILD_REPORT.md` and `facts.md` under "As-built diagram contents". Standalone copies for the video: `diagram/arch-as-built.svg` and `diagram/arch-as-built-1920x1080.png`.

## Output

`~/Projects/Personal/Meta-Global-AI-Developer-Hackathon-2026-City-Permits/docs/solution-architecture/acme-city-permits/vollen_acme-city-permits_solution-architecture_2026-10-26.html`

One self-contained HTML file. 932654 bytes. SHA-256 `93e6cd0554f8c7e8481fdc3885a67476f0ec7d22151860876fc738e50649b55f`. It loads nothing from the network and renders offline in a browser.

## Rebuild

Run from the solution workspace root, in this order:

```
python3 -I ~/.claude/skills/solution-architecture-page/scripts/inline_assets.py page
python3 -I "~/Documents/Vollen Data Analytics/Solution_Architecture_Kit/build_page.py" page
~/.claude/skills/solution-architecture-page/scripts/check_linux.sh \
  "$PWD/vollen_acme-city-permits_solution-architecture_2026-10-26.html" "$PWD/check"
python3 -I check/verify_page.py \
  vollen_acme-city-permits_solution-architecture_2026-10-26.html STATUS.json page/page.json
```

The checker needs absolute paths because its Linux wrapper changes the working directory. The output path in `page/page.json` is absolute, so the builder needs no argument change.

Sources of truth for a rebuild:

- `page/body.src.html` is the markup, including the status panel block.
- `page/data.json` is the diagram, the six views, the eight steps, the node panels, the explorer and the tree.
- `page/extra.css` is the Vollen brand layer plus the page local block. Recopy the brand layer first, then reapply the page local block, so a brand update is not lost.
- `page/page.json` holds the title, description, brand, output, banner, client and denylist.

Do not edit the built HTML. Edit the sources and rebuild.

## Status source

`STATUS.json` in this workspace is the one architecture status record. The status panel on the page, the status node in the diagram and the `info.status` panel entry all carry its values.

The record is written by the parent and can move while a page is being built. It moved from 19:10 to 19:41 during the first build of this page. Re-read `STATUS.json` before every rebuild and take the values as they stand. The brief figures for the status panel are a snapshot and the file wins.

`STATUS_RUNBOOK.md` and `update_status.py` implement the maintained update path. The script validates count bounds and exactly four personas, rewrites the marked status section and `info.status`, rebuilds, runs the Linux checker, runs independent page verification and copy lint, and optionally replaces the private AVA article.

The status block lives in `page/body.src.html` between the exact comments:

```
<!-- ARCH_STATUS_BEGIN -->
...
<!-- ARCH_STATUS_END -->
```

The six stable ids are `status-overall`, `status-requirements`, `status-tasks`, `status-phase`, `status-verification` and `status-muse`. Each card also carries data attributes, for example `data-outlined`, `data-implemented`, `data-verified`, `data-total`, `data-phase` and `data-live-muse-primary-chain`, so the values can be regenerated rather than retyped.

`check/verify_page.py` compares the rendered panel against `STATUS.json` and fails when a value drifts. Run it on every build.

## Phase update rule

The page is rebuilt and replaced at each accepted phase transition, and only then.

- The status values come from actual task and test evidence. A plan, a screenshot, a generated file or a worker claim alone never increments an implemented or verified count.
- The architecture status stays PLANNED until the integrated evidence gate passes. Only then does the status record change, and only then does the page change.
- Each rebuild records the new output hash in `BUILD_REPORT.md` and replaces the previous report section rather than deleting the history.

## Publication target

The library article identifier is `acme-city-permits-architecture`, as recorded in the status record under `library.article_id`. The page replaces the previous content under that same identifier. It does not create a new article.

The private AVA Library article is published under `acme-city-permits-architecture`, as recorded in the status record under `library.article_id`. Each accepted phase update replaces the previous content under that same identifier and never creates a new article.

The article remains an internal draft with the review banner. Brand, delivery-owner and security approvals are still open. AVA was updated offline while its service remained inactive.

## Boundaries

- Fictional ACME City data only. No real applicant, contractor, parcel, payment or permit record appears on the page.
- Text only Vollen Data Services branding. No wrong brand word, logo or client mark reaches the output, and the builder denylist enforces that.
- Every mockup frame says "Example with fictional data".
- The page states no measured benefit, accuracy, savings, performance, compliance or production readiness claim, and no tamper-proof claim.
- The shared kit is not edited. The unused Aptos face in the kit shell remains, and its embedding rights outside the kit owner stay unverified.
- The standalone standard and its templates are absent on this host. The kit README, this fact sheet, the sibling worked example and the Vollen Linux instructions set the page shape.

## Planned content

The `roadmap` (Planned: phase 3) and `video` (Planned explainer video) sections are planned content only. They claim no result, and nothing in them is built, published or submitted.
