# New company configuration — fill this in

Copy this file, fill in every section for the company you're onboarding, and hand it back along
with **at least one real, representative document** for each row you list below. This file is the
one thing a reviewer needs to set up a new company without asking you follow-up questions — the
more precise you are here, the less back-and-forth it costs later.

You do not need to know anything about how the extraction engine works to fill this in. You do
need to know this company's documents — what kinds arrive, and which numbers/names on them
actually matter to your team.

---

## 1. Company

**Company name:** _____________________

**How do we recognise this company's documents?** List everything printed on the page that
identifies them — not a filename, not an email subject line, the actual printed text:

- Company name exactly as it appears on the document: _____________________
- Any other names it's printed under (a parent company, a "doing business as," a remittance
  payee that differs from the letterhead): _____________________
- A printed address, phone number, or email you could match on: _____________________

## 2. Document types

List every distinct *kind* of document this company sends or receives — an invoice and a credit
memo are two different rows, even from the same company. Add rows as needed.

| # | What you'd call it | One real sample attached? | How often does it arrive |
|---|---|---|---|
| 1 | e.g. "monthly invoice" | ☐ yes ☐ no | e.g. monthly |
| 2 | | ☐ yes ☐ no | |
| 3 | | ☐ yes ☐ no | |

**A document with no sample attached cannot be configured yet** — everything below this point is
per document type, and it's built by looking at a real one, not by description alone.

## 3. Fields — per document type

For **each** document type from section 2, fill in a copy of this table. Only list what your team
actually needs — a field nobody reads is a field nobody needs extracted correctly, and every row
you add here is one the reviewer has to go find on the actual page.

**Document type:** _____________________ (matches a row number from section 2)

| Field (plain language) | Where does it sit on the page? | Example value (do NOT use a real one from a live document — invent a placeholder) |
|---|---|---|
| e.g. "the total we owe" | e.g. "bottom right, next to 'Total Amount Due'" | e.g. `$1,234.56` |
| | | |
| | | |

If a field is a **total, a balance, or anything computed from other numbers on the page** (not
just copied), say so explicitly and describe the computation in plain language — e.g. "the amount
we actually owe is the current charges, unless a prior balance carries forward, in which case
it's both added together." This is the single most important thing to get right: a wrong total on
one invoice can be a five-figure mistake, and it is never solved by reading the page more
carefully — it needs the actual business rule written down.

## 4. Billing conventions (skip this section if every document type above is a one-time purchase,
not a recurring bill)

- Does any document type print a "previous balance" or "balance forward"? ☐ yes ☐ no
- If yes: when a payment has already been applied, does the printed previous balance already
  reflect it (net), or does it show the full amount still needing the payment subtracted (gross)?
  ☐ already net of payments ☐ still gross, payments shown separately ☐ not sure
  - **"Not sure" is a completely fine answer.** Guessing wrong here is worse than leaving it
    blank — the system will hold documents for manual review rather than silently assume, until
    someone who can look at a real statement and a real payment confirms which one it is.

## 5. Anything else a reviewer should know

Multiple tables on one page, negative amounts/credits, foreign currency, documents that arrive as
scans/photos rather than clean digital files, anything unusual about how this company formats
things — write it here in plain language.

_____________________

---

## What happens after you hand this back

1. A reviewer reads this file and your sample document(s) and builds the actual configuration
   (increasingly, with an automated first draft — see `docs/onboarding/CONFIG-SPACE.md` — but
   always checked by a person before it goes live).
2. It's tested against your sample document(s) and the result is shown to you before it goes
   live — you should be able to look at the extracted values and confirm they're right.
3. Once confirmed, this company's documents route automatically going forward. Anything the
   system isn't confident about still goes to a review queue rather than guessing — that's true
   on day one and stays true after.
