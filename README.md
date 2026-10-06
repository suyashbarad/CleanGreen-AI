# Clean and Green Tech — Team Pixel Minds

A full-stack municipal waste geo-tagging & forensic audit platform.
Allows users to upload photos of garbage, pinpoint exact coordinates on an interactive map (pre-set to MIT-WPU Kothrud, Pune), and automatically triggers the **Garbage-Vision (v2.0)** skill on **Gemini 3.8** via the Antigravity CLI (`agy`) headlessly in the background.

---

## 🏗️ Architecture

```
garbade/
├── front end/               # Client interface
│   ├── index.html          # Clean & Green Tech UI
│   ├── style.css           # Modern engineering styling & microphysics
│   ├── app.js              # Leaflet map + backend API integration
│   ├── server.py           # Launcher pointing to backend server
│   └── start.bat           # 1-click Windows launcher
├── backend/                # Backend API & AI pipeline
│   ├── server.py           # Threaded HTTP server (Static + /api/submit-complaint)
│   └── analyzer.py         # Headless agy runner + bbox annotator + CSV exporter
├── complaints/             # Output directory for all submitted complaints
│   └── loc_{lat}_{lng}_{timestamp}_{id}/
│       ├── waste_photo.jpg       # Original user photo
│       ├── metadata.json         # Telemetry, GPS, address & timestamp
│       ├── report.json           # Forensic JSON report (garbage-vision schema)
│       ├── annotated_photo.jpg   # Photo with color-coded stream bounding boxes
│       ├── report.csv            # CSV audit item inventory
│       └── report_summary.md     # Executive markdown audit summary
├── server.py               # Root server launcher
└── start.bat               # Root Windows launcher
```

---

## ⚡ Backend AI Workflow

1. **User Submission**:
   - User uploads/captures a waste photo and selects or fine-tunes coordinates on the Leaflet map.
   - User clicks **`Submit Complaint`**.
2. **Folder Creation**:
   - Backend saves the complaint into a unique folder: `complaints/loc_{lat}_{lng}_{timestamp}_{random_hex}/`.
   - Stores `waste_photo.jpg` and `metadata.json` (GPS coordinates, time, address).
3. **Vision Analysis** (background thread, never blocks the upload response):
   - With `GEMINI_API_KEY` set: the Gemini API is called for brand-level item detection.
   - Without a key: `analyzer.generate_dynamic_image_analysis()` runs the offline
     colour/edge pipeline (local-contrast grid, blob segmentation, HSV classification).
   - If `torch` + `transformers` are installed, `backend/vision_ml.py` additionally loads
     CLIP (`openai/clip-vit-base-patch32`) as a **verifier** — see below.
4. **Artifact Generation in the Same Folder**:
   - **`report.json`**: Multi-item enumeration with 0–1000 2D bounding boxes (`box_2d`), SWM classification, resin codes, SUP infractions, and EPR brand audit.
   - **`annotated_photo.jpg`**: Colored bounding boxes drawn over detected items with brand and stream labels.
   - **`report.csv`**: Tabular CSV spreadsheet listing all items, counts, streams, materials, and bounding boxes.
   - **`report_summary.md`**: Executive forensic audit summary.
5. **UI Update**:
   - Frontend reveals a summary modal with live preview of the annotated photo, key metrics (item count, SUP violations, estimated weight), and download links for the CSV and JSON files.

---

## 🛡️ The CLIP false-positive guard (`backend/vision_ml.py`)

Pixel heuristics only measure contrast and edges, so a pug on a white backdrop or a flat-lay
photo of a desk "pops" like a pile of wrappers. `vision_ml.py` loads the CLIP vision-language
model once and asks it two questions:

1. **Whole frame** — `P(litter)` from a softmax over 5 litter prompts vs 13 non-litter prompts.
   Below `SCENE_LITTER_THRESHOLD` (0.50) the report is `0 items / CLEAN`, whatever the
   heuristics proposed. Above `SCENE_LITTER_RESCUE` (0.80) it can also *re-open* a frame the
   pixel gates wrongly dismissed.
