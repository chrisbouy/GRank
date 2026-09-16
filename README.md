# GRank

Find which page of Google search results your site ranks on for a list of
search terms. You paste in terms and a target domain; GRank queries the
**Serper.dev Google Search API**, pages through the results, and tells you the
page number, position, and the matching URL for each term.

## Why Serper (and not Google's own API or scraping)

- **Scraping Google directly** gets blocked fast with CAPTCHAs and IP blocks
  once traffic looks automated, and it's against Google's terms.
- **Google's Custom Search JSON API is closed to new accounts.** New Google
  Cloud projects get `403 PERMISSION_DENIED` ("This project does not have the
  access to Custom Search JSON API") even when the API shows "Enabled" in the
  console, so it can't be used for whole-web rank checking anymore.
- **Serper.dev** returns real, whole-web Google organic results as JSON, with
  rank positions, and has a free tier. It's the practical way to get true
  Google rankings programmatically.

Note: results still reflect Serper's query context, not your personal logged-in
Google session, so treat ranks as a consistent, trackable measure rather than an
exact reproduction of what one specific person sees.

## Setup

### 1. Install Python dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Get a Serper API key

1. Go to <https://serper.dev> and sign up (free tier available).
2. Copy your API key from the dashboard.

### 3. Configure credentials

```bash
cp .env.example .env
```

Edit `.env` and set your key:

```
SERPER_API_KEY=your_real_key_here
```

`.env` is gitignored so your key stays out of version control.

## Run

```bash
python app.py
```

Open <http://127.0.0.1:5000>, enter your target domain (e.g. `example.com`),
paste your search terms (one per line), and click **Check rankings**.

## Use the JSON API directly

```bash
curl -X POST http://127.0.0.1:5000/api/rank \
  -H "Content-Type: application/json" \
  -d '{
        "target": "example.com",
        "terms": "best running shoes\nmarathon training plan"
      }'
```

`terms` accepts either a newline/comma-separated string or a JSON array.
Response shape:

```json
{
  "target": "example.com",
  "count": 2,
  "results": [
    {
      "term": "best running shoes",
      "found": true,
      "page": 3,
      "position": 24,
      "url": "https://example.com/shoes",
      "title": "Best Running Shoes",
      "total_results_scanned": 24,
      "error": null
    }
  ]
}
```

## How the page number is calculated

Google shows 10 results per page by convention, so absolute position 24 lands
on page 3 (`((position - 1) // 10) + 1`). GRank uses the position Serper
reports for each organic result.

## Configuration reference

| Variable | Default | Meaning |
|---|---|---|
| `SERPER_API_KEY` | — | Serper.dev API key (required) |
| `MAX_PAGES` | 10 | How many result pages deep to search (10 pages = top 100) |
| `SEARCH_COUNTRY` | — | Optional country bias, e.g. `us`, `gb` (Serper `gl`) |
| `SEARCH_LANGUAGE` | — | Optional language bias, e.g. `en` (Serper `hl`) |
| `PORT` | 5000 | Port the web app listens on |
| `LOG_LEVEL` | INFO | Logging verbosity: `INFO` or `DEBUG` |

## Logging & troubleshooting

GRank logs to the console (stderr). At the default `INFO` level you'll see each
term's outcome and a per-run summary:

```
2026-09-15 10:22:01  INFO     grank.app     /api/rank request: target='example.com' terms=5
2026-09-15 10:22:01  INFO     grank.serper  Checking term='best running shoes' for target='example.com'
2026-09-15 10:22:02  INFO     grank.serper  FOUND term='best running shoes'  page=3  position=24  url=https://example.com/shoes
2026-09-15 10:22:05  INFO     grank.serper  Rank check complete: 5 checked, 3 found, 0 error(s)
```

Set `LOG_LEVEL=DEBUG` in `.env` to also see each request and its timing. If
Serper rejects a request, the logs capture the status and response body:

- **HTTP 401 / 403** — `SERPER_API_KEY` is missing or wrong.
- **HTTP 429** — rate limit hit or credits exhausted; check your Serper plan.

## Project layout

```
GRank/
├── app.py                  # Flask web app + /api/rank endpoint
├── grank/
│   ├── __init__.py
│   ├── logging_config.py   # Shared logging setup + key redaction
│   ├── search_client.py    # Shared helpers + (legacy) Google client
│   └── serper_client.py    # Serper.dev client + rank detection
├── templates/
│   └── index.html          # Web UI
├── requirements.txt
├── .env.example
└── README.md
```
