# Plan

What's built, what's next, and what's decided. Facts and prices: [research.md](research.md).
How each page works: [guide.md](guide.md).

## Stages

The one list everything follows (`backend/pipeline.py`). The Pipeline page shows it.

| Stage | Built | Reads | Writes |
|---|---|---|---|
| source | yes | — | sourced |
| enrich | yes | sourced | enriched, verified, needs_check, hold, dropped |
| verify | rules only (Clay's result) | enriched, needs_check | verified, needs_check, hold, dropped |
| personalize | no | verified | personalized |
| qa | no | personalized | approved, hold |
| send | no | approved | in_campaign |
| track | no | in_campaign | replied, bounced, unsubscribed, finished |
| classify | no | replied | finished, dropped |

## Built

| Module | What works |
|---|---|
| M0a Foundation | Supabase Postgres shared by two laptops (SQLite for tests), stage list, `outbound check` and `backup`, CI on SQLite and Postgres |
| M0b App | `outbound serve`: the local web app for everything below |
| M1 ICPs + Source | ICPs on an app page with settings per source; Apollo sourcing per ICP, with the job-post signal; one Clay file per ICP; Clay import with the verify rules |
| M1b Google Maps | Places API (New) Text Search as the second source: phrase x city searches, request cap, skips closed, no-website and chain places |

Waiting for Wania's go-ahead: the first live Apollo run of `dev_us_signal` (1 page, 1 credit) and
the first live Google Maps run (1 search, 1 page, 1 request).

## Build order ahead

One module at a time; each is usable in the app and ships with its `guide.md` section. Pilot:
lists built by 8 Nov, launch 9–15 Nov, so M2–M5 should work by about 7 Nov.

| Step | What | Needs |
|---|---|---|
| M2 | Enrich: the Clay round trip per ICP at pilot scale | D3 |
| M3 | Verify: Instantly's verifier for needs_check | D4, D5 |
| M4 | Personalize + QA + review queue | D13 if AI line |
| M5 | Send: Instantly campaigns created by code | D6–D9, D16 |
| M6 | Track + classify replies | D6, D11 |
| M7 | Follow-up campaigns + weekly report | — |

Pilot sequence: 4 steps (day 1, 3, 7, 14), send window 9–11am Eastern. Success test: a positive
reply rate of 2% or more after 300 delivered emails.

## Decisions

| # | Question | Decision |
|---|---|---|
| D1 | Which source for which ICP? | Chosen per run in the app: Apollo, Google Maps, or both. Apify is dropped. |
| D2 | Google Maps | Google Places API (New), Text Search. Wania accepts the Google terms risk (storing names, websites, addresses, phones). Ask only for id, displayName, websiteUri, formattedAddress, addressComponents, nationalPhoneNumber, types, primaryType, businessStatus; never reviews or photos. Cap: 1,000 requests a month (the free allowance). Likely chains (3+ places on one website) skipped by default, per ICP. |
| D3 | Emails | Clay only, by CSV out and in (Clay Free/trial has no API); no Google Sheet. Company filters go to the sources; people filters (titles, person locations) go into Clay's "Find people". Number of Clay accounts: open; credits are recorded per batch. |
| D4 | Email check | Clay "valid" = verified. Catch-all or unknown = needs_check, re-checked with Instantly's verifier. Role addresses = hold until D5. |
| D5 | Role-based emails (`info@`) | **Open.** Suggestion: drop them. |
| D6 | Instantly plan | Growth (1,000 contacts total, 5,000 emails a month, no webhooks). Campaigns created by code. A finished lead's outcome is saved before it's removed from Instantly. |
| D7 | Inboxes | **Open.** Need numbers. |
| D8 | CAN-SPAM details | **Open.** |
| D9 | Sequence and campaigns | Follow the Miro campaign logic; campaigns created in Instantly by code. |
| D10 | Apollo | Apollo Basic, Organization Search only (1 credit per 100 companies). No person enrichment. |
| D11 | Re-contact | **Open.** Suggestion: once per offer. |
| D12 | Database | Supabase Postgres, shared by two laptops; SQLite for tests. |
| D13 | AI-written first line | **Open.** Snooze until sending works. |
| D14 | UI | FastAPI + React (Vite), on 127.0.0.1 only. |
| D15 | Where targets live | ICPs, on an app page, stored in Supabase. Caps stay in `config/settings.yaml` as hard stops. |
| D16 | Parked until just before M5 | Developer offer details; Arsuno's legal name and postal address (D8); inbox warmup on arsuno.io and arsuno.si (D7); tracking (Miro has none on day 1, but its follow-ups depend on clicks and opens). |
| D17 | Sources and ICPs | An ICP says who we target, not where to look. Every source saves into the same companies table (one row per domain, do-not-contact checked) and the same Clay flow. No niche-specific code. |
| D18 | Pilot campaigns | The 3 pilot ICPs are the 3 pilot campaigns. Run `dev_us_signal` before `dev_us_pain`, so Signal keeps the companies they share. |
| D19 | Exclusions | Applied in Clay, by hand, from the ICP's "Exclude" note. Apollo's company search returns no industry. |