2. **Each box** — every proposed crop is re-scored; below `BOX_LITTER_THRESHOLD` (0.20) the
   box is vetoed, so the officer only sees regions the model agrees contain waste.

Measured on the project's labelled photos: genuine garbage 0.987–0.9998, non-litter
(pugs, brick wall, landscape, desk, 12 unseen stock photos) 0.001–0.219 — the threshold sits
in the middle of that gap.

The module is **optional by design**: it is lazy-loaded, prints
`[VISION ML] Disabled (...)` and steps aside when `torch` is missing (Render free tier = 512 MB),
and `CV_ML=0` turns it off for side-by-side testing of the pure heuristics.

---

## 📤 Why an upload always reaches the ward office (`front end/app.js`)

The free Render tier sleeps after ~15 idle minutes, so a plain `fetch()` from the phone either
hangs or is lost when the tab closes — the citizen sees "submitted" while the server has nothing.
The front end therefore treats the browser as the source of truth until the server confirms:

1. The photo is downscaled to 1600 px JPEG (`UPLOAD_MAX_EDGE`, `UPLOAD_QUALITY`) before it is sent,
   so a 12 MB phone camera file becomes a few hundred KB that survives mobile data.
2. The ledger stores only a 320 px thumbnail (`urls.original_image`), keeping localStorage under quota.
3. The real payload goes into the **upload outbox** (`swachhUploadOutbox`) and is retried with
   exponential backoff (`RETRY_DELAYS_MS` = 5 s → 240 s), pinging `/api/complaints` first to wake
   Render. Both the Vercel rewrite (`/api/submit-complaint`) and the direct Render URL are tried.
4. Only a `200` with a `complaint_id` (or `status: "duplicate"`) removes the item from the queue;
   the local row is then renamed to the server ID and marked `sync_status: "synced"`.
5. Retries also fire on page load and on the browser `online` event, so a report queued in a
   tunnel is delivered the moment signal returns. Until then the admin console shows it as
   **QUEUED ON DEVICE**, so nothing silently disappears from the ward's ledger.

---

## 🌐 Live deployment (Vercel front end + Render backend)

`front end/vercel.json` rewrites `/api/:path*` and `/complaints/:path*` to
`https://cleangreen-ai-backend.onrender.com`. Set these in the Render service:

| Variable | Value | Effect |
|---|---|---|
| `GEMINI_API_KEY` | free key from AI Studio | brand-level item names, real scene reading |
| `COMPLAINTS_DIR` | `/data/complaints` (+ a 1 GB Persistent Disk mounted at `/data`) | filed complaints survive a restart/redeploy |
| `CV_ML` | `0` (only to force the heuristic path) | turns the CLIP verifier off |

`GET /api/health` answers with the engine actually live, e.g.
`{"clip_verifier":"unavailable","gemini_key_present":true,"primary_engine":"Gemini 2.5 Flash + CLIP verifier"}`
— the admin console shows the same state in the tab-bar chip, and every report carries
`analysis_engine` so a judge can see which model wrote it.

---

## 🚀 How to Run on Localhost

The backend needs **Pillow** (image analysis) and **google-genai**. Plain `python server.py`
only works if those are installed in that exact interpreter — otherwise every photo
fails with "Pillow is not installed".

### macOS / Linux — use the project virtualenv (recommended)
```bash
cd ~/Desktop/CleanGreen-AI
./.venv/bin/python server.py
```

Optional — enables the CLIP false-positive guard (about 2.5 GB, local machines only):
```bash
./.venv/bin/python -m pip install torch transformers
```

### Or install the dependencies into the Python you already use
```bash
python3 -m pip install --break-system-packages -r requirements.txt
python3 server.py
```

### Method 1: Double-Click (Windows)
Double-click **`start.bat`** in the project root or inside `front end/`.

Open **`http://localhost:8000`** in your browser. Admin console: **`http://localhost:8000/admin`**.
