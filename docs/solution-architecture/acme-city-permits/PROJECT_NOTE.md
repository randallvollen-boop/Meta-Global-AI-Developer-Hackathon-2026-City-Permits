# ACME City Permits architecture page, project note

Date: 2026-11-02 (final rebuild; originally 2026-10-26). Status: AS BUILT.

## Revision 2026-10-28

The diagram now shows the parts built through repo commit `4ea0497`. See the revision section at the end of `BUILD_REPORT.md` and `facts.md` under "As-built diagram contents". Standalone copies for the video: `diagram/arch-as-built.svg` and `diagram/arch-as-built-1920x1080.png`.

## Revision 2026-10-29, hosting copy

The Hosting and Production passages now describe the live public demonstration on a paid Render web service. They distinguish the demo image and public demonstration lock from production mode, record manual release deploys and the nightly reset, and state that live Muse calls have no provider or key on the hosted demonstration. The artifact was not published. The scheduled reset that this revision described was withdrawn on 2026-11-02; see the last revision.

## Output

`~/Projects/Personal/Meta-Global-AI-Developer-Hackathon-2026-City-Permits/docs/solution-architecture/acme-city-permits/vollen_acme-city-permits_solution-architecture_2026-10-26.html`

One self-contained HTML file. 364310 bytes. SHA-256 `566691fffe0acc036687b50501c11e0dea246112c96412919e0c0f6c7740089d` (2026-11-02, picture lock and no scheduled reset). It loads nothing from the network and renders offline in a browser.

The application serves this file at `/help/technical/architecture`. It is the only copy in the repository, and `repo/tests/integration/test_help_docs.py` checks that the served bytes are the committed bytes.

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

The review banner was removed from the page by the project owner's decision of 2026-11-02. The same decision keeps every open-gate and review-status line off the page, so the release gates row and the review gates row are gone. Brand and delivery-owner approvals are still open, and the security review has run; those notes stay here and in the fact sheet, which are internal. Muse is the only model name the page carries. The AVA article was replaced with this build under the same identifier, while its service remained inactive.

## Boundaries

- Fictional ACME City data only. No real applicant, contractor, parcel, payment or permit record appears on the page.
- Text only VollenData branding. No wrong brand word, logo or client mark reaches the output, and the builder denylist enforces that.
- Every mockup frame says "Example with fictional data".
- The page states no measured benefit, accuracy, savings, performance, compliance or production readiness claim, and no tamper-proof claim.
- The page embeds no fonts and uses no kit icons. `page/extra.css` sets system font stacks, and `page/icons.json` holds our own 38 line icons, which the kit builder uses in place of its set. The kit's Aptos font data was removed (2026-10-28).
- The standalone standard and its templates are absent on this host. The kit README, this fact sheet, the sibling worked example and the Vollen Linux instructions set the page shape.

## Planned content

The `roadmap` section (Phase 3: built) and the `video` section (the finished demo video) state what is built. The video is the final cut and plays on the landing page of the live demonstration. Neither section publishes or submits anything.

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

## Revision 2026-11-02, final rebuild

- The internal-review banner is gone. The project owner's decision of 2026-11-02 overrides the banner rule of the build skill for this page, so `page/page.json` carries an empty banner and no internal-review or draft marker stays on the page. The byline and the "Example with fictional data" labels stay.
- The facts of 2026-11-02 are on the page: steward data no longer holds a case, approving against a failed rule is a recorded exception, the pre-submit check with Check my application and Submit anyway, the real clock in the demonstration, 85 permissions, and the current test figures.
- The Muse passage names the live paths: the applicant help answer, Check my application, Explain with Muse, the council briefing and the what-if proposals. The document extraction stays a recorded run that is replayed.
- The video rows carry no draft number. The page says the demo video is being recorded from the final build.
- The diagram keeps its Play and step-through engine. `repo/src/acme_city/templates/help.html` and `repo/src/acme_city/ui/help_docs_routes.py` were not touched.
- Kit builder and the Linux checker ran clean, and `check/verify_page.py` passes. The AVA Library copy was not replaced in this revision.

## Revision 2026-11-02, brand line and theme toggle

