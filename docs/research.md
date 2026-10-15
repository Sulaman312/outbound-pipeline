# Research: what the tools can do, what they cost, and the rules

Date: 2026-10-15. Scope: cold email to US companies with 1–20 employees, for two offers:
AI automation, and outsourced front-end developers. Tools looked at: Apollo and Google Maps
(finding companies), Clay (finding people and emails, CSV in and out only), Clay plus Instantly
(checking emails), Instantly (sending).

**How this was researched.** This environment blocks opening web pages directly, so every fact
below comes from web searches limited to each vendor's own docs where possible. The searches
return quoted text from those pages. Three labels are used:

- **Conflict**: the vendor's own pages disagree. Check in the account before relying on it.
- **Unconfirmed**: couldn't be confirmed. Check on the first approved test call.
- **Estimate**: my own arithmetic, not a vendor number.

Everything without a label was stated by the vendor's docs or the official source.

## Contents

1. [Apollo](#1-apollo)
2. [Google Places API](#2-google-places-api)
3. [Clay](#3-clay)
4. [Email verification](#4-email-verification)
5. [Instantly](#5-instantly)
6. [Deliverability rules: Gmail, Yahoo, Microsoft](#6-deliverability-rules-gmail-yahoo-microsoft)
7. [US law](#7-us-law)
8. [The market: who replies, and how often](#8-the-market-who-replies-and-how-often)
9. [The facts that shape the design](#9-the-facts-that-shape-the-design)

---

## 1. Apollo

**Use for us:** find US companies with 1–20 employees, by API.

### Endpoints that matter

| Endpoint | Cost | What comes back |
|---|---|---|
| People API Search `POST /api/v1/mixed_people/api_search` | 0 credits | Apollo person id, first name, **masked last name** (like `Mo***s`), title, a `has_email` yes/no flag, and the employer's **name** with yes/no flags. **No email, no phone, no LinkedIn URL, no company domain.** |
| Organization Search `POST /api/v1/mixed_companies/search` | 1 credit per page (up to 100 companies) | Companies matching filters. Domain field in the response: **Unconfirmed**. Apollo's examples show `primary_domain` on organization objects, but those examples are from the enrichment endpoints. |
| People Enrichment `POST /api/v1/people/match` (also a bulk version) | 1 credit if an email or demographics are found, plus 8 for a mobile number, 0 if nothing found | Full name, work email, `email_status`, LinkedIn URL, employer with `primary_domain` |
| Organization Enrichment | 1 credit per company | Industry, headcount, revenue, location |

Useful search filters:

- `organization_num_employees_ranges[]`: headcount ranges written as `"1,10"` and `"11,20"`.
- `organization_locations[]`: where the company is. `person_locations[]` is where the person lives.
- `person_titles[]`, with `include_similar_titles` (fewer than 100 titles in total).
- `q_organization_keyword_tags[]`: company keywords.
- `q_organization_domains_list[]`: up to 1,000 domains.

Paging: up to 100 results per page and 500 pages, so 50,000 records per search at most.

`reveal_personal_emails` is off by default. Keep it off, because we want work emails.

### Plans and limits

- **Free:** Apollo's developer portal shows **100 credits a month** on Free (seen in the team's
  account, October 2026). Apollo's blog says 900 a year (about 75 a month); trust the portal.
- **Basic:** $49 per user per month billed annually, 30,000 credits a year. Professional is $79,
  Organization is $119 with 3 users minimum. These come from Apollo's own blog; check
  apollo.io/pricing.
- **Superseded:** the team's portal shows that Free has no API access to these endpoints at all.
  See "What the team's own test showed" below. The docs at the time said:
- **Free accounts must be registered with a work email** to use People Search, Organization
  Search and enrichment through the API. Free accounts on a personal email (gmail etc.) are blocked
  from these endpoints. Paid accounts aren't affected.
- **Rate limits (Free):** 50 requests a minute, 200 an hour, 600 a day on search endpoints.
- **Rate limits (paid):** 200 a minute, 6,000 an hour, 50,000 a day.
- **Conflict:** Apollo's help center says API access is on every plan, but its pricing page says
  API access is for Custom plans. The developer docs have a Free row in the rate-limit table and a
  work-email rule for free accounts, which supports "free works, with limits".

### Data quality

- Apollo claims about 97% email accuracy.
- Independent reviews say accuracy drops for small companies and for catch-all domains (defined in
  [section 4](#4-email-verification)).
- Reported bounce rates range widely: 4% in one 1,000-email test, 15–35% in user reports.
- No source gives numbers for companies under 20 employees specifically.

### Terms

- No using the API to copy or compete with Apollo, no reselling access, no getting around limits.
- Apollo data may not be used to let a third party train AI models.
- Apollo's DPA says that when a person asks for their data to be deleted, it must be deleted from
  downstream systems too. Just suppressing the person isn't enough.

### What the team's own test showed

In September 2026 a teammate built a small prototype: Apollo People Search, then bulk
enrichment, then CSV, plus a web page for review and AI-written first lines. Its saved results
are real Apollo responses (48 enriched people across 4 runs). Only field names and totals are
recorded here.

- **Enrichment does return the company fields we need.** `organization.primary_domain`,
  `website_url`, `estimated_num_employees`, `industry` and `keywords` were present on all 48.
- **Enrichment also returns `email_domain_catchall`.** Apollo marked all 48 emails `verified`,
  but **13 of 48 (27%) were on catch-all domains**. Apollo's "verified" is not "safe to send".
  The send rules must read the catch-all flag, not only the status.
- **`reveal_personal_emails=true` returned personal addresses for 13 of 48.** Keep it off.
- **Narrow filters shrink the pool fast.** Here's how many matches Apollo reported for two runs:

  | Filters | Matches |
  |---|---|
  | CEO, tech, US/UK, 11–50 staff, verified only | 2,046 |
  | Head of Ops, software, 1–10 staff, excluding 8 common tools, verified only | 27 |

  Check a segment's size before spending on it.
- **How the calls are made:**
  - The API key goes in the `x-api-key` header. Apollo's portal now warns that keys in URL
    parameters are being deprecated.
  - Search filters go as URL query parameters (`person_titles[]=...`) on a POST.
- **Cost seen:** about 1 credit per enriched person, so roughly 48 credits for 48 leads.
- **The Free plan has no API access to search or enrichment** (confirmed in the team's developer
  portal, October 2026). The key dialog says these APIs "aren't included in your Free plan and
  won't be accessible even with a master key. All paid plans include full API access." The listed
  endpoints include:
  - `people/bulk_match`, `people/match` and `people/show`;
  - `organizations/show`;
  - `mixed_people/api_search` and `mixed_companies/search`;
  - `phone/validate` and `agents/task`.
- So the September test runs either happened before this restriction, or on a trial. The warning
  icon on the old "lead scrape for arsuno.ai" key probably means it lost access (**Unconfirmed**).

### What it means for us

- **Decision (2026-10-15):** the team bought Apollo Basic (see D10 in the plan).
- **First live run (2026-10-15):**
  - The `ai_accounting` segment found about 82,300 matching companies. Of the first 100, 96 had
    a website.
  - Organization Search left our employee, country, city and industry columns empty for all
    100. Either it doesn't return those fields or it names them differently. `outbound fields`
    lists what it did send.
  - Until that's known, the "not US" and "over 20 staff" checks can't fire, and we rely on
    Apollo's own filters. Person enrichment returns full company details (seen in the
    teammate's data), so those checks can run at the email step at no extra cost.
  - About 1 in 10 results were off-target, matching the keyword "accounting" without being
    firms: a podcast, a Malta job board, staffing agencies, a trade publication, a course
    provider.
- **Update (October 2026):** Apollo Free can't be used by API at all for this. The points below
  hold only on a paid plan (Basic $49/user/month billed annually, 30,000 credits a year; the
  monthly-billing price is **Unconfirmed**). Apollo has no free trial of its paid plans.
- On a paid plan, Apollo is good for **finding companies**: 1 credit per 100 companies through
  Organization Search. It's also good for **seeing who works there** (People Search, free).
- On Free it is **not an email source** either: about 100 credits a month.
- Apollo's website on Free allows CSV export, but only 25 records at a time, and each net-new
  person with an email costs 1 credit.
- People Search results can't go straight into email finding, because last names are masked and
  there's no domain. So the flow is: companies (with domain) from Apollo, then Clay finds the
  person and the email.
- The Apollo account must be on a work email.

Sources:
[People API Search](https://docs.apollo.io/reference/people-api-search) ·
[Find people using filters](https://docs.apollo.io/docs/find-people-using-filters) ·
[Organization Search](https://docs.apollo.io/reference/organization-search) ·
[People Enrichment](https://docs.apollo.io/reference/people-enrichment) ·
[API pricing and credits](https://docs.apollo.io/docs/api-pricing) ·
[Rate limits](https://docs.apollo.io/reference/rate-limits) ·
[Developer FAQs](https://docs.apollo.io/docs/developer-faqs) ·
[Use Apollo API](https://knowledge.apollo.io/hc/en-us/articles/4416173158541-Use-Apollo-API) ·
[Pricing](https://www.apollo.io/pricing) ·
[What Apollo's pricing includes](https://www.apollo.io/insights/more-information-on-what-they-are-paying-for-in-apollo-plan-detailsusage-walkthrough) ·
[API terms](https://www.apollo.io/terms/api) ·
[DPA](https://www.apollo.io/dpa) ·
[Accuracy review (third party)](https://inboundlabs.app/blog/how-accurate-is-apollo-io-data) ·
[Masked last names (third party)](https://deepline.com/docs/providers/apollo)

---

## 2. Google Places API

**Use for us:** find local businesses (name and website) by category and city.

### How Text Search works

- `POST https://places.googleapis.com/v1/places:searchText`, with headers `X-Goog-Api-Key` and
  `X-Goog-FieldMask`. The field mask is required: without it the request fails.
- **Request body:**
  - `textQuery`, for example `"dentist in Austin, TX"`.
  - Optional `includedType` with `strictTypeFiltering`.
  - `locationRestriction` (rectangle only) or `locationBias` (rectangle or circle). You can't set
    both.
  - `regionCode` (`"US"`), `pageSize` (1–20) and `pageToken`.
- **Results:** up to 20 per page and **at most 60 per query** (3 pages). Every page request must
  repeat the same parameters.
- **No employee count.** You can't filter for 1–20 employees. Local businesses are usually small,
  but that isn't guaranteed.

### Pricing

Since March 1, 2025, Google no longer gives a $200 monthly credit. Each SKU has its own free
monthly allowance. A request is billed at the most expensive field you ask for.

| SKU | Example fields | Free per month | After that, per 1,000 |
|---|---|---|---|
| Text Search Essentials (IDs only) | `places.id` | unlimited | — |
| Text Search Pro | `displayName`, `formattedAddress`, `location`, `primaryType` | 5,000 | $32 |
| Text Search Enterprise | **`websiteUri`**, `nationalPhoneNumber`, `rating` | 1,000 | $35 |

- We need `websiteUri`, so every request is Enterprise. That gives 1,000 free requests a month,
  each with up to 20 places.
- New Google Cloud projects can't turn on the old ("legacy") Places API, so this is the only
  version available to us.

### Terms: the big catch

- Google Maps Platform Terms §3.2.3 bans exporting, extracting or scraping Google Maps content for
  use outside Google's services. The examples it gives include **copying business names and
  addresses**. It also bans caching, except where the Service Specific Terms allow it.
- Places exceptions: the **place ID can be stored forever**, and latitude/longitude for up to 30
  days. Everything else (name, address, website, phone) can't be stored.
- So building a lead list or CRM from Places results breaks Google's terms as written, even
  through the official paid API. Plenty of tools do it anyway. That's a risk decision, not a
  technical one.
- **Alternative:** Clay has its own Google Maps "Local Businesses" source, and says building lists
  from Google Maps is free (credits are only used for enrichment). It returns name, address, phone,
  website and rating, up to 1,000 results per query (**Conflict**: an older community post says
  200).

### What it means for us

- It's technically easy and free at our volume: 1,000 Enterprise requests is far more than Clay
  can enrich.
- It fits the AI-automation offer for local service businesses (clinics, law firms, home services).
  It fits front-end outsourcing much less.
- It needs a decision on the terms issue before we build it.

Sources:
[Text Search (New)](https://developers.google.com/maps/documentation/places/web-service/text-search) ·
[searchText reference](https://developers.google.com/maps/documentation/places/web-service/reference/rest/v1/places/searchText) ·
[Places usage and billing](https://developers.google.com/maps/documentation/places/web-service/usage-and-billing) ·
[Pricing list](https://developers.google.com/maps/billing-and-pricing/pricing) ·
[March 2025 changes](https://developers.google.com/maps/billing-and-pricing/march-2025) ·
[Legacy products](https://developers.google.com/maps/legacy) ·
[Places policies](https://developers.google.com/maps/documentation/places/web-service/policies) ·
[Maps Platform Terms](https://cloud.google.com/maps-platform/terms) ·
[Service Specific Terms](https://cloud.google.com/maps-platform/terms/maps-service-terms) ·
[Clay Google Maps template](https://www.clay.com/templates/find-local-businesses-using-google-maps) ·
[Clay: find local companies](https://www.clay.com/tools/find-local-companies) ·
[Clay FAQ](https://www.clay.com/faq)

---

## 3. Clay

**Use for us:** for each company, find the decision-maker, find their work email, and check it.
CSV in, CSV out.

### Plans after Clay's March 11, 2026 pricing change

Clay now measures usage in two ways:

- **Data Credits** pay for data from Clay's providers, from about $0.05 each.
- **Actions** pay for platform work. Every enrichment run uses 1 action.

Clay's pricing page and memo say that if an enrichment finds nothing, no credits or actions are
charged (**Conflict**: one third-party article says failed lookups still cost).

| Plan | Price | Data Credits | Actions | Rows per table | Notes |
|---|---|---|---|---|---|
| Free | $0 | 100 a month | 500 a month | 200 (memo). **Conflict**: Clay's FAQ says 50 | Waterfalls, bring your own API keys. No phone numbers, no CRM sync. |
| Trial | 14 days | 1,000 (docs). **Conflict**: FAQ says 2,000 | 10,000 for the trial | **50** | Growth features (webhooks, HTTP API, CRM) during the trial. Credits expire when it ends. No phone numbers. |
| Launch | $185/mo ($167 billed annually) | 2,500 a month | 15,000 a month | 50,000 | Phone numbers, signals, email sequencer integrations |
| Growth | $495/mo ($446 billed annually) | 6,000 a month | 40,000 a month | 50,000 | HTTP API, webhooks, CRM sync. This is the "$500 plan". |

- **CSV works on every plan.** Import: Actions → Import from CSV. Export: Actions → Export →
  Download CSV. One upload can have at most 72 columns and 50,000 rows (from a Clay community
  answer).
- On paid plans, unused Data Credits roll over (capped at 2× the monthly amount). Actions don't
  roll over.

### Cost per finished lead

A finished lead means: person found, email found, email checked.

- **Finding people** in Clay's own database: 0 Data Credits per Clay's docs. It still uses
  actions.
- **Finding a work email:** about 0.5 credits per email found in Clay's own example. One user
  reports about 1.3 credits on average for a multi-provider waterfall. Before the 2026 change it
  was 2–5 credits.
- **Checking the email:** free with some validation providers under the new pricing.
- **Estimate:** about 0.5–1.3 Data Credits and about 3 actions per finished lead.

That gives this rough capacity (**Estimate**, to be replaced by real numbers from month 1):

| Plan | Finished leads | Bottleneck |
|---|---|---|
| Free | about 75–150 a month | credits or actions |
| One trial | about 750–2,000 | split into tables of 50 rows, so 15–40 separate upload and export rounds |
| Launch | about 1,900–5,000 a month | credits |

The people table counts against the row limit too. Keep it to one person per company so 50
companies don't turn into more than 50 people rows.

### The new developer API (2026)

- Clay now has a developer platform (API and command line) **on every plan, including free and
  trial**.
- It can search Clay's people and company database. Free allows 50 results per request and 100
  per 30 days; the trial allows 10,000 for its whole length.
- It can run **Workflows**, which can call enrichments. Workflows are labeled **Alpha** by Clay.
- Tables are **read-only** through the API: you can't create tables or write rows.
- It uses the same credits as working in the app.
- It's too new to build on now, so CSV stays the plan. Worth checking again in a few months.

### Rotating accounts (your month-1 idea)

- **The facts:**
  - A trial lasts 14 days, has 50-row tables, and its 1,000 credits expire at the end.
  - Clay's docs say "each team member can create their own trial account".
  - I couldn't read Clay's Terms of Service (the page was blocked). Most SaaS terms ban one person
    opening repeated trials, and an account can be closed for it, possibly in the middle of a
    batch.
- **The practical cost:** every account needs its own signup email and its own copy of the Clay
  table setup, plus uploads of 50 rows at a time.
- **My honest read:** it can work for a test month, but it's fragile and a terms risk. The code
  shouldn't depend on it. The pipeline treats Clay as "CSV goes out, CSV comes back" and records
  the cost of each batch, so after month 1 you'll have real numbers to compare against Launch.

### Clay's email check results

- Clay's validation returns one of: **valid, invalid, catch-all, role-based, unknown**.
- **Gotcha:** with ZeroBounce or Debounce inside Clay, a catch-all can show as "valid" with a
  "catch-all" sub-status. Debounce shows "risky" as valid by default. Either read the provider's
  detailed status, or turn on "only mark safe to send" (available for ZeroBounce and LeadMagic).
- In a waterfall you can set a validation provider and a strictness level: Conservative, Balanced
  (the default), or Aggressive.
- Clay's own test results: about 99% accurate on normal domains, about 95% on catch-all domains.

Sources:
[Pricing](https://www.clay.com/pricing) ·
[Pricing memo, Mar 2026](https://www.clay.com/blog/clay-pricing-memo-internal) ·
[Plans and billing](https://university.clay.com/docs/plans-and-billing) ·
[Actions and Data Credits](https://university.clay.com/docs/actions-data-credits) ·
[50-row limit FAQ](https://www.clay.com/faq/why-is-there-a-50-row-limit-for-trial-and-free-accounts) ·
[Free trial FAQ](https://www.clay.com/faq/what-do-i-get-in-the-free-trial) ·
[CSV import](https://www.clay.com/university/guide/csv-import-overview) ·
[Finding companies and people](https://university.clay.com/docs/finding-companies-and-people-in-clay) ·
[Email verification statuses](https://university.clay.com/docs/email-verification-statuses) ·
[Catch-all validation thread](https://community.clay.com/x/support/nk8q1655xcyd/experiences-with-catch-all-email-validation-using) ·
[Waterfalls](https://university.clay.com/docs/building-a-data-waterfall) ·
[Work email cost thread](https://community.clay.com/x/general/msg_rLVaL9APcjRe/how-much-do-work-email-enrichments-cost-sharing-my) ·
[Developer searches](https://developers.clay.com/searches) ·
[Clay API and CLI](https://university.clay.com/docs/using-clay-as-an-api) ·
[Workflows](https://university.clay.com/docs/workflows) ·
[Third-party pricing summary](https://www.cleanlist.ai/blog/2026-03-12-clay-pricing-changes-2026)

---

## 4. Email verification

### How it actually works

- A verifier connects to the domain's mail server and asks "would you accept mail for this
  address?" (SMTP `RCPT TO`). It sends nothing. A `250` reply means accepted; a `550` means no
  such mailbox.
- **Catch-all** (also called accept-all) domains say yes to every address, real or not. They can't
  be verified this way. Verifiers detect them by also asking about a made-up address, and label
  them catch-all or risky.
- **Unknown** usually means the server timed out, or temporarily refused a sender it doesn't
  recognise (called greylisting). Trying again later often fixes it.
- **Role-based** means a shared inbox like `info@`, `sales@` or `support@`. They're real, but more
  likely to mark mail as spam, and less likely to be the decision-maker.
- Some big providers don't answer these checks reliably, so verifiers fall back on other signals.
- **Bounce targets for cold email:** under 2% of all emails bounced, and under 1% "hard" bounces
  (the address doesn't exist). This is the industry consensus, not a published Gmail or Microsoft
  number. Suppress hard bounces immediately.

### Instantly's verifier

- **API:** `POST /api/v2/email-verification` with `{"email": ...}`; a `webhook_url` is optional.
  If the check takes more than 10 seconds it returns `pending`; then poll
  `GET /api/v2/email-verification/{email}`.
- **Result:**
  - `verification_status` is one of `pending`, `verified`, `invalid`.
  - `catch_all` is true or false.
  - Don't use the `status` field: it describes the request, not the email.
- In the app, results show as Valid, Invalid or Risky. Instantly doesn't send to Invalid or Risky
  leads by default.
- Instantly says its catch-all check can confirm some catch-alls. Its own figures disagree
  (30–40% on one page, about 80% on another). That's a vendor claim; we'll measure it.
- **Cost:** 0.25 Instantly credits per email.
- **Credits are a separate subscription from the sending plan:**
  - Nano: $9/mo, 150 credits, about 600 checks.
  - Growth Credits: $47/mo, 1,500 credits, about 6,000 checks.
  - Monthly credits expire after 2 months.
  - The free trial gives 100 credits.
- **Alternative:** the bulk add-leads endpoint has `verify_leads_on_import=true`. But leads
  uploaded to a campaign count against the sending plan's contact cap even if they turn out
  invalid. So it's better to **check before uploading**.

### What it means for us

Your idea is sound: Clay checks first, then Instantly re-checks only the maybes. Two things still
need a rule:

1. Catch-alls that Instantly still can't confirm.
2. Role-based emails.

Sources:
[Create email verification](https://developer.instantly.ai/api-reference/emailverification/create-email-verification) ·
[Email verification schema](https://developer.instantly.ai/api-reference/schemas/email-verification) ·
[Instantly: email verification](https://help.instantly.ai/en/articles/8587347-email-verification) ·
[Instantly: catch-all verification](https://help.instantly.ai/en/articles/9662611-catch-all-email-verification) ·
[Instantly credit system](https://help.instantly.ai/en/articles/11381241-instantly-credit-system) ·
[How to verify leads](https://help.instantly.ai/en/articles/6514690-how-to-verify-leads) ·
[Callback verification](https://en.wikipedia.org/wiki/Callback_verification) ·
[Bounce thresholds (third party)](https://www.suped.com/knowledge/email-deliverability/sender-reputation/what-is-an-acceptable-bounce-rate-threshold-and-how-does-it-affect-sender-reputation)

---

## 5. Instantly

### Sending plans

| Plan | Price | Uploaded contacts | Emails a month | Webhooks |
|---|---|---|---|---|
| Growth | $47/mo (help center and pricing page; older blog posts say $37) | 1,000 | 5,000 | No |
| Hypergrowth | $97/mo | 25,000 | 125,000 | Yes |
| Light Speed | $358/mo | 100,000 | 500,000 | Yes |

- **Every plan:** unlimited email accounts, warmup, and API access. **Conflict**: one Instantly
  blog post says Growth has no API, but the pricing page says all plans have it. Check under
  Settings → Integrations in your account.
- **"Uploaded contacts" is a total limit, not a monthly one:**
  - Every lead in any campaign counts: active, paused, completed and draft.
  - The same person in two campaigns counts twice.
  - Deleting leads **from campaigns** frees space (the count takes 5–10 minutes to update).
    Deleting from lists doesn't.
  - Deleted leads can't be recovered.
  - Going over the limit means upgrading; there's no pay-per-extra-lead option.

### Sending volume

This is Instantly's guidance: a rule of thumb, not a Gmail or Microsoft rule.

- About **30 cold emails per inbox per day**, with warmup still running alongside.
- At least 2 weeks of warmup before the first campaign.
- Ramp up slowly. Instantly's "slow ramp" setting starts at 2 emails a day and adds 2 a day.

### API v2

**Basics**

- Base URL `https://api.instantly.ai/api/v2`, header `Authorization: Bearer <key>`.
- Keys have scopes (for example `leads:create`, `campaigns:all`). Create a key with only what we
  need.
- **Rate limit:** 100 requests a second and 6,000 a minute for the whole workspace, shared across
  all keys and both API versions. Some endpoints are stricter: listing emails allows 20 a minute.
  Going over returns `429`. The docs suggest batches of 100 leads with 2 seconds between batches.

**Campaigns**

- `name` and `campaign_schedule` (time windows, days, timezone, start and end dates) are
  required.
- `sequences[].steps[]`: each step has `type`, `delay`, `delay_unit` and `variants[]` (subject and
  body).
- Settings:
  - `email_list` (which inboxes send) and `daily_limit`.
  - `stop_on_reply` and `stop_on_auto_reply`.
  - `open_tracking` and `link_tracking`: both are **true** in the examples, so we must set them to
    false.
  - `text_only`, `email_gap`, `random_wait_max`.
  - `insert_unsubscribe_header`: false in the examples.
- There is a separate endpoint to activate (start or resume) a campaign.
- The exact body for creating a campaign is **Unconfirmed**: check it with the first test call.

**Leads**

- `POST /api/v2/leads/add`: up to 1,000 leads per call, into a campaign or a list.
- Options: `skip_if_in_workspace`, `skip_if_in_campaign`, `skip_if_in_list`,
  `verify_leads_on_import`, and `custom_variables` on each lead.
- The response gives `created_leads`, `skipped_count` and `invalid_email_count`. It also checks
  the workspace blocklist.

**Reading results**

- **Analytics:** `/campaigns/analytics`, `/campaigns/analytics/overview`,
  `/campaigns/analytics/daily` and `/campaigns/analytics/steps` cover replies, bounces and so on.
- **Replies:** `GET /api/v2/emails` reads the Unibox (Instantly's shared inbox), at 20 requests a
  minute.
- Leads carry a numeric `lt_interest_status`. What each number means is **Unconfirmed**.

**Blocklist and webhooks**

- **Blocklist:** `POST /api/v2/block-lists-entries` with `bl_value` set to an email or a domain.
  There are also bulk create and delete endpoints and an export.
- **Webhooks** (`reply_received`, `email_bounced`, `lead_unsubscribed` and others) need Hypergrowth
  or higher. On Growth, our code has to ask Instantly for changes on a schedule instead (polling).

**Unsubscribes**

There are two parts, and we want both:

- A one-click unsubscribe **header** (`insert_unsubscribe_header`, or Campaign → Options →
  Advanced).
- An unsubscribe **link** in the email body (editor → "+" → Insert unsubscribe link). The link
  only works for real campaign leads, not in preview test emails.

### What it means for us

- On Growth, the hard limits are **1,000 contacts in campaigns at any time** and **5,000 emails a
  month**.
  - With a 3-email sequence that's at most about 1,666 new people a month (**Estimate**).
  - That only works if finished leads are cleared out to make room.
- **Estimate:** 5,000 emails over about 22 sending days is about 230 a day, or about 8 inboxes at
  30 a day.
- With no webhooks, our code checks once or twice a day for replies, bounces and unsubscribes.
- Since cleared leads are gone from Instantly, **our own database has to be the permanent record**
  of who has been contacted, and of who must never be contacted again.

Sources:
[Pricing](https://instantly.ai/pricing) ·
[Plans overview](https://help.instantly.ai/en/articles/10273259-instantly-plans-overview) ·
[Uploaded contacts limits](https://help.instantly.ai/en/articles/7918680-uploaded-contacts-limits) ·
[How to delete leads](https://help.instantly.ai/en/articles/6996491-how-to-delete-leads) ·
[Warmup settings](https://help.instantly.ai/en/articles/7988514-warmup-settings) ·
[Campaign options](https://help.instantly.ai/en/articles/6222396-campaign-options) ·
[API introduction](https://developer.instantly.ai/) ·
[Rate limit](https://developer.instantly.ai/getting-started/rate-limit) ·
[Campaign schema](https://developer.instantly.ai/api-reference/schemas/campaign) ·
[Add leads in bulk](https://developer.instantly.ai/api-reference/lead/add-leads-in-bulk-to-a-campaign-or-list) ·
[Activate campaign](https://developer.instantly.ai/api-reference/campaign/activatestart-or-resume-a-campaign) ·
[Analytics](https://developer.instantly.ai/api-reference/groups/analytics) ·
[Emails](https://developer.instantly.ai/api-reference/groups/email) ·
[Block list entry](https://developer.instantly.ai/api-reference/blocklistentry/create-block-list-entry) ·
[Webhooks](https://help.instantly.ai/en/articles/6261906-webhooks) ·
[List-Unsubscribe](https://help.instantly.ai/en/articles/8860388-list-unsubscribe) ·
[Unsubscribe link](https://help.instantly.ai/en/articles/6191077-add-an-unsubscribe-link)

---

## 6. Deliverability rules: Gmail, Yahoo, Microsoft

These are the rules for **bulk senders**: about 5,000 or more emails a day to personal Gmail,
Yahoo or Outlook addresses, counted per sending domain. At Gmail, a domain that crosses that line
once counts as a bulk sender forever. We'll be well under 5,000 a day, but spam filters judge
everyone against these rules, so we meet them anyway.

| | Gmail | Yahoo | Microsoft (Outlook.com, Hotmail) |
|---|---|---|---|
| Authentication | SPF + DKIM + DMARC, with the From domain matching SPF or DKIM (all senders need at least SPF or DKIM) | SPF + DKIM, DMARC at least `p=none` and matching, DKIM key ≥1024 bits (2048 recommended) | SPF and DKIM must pass, DMARC record with matching domain. Otherwise rejected with `550 5.7.515` (since May 5, 2025) |
| Unsubscribe | One-click (`List-Unsubscribe` header, RFC 8058) on marketing mail, honored **within 48 hours** | One-click header; a link in the body alone doesn't count; honored **within 2 days** | — |
| Spam complaints | Aim for under 0.1%, never reach 0.3% | Under 0.3% | — |

Gmail started enforcing these more strictly in November 2025: mail that fails them can be
rejected.

Practice (advice from tool vendors, not official rules):

- **Turn open tracking off.** Apple Mail loads the tracking pixel on its own, so open counts are
  inflated anyway. Pixels and tracked links can also hurt inbox placement. Measure replies, not
  opens.
- **Plain text,** no images, and no links (or at most one) in the first email.
- **About 30 emails per inbox per day,** a slow ramp, and warmup kept on.

Sources:
[Gmail sender guidelines](https://support.google.com/mail/answer/81126) ·
[Gmail sender FAQ](https://support.google.com/mail/answer/14229414) ·
[Gmail subscription guidelines](https://support.google.com/mail/answer/15263077) ·
[Yahoo sender best practices](https://senders.yahooinc.com/best-practices/) ·
[Microsoft high-volume sender requirements](https://techcommunity.microsoft.com/blog/microsoftdefenderforoffice365blog/strengthening-email-ecosystem-outlook%E2%80%99s-new-requirements-for-high%E2%80%90volume-senders/4399730) ·
[Microsoft 550 5.7.515](https://support.microsoft.com/en-us/outlook/fix-ndr-error-550-5-7-515-in-outlook-com) ·
[Tracking pixels and deliverability (third party)](https://glockapps.com/blog/email-tracking-pixels-investigating-their-purpose-and-impact-on-deliverability/)

---

## 7. US law

This is a summary of public sources, not legal advice.

### CAN-SPAM (federal)

- **It covers business-to-business email.** The FTC says there's no B2B exception.
- **No opt-in is needed.** You may email until the person opts out.
- **Every email must have:**
  - Honest From, To and Reply-To, and honest routing information.
  - A subject line that matches the content.
  - A clear statement that it's an advertisement. The law allows flexibility in how.
  - A valid physical postal address: a street address, a USPS PO box, or a registered commercial
    mail receiving agency.
  - A working opt-out that keeps working for at least 30 days after sending. It must be honored
    within 10 business days, with no fee and nothing asked beyond the email address.
- **You can't sell or pass on opted-out addresses.**
- **Using a tool (Instantly) doesn't move the legal responsibility** away from you.
- **Penalty:** up to **$53,088 per violating email**. That's the 2025 figure; there was no
  inflation adjustment in 2026.

### State laws

- CAN-SPAM overrides most state email laws, except the parts that target falsehood or deception.
  California's §17529.5 is the main one; it was applied in *Hypertouch v. ValueClick*.
- In practice: no fake "Re:" or "Fwd:" subjects, and no misleading sender names.

### Privacy (CCPA/CPRA, California)

It applies only above certain thresholds. A business is covered if it has any one of:

- More than $26.625M revenue.
- Buys, sells or shares data on 100,000+ California residents or households a year.
- Makes half or more of its revenue from selling personal data.

A small agency is likely below all three. The 100,000 test is the one to watch as lists grow. My
understanding is that business contact data has not been exempt since January 2023. Confirm that
with a professional.

### What it means for us

- Every email carries a postal address, an unsubscribe line and the unsubscribe header.
- Our own rule should be stricter than the law: process opt-outs **within 48 hours**
  (Gmail/Yahoo), and never email that person again.

Sources:
[FTC CAN-SPAM compliance guide](https://www.ftc.gov/business-guidance/resources/can-spam-act-compliance-guide-business) ·
[FTC: candid answers to CAN-SPAM questions](https://www.ftc.gov/business-guidance/blog/2015/08/candid-answers-can-spam-questions) ·
[FTC civil penalty adjustments, Sep 2026](https://www.federalregister.gov/documents/2026/09/15/2026-18853/civil-penalty-inflation-adjustments) ·
[Hypertouch v. ValueClick](https://blog.ericgoldman.org/archives/2011/01/hypertouch_v_valueclick.htm) ·
[CCPA applicability (third party)](https://www.clym.io/blog/ccpa-applicability-guide)

---

## 8. The market: who replies, and how often

- **AI use at tiny US firms is low and not growing.**
  - US Census survey data from May 2026: about 37% of firms with 250+ employees use AI, but under
    20% of firms with 4 or fewer.
  - Use is rising at firms with 20+ employees and flat below 20.
  - The most cited reason for not using it (from a secondary source I couldn't verify) is "AI
    isn't relevant to my business".
  - So the email has to name one concrete job the automation does, such as answering missed calls
    or booking appointments, not "AI".
- **Who buys outsourced front-end work:** startups and SaaS companies that build their backend
  in-house, agencies, and non-software companies with a one-off project. This comes only from
  vendor pages, so the evidence is thin.
- **Reply rates:**
  - All replies: about 3–5% on average (Instantly 3.43%, Saleshandy 3.7%, Belkins 5.8%).
  - Positive replies: about 1.5–3%.
  - Belkins found companies with 0–10 employees reply at only **0.72%**. Another source says
    small businesses reply more. They conflict, so we measure our own.
- **Estimate:** 1,000 contacts a month might bring about 7–30 positive replies.

Sources:
[Census AI adoption, 2026 (secondary)](https://www.apexbusinesstech.com/us-census-ai-adoption-small-business-2026/) ·
[Belkins reply rates](https://belkins.io/blog/cold-email-response-rates) ·
[Reply rate benchmarks 2026](https://leadhaste.com/blog/cold-email-reply-rate-benchmarks-2026) ·
[Apollo: good reply rate](https://www.apollo.io/insights/what-is-a-good-benchmark-for-reply-rates-in-cold-outreach)

---

## 9. The facts that shape the design

1. **Apollo free gives companies, not emails.** Emails come from Clay.
2. **Clay's free and trial limits are the bottleneck.** That's 50–200 rows per table and 100–1,000
   credits. The code must make CSV batches painless and measure the cost per lead.
3. **Instantly Growth allows 1,000 contacts in total, 5,000 emails a month, and has no webhooks.**
   So we check emails before uploading, clear out finished leads, poll for events, and keep our
   own database as the master record.
4. **No one can fully verify a catch-all.** We need a rule for them.
5. **Google's terms ban storing Places data** (except the place ID). That needs a decision before
   building.
6. **CAN-SPAM:** every email needs a postal address, an opt-out and honest headers. Opt-outs are
   processed within 48 hours.
