"""
FastAPI Backend Application for Villazzo Miami Mansion Scraper & Gallery Dashboard
"""

import os
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any

import uvicorn
from fastapi import FastAPI, BackgroundTasks, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from scraper import (
    VillazzoScraper,
    global_scraper_state,
    list_downloaded_villas,
    DEFAULT_DOWNLOAD_DIR,
)

# Initialize FastAPI app
app = FastAPI(
    title="Villazzo Miami Portfolio Scraper & Dashboard",
    description="High-resolution luxury villa image scraper and responsive web viewer",
    version="1.0.0",
)

# Base Paths
BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
TEMPLATES_DIR = BASE_DIR / "templates"

# Ensure directory structures exist
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

# Mount downloads directory as static route
app.mount("/downloads", StaticFiles(directory=str(DOWNLOAD_DIR)), name="downloads")

# Setup Jinja2 template engine
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


class ScrapeRequest(BaseModel):
    force_rescrape: bool = False


async def run_scraper_background(force_rescrape: bool = False):
    """Background worker task to run the scraper."""
    scraper = VillazzoScraper(download_dir=DOWNLOAD_DIR, state=global_scraper_state, force_rescrape=force_rescrape)
    await scraper.run()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Serves the interactive frontend web dashboard."""
    villas = list_downloaded_villas(download_dir=DOWNLOAD_DIR)
    total_photos = sum(v["count"] for v in villas)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "villas": villas,
            "total_villas": len(villas),
            "total_photos": total_photos,
            "status": global_scraper_state.to_dict(),
        }
    )


@app.post("/api/scrape/start")
async def start_scrape(background_tasks: BackgroundTasks, payload: Optional[ScrapeRequest] = None):
    """
    Kicks off the scraper asynchronously in the background.
    """
    if global_scraper_state.is_running:
        return JSONResponse(
            status_code=409,
            content={
                "status": "error",
                "message": "Scrape task is already in progress.",
                "state": global_scraper_state.to_dict(),
            }
        )

    force = payload.force_rescrape if payload else False
    background_tasks.add_task(run_scraper_background, force_rescrape=force)

    return {
        "status": "started",
        "message": f"Scrape job initialized (force_rescrape={force}).",
        "state": global_scraper_state.to_dict(),
    }


@app.get("/api/scrape/status")
async def get_scrape_status():
    """
    Returns current scraping state (idle, in-progress, logs, latest stats).
    """
    return global_scraper_state.to_dict()


@app.get("/api/villas")
async def get_villas():
    """
    Returns JSON list of all scraped villas, image counts, and URLs to the static images.
    """
    villas = list_downloaded_villas(download_dir=DOWNLOAD_DIR)
    total_photos = sum(v["count"] for v in villas)
    return {
        "total_villas": len(villas),
        "total_photos": total_photos,
        "villas": villas,
    }


from airbnb_finder import match_villa_to_airbnb

@app.post("/api/villas/{folder_name}/airbnb/search")
async def search_single_villa_airbnb(folder_name: str, force: bool = False):
    """Searches for corresponding Airbnb listing for a single villa."""
    result = await match_villa_to_airbnb(folder_name=folder_name, download_dir=DOWNLOAD_DIR, force_refresh=force)
    return result


@app.post("/api/airbnb/search-all")
async def search_all_villas_airbnb(background_tasks: BackgroundTasks, force: bool = False):
    """Scans and matches all downloaded villas against Airbnb in background."""
    async def run_all_matches():
        villas = list_downloaded_villas(download_dir=DOWNLOAD_DIR)
        for v in villas:
            await match_villa_to_airbnb(folder_name=v["folder_name"], download_dir=DOWNLOAD_DIR, force_refresh=force)
            await asyncio.sleep(1.0)
    
    background_tasks.add_task(run_all_matches)
    return {"status": "started", "message": "Searching Airbnb cross-listings for all villas in background."}


@app.get("/healthz")
async def health_check():
    """Service health probe for container and deployment monitors."""
    return {"status": "ok", "service": "villazzo-scraper-app"}


if __name__ == "__main__":
    # Render and Cloud dynamic port configuration
    port = int(os.environ.get("PORT", 8000))
    host = "0.0.0.0"
    print(f"Starting Villazzo Web Service on http://{host}:{port}")
    uvicorn.run("main:app", host=host, port=port, reload=False)
