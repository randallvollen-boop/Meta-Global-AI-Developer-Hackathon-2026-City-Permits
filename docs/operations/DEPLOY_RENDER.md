# Deployment runbook: the public demonstration on Render

This is the single runbook for the hosted demonstration: first setup, every later deploy, the smoke check, live Muse for judging, the nightly reset and rollback. Other documents point here.

This document sets up the public ACME City permits demonstration on Render. The live address is `https://acme-city-permits.onrender.com`. The custom domain `permits.vollendata.com` is the intended address; it did not respond when last checked, so do not rely on it. The service runs in `demo` mode with fictional data only. Anyone who opens the site can act as any of the five personas, so the deployment adds rate limits, a request size limit and a visible notice.

The blueprint is `render.yaml` at the repository root. It was written and tested without calling Render, so Render reports any field it does not accept when the Blueprint is created.

## What the deployment does

- **One web service**, built from `repo/Dockerfile-demo`. That file builds the same image as `docker build --target demo` of `repo/Dockerfile`, because Render builds the last stage of a Dockerfile and has no field for a build target. A test keeps the two files in step. The production target leaves out the demonstration scripts and refuses `ACME_DEMO_SEED_ON_START`.
- **No disk.** The SQLite database lives on the container filesystem. Every start deletes it and rebuilds it.
- **Seeding on start.** With `ACME_DEMO_SEED_ON_START=1` the entrypoint prepares the same state as the local demonstration, then starts the server:
  1. `prepare_user_test.py --mode ready-for-review` (resets the database, runs the recorded Muse replay walkthrough, no live call);
  2. `load_synthetic_year.py --seed 20261028 --count 600`;
  3. `load_steward_demo.py`.

  `ACME_SCENARIO_CLOCK=auto` sets the demonstration date from the data. A failed step stops the start, so Render keeps the previous deploy running. On a laptop the whole sequence took about 10 seconds before the readiness check passed.
- **Nightly reset.** A Render cron job calls the web service's deploy hook at 02:00 Coordinated Universal Time (UTC). The redeploy rebuilds the data. Render keeps the old instance serving until the new one passes `/readyz`.
- **Port.** The entrypoint listens on `PORT` (set by Render), then `ACME_BIND_PORT`, then 8000.

People who are signed in as a persona at 02:00 UTC lose their session and any unsaved work when the redeploy completes. The data is meant to be disposable.

## Protection settings

All limits count requests per minute for one client address. A setting of `0` switches that limit off. The code default is off, so tests and the local demonstration are unaffected. `render.yaml` turns them on.

| Setting | In `render.yaml` | What it limits |
|---|---|---|
| `ACME_RATE_LIMIT_ALL_PER_MINUTE` | 300 | Every request except `/readyz`, `/healthz` and `/ui/static` |
| `ACME_RATE_LIMIT_WRITE_PER_MINUTE` | 60 | Requests that are not GET, HEAD or OPTIONS |
| `ACME_RATE_LIMIT_SESSION_PER_MINUTE` | 20 | Persona and session switches (`/ui/actor`, `/ui/end`, `/api/session/select`, `DELETE /api/session`) |
| `ACME_RATE_LIMIT_UPLOAD_PER_MINUTE` | 10 | Multipart (file upload) requests |
| `ACME_MUSE_LIVE_CALL_CAP` | 2 | Live Muse calls in total since the data was last rebuilt, across every visitor and every Muse button (see Live Muse below) |
| `ACME_MUSE_DAILY_CALL_CAP` | not set (code default 10) | Provider calls per day, shared by every path that can reach the provider |
| `ACME_MUSE_IMAGE_DAILY_CAP` | 10 | Live Muse image calls per day |
| `ACME_MAX_REQUEST_BYTES` | 26214400 | Largest request body (25 MB). The code default is 32 MB, `0` switches it off |

A request counts against every limit that applies to it. A persona switch, for example, counts against the first three. A refused request spends nothing. Each limit is a token bucket: the full allowance is available at once, and tokens return at an even rate. An address that goes over receives a 429 page in the application's style (a JSON body for API callers) with a `Retry-After` header. A body over the size limit receives 413.

The limits live in memory in one process. They reset when the service restarts, and they stop one visitor from hammering the demonstration. They do not stop a distributed attack. Keep the instance count at 1: a second instance would hold its own copy of the data and its own counters.

### Client address and the trusted proxy setting

Render terminates Transport Layer Security (TLS) and forwards requests to the container. The service has to know it is behind that proxy for two reasons: so the secure cookie and links use https, and so the rate limits count the visitor and not Render.

`ACME_TRUST_PROXY_HEADERS=1` makes the application:

- honour `X-Forwarded-Proto` (secure scheme);
- take the client address for rate limits from `X-Forwarded-For`.

The address is the **right-most entry that is not a trusted proxy**. Each proxy appends the address it received the request from, so the right-most entries come from Render and the left-most entries are whatever the visitor claimed. A visitor who sends a forged `X-Forwarded-For` only adds entries on the left, so the forged value is never read. Private, loopback and link-local addresses are treated as infrastructure and skipped. `ACME_TRUSTED_PROXY_HOPS` skips that many more entries from the right, for a known extra proxy such as a content delivery network (CDN). When no usable entry is left, the address of the direct connection is used. With the setting off, `X-Forwarded-For` is ignored.

