"""
Villazzo Miami Portfolio Scraper
Extracts villa details and full-resolution gallery photographs from Villazzo's Miami portfolio.
"""

import os
import re
import sys
import time
import shutil
import logging
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional, Set, Callable
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("villazzo_scraper")

# Base constants
BASE_URL = "https://www.villazzo.com"
MIAMI_LISTING_URL = "https://www.villazzo.com/rental-villas/miami/"
DEFAULT_DOWNLOAD_DIR = Path("./downloads")

# Browser-like headers to avoid Cloudflare/WAF blocks
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

IMG_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Referer": "https://www.villazzo.com/",
}

# Non-Miami destinations to explicitly exclude if present in navigation menus
OTHER_DESTINATIONS = [
    "ibiza", "saint-tropez", "st-tropez", "aspen", "st-barts", "saint-barth", 
    "courchevel", "marbella", "tuscany", "mykonos", "capri", "amalfi"
]


def sanitize_folder_name(name: str) -> str:
    """Sanitizes a villa name into a clean directory name (e.g. Villa_Naomi)."""
    clean = re.sub(r'[\/:*?"<>|]', '', name)
    clean = clean.strip().replace(' ', '_')
    # Collapse multiple underscores
    clean = re.sub(r'_+', '_', clean)
    clean = clean.strip('_')
    if not clean.lower().startswith('villa_') and not clean.lower().startswith('villa'):
        clean = f"Villa_{clean}"
    return clean


def clean_image_url(url: str) -> str:
    """
    Transforms WordPress resized image URLs to original full-resolution URLs.
    Example: 00-Villa-Naomi-1090x750.jpg -> 00-Villa-Naomi.jpg
    """
    base = url.split('?')[0]
    # Remove dimension suffixes like -1090x750 or -675x490
    high_res = re.sub(r'-\d+x\d+(?=\.(?:jpe?g|png|webp)$)', '', base, flags=re.IGNORECASE)
    # Remove -scaled suffix if present before extension
    high_res = re.sub(r'-scaled(?=\.(?:jpe?g|png|webp)$)', '', high_res, flags=re.IGNORECASE)
    return high_res


class ScraperState:
    """Thread-safe state container for monitoring scraper runs."""
    def __init__(self):
        self.is_running: bool = False
        self.status: str = "idle"  # idle | running | completed | error
        self.message: str = "Scraper is idle."
        self.current_villa: str = ""
        self.total_villas: int = 0
        self.processed_villas: int = 0
        self.total_images_downloaded: int = 0
        self.logs: List[str] = []
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.error: Optional[str] = None
        self._max_logs: int = 100

    def add_log(self, text: str):
        timestamp = time.strftime("%H:%M:%S")
        entry = f"[{timestamp}] {text}"
        self.logs.append(entry)
        if len(self.logs) > self._max_logs:
            self.logs = self.logs[-self._max_logs:]
        logger.info(text)

    def to_dict(self) -> Dict[str, Any]:
        elapsed = 0.0
        if self.start_time:
            end = self.end_time or time.time()
            elapsed = round(end - self.start_time, 1)

        progress_pct = 0
        if self.total_villas > 0:
            progress_pct = int((self.processed_villas / self.total_villas) * 100)

        return {
            "is_running": self.is_running,
            "status": self.status,
            "message": self.message,
            "current_villa": self.current_villa,
            "total_villas": self.total_villas,
            "processed_villas": self.processed_villas,
            "progress_percent": progress_pct,
            "total_images_downloaded": self.total_images_downloaded,
            "elapsed_seconds": elapsed,
            "logs": self.logs[-25:],
            "error": self.error,
        }


# Global scraper state instance
global_scraper_state = ScraperState()


