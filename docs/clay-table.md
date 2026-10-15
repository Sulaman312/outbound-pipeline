# The Clay round trip, click by click

This is what you do in Clay for each batch of companies. Our app does everything before and
after it. Clay's menus change now and then: if a button is named slightly differently, look
for the closest match.

## 1. Make the file for Clay (our app)

On the web page (`outbound ui`):

1. Open the **Clay** tab, section "1. Send companies to Clay".
2. Pick a segment, or "All segments".
3. Set **Companies per file**:
   - **200** on Clay Free;
   - **50** on a Clay trial (trial tables only take 50 rows).
4. Click **Create the Clay file**, then **Download the Clay file**.

Those companies are now marked "sent to Clay" and will never go out twice. The command-line
version is `outbound clay export --rows 200`.

The file has 5 columns: `company_id` (ours, so the results can be matched back), `domain`,
`name`, `linkedin_url` and `segment`.

## 2. Put it in Clay

1. In Clay: **Home → Import data → CSV**. Pick the file and create a **new table**.
2. **Switch Auto-run off** (top-left of the table) while you set up the columns, so nothing
   runs on every row by accident.

## 3. Find one person per company

1. **Add column**, then search **"Find people"**. Clay's action that finds people at a company
   may be called "Find people at these companies" or "Find contacts at company".
2. **Company:** use the `domain` column.
3. **Job titles:** Founder, Co-Founder, Owner, CEO, President.
4. **Limit:** 1 person per company.

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

You don't need to rename or delete any columns.

## 6. Bring the results back (our app)

1. Back in the **Clay** tab, section "2. Bring Clay's results back": drop the downloaded CSV in.
2. **Check the dropdowns.** The app guesses which Clay column is the email, the check result,
   the company domain, the name and the title. Fix any guess that's wrong.
3. **Optional:** type which Clay account ran it, and how many credits it used. The batches table
   then shows the cost per ready email, which is the number for deciding between Free, a trial
   and Launch.
4. Click **Import**.

The command-line version is:

```
outbound clay import path\to\clay.csv --account "clay-1" --credits 40
```

## What happens to each person

| Decision | When | What happens next |
|---|---|---|
| **ready** | Clay says valid | Goes to Instantly (next step) |
| **maybe** | Catch-all or unknown | Re-checked with Instantly's verifier first |
| **hold** | Role address like info@ or sales@ | Waits for your decision D5 |
| **drop** | No email, invalid, or on the do-not-contact list | Never sent |

**Companies:**
- A company Clay found nobody for becomes `no_contact`.
- A company with an email becomes `enriched`.

**Importing the same file twice is safe:** repeats are skipped. See everything in the
**Contacts** tab, or with `outbound export --contacts`.
