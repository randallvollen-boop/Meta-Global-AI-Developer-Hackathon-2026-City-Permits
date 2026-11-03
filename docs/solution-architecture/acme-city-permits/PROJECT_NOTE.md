# ACME City Permits architecture page, project note

Date: 2026-10-30 (accuracy rebuild; originally 2026-10-26). Status: AS BUILT. Internal draft.

## Revision 2026-10-28

The diagram now shows the parts built through repo commit `4ea0497`. See the revision section at the end of `BUILD_REPORT.md` and `facts.md` under "As-built diagram contents". Standalone copies for the video: `diagram/arch-as-built.svg` and `diagram/arch-as-built-1920x1080.png`.

## Revision 2026-10-29, hosting copy

The Hosting and Production passages now describe the live public demonstration on a paid Render web service. They distinguish the demo image and public demonstration lock from production mode, record manual release deploys and the nightly reset, and state that live Muse calls have no provider or key on the hosted demonstration. The artifact remains an internal draft and was not published.

## Output

`~/Projects/Personal/Meta-Global-AI-Developer-Hackathon-2026-City-Permits/docs/solution-architecture/acme-city-permits/vollen_acme-city-permits_solution-architecture_2026-10-26.html`

One self-contained HTML file. 362853 bytes. SHA-256 `4d7f96568540e7aae44cdb1a5e9429457ee144d256550fac3bea46a678b18c27` (2026-11-02 no nightly reset). The file before that change was 363085 bytes, SHA-256 `b5015940480bceef54a794dd22cd7d8bce1b1b88cd199d5405679c724fefe73d` (2026-11-02 hosting wording). The file before that was 362944 bytes, SHA-256 `6d95b250204520da18a2b6fa8a57b9b622e8b5a1fe4b42da08e455a0e7de7f9b` (2026-10-30 accuracy rebuild). It loads nothing from the network and renders offline in a browser.

## Rebuild

Run from the solution workspace root, in this order:

```
python3 -I ~/.agents/skills/solution-architecture-page/scripts/inline_assets.py page
# The current kit requires page/page.json output to be an absolute path for this build.
python3 -I "~/Documents/Vollen Data Analytics/Solution_Architecture_Kit/build_page.py" page
~/.agents/skills/solution-architecture-page/scripts/check_linux.sh \
  "$PWD/vollen_acme-city-permits_solution-architecture_2026-10-26.html" "$PWD/check"
python3 -I check/verify_page.py \
  vollen_acme-city-permits_solution-architecture_2026-10-26.html STATUS.json page/page.json
```

The checker needs absolute paths because its Linux wrapper changes the working directory. Before the build, set `page/page.json` `output` to the absolute path of the target HTML. Restore the portable relative value after the build if the workspace is a temporary worktree.

Sources of truth for a rebuild:

- `page/body.src.html` is the markup, including the status panel block.
- `page/data.json` is the diagram, the six views, the eight steps, the node panels, the explorer and the tree.
- `page/extra.css` is the Vollen brand layer plus the page local block. Recopy the brand layer first, then reapply the page local block, so a brand update is not lost.
- `page/page.json` holds the title, description, brand, output, banner, client and denylist.

Do not edit the built HTML. Edit the sources and rebuild.

## Status source

`STATUS.json` in this workspace is the one architecture status record. The status panel on the page, the status node in the diagram and the `info.status` panel entry all carry its values.

The record is written by the parent and can move while a page is being built. It moved from 19:10 to 19:41 during the first build of this page. Re-read `STATUS.json` before every rebuild and take the values as they stand. The brief figures for the status panel are a snapshot and the file wins.

`STATUS_RUNBOOK.md` and `update_status.py` implement the maintained update path. The script validates count bounds and exactly four personas (the page now has five, so do not use it until it is updated), rewrites the marked status section and `info.status`, rebuilds, runs the Linux checker, runs independent page verification and copy lint, and optionally replaces the private AVA article.

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
- Text only VollenData branding. No wrong brand word, logo or client mark reaches the output, and the builder denylist enforces that.
- Every mockup frame says "Example with fictional data".
- The page states no measured benefit, accuracy, savings, performance, compliance or production readiness claim, and no tamper-proof claim.
- The page embeds no fonts and uses no kit icons. `page/extra.css` sets system font stacks, and `page/icons.json` holds our own 38 line icons, which the kit builder uses in place of its set. The kit's Aptos font data was removed (2026-10-28).
- The standalone standard and its templates are absent on this host. The kit README, this fact sheet, the sibling worked example and the Vollen Linux instructions set the page shape.