class VillazzoScraper:
    def __init__(
        self,
        download_dir: Path = DEFAULT_DOWNLOAD_DIR,
        state: Optional[ScraperState] = None,
        force_rescrape: bool = False,
    ):
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.state = state or global_scraper_state
        self.force_rescrape = force_rescrape
        self.semaphore = asyncio.Semaphore(5)  # Safe concurrency limit

    async def fetch_html(self, client: httpx.AsyncClient, url: str) -> Optional[str]:
        """Fetches page HTML with custom browser headers and retries."""
        for attempt in range(3):
            try:
                resp = await client.get(url, headers=BROWSER_HEADERS, timeout=25.0, follow_redirects=True)
                if resp.status_code == 200:
                    return resp.text
                elif resp.status_code == 404:
                    self.state.add_log(f"Page not found (404): {url}")
                    return None
                else:
                    self.state.add_log(f"HTTP {resp.status_code} for {url} (attempt {attempt + 1})")
            except Exception as e:
                self.state.add_log(f"Fetch error on {url} (attempt {attempt + 1}): {str(e)}")
            await asyncio.sleep(1.5 * (attempt + 1))
        return None

    async def extract_villa_links(self, client: httpx.AsyncClient) -> List[Dict[str, str]]:
        """
        Crawls the Miami listing page and extracts all individual Miami villa URLs and names.
        """
        self.state.add_log("Connecting to Villazzo Miami portfolio page...")
        html = await self.fetch_html(client, MIAMI_LISTING_URL)
        if not html:
            self.state.add_log("HTTP fetch returned no content. Trying Playwright fallback...")
            html = await self._fetch_with_playwright(MIAMI_LISTING_URL)

        if not html:
            raise RuntimeError("Failed to fetch Miami portfolio page content.")

        soup = BeautifulSoup(html, "html.parser")
        villas_dict: Dict[str, str] = {}

        # Scan all links matching Miami villa patterns
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            full_url = urljoin(BASE_URL, href)
            lower_url = full_url.lower()
            
            # Exclude non-Miami destination hubs
            if any(f"/{dest}/" in lower_url or f"-{dest}/" in lower_url for dest in OTHER_DESTINATIONS):
                continue

            # Check for Miami villa specific URLs
            is_miami_villa = (
                "/miami-rental-villas/" in lower_url or
                "/miami-s1/" in lower_url or
                ("/rental-villas/miami/" in lower_url and lower_url != MIAMI_LISTING_URL.lower())
            )

            # Exclude non-villa paths
            ignored_tokens = [
                "contact", "experience", "services", "lostpassword", "wp-content", 
                "feed", "terms", "privacy", "tag", "category", "yacht-charters", "vvip"
            ]
            if any(token in lower_url for token in ignored_tokens):
                continue

            if is_miami_villa:
                clean_url = full_url.split("?")[0].split("#")[0]
                if not clean_url.endswith("/"):
                    clean_url += "/"

                text = a_tag.get_text(strip=True)
                slug_match = re.search(r'/([^/]+)/$', clean_url)
                fallback_name = slug_match.group(1).replace('-', ' ').title() if slug_match else "Villa"
                
                name = text if text and len(text) > 2 and "read more" not in text.lower() else fallback_name
                
                # Normalization
                if not name.lower().startswith("villa ") and not name.lower().startswith("villa"):
                    name = f"Villa {name}"

                if clean_url not in villas_dict:
                    villas_dict[clean_url] = name

        results = [{"url": url, "name": name} for url, name in villas_dict.items()]
        self.state.add_log(f"Discovered {len(results)} Miami luxury villas in portfolio.")
        return results

    async def _fetch_with_playwright(self, url: str) -> Optional[str]:
        """Playwright headless browser fallback for JavaScript-rendered DOMs."""
        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
                )
                context = await browser.new_context(user_agent=BROWSER_HEADERS["User-Agent"])
                page = await context.new_page()
                await page.goto(url, wait_until="networkidle", timeout=30000)
                content = await page.content()
                await browser.close()
                return content
        except Exception as e:
            self.state.add_log(f"Playwright fallback failed: {str(e)}")
            return None

    def extract_image_urls_from_page(self, soup: BeautifulSoup, page_url: str) -> List[str]:
        """
        Finds all gallery images, strips WP thumbnail scalings to get maximum resolution originals.
        """
        image_candidates: Set[str] = set()

        # 1. Look for all <img> tags
        for img in soup.find_all("img"):
            srcset = img.get("srcset") or img.get("data-srcset")
            if srcset:
                parts = [p.strip().split(" ")[0] for p in srcset.split(",") if p.strip()]
                for p in parts:
                    if "wp-content/uploads" in p:
                        image_candidates.add(p)

            for attr in ["src", "data-src", "data-lazy-src", "data-full-image", "data-large_image"]:
                src = img.get(attr)
                if src and "wp-content/uploads" in src:
                    image_candidates.add(src)

        # 2. Look for anchor links pointing directly to images
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "wp-content/uploads" in href and re.search(r'\.(jpe?g|png|webp)$', href, re.IGNORECASE):
                image_candidates.add(href)

        # 3. Regex scan over page HTML
        html_str = str(soup)
        regex_matches = re.findall(
            r'https://www\.villazzo\.com/wp-content/uploads/[^"\'\s<>\)]+?\.(?:jpe?g|png|webp)',
            html_str,
            re.IGNORECASE
        )
        for m in regex_matches:
            image_candidates.add(m)

        # Filter and normalize candidates
        high_res_urls: Set[str] = set()
        for raw_url in image_candidates:
            clean_url = clean_image_url(raw_url)
            
            # Exclude site logos, icons, avatars, banners, branding assets, and non-mansion stock photos
            exclude_keywords = [
                "logo", "favicon", "icon", "avatar", "placeholder", 
                "map", "arrow", "badge", "tripadvisor", "instagram", "facebook", "youtube",
                "villazzo", "shutterstock"
            ]
            filename = os.path.basename(urlparse(clean_url).path).lower()
            if any(k in filename for k in exclude_keywords):
                continue
            
            if re.search(r'\.(jpe?g|png|webp)$', clean_url, re.IGNORECASE):
                high_res_urls.add(clean_url)

        return sorted(list(high_res_urls))

    async def download_single_image(
        self,
        client: httpx.AsyncClient,
        img_url: str,
        dest_path: Path
    ) -> bool:
        """Downloads an image asset with idempotency and semaphore control."""
        if dest_path.exists() and dest_path.stat().st_size > 1024:
            return True

        async with self.semaphore:
            for url in [img_url]:
                try:
                    resp = await client.get(url, headers=IMG_HEADERS, timeout=25.0)
                    if resp.status_code == 200 and len(resp.content) > 1024:
                        dest_path.write_bytes(resp.content)
                        return True
                    elif resp.status_code == 404:
                        logger.warning(f"404 for image: {url}")
                except Exception as e:
                    logger.debug(f"Failed to download image {url}: {e}")
            return False

    async def scrape_villa(self, client: httpx.AsyncClient, villa_info: Dict[str, str]) -> Dict[str, Any]:
        """Scrapes a single villa page and downloads its gallery images."""
        url = villa_info["url"]
        name = villa_info["name"]

        html = await self.fetch_html(client, url)
        if not html:
            self.state.add_log(f"Skipping {name}: Failed to load detail page.")
            return {"name": name, "url": url, "count": 0, "status": "failed"}

        soup = BeautifulSoup(html, "html.parser")

        h1 = soup.find("h1")
        if h1 and h1.get_text(strip=True):
            name = h1.get_text(strip=True)

        sanitized_name = sanitize_folder_name(name)
        villa_dir = self.download_dir / sanitized_name

        # Idempotency check: check if already downloaded
        existing_images = list(villa_dir.glob("image_*.jpg")) if villa_dir.exists() else []
        if not self.force_rescrape and villa_dir.exists() and len(existing_images) > 0:
            self.state.add_log(
                f"[Cached] {sanitized_name}: {len(existing_images)} photos already downloaded (Skipping)."
            )
            return {
                "name": name,
                "sanitized_name": sanitized_name,
                "url": url,
                "count": len(existing_images),
                "status": "cached",
                "folder": str(villa_dir)
            }

        villa_dir.mkdir(parents=True, exist_ok=True)
        self.state.add_log(f"Extracting photo gallery for {name} ({sanitized_name})...")

        img_urls = self.extract_image_urls_from_page(soup, url)
        self.state.add_log(f"Found {len(img_urls)} photo candidates for {name}")

        downloaded_count = 0
        tasks = []
        for idx, img_url in enumerate(img_urls, start=1):
            file_name = f"image_{idx:03d}.jpg"
            dest_file = villa_dir / file_name
            tasks.append(self.download_single_image(client, img_url, dest_file))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        downloaded_count = sum(1 for r in results if r is True)

        self.state.total_images_downloaded += downloaded_count
        self.state.add_log(f"Downloaded {downloaded_count} high-res photos for {sanitized_name}")

        return {
            "name": name,
            "sanitized_name": sanitized_name,
            "url": url,
            "count": downloaded_count,
            "status": "downloaded",
            "folder": str(villa_dir)
        }

    async def run(self) -> Dict[str, Any]:
        """Executes full automated scrape of the Miami portfolio."""
        if self.state.is_running:
            return {"status": "already_running", "message": "Scraper is currently active."}

        self.state.is_running = True
        self.state.status = "running"
        self.state.message = "Scraping Miami villa portfolio..."
        self.state.start_time = time.time()
        self.state.end_time = None
        self.state.error = None
        self.state.processed_villas = 0
        self.state.total_images_downloaded = 0
        self.state.logs.clear()

        self.state.add_log("Starting Villazzo Miami scraper automation...")

        try:
            async with httpx.AsyncClient(
                verify=True,
                follow_redirects=True,
                limits=httpx.Limits(max_keepalive_connections=20, max_connections=30)
            ) as client:
                villa_links = await self.extract_villa_links(client)
                self.state.total_villas = len(villa_links)

                if not villa_links:
                    self.state.status = "completed"
                    self.state.message = "No Miami villas found."
                    self.state.is_running = False
                    return self.state.to_dict()

                for idx, villa_info in enumerate(villa_links, start=1):
                    self.state.current_villa = villa_info["name"]
                    self.state.message = f"Processing villa {idx} of {self.state.total_villas}: {villa_info['name']}"
                    
                    await self.scrape_villa(client, villa_info)
                    self.state.processed_villas += 1
                    await asyncio.sleep(0.4)

            self.state.status = "completed"
            self.state.message = (
                f"Scrape completed successfully. "
                f"Processed {self.state.processed_villas} Miami villas, "
                f"saved {self.state.total_images_downloaded} master photographs."
            )
            self.state.add_log("Miami scraping task finished successfully.")

        except Exception as e:
            self.state.status = "error"
            self.state.error = str(e)
            self.state.message = f"Scrape failed: {str(e)}"
            self.state.add_log(f"ERROR: {str(e)}")
            logger.exception("Scraper encountered a critical error")

        finally:
            self.state.is_running = False
            self.state.end_time = time.time()

        return self.state.to_dict()