- The footer brand line, "VollenData" over "A Brighter Future, Rooted in Data.", is right aligned against the page edge and the two are separated by a visible 6px gap. The markup also carries a space between the two spans, so a text copy no longer runs them together. The rule lives in the page local block of `page/extra.css`, not in the brand layer copy, because the shared brand layer is recopied on every rebuild.
- The theme toggle flips `data-theme` on the root element and does not depend on `localStorage`. The script now guards `matchMedia` and the storage calls, and keeps the reader's choice in force when the operating system theme moves. In a frame with an opaque origin, `localStorage` raises a `SecurityError`, and the toggle still works.
- `check/verify_page.py` gained two checks, the theme toggle and the footer brand line, and now runs eight. Both were run against the previous build: check 7 passed there and check 8 failed there with three problems.
- The shared brand layer in the skill, `assets/vds-brand/extra.css` and `assets/vds-brand/snippets.html`, was not changed. The sandbox refused both files, so the skill still carries the older footer rule and the older theme script. Every other page copies that script into its own `body.src.html`, so the skill template should take the same script in a later pass.
- The frame that carries the page still blocks scripts on this branch. The toggle was read against a frame that allows scripts and an opaque origin, which is what the branch that allows scripts provides.
- Kit builder and the Linux checker ran clean, `check/verify_page.py` passes, and `repo/tests/integration/test_help_docs.py -k architecture` passes, so the served bytes are the committed bytes. The AVA Library copy was not replaced in this revision.

## Revision 2026-11-02, no review status and Muse as the only model name

- The page carries no open-gate or review-status line. The release gates row of "What exists now" and the review gates row of "Open decisions and limitations" are gone, and the open-decisions rows are renumbered from 6 to 10 into 5 to 9.
- Muse is the only model name on the page. The Muse product variants, the model versions and the model identifiers are out of the copy, the diagram, the diagram alt text and the info panels. The diagram's external model services keep one node titled "Muse" and one titled "Icon generation".
- The decision is recorded in `facts.md`, so the build skill does not restore a gate status or a model name. `update_status.py` no longer writes a release-gates row.
- `check/verify_page.py` gained two checks, the model names and the open-gate phrases, and now runs ten. Both were run against the previous build: they failed there with eleven problems, all of them the ones this pass removes.
- The AVA Library article was replaced under `acme-city-permits-architecture` with this build, and `STATUS.json` records the new publication time and hash.
- Kit builder and the Linux checker ran clean, `check/verify_page.py` passes, `repo/tests/integration/test_help_docs.py` passes, so the served bytes are the committed bytes.

## Revision 2026-11-02, picture lock and no nightly reset

- The nightly reset is gone from the blueprint and from the page. `render.yaml` holds one web service and no scheduled job. The Hosting section now says that the blueprint defines one web service, built from `repo/Dockerfile-demo`, and that every deploy rebuilds the demonstration data. The words "nightly" and "cron" and the time 02:00 appear nowhere on the page.
- The demo video is finished. Picture lock was reached on 2026-11-02. The page says so: the "In progress" chip, the "being recorded" sentence, the "Final pass" row about the drifting face and the "replaced at picture lock" sentence are gone. The video rows now carry the cut, the presenter, the voice, the screens, the file (720p, 179.7 s, about 3:00, 7.83 MB, preload none, no autoplay) and where it plays (the landing page of the live demonstration, under the persona cards).
- The collected test count on the page and in the fact sheet is 3819, counted on 2026-11-02 with `python -m pytest --collect-only -q`. The sentence about two held-submit checks landing later the same day is dropped.
- `check/verify_page.py` follows the page: the allowed figure list carries the collected count, the video length and size, and the date fragment of 2026-11-02.
- The build ran the same steps as before. `inline_assets.py` wrote `page/body.html` from `page/body.src.html`, the kit builder wrote the self-contained HTML, the Linux checker ran the kit checker in headless Chrome, and `check/verify_page.py` passed. `page/page.json` was set to an absolute output path for the build and restored to the portable relative value afterwards, because this workspace is a temporary worktree and a machine path must not enter tracked history.
- The kit checker passed with 11 writing warnings, the same kinds as before, and no functional problem. `repo/tests/integration/test_help_docs.py` passed, so the served bytes are the committed bytes.
- The rebuilt page lives on this branch. The copy in the main checkout is the one before this revision until the branch is merged.
- The AVA Library copy was not replaced in this revision.
