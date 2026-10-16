# The Clay round trip, click by click

This is what you do in Clay for each batch of companies. Our app does everything before and
after it. Clay's menus change now and then: if a button is named slightly differently, look
for the closest match.

## 1. Make the file for Clay (our app)

In the app: **Enrich with Clay**. Pick the ICP at the top, then in step 1 the rows, **Create
the file**, **Download**. One file holds one ICP, because each ICP looks for different people.
Or in the terminal:

```
outbound clay export bpa_us_recruit --rows 200
```

Use 50 rows (`--rows 50`) on a Clay trial (trial tables only take 50 rows).

Those companies are now marked "sent to Clay" and will never go out twice. Two laptops never
claim the same company.

The file has 5 columns: `company_id` (ours, so the results can be matched back), `domain`,
`name`, `linkedin_url` and `icp`.

## 2. Put it in Clay

1. In Clay: **Home → Import data → CSV**. Pick the file and create a **new table**.
2. **Switch Auto-run off** (top-left of the table) while you set up the columns, so nothing
   runs on every row by accident.

## 3. Find one person per company

1. **Add column**, then search **"Find people"**. Clay's action that finds people at a company
   may be called "Find people at these companies" or "Find contacts at company".
2. **Company:** use the `domain` column.
3. **Job titles** and **person location:** the ones the app shows in step 2 for this ICP (from
   the ICP's "People to find in Clay"). For `bpa_us_recruit`, for example: Founder, Owner, CEO,
   President, Managing Director, Director of Operations, Head of Delivery, in Texas or Florida.
4. **Limit:** 1 person per company.
5. **Leave out** the companies the ICP's "Exclude" note names (shown in step 2). Apollo can't
   filter these, so it's done here, by eye.

This gives a people table (or people rows), with columns like First Name, Last Name, Job Title,
LinkedIn Profile and Company Domain.

## 4. Find and check their email

In the people table:

1. **Add column → "Find work email"**. This is Clay's waterfall: it tries several providers until
   one finds the email. Clay shows the cost per row before you run it.
2. **Add column → "Validate email"**, pointed at the work email column. If you pick ZeroBounce or
   LeadMagic as the checker, turn on **"only mark safe to send"**. Otherwise catch-all emails can
   show as "valid".
3. **Run it on 5 rows first** (select them, then run). Check it looks right, then run the rest.

Before running, note your **Clay credits**. After, note them again. The difference is what this
batch cost; you'll type it in at step 6.

## 5. Download Clay's results

In the people table: **Actions → Export → Download CSV**.

You don't need to rename or delete any columns. Prefer names the importer recognises (Work Email,
Validate Email, Company Domain, First Name, Last Name, Job Title, LinkedIn Profile).

## 6. Bring the results back (our app)

In the app: **Enrich with Clay → step 3**. Choose Clay's CSV, check the pre-filled column
dropdowns, fill in the Clay account and credits if you know them, **Import**. Or in the terminal:

```
outbound clay import path\to\clay.csv --account "clay-1" --credits 40
```

The account and credits are optional. Credits per batch let you compare Free, trial and Launch
on cost per verified email.

## What happens to each person

| State | When | What happens next |
|---|---|---|
| **verified** | Clay says valid | Ready for later stages |
| **needs_check** | Catch-all or unknown | Re-checked with Instantly's verifier first |
| **hold** | Role address like info@ or sales@ | Waits for your decision D5 |
| **dropped** | No email, invalid, or on the do-not-contact list | Never sent |

**Companies:**
- A company Clay found nobody for becomes `no_contact`.
- A company with an email becomes `enriched`.

**Importing the same file twice is safe:** repeats are skipped. See everything on the app's
**Leads** page, or with `outbound export --contacts`.