def list_downloaded_villas(download_dir: Path = DEFAULT_DOWNLOAD_DIR) -> List[Dict[str, Any]]:
    """Inspects the download directory and returns metadata for all downloaded villas."""
    dpath = Path(download_dir)
    if not dpath.exists():
        return []

    villas = []
    for item in sorted(dpath.iterdir()):
        if item.is_dir():
            images = sorted(
                list(item.glob("image_*.jpg")) + 
                list(item.glob("image_*.png")) + 
                list(item.glob("image_*.webp"))
            )
            if images:
                folder_name = item.name
                display_name = folder_name.replace('_', ' ')
                image_urls = [f"/downloads/{folder_name}/{img.name}" for img in images]
                hero_image = image_urls[0] if image_urls else None

                # Check for cached airbnb match
                airbnb_data = None
                match_file = item / "airbnb_match.json"
                if match_file.exists():
                    try:
                        import json
                        airbnb_data = json.loads(match_file.read_text(encoding="utf-8"))
                    except Exception:
                        pass

                villas.append({
                    "folder_name": folder_name,
                    "display_name": display_name,
                    "count": len(images),
                    "hero_image": hero_image,
                    "images": image_urls,
                    "airbnb": airbnb_data
                })

    return villas


if __name__ == "__main__":
    print("Running Villazzo Scraper CLI...")
    scraper = VillazzoScraper(force_rescrape=False)
    asyncio.run(scraper.run())
