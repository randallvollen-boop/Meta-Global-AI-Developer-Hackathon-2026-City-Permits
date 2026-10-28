# Production readiness

ACME City permits runs in one of two deployment modes. Demo mode is the fictional demonstration that the judges use, with its behaviour unchanged. Production mode is opt-in and removes everything that exists only for the demonstration. This page lists the modes, every setting, the deploy, rollback, restore and key rotation steps, what is finished with its evidence, and what remains.

Production mode is a hardened core. It is not yet a finished product: real sign-in, a server database, backups and monitoring are still open (see "What remains"), and the deployment decision stays on hold until they are closed.

## The two modes

The mode comes from `ACME_DEPLOYMENT_MODE`. It is `demo` when unset.

| Area | Demo (default) | Production |
|---|---|---|
| Persona selector (`/api/session/select`, `/api/session/actors`, `POST /ui/actor`, the `/select` picker) | Mounted | Not mounted. `/select` shows "Sign-in is not configured" with HTTP 503 |
| "Demo controls: switch user" panel | Shown | Never rendered |
| Intake simulator (`/api/intake/simulate`, `/api/intake/scenarios`, the Governance "Simulate incoming permits" action) | Mounted | Not mounted; the action answers 404 and is not listed |
| Simulated GIS (Geographic Information System) service under `/sim/arcgis/...` | Mounted | Not mounted |
| Fixture replay (general Muse command, applicant assistant, what-if policy tasks) | Available | Refused or skipped; no recorded answer is ever substituted |
| Scenario clock (`ACME_SCENARIO_CLOCK`) | Honoured on a database marked as the demo | Always off; the setting is ignored with a warning |
| Database marked as the fictional demo | Normal | The service refuses to start; `/readyz` returns 503 if the marker appears later |
| `ACME_SECRET_KEY` | Optional; a warning is logged when the key is generated per process | Required; the service refuses to start without it |
| Staff and applicant pages without a session | Redirect to the persona picker | Redirect to "Sign-in is not configured" (503) |
| Application error details | Today's messages | Fixed message per status plus the stable `code` |
| API documentation (`/docs`, `/redoc`, `/openapi.json`) | Available | Not mounted |
| External AI provider | Allowed (existing caps and live switches still apply) | Denied unless `ACME_MUSE_PROVIDER_ENABLED=true` |
| Session cookie `Secure` attribute | Off | On |
| HSTS header (HTTP Strict Transport Security) | Not sent | Sent |

These parts apply in both modes: the security headers, the stable secret when one is configured, the `Secure` cookie option, trusted proxy handling, and the readiness check.

Every existing test, the start scripts, and the judged deployment run in demo mode and behave as before.

## Settings

| Setting | Demo default | Production default | Effect |
|---|---|---|---|
| `ACME_DEPLOYMENT_MODE` | `demo` | set to `production` | `demo` or `production`. Any other value stops the start |
| `ACME_SECRET_KEY` | generated per process (warning logged) | none; start refused | Signs session cookies and form tokens. Use at least 16 random characters |
| `ACME_COOKIE_SECURE` | off | on | `true` or `false`. Set `true` for a demo served over HTTPS |
| `ACME_TRUST_PROXY_HEADERS` | off | off | `true` makes the app honour `X-Forwarded-Proto` from a reverse proxy. Enable only when clients cannot reach the service directly |
| `ACME_MUSE_PROVIDER_ENABLED` | on | off | Global switch for every call to the external AI provider. Enforced in `muse/client.py` and `muse/image_client.py` |
| `ACME_DATABASE_URL` | `sqlite:///var/acme_city.db` | same (container image: `sqlite:////app/var/acme_city.db`) | Database location |
| `ACME_SCENARIO_CLOCK` | empty (start script uses `auto`) | ignored | Demo date |
| `META_API_KEY` | none | none | Provider credential. Leave unset until the AI controls below are closed |
| `ACME_APPLICANT_ASSIST_LIVE_ENABLED`, `ACME_POLICY_ASSIST_LIVE_ENABLED` | off | off | Task switches, checked in addition to the global switch |
| `ACME_MUSE_LIVE_CALL_CAP`, `ACME_MUSE_IMAGE_DAILY_CAP`, `ACME_MUSE_MODEL_ALLOWLIST` | 2, 10, `muse-spark-1.3` | same | Existing caps, unchanged |
| `ACME_GIS_BASE_URL`, `ACME_GIS_AUTO_PROPOSE_SCORE`, `ACME_DEMO_TIMEZONE`, `ACME_EVIDENCE_ROOT`, `ACME_KEY_FILE` | as before | as before | Unchanged |
| `ACME_RUN_MIGRATIONS`, `ACME_BIND_PORT`, `ACME_FORWARDED_ALLOW_IPS` | container entrypoint only | container entrypoint only | Skip the upgrade, listen port, proxy addresses uvicorn trusts |

