# Booth demo

Everything that runs *on the booth-day laptop*, separate from the device-side code in [`scripts/`](../scripts/) and the OTA pipeline in [`.github/workflows/`](../.github/workflows/).

## What's here

```
demo/
├── README.md
└── dashboard/                # the big-screen "Show. Train. Ship. Repeat." view
    ├── server.py             # FastAPI backend that aggregates EI + Foundries + GitHub
    ├── requirements.txt
    ├── .env.example
    ├── Dockerfile
    ├── docker-compose.yml
    └── static/               # vanilla HTML/CSS/JS — no build step
        ├── index.html
        ├── dashboard.css
        └── dashboard.js
```

## The dashboard

A single-page view designed for a booth monitor:

- **Live inference** — iframes the `edge-impulse-linux-runner` web UI on the UNO Q (`:4912`)
- **Current version** — what's running on the device right now, with a sparkline of versions shipped today
- **Samples** — total samples in the EI project, plus how many landed in the last hour
- **Pipeline status** — current EI job, latest GitHub Actions run, Foundries target count + device count
- **Recent activity ticker** — the last few releases / EI jobs

The backend caches API responses on a 20-second interval, so the dashboard polls a single local endpoint (`/api/stats`) and the frontend stays cheap.

### Run it

Locally:

```bash
cd demo/dashboard
cp .env.example .env       # fill in the values
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8088
```

Then open <http://localhost:8088>.

Or with Docker:

```bash
cd demo/dashboard
cp .env.example .env       # fill in the values
docker compose up
```

### What env it needs

| Var | Purpose |
|---|---|
| `EI_API_KEY` | Edge Impulse project API key (read scope is enough) |
| `EI_PROJECT_ID` | numeric EI project ID |
| `FOUNDRIES_API_TOKEN` | Foundries OSF token (read scope on devices/targets) |
| `FOUNDRIES_FACTORY` | factory name (e.g. `jenny`) |
| `GH_REPO` | `owner/repo` (defaults to `yennster/ei-vision-uno-q-foundries`) |
| `GH_TOKEN` | optional — gives you 5000 req/hr instead of 60 |
| `RUNNER_URL` | URL of the live EI runner UI to iframe (e.g. `http://uno-q.local:4912`) |

These are *separate* from the GitHub Actions secrets — they live in the laptop's `.env` only and never get committed.
