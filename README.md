# Foundry Account Intelligence demo

A local web app that turns an Excel workbook of public-market data into a live demonstration of what Microsoft Foundry adds beyond Copilot Studio. It follows the three stages in the sample workbook's "Demo Prompts" sheet: AI helps (Copilot in Excel), AI works with you (Copilot Studio), AI executes (Foundry).

## Start

You need Python 3.12 and, for live mode, an Azure sign-in (`az login`).

```powershell
.\start.ps1
```

One command opens the server in its own terminal window, so your current terminal stays free. The script checks Python and the packages (and installs them on the first run), creates `.env` if it is missing, waits until the app answers, reports whether live mode is available and opens the browser at <http://127.0.0.1:8765>.

| Command | What it does |
|---------|--------------|
| `.\start.ps1` | Server in a new terminal, browser opens |
| `.\start.ps1 -WithTests` | Also opens a second terminal that runs the offline test suite |
| `.\start.ps1 -Reload` | Development mode: the server restarts when you edit files in `app\` |
| `.\start.ps1 -Port 9000 -NoBrowser` | Another port, without opening the browser |
| `.\start.ps1 -Stop` | Closes the terminals and stops the server (add `-Port` if you used one) |

Running it again while the app is up just opens the browser. If another program uses the port, the script says so and suggests `-Port`. It works in PowerShell 7 and Windows PowerShell 5.1.

To run in the current terminal instead, use `.\run.ps1`. If the page is open but empty, the server is not running. The page then says so and tells you how to restart it.

## Pages

| Page | What it shows | Stage |
|------|---------------|-------|
| Overview | The three levels of AI, Copilot Studio versus Foundry, and how they work together | All |
| Upload workbook | Drop an Excel file and watch the app read it: sheet found, columns mapped to app fields, companies extracted, data checked | Step 1 |
| Workbook | KPIs, sector momentum, rankings and data-quality findings computed from the loaded file | 1 |
| Public reports | Half-year reports published by five companies: verified headline figures with page links, growth and margin across companies, and a search over the report text | New |
| Account Monitor | Four Foundry agents (Data Steward, Signal Scout, Account Analyst, Compliance Reviewer) and a human approval step, with a live trace of tool calls, tokens and cost. The agents work on real share prices and news headlines | 3 |
| Insights chat | Chat with the peer and competitor analysis. A peer explorer lets you click companies to attach them to the question. Every answer lists its sources and is checked | 3 |
| Trust Lab | 15 test cases run against a basic agent and a governed agent, scored by rules and a judge model | 3 |
| Model Bake-off | The same briefing task on three models, with quality, latency and cost, plus an adjustable quality bar | 3 |

Long-running actions show their progress: a bar at the top of the page, loading skeletons, step-by-step progress in the Account Monitor, Trust Lab and Model Bake-off, and a typing indicator with tool steps in the chat.

## Less text, more indicators

Each page shows the main idea first and keeps the detail one click away.

* The page subtitle is the one-line message of the page. The small (i) button next to the title opens a guide with what the page shows, what to try and why it matters. It starts closed and remembers your choice per page
* Findings are tiles with a severity colour and a title. Click a tile for the explanation and the fix
* Long lists show the first items (10 securities in the Workbook table, 3 changes in the Account Monitor) and a button for the rest
* The Overview shows where Copilot Studio and Foundry sit on five spectrums (built by, autonomy, models, testing, interface) instead of a table. Hover a dot for the detail, open "More differences" for the rest
* The Account Monitor briefing is an accordion with counts (facts open, hypotheses, data gaps and open questions closed), and the compliance review is a row of six check marks
* Trust Lab shows a heat map of the 30 results (click a cell to read both answers) and keeps the question table behind "All 15 questions"
* The Model Bake-off recommendation is three numbers (quality, how much cheaper, cost per year) with the reason behind "Why this model?"
* On the Upload page each finished step folds into one line with its result. Click a step to open it again
* The chat keeps its suggestions in one place and shows three check indicators instead of paragraphs. The peer explorer shows each peer as one row: a signal dot, a momentum bar and an icon when a report is loaded
* The Public reports page shows growth and margin as bars, each figure with a page chip, and keeps the document details behind "About this report"

## Help for the audience and the presenter

* Dotted terms such as momentum score, signal, public feed, judge model and tokens show a plain-language explanation on hover or focus
* The Demo guide button opens an 8 step run-book with what to do and what to say, and moves you through the pages with Back and Next
* The A+ button enlarges everything for a projector
* On narrow windows the left rail shrinks to labelled icons and then turns into a tab bar at the top
* After the Account Monitor produces a briefing, "Discuss this briefing in chat" opens the chat and asks about it

## Using your own workbook

Open Upload workbook and drop an `.xlsx` file. The file is read in memory, never changed, and forgotten when the app restarts.

* One sheet needs a header row (it can sit below title rows) with Company, Ticker, Sector, Price, and the daily, 3M, 6M and 1Y performance columns
* Column names can vary, for example "Unternehmen", "Symbol", "Branche" or "Kurs"
* Performance can be decimals (0.0636), percent text ("6.36%") or percentage points (6.36)
* Blank or unreadable values are treated as missing, never as zero. A price of zero or below is treated as missing too
* Formulas that have no saved result (typical for files written by a script) are reported, because Excel has to open and save the file to store their values
* Tickers must be unique, and the first 2000 rows are read

The Workbook page, Account Monitor and Insights chat then use the loaded file. The monitoring events come from the real public feed (see Real market data) for every ticker the feed covers, which is the whole SMI Expanded list. A company the feed does not know gets no events and the briefing says so; nothing is generated. Trust Lab and Model Bake-off always run on the sample workbook because their test cases and recordings are written for it.

Two ready-made files are in `data/examples`. Both are cut from the real SMI Expanded workbook, so the prices, performance and companies are real. `Kundenportfolio_Demo.xlsx` holds 14 of the companies with German column names, title rows above the header and percent values, so it shows the mapping at work. `Stammdaten_ohne_Kurse.xlsx` holds the same companies as master data without any price column, so it shows the error message. `python -m app.examples` rebuilds both.

## Real market data

The monitoring agents and the chat use real data only. Nothing is invented or generated.

* Share prices: end-of-day closes on SIX from the Yahoo Finance chart endpoint, one series per security
* News: headlines from the Google News RSS search for each company, with publisher, date and link. Quote pages, valuation spam and ownership notices are filtered out
* The data is downloaded once into `data/feed/market_feed.json` with the time it was retrieved. The app only reads that file, so a demo works without internet
* A price event compares the latest close with the workbook price. Moves of 3% or more are events, 10% or more are material. A news event is kept when a keyword rule can say what it reports (outlook, leadership change, restructuring, deal, regulatory, results, analyst view or product news) and it is dated after the snapshot. At most two news events per company
* Events carry ids such as SIG-042. In answers and briefings the id is a chip that opens the publisher's page. The text names the publisher and the date, and headlines are quoted word for word
* Headlines are reports, not verified facts. Briefings say that they were not checked against company filings
* The workbook prices are real too: 42 of 44 match the Yahoo close on 28.08.2026. Roche (RO) and Roche (ROP) have each other's price, which may be a share class mapping difference. Pre-flight shows this check

```powershell
python -m app.feed refresh          # download quotes and news again (about a minute, no key needed)
python -m app.feed refresh NOVN RO  # only some tickers
python -m app.feed status
python -m app.record bakeoff        # after a refresh, so the replayed Bake-off uses the new evidence
```

Limits to mention when presenting:

* The keyword rules sometimes misread a headline (an analyst note about an outlook is not company guidance). In production a model would classify the headlines
* Google News and Yahoo Finance are free public sources without a service agreement. A production system would use a licensed market data and news feed
* The feed covers the companies in the SMI Expanded list. Other tickers get no events

## Public reports

Price data alone says what the market did. The app also reads the half-year reports that five companies published themselves, so answers can say what the business did.

| Company | Document | Standard |
|---------|----------|----------|
| VAT Group | Half-Year Report 2026 | IFRS |
| Partners Group | Interim Report 2026 | IFRS |
| Novartis | Q2 and H1 2026 Condensed Interim Financial Report | IFRS |
| Clariant | Condensed Consolidated Interim Financial Statements, H1 2026 | IFRS |
| Alcon | Interim Financial Report, Q2 2026 | IFRS |

The PDFs are public but copyrighted. They are kept in `data/reports` on this machine, are never modified and are not part of the project. Each answer quotes only short passages with the page number. `data/reports/manifest.json` records where each file came from. Download the PDFs from the company websites listed there to rebuild the folder.

How it works:

* The app reads every page, splits it into passages and, with an Azure sign-in, embeds them with the `text-embedding-3-large` deployment. Search combines keywords and embeddings (live mode). Offline mode uses keywords only and never calls Azure
* Headline figures (revenue, operating profit, net income, H1 2026 against H1 2025) are read by a model once and stored in `data/reports/financials.json`. Each figure has to pass three checks before it is used: the quote is on the stated page, both numbers appear in it exactly as printed, and the two numbers are neighbouring columns of one row. The tests also compare every figure with values read by hand from the PDFs
* The chat has three new tools (`get_financials`, `compare_financials`, `search_reports`). The Account Monitor briefing adds two report facts for these companies. Sources show as page chips that open the PDF at that page
* A company without a report gets a plain answer saying so, and the answer names the companies that do have one

Commands:

```powershell
python -m app.reports build      # read the PDFs, split into passages, embed them (embedding needs az login)
python -m app.reports extract    # let a model read the headline figures, keep only those that pass the checks
python -m app.reports status
```

Limits to mention when presenting:

* The reports cover the first half of 2026 (to 30 June). The workbook prices are from 28.08.2026. The app says so in answers and briefings
* Operating profit is labelled as each company reports it (EBIT, operating income, operating profit), so margins are comparable only with care
* Only five companies have a report, and only the latest half year. Annual reports and exchange announcements can be added the same way
* The Clariant file still shows the cover of its 2022 report on page 1. The statements inside are for the first half of 2026, and the app discloses this
* In tables that group thousands with spaces ("1 167.0") a number cannot be told from the end of a longer one by text alone. The row check and the hand-checked values cover that

## Insights chat

The chat answers from tools that read the workbook, the real market feed, the public reports and briefings created in this session: company profile, peers in the same sector, side-by-side comparison, deterministic rankings, sector overview, changes since the snapshot, briefings, data quality, and report figures and passages.

* "Competitors" means peers in the same sector. The workbook has no market share or product data and the assistant says so. For the five companies with a report it can also compare revenue growth and margins
* Every answer shows its sources, how many figures match the tool results, and whether advice-like wording was held back
* Each answer ends with up to three "Ask next" questions that build on it, so the conversation can continue with one click
* Live mode lets a Foundry model choose the tools (13 of them). Offline mode uses a rule-based router over the same tools

The peer explorer is the part to show when comparing Foundry with Copilot Studio: the interface around the agent is yours to design.

* The side panel shows a company and its sector peers, strongest momentum first. Pick another company from the list to change it. It also follows the conversation: when an answer is about a company in another sector, the explorer moves there
* Click a peer to attach it to your question. Attached companies appear as pills above the input and again on your message, so everyone sees what the question was about
* Click a company code (NOVN, RO) in an answer to attach it too. The tray offers one-click questions: Compare, Peers, What changed, H1 results
* Attached companies stay for the next question until you remove them or press Clear. A company named in the question wins over the attached ones, and a question about the whole workbook ("Who are the strongest companies?") ignores them
* In live mode the model is told which companies were attached and still has to look everything up and cite it. In offline mode the same selection steers the router
* Up to five companies can be attached. The browser sends their tickers as `references` with the question

## Before you go on stage

Run the pre-flight check once on the machine you present from. It needs the app to be started only for the last line.

```powershell
.\start.ps1 -Check                # files, reports, market feed, Azure sign-in, every model answers, is the app running with the sample workbook
.\start.ps1 -Rehearse             # also runs the live demo flow and times each step
.\start.ps1 -Rehearse -Full       # also runs Trust Lab and Model Bake-off live (about 2 minutes, a few cents)
```

The result is READY, READY WITH CAUTION (read the warnings) or NOT READY (fix the FAIL lines). A failed sign-in names the fix: `az login`.

Timings measured live (your network and model load will vary):

| Step | Live | Offline replay |
|------|------|----------------|
| Account Monitor cycle | about 17 s | about 20 s |
| Insights chat answer | 3 to 5 s | 3 to 4 s |
| Trust Lab (30 answers) | about 20 s | about 10 s |
| Model Bake-off (15 briefings) | about 65 s | about 8 s |

The Model Bake-off is the one to plan for: talk through the three models while it runs, or switch to Offline replay. The Demo guide shows these hints next to each step.

## Live and offline mode

The toggle in the top bar switches between the two modes.

* Live mode calls model deployments in a Foundry resource using your Entra identity. No API key is stored.
* Offline mode runs without Azure. The Account Monitor and the chat use the same tools and rules with template text. Trust Lab and Model Bake-off replay `app/recordings/*.json`, which were captured from real live runs.

The app falls back to offline mode automatically when no Azure sign-in is available.

## Configuration

Copy `.env.example` to `.env` and adjust the endpoint, the deployment names per agent role and the quality bar. Token prices live in `app/config.py` (Azure retail list prices, Global Standard, Sweden Central, retrieved 2026-10-15).

Models in the default setup (each must exist as a deployment with that name in your Foundry resource):

| Job | Model | USD per 1M tokens (in / out) |
|-----|-------|------------------------------|
| Data Steward, Signal Scout, Account Analyst, Insights chat, Trust Lab agents | `gpt-6-luna` | 0.10 / 0.50 |
| Compliance Reviewer and the judge in Trust Lab and Model Bake-off | `gpt-5.5` | 5.00 / 30.00 |
| Third Model Bake-off candidate | `gpt-5.6-luna` | 0.20 / 1.20 |

The luna models refuse function tools together with a reasoning effort. The client in `app/llm.py` detects that on the first rejection, retries with reasoning effort `none` and remembers it for that model, so the chat and the agent tool loops work without any setting. Calls without tools keep reasoning effort `low`.

Reading the reports uses `MODEL_EXTRACTOR` (default `gpt-6-luna`) for the headline figures and `MODEL_EMBEDDINGS` (default `text-embedding-3-large`, 768 dimensions) for search. The `pypdf` package reads the PDFs.

After you change a model or refresh the market feed, refresh the replay data with `python -m app.record`, because Trust Lab and Model Bake-off replay what was recorded.

To refresh the recordings after changing prompts, test cases or models:

```powershell
python -m app.record
```

## Tests

The tests treat the Excel file as ground truth and read it independently of the app code.

```powershell
pip install pytest
python -m pytest -m "not ui"                  # 377 offline tests, about 20 seconds, no Azure needed
python -m pytest                              # 437 tests including the 60 browser tests, about 3 minutes
$env:RUN_LIVE=1; python -m pytest -m live     # 21 tests that ask real models about the Excel data, the reports and the clicked companies
```

The browser tests need Playwright and Chromium (`pip install playwright; playwright install chromium`). Without them they are skipped.

* Page text: every page has a word limit for what a first-time viewer sees on arrival (for example 140 words for the chat), so new text has to go behind a disclosure
* Browser behaviour: the guide starts closed and is remembered per page, finding tiles and table rows expand on request, finished upload steps fold, the Account Monitor briefing is an accordion, the Trust Lab heat map matches the scores, and no page scrolls sideways at 1200, 900 and 600 pixels

* Public reports: every figure equals the value read by hand from the PDF, the three figure checks reject made-up quotes, wrong pages and numbers from different rows, search finds the right page offline, answers are grounded and cite pages, a report with hidden instructions is not followed, and the PDFs are never modified. They skip when the PDFs are not on the machine
* Excel integrity: sheets, 50 unique rows, the 6 securities without data, formula weights, cached values
* App versus Excel: every field, momentum scores, corrected signals, KPIs, sector averages, share classes
* Upload: column mapping (including German names and title rows), percent handling, missing values, zero prices, formulas without results, merged cells, a 2000 row file, rejected files, real events for an uploaded portfolio, no invented events for unknown companies, example files that contain real values, and the pages that use an uploaded file
* A running stream keeps the workbook it started with when another file is uploaded
* Pre-flight: it passes on a healthy setup, fails with the fix named when sign-in or files are broken, and the offline rehearsal covers every demo step
* Model client: the retry for models that refuse tools with a reasoning effort, and the default model setup
* Page structure: unique element ids, a guide for every page, and glossary terms that exist
* Real feed: every security has a real quote series and news, workbook prices match the Yahoo close on the snapshot date, price events match the cached quote, news events are real cached headlines without noise, the headline rules classify what they should, and a small fixed feed gives exactly the expected events
* Chat references: clicked companies become the subject of a question that names none, a named company wins, whole-workbook questions ignore them, a live model is told about them, and the peer explorer shows peers by momentum
* Agents: briefings pass the policy checks for every company, and the checks catch advice, invented numbers, bad sources and missing gaps
* Chat: every tool against the Excel data, routing of 25 question types, guardrails against advice and sales inference, answer verification, follow-up questions, and hostile or unusual input
* Trust Lab and Model Bake-off: expected answers match the Excel data and the recordings are consistent
* The Excel file must have the same hash before and after the run

## What is real

* The sample data is read from `data/Verkaufszahlen_Demo_SMI_Expanded.xlsx` and is never modified.
* The report figures come from the companies' own published half-year reports (see Public reports). The workbook itself has no revenue or earnings data.
* The monitoring events are real share prices and news headlines downloaded from public sources (see Real market data). The example workbooks are cut from the real file. No data in the app is invented.
* Free public sources are fine for a demo. For production use a licensed market data and news feed, or Foundry web search or an MCP server, and let a model classify the headlines.
* The agents run in this local app and use Foundry for the models and content safety. In production they would be hosted in Foundry's agent service.
* The approval step logs a decision in memory only. No message is sent.
* Nothing in the app is investment advice.

## Findings in the sample workbook

The Data Steward agent reports these issues, which also make good talking points:

* The Signal column is mis-scaled. Returns are decimals but the thresholds are percentage points, so all 44 rows show "Mixed". After rescaling there are 8 positive, 33 mixed and 3 negative signals.
* Six securities have no market data and are excluded from rankings.
* Roche, Schindler and Lindt appear twice as share classes.
* The market snapshot is dated 28.08.2026.

## Suggested 20-minute flow

1. Overview (2 min): the ladder and the comparison table.
2. Upload workbook (3 min): drop the file and narrate the mapping and the extracted companies.
3. Workbook (2 min): the findings and the "same data, two answers" panel.
4. Public reports (2 min): growth and margin across the five companies, open a figure's PDF page, search for the outlook.
5. Account Monitor (5 min): run a cycle in live mode, open the trace, approve the briefing.
6. Insights chat (4 min): click Novartis and two peers in the Peer explorer and press Compare, ask for Novartis' results, then try the trap question. Say that the selection is your own interface around the agent.
7. Trust Lab (2 min): run the evaluation and open a failing case.
8. Model Bake-off (2 min): drag the quality bar and read the annual cost.
