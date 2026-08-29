# Villazzo Miami Mansion Scraper & Interactive Web Dashboard

A complete, production-ready full-stack Python application (FastAPI backend + responsive web dashboard) designed for GitHub hosting and seamless zero-configuration deployment to Render as a Web Service.

The application automatically crawls high-resolution architectural photographs from [Villazzo's Miami Luxury Villa Portfolio](https://www.villazzo.com/rental-villas/miami/) (e.g. *Villa Naomi*, *Villa Denise*, *Villa Celeste*, *Villa Siri*, *Villa Contenta*, etc.) and serves them through an interactive web gallery with a fullscreen lightbox viewer.

---

## Key Features

- **Asynchronous Scraping Pipeline:** High-performance async crawler using `httpx` and `BeautifulSoup4` with fallback support for headless `Playwright` Chromium.
- **Full-Resolution Image Extraction:** Automatically detects and strips WordPress dimension crops (`-1090x750`, `-675x490`, `-scaled`) to retrieve uncompressed original master photographs.
- **Idempotency & Smart Caching:** Checks `./downloads/<Sanitized_Villa_Name>/` before downloading. Existing collections are preserved and skipped unless `force_rescrape=True` is requested.
- **Organized Storage:** Standardizes folder names and enumerates photos sequentially (`image_001.jpg`, `image_002.jpg`, etc.).
- **FastAPI Web Service:** Real-time background task execution, static asset streaming, and live status endpoints.
- **Responsive Dashboard:** Modern luxury UI built with Tailwind CSS, Lucide icons, live polling status indicator, animated progress bar, real-time log drawer, search filter, and a responsive Lightbox modal with keyboard navigation.
- **Render & Cloud Ready:** Pre-configured `render.yaml` blueprint and a multi-stage `Dockerfile` with all required headless browser system dependencies.

---

## File Structure

```
villazzo-scraper-app/
├── main.py              # FastAPI application server and REST endpoints
├── scraper.py           # Asynchronous scraper engine with idempotency logic
├── templates/
│   └── index.html       # Responsive frontend dashboard with Lightbox modal
├── requirements.txt     # Production Python dependencies
├── Dockerfile           # Playwright-ready container image
├── render.yaml          # Render Infrastructure-as-Code Blueprint
├── .gitignore           # Git ignore rules for assets, venv, and cache
└── README.md            # Project documentation and deployment guide
```

---

## API Endpoints Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Serves the interactive frontend web dashboard. |
| `POST` | `/api/scrape/start` | Triggers the asynchronous scraper in the background (`{"force_rescrape": false}`). |
| `GET` | `/api/scrape/status` | Returns live scraping state (`idle`, `running`, `completed`, `error`), progress percent, and recent logs. |
| `GET` | `/api/villas` | Returns JSON catalog of all scraped villas, counts, hero thumbnails, and static photo URLs. |
| `GET` | `/downloads/{path}` | Static file endpoint serving downloaded full-res mansion images. |
| `GET` | `/healthz` | Service health check probe for cloud monitors. |

---

## Local Development & Setup

### 1. Prerequisites
- Python 3.10+ installed
- Git

### 2. Clone and Setup Environment
```bash
# Clone repository
git clone https://github.com/<your-username>/villazzo-scraper-app.git
cd villazzo-scraper-app

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# On Linux / macOS:
source .venv/bin/activate
# On Windows (PowerShell):
.venv\Scripts\Activate.ps1
# On Windows (CMD):
.venv\Scripts\activate.bat

# Install dependencies
pip install -r requirements.txt

# Install Playwright browser binaries
playwright install chromium
```

### 3. Run the Application
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```
Open your browser and navigate to `http://localhost:8000`.

---

## Running with Docker

You can build and run the application locally using Docker:

```bash
# Build the Docker image
docker build -t villazzo-scraper-app .

# Run the container (mounting a local downloads directory for persistence)
docker run -d -p 8000:8000 -v $(pwd)/downloads:/app/downloads --name villazzo-scraper villazzo-scraper-app
```

Navigate to `http://localhost:8000`.

---

## Deploying to Render & GitHub

### Step 1: Push Code to GitHub
1. Create a new repository on GitHub (e.g., `villazzo-scraper-app`).
2. Initialize and push your code:
   ```bash
   git init
   git add .
   git commit -m "Initial commit: Villazzo Miami scraper and web dashboard"
   git branch -M main
   git remote add origin https://github.com/<your-username>/villazzo-scraper-app.git
   git push -u origin main
   ```

### Step 2: Deploy to Render via Blueprint (Recommended)
1. Sign in to [Render.com](https://dashboard.render.com/).
2. Click **New +** in the top navigation and select **Blueprint**.
3. Connect your GitHub account and select your `villazzo-scraper-app` repository.
4. Render will automatically detect `render.yaml` and configure the **Docker Web Service**:
   - Runtime: `Docker`
   - Plan: `Standard` / `Starter`
   - Health check path: `/healthz`
5. Click **Apply**. Render will build the Docker container with all Playwright dependencies and start your live web service.

### Step 3: Deploying Manually on Render (Alternative)
1. In Render Dashboard, click **New +** -> **Web Service**.
2. Select your GitHub repository.
3. Select **Docker** as the Runtime environment.
4. Set the Health Check Path to `/healthz`.
5. Click **Create Web Service**.

---

## Idempotency & Folder Architecture

When the scraper runs, assets are stored in the `./downloads/` directory structured by sanitized villa name:

```
downloads/
├── Villa_Naomi/
│   ├── image_001.jpg
│   ├── image_002.jpg
│   └── ...
├── Villa_Celeste/
│   ├── image_001.jpg
│   └── ...
└── Villa_Denise/
    ├── image_001.jpg
    └── ...
```

- If `downloads/Villa_Naomi/` already contains images, the scraper immediately logs `[Cached]` and skips re-downloading to save bandwidth and execution time.
- Passing `force_rescrape=True` (or checking the "Force Re-scrape All" toggle in the dashboard) forces fresh asset extraction.

---

## License
MIT License