## Planned content

The `roadmap` (Planned: phase 3) and `video` (Planned explainer video) sections are planned content only. They claim no result, and nothing in them is built, published or submitted.

## Revision 2026-10-29, permit life cycle section

- New section `#lifecycle` with a state diagram and a table of every move. It is generated into `page/body.src.html`, between the LIFECYCLE markers, by `repo/scripts/build_lifecycle_diagram.py`, from `repo/src/acme_city/permits/lifecycle_map.py`. Regenerate it before a rebuild whenever the life cycle changes. Do not hand-edit between the markers.
- Two builder failures already in the sources were fixed: the Scene 7 card now uses the "Randy Vollen" byline, and the deployment row no longer names the signing-key variable. Both had tripped the page denylist.
- `page/page.json` keeps the committed relative `output`. The kit builder needs an absolute path, so set it to an absolute worktree path for the build and restore it afterwards.
- Open: `check/verify_page.py` fails on 8 figures that predate this revision (02, 1080, 18, 2.0, 300, 503, 60, 600). Each needs a sourced line in `facts.md` or a rewording. The AVA Library copy was not replaced in this revision.

## Revision 2026-10-30, accuracy rebuild

- Audited against code at `07f048b` and rebuilt from edited sources. Five personas (Agent Operator added, story order), later-lane screens and parts, current screen names, Administration tabs, local map tiles, bundled video copy, all-rights-reserved licence, current test figures. See the 2026-10-30 section of `BUILD_REPORT.md` and the last section of `facts.md`.
- `update_status.py` hard-codes four personas and was not used. `STATUS.json` was edited by hand (as_of and personas) and the status block in `page/body.src.html` matches it.
- Not done: the AVA Library copy was not replaced.

## Revision 2026-10-30, master data as the spine

- New section "Why master data is central", a registry-first standfirst, and a System view with the registry master data node at the centre (class `core`, heavier outline in `page/extra.css`). Edges: proposes link, decides, reads. Non-Muse product and model names were removed from the sources and the page.

## Revision 2026-11-02, hosting reset wording

- The Hosting section no longer states the nightly reset as a fact. The Blueprint
  line says the cron job runs at 02:00 UTC. The cron job line says the deploy
  hook URL is a secret set in the Render dashboard, and that until it is set the
  nightly run fails and the data is not reset. The same wording is in
  `facts.md` under "Hosting and production".
- Superseded by the revision below: the cron job was dropped from the blueprint
  on Randall's word, so the page no longer names it at all.
- The kit and its standard are not on this host, so the page was not rebuilt.
  `page/body.src.html`, `page/body.html` and the built file carry the same two
  sentences, and the built file still embeds the body verbatim, so a rebuild
  from these sources gives the same output.
- The AVA Library copy was not replaced.

## Revision 2026-11-02, the nightly reset is gone

- The Hosting section names no cron job and no nightly reset. The Blueprint line
  says the blueprint defines one web service, built from `repo/Dockerfile-demo`.
  The next line says every deploy rebuilds the fictional data. The same wording
  is in `facts.md` under "Hosting and production", and the live call allowance
  there now says 100 live calls per deploy and a daily provider cap of 100.
- The cron job was dropped from `render.yaml` on 2026-11-02 (Randall), so the
  page and the blueprint agree. The deploy hook stays a manual tool in the
  Render dashboard.
- The kit and its standard are not on this host, so the page was not rebuilt.
  `page/body.src.html`, `page/body.html` and the built file carry the same two
  sentences, and the built file still embeds the body verbatim, so a rebuild
  from these sources gives the same output.
- The AVA Library copy was not replaced.
