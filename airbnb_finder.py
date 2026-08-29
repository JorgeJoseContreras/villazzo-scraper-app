"""
Airbnb Cross-Listing & Visual Matcher Module
Locates corresponding Airbnb listings and builds visual reverse-search links for scraped mansions.
"""

import json
import logging
import re
import urllib.parse
from pathlib import Path
from typing import List, Dict, Any, Optional

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger("airbnb_finder")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def get_cached_airbnb_match(villa_dir: Path) -> Optional[Dict[str, Any]]:
    """Reads saved Airbnb match from local json if it exists."""
    match_file = villa_dir / "airbnb_match.json"
    if match_file.exists():
        try:
            return json.loads(match_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Failed to read cached match from {match_file}: {e}")
    return None


def save_airbnb_match(villa_dir: Path, data: Dict[str, Any]) -> None:
    """Saves Airbnb match result into villa directory."""
    match_file = villa_dir / "airbnb_match.json"
    try:
        match_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to write match cache to {match_file}: {e}")


async def find_airbnb_matches_by_query(villa_name: str) -> List[str]:
    """
    Searches for exact Airbnb room links matching the property name and Miami location.
    """
    clean_name = villa_name.replace("Villa_", "").replace("Villa", "").strip()
    query = f'site:airbnb.com/rooms "Miami" "{clean_name}"'
    search_url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"

    found_links: List[str] = []

    try:
        async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=12.0) as client:
            resp = await client.get(search_url)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    match = re.search(r"uddg=([^&]+)", href)
                    target = urllib.parse.unquote(match.group(1)) if match else href
                    
                    if "/rooms/" in target or "/luxury/listing/" in target:
                        clean_link = target.split("?")[0]
                        if clean_link.startswith("https://www.airbnb.com") or clean_link.startswith("https://airbnb.com"):
                            if clean_link not in found_links:
                                found_links.append(clean_link)
    except Exception as e:
        logger.debug(f"Search index query notice for {villa_name}: {e}")

    return found_links


def build_airbnb_search_url(villa_name: str) -> str:
    """Creates a direct Airbnb query URL for Miami."""
    clean_name = villa_name.replace("Villa_", "").replace("Villa", "").strip()
    query_str = urllib.parse.quote(f"Villa {clean_name}")
    return f"https://www.airbnb.com/s/Miami--FL/homes?query={query_str}"


def build_google_airbnb_search_url(villa_name: str) -> str:
    """Creates a scoped Google search URL strictly for airbnb.com listings."""
    clean_name = villa_name.replace("Villa_", "").replace("Villa", "").strip()
    query = f'site:airbnb.com/rooms "Miami" "{clean_name}"'
    return f"https://www.google.com/search?q={urllib.parse.quote(query)}"


def build_lens_search_url(image_url: str) -> str:
    """Creates a Google Lens reverse-image search link."""
    return f"https://lens.google.com/uploadbyurl?url={urllib.parse.quote(image_url)}"


async def match_villa_to_airbnb(
    folder_name: str,
    download_dir: Path,
    force_refresh: bool = False
) -> Dict[str, Any]:
    """
    Main matching routine for a specific villa folder.
    """
    vdir = download_dir / folder_name
    if not vdir.exists():
        return {"status": "not_found", "message": "Villa directory does not exist."}

    # Check cached match
    if not force_refresh:
        cached = get_cached_airbnb_match(vdir)
        if cached:
            return cached

    display_name = folder_name.replace("_", " ")
    
    # 1. Attempt automated search index lookup
    direct_links = await find_airbnb_matches_by_query(display_name)
    primary_airbnb_url = direct_links[0] if direct_links else None

    # 2. Build direct search and reverse visual URLs
    airbnb_search_url = build_airbnb_search_url(display_name)
    google_airbnb_url = build_google_airbnb_search_url(display_name)

    result_data = {
        "folder_name": folder_name,
        "display_name": display_name,
        "is_matched": bool(primary_airbnb_url),
        "primary_url": primary_airbnb_url,
        "all_matched_urls": direct_links,
        "airbnb_search_url": airbnb_search_url,
        "google_airbnb_url": google_airbnb_url,
        "total_matches": len(direct_links),
        "status": "completed"
    }

    # Cache locally
    save_airbnb_match(vdir, result_data)

    return result_data
