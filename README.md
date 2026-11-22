# Buyer Finder

An AI research agent that helps small exporters find overseas buyers.
Describe what you sell and which country you want to sell into. Buyer Finder finds real importers and distributors there, shows the evidence for each one, and drafts a first email.

**[Try the live demo](https://buyer-finder-txxd9mw4zwaewnsz5tqo3h.streamlit.app)**: click *View a sample result* to see a real search without a password.

![Buyer Finder showing ten Spanish distributors for stainless steel kitchen hardware, with the evidence for one of them](screenshot.png)

## Why I built this

My family runs a small export business in Zhejiang. We still find new buyers the traditional way: referrals from people we know, exhibiting at trade fairs and summits, promoting our products on social media, and digging through data online by hand.

I felt this wasn't efficient enough, and it has real problems:
- Data scraped online is often inaccurate, and a lot of useful information isn't public.
- Checking companies one by one takes too much time and manpower.
- Referrals are limited, and competition is intense.
- Breaking into a new market is hard when everyone is chasing the same buyers and you don't have a clear edge.

So I wanted to use AI to speed this up.

## How it works

1. **Search.** Three web searches for importers, distributors and wholesalers of your product in the target market. Product and country are translated to English first, so a search typed in Chinese still finds local companies.
2. **Filter.** Manufacturers, B2B marketplaces, directories, social media and job sites are removed. A company is kept only if its source really is one of the search results, so the AI can't invent one. If a company's own page says it makes the product itself ("fabricamos", "we manufacture", in six languages), it is marked as a possible competitor instead of being counted as a buyer.
3. **Check the evidence.** For every company the AI must quote the source word for word. The app then opens the source page and looks for that quote. Each company shows whether the quote was found on the page, only in the search summary, or not at all.
4. **Confirm the website.** If the AI gives no website, the app searches for it and only accepts a domain built from the company's own name. Sites found by guessing the name are labelled as such, and are dropped if the page points to another country (domain ending, page language, phone and postal codes).
5. **Score.** The AI answers four yes/no questions (sells this category, sells your exact products, buys in bulk, already imports or uses the same material) and the app adds up the points. The same answers always give the same score, and every score shows its reasons.
6. **Draft.** Short first emails for the best matches with a confirmed website, in English or the buyer's language. Buyer Finder never sends anything: you read the drafts and decide.

Then work through the list like in a sales tool: a table of leads, a detail panel, a status for each company (new, contacted, replied, not a fit) and CSV export. The interface works in English and Chinese.

## Results so far

Same test every round: stainless steel kitchen hardware for Spain, 10 companies. Full test log and the decisions behind each change are in [NOTES.md](NOTES.md).

| Metric | First version | Latest |
|---|---|---|
| Fully verified buyers (evidence checked, website confirmed, not flagged as a possible manufacturer) | about 1 | 4 |
| Official website confirmed | 30% | 60% |
| Quotes checked | 80% (search summary only) | 100% (6 on the page itself) |
| Cost per search | about US$0.01 | about US$0.01 |

## Run it yourself

Buyer Finder works with two AI setups. Switch with one setting, no code changes.

| Setting | Search | Model | Cost per run |
|---|---|---|---|
| `deepseek` (default) | DeepSeek Search API (or [SerpAPI](https://serpapi.com) if you prefer) | DeepSeek Flash | about $0.01 |
| `claude` | Claude's built-in web search | Claude Haiku 5.5 | about $0.06 |

```bash
git clone https://github.com/hailey-studio/buyer-finder.git
cd buyer-finder
pip install -r requirements.txt

# DeepSeek setup: one key does both search and the model
export BUYER_FINDER_PROVIDER=deepseek
export DEEPSEEK_API_KEY="your-deepseek-key"

# or Claude setup
# export BUYER_FINDER_PROVIDER=claude
# export ANTHROPIC_API_KEY="your-claude-key"

streamlit run app.py
```

To deploy on Streamlit Community Cloud, put the same values in the app's **Secrets**, plus a password:

```toml
BUYER_FINDER_PROVIDER = "deepseek"
DEEPSEEK_API_KEY = "your-deepseek-key"
APP_PASSWORD = "choose-a-password"
```

## Tests

35 automated tests, one or more for every issue found in review (logic bugs, trust issues and usability problems). They replace every network call, so they run without an API key:

```bash
pip install -r requirements-dev.txt
python -m pytest tests
```

## Learned from

I studied open-source tools that solve similar problems and borrowed what works:
[b2b-buyer-discovery](https://github.com/Tommy-old/b2b-buyer-discovery) and [dsh-waimao](https://github.com/shine-233/dsh-waimao) (filtering out non-buyers, emails in the buyer's language),
[OpenOutreach](https://github.com/eracle/OpenOutreach) (a plain-language reason for every lead),
[company-research-agent](https://github.com/guy-hartstein/company-research-agent) (source-backed research).
Buyer Finder aims to be the simplest of these to use: one web page, in Chinese or English, with no setup for the end user.

## Limitations

- Web search misses companies with little online presence, and it can't verify emails or phone numbers.
- Searches and statuses are kept only while the browser tab is open.
- Built for a first list of leads, not for sending emails at scale.

## Next

- Test it with exporters I know and record what they do with the results.
- Trade fair exhibitor lists as a source (for example Canton Fair, India ITME).
- Save searches and statuses between visits.

## Built with

Python, Streamlit, [DeepSeek API](https://api-docs.deepseek.com) (model and search) or [Claude API](https://docs.claude.com). Developed with Claude as a coding assistant.