The general Muse command (`/api/muse/run`) now defaults to the `replay` mode instead of `live`, so a command that omits the mode cannot spend a live call. A caller that wants a live run names `"mode": "live"`. In production a replay is refused and a live run is refused while the provider switch is off.

## Security headers

The CSP (Content Security Policy) and the other headers apply in both modes.

Both modes send these headers on every response:

- `Content-Security-Policy` (CSP) with `default-src 'self'`, `script-src 'self'`, `style-src 'self'`, `img-src 'self' data:`, `connect-src 'self'`, `object-src 'none'`, `base-uri 'self'`, `form-action 'self'` and `frame-ancestors 'none'`. No template or script uses an inline script or an inline event handler, so none is allowed.
- `style-src-attr 'unsafe-inline'`. About 80 inline `style="..."` attributes in 14 templates need it. An attribute can restyle an element but cannot run code. Moving them into the stylesheets is a cleanup that touches many templates and is left open.
- Downloaded HTML documents (the printable permit and the application copy) carry an inline `<style>` block and no script. They get their own policy: `default-src 'none'; style-src 'unsafe-inline'`.
- In demo mode only, `/docs` and `/redoc` use a policy that allows the public CDN (content delivery network) those generated pages load from.
- `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `X-Frame-Options: DENY`, and a `Permissions-Policy` that turns off camera, microphone and location.
- `Cache-Control: no-store` on HTML and JSON answered to a request that carries a session cookie. Static files stay cacheable.
- `Strict-Transport-Security` in production only.

## Deploy

Prerequisites: a TLS (Transport Layer Security) terminating reverse proxy in front of the service, a persistent volume for `/app/var`, and a secret store that holds `ACME_SECRET_KEY`.

1. Build once from a recorded commit: `docker build --target production -t acme-permits:<commit> repo/`. The production target omits `scripts/` (reset, loaders, walkthrough) and `fixtures/replay`.
2. Back up the database and `var/documents` (see "Backup and restore").
3. Start with `ACME_DEPLOYMENT_MODE=production`, `ACME_SECRET_KEY`, `ACME_COOKIE_SECURE` left at its default, and `ACME_TRUST_PROXY_HEADERS=true` plus `ACME_FORWARDED_ALLOW_IPS=<proxy address>` when the proxy sets `X-Forwarded-Proto`. The compose file has a `production` profile: `docker compose --profile production up -d`.
4. The entrypoint runs `alembic upgrade head` once, then starts uvicorn. Run only one instance, or set `ACME_RUN_MIGRATIONS=false` on all but a single migration job.
5. Admit traffic only after `GET /readyz` returns 200. `/healthz` stays a liveness probe.
6. Expect staff pages to show "Sign-in is not configured" until identity is connected.

The container build and run are not exercised by the automated checks in this repository. `docker compose config` and `docker build --check` validated the files; no image was built or started for this change.

## Rollback

1. Stop writes (stop the container or switch the proxy to a maintenance page).
2. If the new release did not change the schema (same Alembic head), start the previous image tag.
3. If it did, do not rely on `alembic downgrade`: migration 0013 drops the support cases table on downgrade. Restore the database and documents from the backup taken before the deploy (below), then start the previous image.
4. Check `/readyz`. It returns 503 when the stored revision is not the head of the running build, which also catches an old image started on a newer database.

## Backup and restore

SQLite is acceptable only for a bounded single-instance pilot. The database file and the uploaded documents form one unit and must be copied together.

Backup (service stopped or writes paused):

1. `sqlite3 var/acme_city.db ".backup 'backup/acme_city.db'"`
2. `tar -C var -czf backup/documents.tgz documents`
3. Record both file hashes next to the backup.

Restore into an isolated environment first:

1. Put the database and the document archive in an empty `var/`.
2. Start in production mode with the same `ACME_SECRET_KEY` (or accept that every user signs in again).
3. Confirm `/readyz` returns 200, then open a few documents. Each read verifies the stored bytes against the recorded hash.
4. Repeat on the live volume only after the isolated restore passes.

An automated schedule, off-host copies, encryption and a measured recovery time are still open.

## Key rotation and forced logout

`ACME_SECRET_KEY` signs the session cookie and the form tokens.

1. Generate a new value: `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
2. Store it in the secret store and restart the service with it.
3. Every existing cookie fails its signature check, so every person is signed out. This is also the way to force a global logout.
4. Keep the previous key out of the new deployment. There is no dual-key window.

