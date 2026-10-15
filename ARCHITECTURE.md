# Outbound pipeline: architecture

Status: draft v0.1, 2026-10-14. Stage 1 (sourcing) is built and tested offline. Later stages are designed here, not built.

## 1. The idea in one paragraph

A lead is one company we might email, for one ICP. It moves through fixed stages (sourced, enriched, verified, queued). Each stage is a small module that reads leads at its input stage from one SQLite file, does one job, and writes them back at the next stage. Every outside tool (Apollo, Google, FullEnrich, Clay, Instantly, Pipedrive or HubSpot) sits behind an adapter with a fixed interface, chosen by name in config. So when the ICP, a tool, a plan or a mailbox changes, we edit YAML or swap one adapter; the stages and the lead format stay the same.

## 2. Stages

| # | Stage | Input → output | Adapter interface | Default adapter | Status |
|---|---|---|---|---|---|
| 1 | Sourcing | ICP + country → `SOURCED` | `LeadSource` | Apollo People Search, Google Places | built |
| 2 | Enrichment | `SOURCED` → `ENRICHED` (email, owner, source URL) | `EmailFinder` | FullEnrich API (Clay CSV as fallback) | module in flux |
| 3 | Verification | `ENRICHED` → `VERIFIED` or `DROPPED` | `Verifier` | Instantly verification API for catch-all/risky | decided |
| 4 | Compliance gate | runs inside 3 → 4 | (rules, no adapter) | per-country rules in `countries.yaml` | designed |
| 5 | Routing | `VERIFIED` → campaign name | (rules, no adapter) | rules in `campaigns.yaml` | designed |
| 6 | Sending | `VERIFIED` → `QUEUED` | `Sender` | Instantly `/api/v2/leads/add` | proposed |
| 7 | Feedback | events → suppression list, CRM | `Crm`, event source | Pipedrive or HubSpot | proposed |
| 8 | Report | analytics → daily message | `Reporter` | Instantly analytics overview | proposed |

Each stage can be run on its own from the CLI, so a manual step (e.g. a Clay CSV round trip) can sit between any two of them without code changes: `export` writes the CSV, and an `import` command (built with stage 2) reads it back.

## 3. Data contract

Defined once in `src/outbound/models.py`. Stages only add their own fields; nothing upstream is overwritten.

```
Lead
  key, icp, country           identity: one row per (icp, key); key = "d:<domain>" or "n:<country>:<name>"
  company   {name, domain, website, phone, city, address, industry, employees, legal_name}
  contact   {first_name, last_name, title, linkedin_url}
  sources, source_ids, signals    who found it, their ids, e.g. "hiring:react developer"
  stage, drop_reason
  email, email_source_url, email_provider     ← enrichment
  email_status                                ← verification
  campaign, personalization{}                 ← routing / copy
```

The raw payload of every provider hit is stored as-is (`raw_records` table), so if we map a field wrongly we fix the mapper and re-read, not re-pay.

## 4. Config (what you edit, not code)

```
config/
  settings.yaml      db path, provider URLs, which env var holds each key, monthly request caps
  countries.yaml     US / UK / AU: names per provider + compliance flags + email footer
  icps/<id>.yaml     one per ICP: countries, disqualifiers, and a block per source with its filters
  campaigns.yaml     (stage 5) routing rules → campaign names like A_UK_Signal_v1
  accounts.yaml      (stage 6) sending mailboxes, daily caps, which campaigns each serves
```

Adding ICP D or a new country is a new YAML file or block. Adding a source (Apify jobs, Crunchbase, a CSV drop) is one adapter class plus one line in the registry. Secrets only in environment variables (`.env`, never committed).

## 5. Rules built into the frame

- Dry run by default. Anything that calls an API needs `--live`; a dry run physically cannot reach the network.
- Budget guard. Every request is counted per provider per month before anything else happens; a request past the cap in `settings.yaml` is refused (Google Places is capped at its 1,000 free requests).
- Idempotent. Re-running a stage merges into existing leads instead of duplicating them.
- Suppression first. Email and domain suppression is checked at sourcing and again before sending; nothing is ever removed from it.
- Failures are contained. One provider failing stops that provider only; results already paid for are kept.
- Compliance per country. Australia: no email without `email_source_url`. UK: limited companies only. Enforced at the gate before sending, where that data exists.

## 6. What the Section 1 playbook needs, and where it lands

| Playbook needs | Where it fits |
|---|---|
| 4 ICPs, 3 countries, different headcounts | one ICP file each; `countries.yaml` |
| Campaign per ICP x country x type (`A_UK_Signal_v1`) | routing rules (stage 5) |
| Signal-based vs pain-based campaign by what enrichment found | `Lead.signals` + routing rules |
| Suppression list, domain-level blocks, pre-import check | `suppression` table, checked at sourcing and sending |
| Australia published-source proof, UK Ltd only | compliance gate |
| Bounce over 2% pauses | verification + Instantly auto-pause |
| HubSpot (playbook) vs Pipedrive (Section 2) | `Crm` adapter, pick one in config |
| MillionVerifier (playbook) vs Instantly check (Section 2) | `Verifier` adapter |
| n8n for webhooks | not needed for the pipeline; a webhook receiver is a later stage-7 adapter |

## 7. Known gaps and open checks

- Apollo's free search docs publish no response schema; one integration reports last names are obfuscated and it is unclear whether the company domain is returned. The mapper reads defensively and keeps the raw payload; the first live call (0 credits) settles it. If there is no domain, Apollo leads dedupe by name + country and enrichment must find the domain.
- Apollo industry names must match Apollo's own list exactly; confirm the names in the ICP files against the Apollo UI.
- A lead keyed by name (no domain) and the same company keyed by domain from another source are not merged yet. Enrichment can re-key once it finds the domain.
- SQLite is fine for thousands of leads on one machine. If several people run it at once, swap the `Store` for Postgres; nothing else changes.
