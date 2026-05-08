"""
Booth dashboard backend.

Aggregates the live state of the EI project + Foundries factory + GitHub
repo into a single /api/stats endpoint that the static frontend polls.
Credentials live only on the booth laptop's .env — they never leak to
the browser.

Refreshes the cache on a fixed interval (default 20s) in the background,
so the frontend can poll cheaply without rate-limiting any of the three
upstream APIs.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

EI_API_KEY          = os.environ.get("EI_API_KEY", "")
EI_PROJECT_ID       = os.environ.get("EI_PROJECT_ID", "")
FOUNDRIES_API_TOKEN = os.environ.get("FOUNDRIES_API_TOKEN", "")
FOUNDRIES_FACTORY   = os.environ.get("FOUNDRIES_FACTORY", "")
GH_REPO             = os.environ.get("GH_REPO", "yennster/ei-vision-uno-q-foundries")
GH_TOKEN            = os.environ.get("GH_TOKEN", "")
RUNNER_URL          = os.environ.get("RUNNER_URL", "")
POLL_INTERVAL       = int(os.environ.get("POLL_INTERVAL", "20"))

EI_BASE  = "https://studio.edgeimpulse.com/v1/api"
FND_BASE = "https://api.foundries.io"
GH_BASE  = "https://api.github.com"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("booth")

state: dict[str, Any] = {
    "ei":         None,
    "foundries":  None,
    "github":     None,
    "config":     {
        "runnerUrl": RUNNER_URL,
        "factory":   FOUNDRIES_FACTORY,
        "repo":      GH_REPO,
        "projectId": EI_PROJECT_ID,
    },
    "lastUpdated": None,
}


# ----- upstream fetchers --------------------------------------------------- #

async def fetch_ei(client: httpx.AsyncClient) -> dict[str, Any]:
    if not (EI_API_KEY and EI_PROJECT_ID):
        return {"configured": False}
    h = {"x-api-key": EI_API_KEY}

    async def get_json(path: str) -> dict[str, Any]:
        r = await client.get(f"{EI_BASE}/{EI_PROJECT_ID}{path}", headers=h)
        r.raise_for_status()
        return r.json()

    proj = await get_json("")
    train = await get_json("/raw-data/count?category=training")
    test  = await get_json("/raw-data/count?category=testing")
    jobs  = await get_json("/jobs?limit=8")
    history = await get_json("/deployment/history")

    p = proj.get("project", {})

    # Find a currently-running job, if any.
    running = None
    for j in jobs.get("jobs", []):
        if j.get("started") and not j.get("finished"):
            running = j
            break

    return {
        "configured":  True,
        "projectName": p.get("name", "?"),
        "projectId":   p.get("id"),
        "trainCount":  train.get("count", 0),
        "testCount":   test.get("count", 0),
        "totalCount":  train.get("count", 0) + test.get("count", 0),
        "runningJob":  running and {
            "id":       running.get("id"),
            "category": running.get("category"),
            "started":  running.get("started"),
        },
        "recentJobs": [
            {
                "id":         j.get("id"),
                "category":   j.get("category"),
                "started":    j.get("started"),
                "finished":   j.get("finished"),
                "successful": j.get("finishedSuccessful"),
            }
            for j in jobs.get("jobs", [])[:6]
        ],
        "deploymentCount": history.get("totalDeploymentCount", 0),
        "latestDeployment": (history.get("deployments") or [{}])[0].get("deploymentVersion"),
    }


async def fetch_foundries(client: httpx.AsyncClient) -> dict[str, Any]:
    if not (FOUNDRIES_API_TOKEN and FOUNDRIES_FACTORY):
        return {"configured": False}
    h = {"OSF-TOKEN": FOUNDRIES_API_TOKEN}

    devices_resp = await client.get(
        f"{FND_BASE}/ota/devices/?factory={FOUNDRIES_FACTORY}", headers=h
    )
    devices_resp.raise_for_status()
    devices_payload = devices_resp.json()
    devices = devices_payload.get("devices", [])

    targets_resp = await client.get(
        f"{FND_BASE}/ota/repo/{FOUNDRIES_FACTORY}/api/v1/user_repo/targets.json",
        headers=h,
    )
    targets_resp.raise_for_status()
    signed = targets_resp.json().get("signed", {}) or {}
    targets = signed.get("targets", {}) or {}

    # Sort target names by trailing version number (best-effort).
    def name_sort_key(name: str) -> int:
        tail = name.rsplit("-", 1)[-1]
        try:
            return int(tail)
        except ValueError:
            return -1

    target_names = sorted(targets.keys(), key=name_sort_key, reverse=True)

    return {
        "configured":   True,
        "factory":      FOUNDRIES_FACTORY,
        "deviceCount":  devices_payload.get("total", len(devices)),
        "devices": [
            {
                "name":       d.get("name"),
                "hardwareId": (d.get("factory_hardware_ids") or ["?"])[0]
                              if isinstance(d.get("factory_hardware_ids"), list)
                              else d.get("hardware-id", "?"),
                "targetName": d.get("target-name"),
                "lastSeen":   d.get("last-seen"),
            }
            for d in devices[:10]
        ],
        "targetCount":   len(targets),
        "latestTargets": target_names[:6],
    }


async def fetch_github(client: httpx.AsyncClient) -> dict[str, Any]:
    h: dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if GH_TOKEN:
        h["Authorization"] = f"Bearer {GH_TOKEN}"

    runs_resp = await client.get(
        f"{GH_BASE}/repos/{GH_REPO}/actions/runs?per_page=8", headers=h
    )
    runs_resp.raise_for_status()
    runs = runs_resp.json().get("workflow_runs", [])

    tags_resp = await client.get(f"{GH_BASE}/repos/{GH_REPO}/tags?per_page=10", headers=h)
    tags_resp.raise_for_status()
    tags = tags_resp.json()

    return {
        "configured": True,
        "repo":       GH_REPO,
        "recentRuns": [
            {
                "name":       r.get("name"),
                "status":     r.get("status"),
                "conclusion": r.get("conclusion"),
                "created":    r.get("created_at"),
                "url":        r.get("html_url"),
                "headBranch": r.get("head_branch"),
                "event":      r.get("event"),
            }
            for r in runs[:6]
        ],
        "recentTags": [{"name": t.get("name")} for t in tags[:8]],
    }


# ----- background refresh -------------------------------------------------- #

async def refresh_state() -> None:
    async with httpx.AsyncClient(timeout=15.0) as client:
        results = await asyncio.gather(
            fetch_ei(client),
            fetch_foundries(client),
            fetch_github(client),
            return_exceptions=True,
        )
    for key, val in zip(("ei", "foundries", "github"), results):
        if isinstance(val, Exception):
            log.warning("fetch_%s failed: %s", key, val)
            state[key] = {"error": str(val)}
        else:
            state[key] = val
    state["lastUpdated"] = time.time()
    log.info(
        "refreshed: ei.total=%s foundries.devices=%s github.runs=%s",
        (state["ei"] or {}).get("totalCount"),
        (state["foundries"] or {}).get("deviceCount"),
        len((state["github"] or {}).get("recentRuns", [])),
    )


async def background_loop() -> None:
    while True:
        try:
            await refresh_state()
        except Exception:
            log.exception("refresh_state failed")
        await asyncio.sleep(max(POLL_INTERVAL, 5))


# ----- app ---------------------------------------------------------------- #

@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(background_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Booth dashboard", lifespan=lifespan)


@app.get("/api/stats")
async def stats():
    return JSONResponse(state)


@app.post("/api/refresh")
async def refresh_now():
    await refresh_state()
    return JSONResponse(state)


@app.get("/healthz")
async def healthz():
    return {"ok": True, "lastUpdated": state.get("lastUpdated")}


# Serve static assets last so the API routes win.
static_dir = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