An individual session can be ended by revoking its row in the `sessions` table (set `revoked_at`) or by `DELETE /api/session` while signed in.

## Where real sign-in plugs in

OIDC (OpenID Connect) is not implemented. The seam is `src/acme_city/auth/identity.py`:

- `IdentityProvider` is the interface: `configured`, `begin_login(request)` and `complete_login(request)`, which returns a `VerifiedIdentity` (issuer and subject, never a role).
- `NotConfiguredIdentityProvider` is the production default. It is what makes every staff route answer "Sign-in is not configured".
- `build_identity_provider(settings)` is the one place to return a real provider.
- `SessionService.establish_session(actor_id)` creates the server-held session for the actor that a verified identity maps to. Grants stay in the database; the provider never states a role.

Steps to connect a provider: implement the interface, add a table that maps issuer and subject to one actor, mount the login and callback routes in `create_app` for production only, and add tests for two applicants and each staff role.

## What is done, with evidence

| Item | Evidence |
|---|---|
| Deployment mode setting, validated at load | `tests/unit/test_deployment_mode.py` |
| Production removes the selector, switch panel, simulators, replay, API docs; staff routes show "Sign-in is not configured" | `tests/security/test_production_mode.py` (direct URL and API negative tests) |
| Production refuses a demo database and a missing secret; scenario clock off | `tests/security/test_production_mode.py`, `tests/unit/test_deployment_mode.py` |
| Demo mode unchanged | The existing acceptance, API, UI, security, supplementary and browser tests run unedited in demo mode; `tests/security/test_production_mode.py` pins the demo side |
| Secure cookie setting, trusted proxy handling | `tests/security/test_production_mode.py` |
| Security headers and CSP | `tests/security/test_production_mode.py`; the browser tests under `tests/browser` run with the CSP active |
| Global AI switch at provider dispatch | `tests/unit/test_deployment_mode.py` (text and image clients make no network call when off) |
| Readiness endpoint with stale revision check | `tests/security/test_production_mode.py` |
| Sanitized error envelopes in production | `tests/unit/test_deployment_mode.py`, `tests/security/test_production_mode.py` |
| Work queue loads assessments in one query | `tests/ui/test_queue_queries.py` |
| Dockerfile, compose file, entrypoint, continuous integration workflow | Syntax validated only (`docker compose config`, `docker build --check`); not built or run |

## What remains

Effort follows the review: S is under 2 hours, M about half a day, L a day or more.

| Item | What is needed | Effort |
|---|---|---|
| OIDC sign-in | Implement `IdentityProvider`, map issuer and subject to actors, applicant ownership, deactivation and session revocation | L |
| PostgreSQL | A driver, dialect-aware connection hooks and health queries (they use SQLite `PRAGMA` and `sqlite_master`), migration and concurrency tests | L |
| Backups and restore | Scheduled coordinated copies of database and documents, encryption, a restore drill, recovery objectives | L |
| Malware scanning and upload limits | Quarantine and scanning, aggregate request quotas, streaming reads, safe download headers, document lifecycle reconciliation | L |
| Monitoring and alerts | Structured redacted logs, request identifiers, metrics for latency, errors, storage, outbox age, AI failures and backup age, an assigned operator | L |
| AI cost reservations | Atomic attempted-call, token and cost reservations, bounded input, per-user limits, a reset for the circuit breaker, provider data approval and retention rules | L |
| Accessibility audit | WCAG (Web Content Accessibility Guidelines) 2.2 AA review with keyboard, screen reader, zoom and contrast checks | L |
| Production business authority | A separate bootstrap with approved rules, fees and real role holders; the demo banner and footer text in `base.html` still say "fictional demonstration" | L, needs outside approval |
| Rate limiting | Shared or edge limits for sign-in, uploads and expensive actions | M |
| CSRF (cross-site request forgery) checks on cookie-authenticated JSON writes | Uniform origin or token checks beyond the interface forms | M |
| Remaining queue queries | The work queue still issues several queries per application for blockers and next actions; add scope filters and pagination | M |
| Inline style attributes | Move them into stylesheets and drop `style-src-attr 'unsafe-inline'` | M |
| Simulated source actions | The simulated ERP (enterprise resource planning) payment import and source record write actions are not blocked in production | S |
| Installed artifact test | Test the image outside the checkout, plus an upgrade test from the previous release | M |
