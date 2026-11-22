# Build notes

How I took Buyer Finder from an idea to a tested product, and the decisions behind it.
I led the product: picking the problem, setting the quality bar, choosing between options, testing every
version with real searches and deciding what to fix next. I built it with Claude as my engineering partner,
which let me move from idea to a working, deployed tool in two days.

## The problem I chose

My family runs a small export business in Zhejiang. New buyers come from referrals, trade fairs,
social media and data scraped by hand. It is slow, and much of what you find online is wrong or out of date.
I set one goal: an exporter types what they make and where they want to sell, and gets real importers and
distributors, proof for each one, and a first email.

From the start I decided the product had to earn trust. A list of names from an AI is easy to make and
hard to believe, so every company needs evidence a user can check.

## Key decisions

**Model and cost.** I compared providers on price, payment and access for the people this is for.
I chose DeepSeek: it is low cost, accepts WeChat Pay and is easy to use for exporters in China.
I kept a switch (`BUYER_FINDER_PROVIDER`) so the same app can run on Claude. I then cut the setup down to
one service for both AI and web search, so the whole tool runs on a single API key.
A full search costs about one US cent.

**Online from day one.** I deployed it on Streamlit Community Cloud so anyone can try it from a link,
with a password to protect my API balance.

**Show the value in five seconds.** An interviewer or a new user should not have to wait a minute to see
what the tool does. I added a saved result from a real search that anyone can open without the password.

**English first.** The people reviewing this read English, so English is the default.
Chinese is one click away for the factory owners the tool is built for.

## How I tested it

I ran the same real search every round (stainless steel kitchen hardware for Spain), read every result
myself and turned what I found into the next fix.

| Round | What I found | Cause | What I changed |
|---|---|---|---|
| 1 | The search returned an error instead of a list | Most likely the model's thinking mode used up its answer budget | Thinking off, plus one automatic retry |
| 2 | 9 of 10 companies scored 0, only 3 websites worked, the best match was ranked 4th | Scores written as "4/5" were read as 0, the website check was too strict, the sort order was wrong | Read any score format, accept any site that answers, rank by score first |
| 3 | 7 of 10 had no website; the "sources" were job sites and directories | The AI only saw directory pages | A second search for each company's official site |
| 4 | 4 websites belonged to someone else (another company, a brand directory, a reseller) | The rule only needed one word of the name in the domain | The domain must be built from the company's own name |
| 4 | 4 of 10 quotes failed the check | The AI joined parts of a page with "..." | Check each part on its own |
| 5 | 9 of 10 scored 5/5, so the score told the user nothing | The scoring rules were too easy | Scoring rules version 2 |
| 6 | All targets met. Scores now 4 or 5: every company really is a close match | The search is already narrow; the rules can't yet tell good from best | Next rule: how to treat companies that also manufacture |
| 7 | Evaluation found 2 false buyers in the round 6 sample. One scored 5/5 as a distributor, but its own homepage says it designs and makes handles. Another was linked to a guessed website that belongs to a Portuguese manufacturer | The manufacturer filter only read the AI's "type" field. Guessed websites were only checked for the company name, not the country | Check page text for "we make this" in six languages and flag the company. Drop a guessed website when the domain, language or address points to another country |

**Round 7: evaluation found 2 false buyers.** While building a separate test set, the round 6 sample was
checked by hand against each company's own page.
- Herrajes Ferramol: typed "distributor", scored 5/5. Its homepage says "FERRAMOL, desde 1979, diseña y fabrica
  tiradores y pomos" (designs and makes handles and knobs). It is a manufacturer.
- Fajota Iberica SL (Spain): linked to fajota.com, a guess built from the name. That site is a Portuguese
  manufacturer in Águeda: Portuguese text, +351 phone numbers, postal code 3754-909.
- Applying the new checks to the same 10 results: Ferramol flagged, Fajota's guessed website dropped, and INTHER
  also flagged (its homepage says "We use top quality materials to manufacture our fittings"). Verdú is not
  flagged: its page says "Somos fabricantes", but the next sentence says they have hardware made for them under
  their own brand.

Decision: flag, don't delete. A page that says "we manufacture" can be out of date, or the company can make one
line and import another. So a flagged company stays in the list with a warning and the sentence that triggered
it ("Page suggests they manufacture this themselves, may be a competitor"). It loses the "importer, distributor
or wholesaler" point and is not counted as fully verified. Emails are drafted for unflagged companies first.
Phrases like "mandamos a fabricar" or "made for us" mean the company buys from factories, so they cancel the flag.
On a directory or reseller page, only sentences that name the company count.
Guessed websites are different: they were only ever a guess, so one that points to another country is dropped,
and the app shows which site was rejected and why.

Round 5 also proved the evidence check works: the AI quoted "Herramientas y accesorios" (tools and
accessories) while the page says "Herrajes y accesorios" (hardware and accessories). One changed word,
and the app refused to mark the quote as checked.

## Measuring instead of guessing

I did not want to judge the product by how it looked, so I defined one north-star metric:
**fully verified buyers per search** (the quote was found in the source and the official website opens).
This is the number of results a user can act on without checking them again.

| Metric | Before the fixes | Round 5 | Round 6 | Round 7 (same results, new checks) | Target |
|---|---|---|---|---|---|
| Fully verified buyers (of 10) | about 1 | 4 | **5** | 4 (one flagged as a possible manufacturer) | 5 or more |
| Official website confirmed | 30% | 70% | 70% (2 matched by name only) | 60% (1 matched by name only) | 70% |
| Possible manufacturers flagged | not checked | not checked | not checked | 2 | |
| Quotes checked | 80% (search summary only) | 70% | **100%** (6 on the page itself, 4 in the summary) | 100% (unchanged) | 80% |
| Cost per search | $0.011 | not recorded | not recorded | not recorded | under $0.02 |

After round 2 the metric showed that website confirmation (30%) was the bottleneck, so I fixed that first.

## Design: familiar, not flashy

- The first version looked like a class project: default styling and raw column names like `fit_score`.
- The second looked AI-generated: gradient banner, emoji cards, all-caps labels. I pushed to remove
  every generic touch and moved to a quieter style taken from trade documents.
- Then I asked a different question: what do the people judging this already use every day?
  Sales teams know Apollo and HubSpot, so I copied how those tools work, not how they look:
  navigation on the left, a list of leads, a detail panel, a status for each lead, export at the top right.
  Nobody has to learn it (Jakob's Law).
- The one new idea is the evidence column: for every company you see whether its quote was found on the page,
  only in the search summary, or not at all.

## Review: 19 issues, no shortcuts

Using the product as a user, I spotted problems such as no way back to the search and a language switch
in the wrong place. I then had the whole app reviewed against Nielsen's 10 usability heuristics and the code
read line by line. That found 19 issues: 8 logic bugs (for example, filtering the table could show the
wrong company in the detail panel), 3 trust issues (for example, saying "checked on the page" when only
the search summary had been checked) and 8 usability issues.

I asked for every one to be fixed properly, with a test so it cannot come back. The tests are in `tests/`.
Run against the old version, 25 of 27 failed; every test passes now.

## Next

1. Put it in front of real exporters I know and record what they do with the results.
2. Add trade fair exhibitor lists as a source (for example Canton Fair, India ITME).
3. Save searches and statuses between visits.

## What I learned

[Write this part yourself: two or three sentences in your own words.]