The risk: with the setting on, any caller who can reach the container without passing through Render could claim https and choose its own address, which would let it pick a fresh rate-limit bucket for every request. On Render the container is reachable only through Render's proxy, so the setting is safe there. Do not copy it to a deployment where the container has a public port of its own. `ACME_FORWARDED_ALLOW_IPS` stays at its default (`127.0.0.1`) so uvicorn does not rewrite the connection address on its own.

Check once after the first deploy that visitors are counted separately (step 9 below). If every visitor shares one limit, Render's chain ends in a public proxy address. Set `ACME_TRUSTED_PROXY_HOPS` to `1` and redeploy.

## Steps

1. **Give Render access to the repository.** In Render, open Account Settings, then GitHub, and install or configure the Render GitHub app so it can read `randallvollen-boop/Meta-Global-AI-Developer-Hackathon-2026-City-Permits`. The repository must contain `render.yaml` and `repo/Dockerfile-demo` on the branch Render deploys (the default branch unless set otherwise).

2. **Create the Blueprint.** In Render choose New, then Blueprint, pick the repository and branch, and confirm. Render reads `render.yaml` and proposes two services: `acme-city-permits` (web) and `acme-city-permits-nightly-reset` (cron job).

3. **Choose the instance type.** `render.yaml` leaves `plan` unset on both services on purpose. In the Blueprint form (or later under each service's Settings) pick the paid instance type already on the account for the web service. Do not use a free instance: it sleeps when idle, so the first visitor would wait for a cold start and a full data rebuild. The cron job runs for seconds each night and takes the smallest type Render offers. Keep the web service at 1 instance.

4. **Fill the prompted variables.** Render asks for the two values marked `sync: false`:
   - `META_API_KEY`: leave it empty. Live Muse stays off (see step 7).
   - `ACME_DEPLOY_HOOK_URL` (cron job): leave it empty for now. It is filled in step 6, because the hook does not exist until the web service does.

   Apply the Blueprint. The first build and start take a few minutes. `ACME_SECRET_KEY` is generated once by Render and stays the same across deploys.

5. **Add the custom domain.**
   1. In Render, open `acme-city-permits`, then Settings, then Custom Domains, and add `permits.vollendata.com`. Render shows the hostname to point at, in the form `acme-city-permits.onrender.com` (use the exact name Render shows).
   2. In Netlify, open Domains, then `vollendata.com`, then DNS records, and add a record of type CNAME, name `permits`, value the Render hostname. Leave other records unchanged. The Domain Name System (DNS) records for the domain stay in Netlify.
   3. Back in Render, press Verify on the custom domain. Render issues and renews the TLS certificate itself once the CNAME resolves. It can take several minutes. The `onrender.com` address keeps working in the meantime.

6. **Set the deploy hook for the nightly reset.**
   1. In Render, open `acme-city-permits`, then Settings, then Deploy Hook, and copy the URL.
   2. Open `acme-city-permits-nightly-reset`, then Environment, edit `ACME_DEPLOY_HOOK_URL`, paste the URL, and save.
   3. Press Trigger Run on the cron job once. The log should say `deploy hook answered 200`, and the web service should start a new deploy.

   The URL is a secret: anyone who holds it can start a deploy. Keep it out of the repository, chat and tickets. If it leaks, use the Regenerate button beside the hook in Render and update the cron job variable. If the cron job cannot be used, the manual alternative is to press Manual Deploy, then Deploy latest commit, on the web service each time the data should be reset. The schedule is in UTC (`0 2 * * *`).

7. **Live Muse.** Leave it off. Turning it on for judging is a separate step, below.

8. **Run the smoke check** (below).

9. **Check the limits.** Open the site from two networks (for example a laptop and a phone on mobile data) and confirm that both load normally. Then send more than 300 requests from one of them in a minute and confirm that only that one receives the "Too many requests" page. If both are blocked together, apply the hop setting described above.

10. **Roll back to a previous deploy.** See Rollback below.

## Deploy a new version

`autoDeploy` is off, so a push never changes the live demonstration by itself.

1. Randall approves the push, and main is pushed to `randallvollen-boop/Meta-Global-AI-Developer-Hackathon-2026-City-Permits`.
2. In Render, open `acme-city-permits` and press Manual Deploy, then Deploy latest commit. The lead may trigger the same deploy through the Render API instead.
3. Wait until the deploy shows Live. Render keeps the old instance serving until the new one passes `/readyz`.
4. Run the smoke check.

Every deploy rebuilds the data from nothing, so it is also a reset.

## Smoke check

Run it after every deploy and every rollback. Use the `onrender.com` address.

1. `/readyz` returns HTTP 200 with `"status":"ready"`, `"mode":"demo"` and `"schema_at_head":true`, and `schema_revision` equals `expected_revision`. Today that revision is `stw_registry_automation`. It changes whenever a migration merges.
2. `/select`, `/lifecycle` and `/walkthrough` return 200. `/select` and `/city/` show the line "This is a public demonstration with fictional data. It resets every night. Don't enter real personal information."
3. Choose each persona in story order and check where it lands:

   | Persona | Lands on |
   |---|---|
   | Applicant | `/city/` |
   | Agent Operator | `/agents` |
   | Data Steward | `/steward` |
   | Permit Reviewer | `/queue` |
   | City Administrator | `/overview` |

4. Press Demo controls at the bottom left and confirm it switches between the personas.

## Live Muse for judging

Live Muse stays off until judging, and Randall turns it on himself. The live service holds:

| Setting | Value now |
|---|---|
| `ACME_MUSE_PROVIDER_ENABLED` | 0 |
| `ACME_APPLICANT_ASSIST_LIVE_ENABLED` | 0 |
| `ACME_POLICY_ASSIST_LIVE_ENABLED` | 0 |
| `ACME_MUSE_LIVE_CALL_CAP` | 2 |
| `ACME_MUSE_IMAGE_DAILY_CAP` | 10 |
| `META_API_KEY` | not present (Render drops a variable left empty) |

### How the limits really work

- `ACME_MUSE_LIVE_CALL_CAP` is not per visitor and not per session. The service counts every completed live model run in the database. At 2, live Muse stops after two live calls in total, from anyone, until the data is rebuilt.
- One recorded provider error stops every further live call until the data is rebuilt, whatever the cap says.
- `ACME_MUSE_DAILY_CALL_CAP` (code default 10, not set in `render.yaml`) caps provider calls per day across every path.
- Randall chooses the cap for judging. Until he does, it stays at 2.

### Turn it on

1. In Render, open `acme-city-permits`, then Environment, then Add Environment Variable. Add `META_API_KEY` with the key.
2. Set `ACME_MUSE_PROVIDER_ENABLED` to `1`. Set `ACME_APPLICANT_ASSIST_LIVE_ENABLED` and `ACME_POLICY_ASSIST_LIVE_ENABLED` to `1` if the help assistant and the council briefing should answer live.
3. Set `ACME_MUSE_LIVE_CALL_CAP` to the number Randall chose for judging.
4. Save. Render redeploys by itself, which also resets the live call count. Run the smoke check.

The key is never sent to a browser, and seeding never uses a live call.

### See that live calls stopped

Once a limit is reached, a live attempt is refused before any request leaves the service. It is recorded as a failed live run carrying one of these reasons; the code does not quietly switch that attempt to the replay:

- "the live call budget of this build run is exhausted" (the cap is used up);
- "a previous live run recorded a provider error; no further live call is sent" (the error stop).

The reason shows wherever the screen lists the run, for example the Muse run panel of the permit workspace.

### Recover

Rebuild the data: press Manual Deploy, then Deploy latest commit, or trigger the deploy hook. The count starts again at zero and the error stop clears. Check the provider first if the stop came from an error.

### Turn it off

Set `ACME_MUSE_PROVIDER_ENABLED` back to `0`, and the two assistant flags to `0`, then save. The key may stay, because the provider switch blocks every call.

### Steward assistant

The Steward assistant lane starts after the current fixes merge. Its Muse button uses the same `ACME_MUSE_PROVIDER_ENABLED` switch and the same limits. Add its own switch here if the lane introduces one.

## Nightly reset

The cron job `acme-city-permits-nightly-reset` calls the web service's deploy hook at 02:00 UTC. It needs `ACME_DEPLOY_HOOK_URL`, a secret Randall sets in the dashboard. Until it is set, every nightly run fails and the data is not reset.

Find the hook under `acme-city-permits`, then Settings, then Deploy Hook. Paste it into the cron job's Environment as `ACME_DEPLOY_HOOK_URL`, save, and press Trigger Run once. The log should say `deploy hook answered 200`. Step 6 above has the details and what to do if the URL leaks.

## Rollback

In Render, open `acme-city-permits`, then Events, find the last good deploy and press Rollback. The previous image starts and replaces the current instance when `/readyz` passes. Then run the smoke check.

The database lives on the container and is rebuilt on every start, so a rollback across a migration needs no separate reset: the older image builds its own schema from nothing. Settings changed in the Environment tab are not rolled back. Check the live Muse settings after a rollback.

## Changing a setting

Edit it under the web service's Environment tab and save, or change `render.yaml` and sync the Blueprint. Either way Render redeploys, and the data is rebuilt. Setting names and meanings for the application are in `PRODUCTION_READINESS.md`.

## What was and was not verified

- Verified locally: the `demo` image built from both Dockerfiles (identical image), a container run with the blueprint's variables and `ACME_DEMO_SEED_ON_START=1` reached `/readyz` 200, listed the four personas that existed at that time, loaded 600 synthetic permit applications and the three steward links, and showed the notice. The tests are in `repo/tests/security/test_public_demo_protection.py`.
- Not verified: anything that needs Render or Netlify. That covers the Blueprint field names, the cron job runtime, whether Render accepts the build, the exact form of Render's `X-Forwarded-For`, the certificate issue and the rollback screen.
