# Clean and Green Tech — Team Pixel Minds

A full-stack municipal waste geo-tagging & forensic audit platform.
Citizens upload a photo of garbage, pinpoint exact coordinates on an interactive map (pre-set to
MIT-WPU Kothrud, Pune), and the report is delivered to the ward office even if the free-tier
backend is asleep. The background **Vision AI** runs one of three engines — Gemini, the offline
colour/edge CV sweep, and CLIP as a verifier — and every report says which one wrote it.

---

## 🏗️ Architecture

```
garbade/
├── front end/               # Client interface
│   ├── index.html          # Citizen uploader UI
│   ├── admin.html          # Ward-office console (map, ledger, forensic drawer)
│   ├── app.js              # Leaflet map, upload outbox, retry + sync status
│   ├── admin.js            # Ledger merge, vision-engine chip, drawer
│   ├── vercel.json         # /api + /complaints rewrites to the Render backend
│   ├── server.py           # Launcher pointing to backend server
│   └── start.bat           # 1-click Windows launcher
├── backend/                # Backend API & AI pipeline
│   ├── server.py           # Threaded HTTP server (static + /api/* + /complaints/*)
│   ├── analyzer.py         # CV sweep, Gemini call, bbox annotator, metrics, CSV exporter
│   └── vision_ml.py        # Optional CLIP verifier that vetoes false positives
├── tests/
│   └── vision_regression.py # Must-be-CLEAN / must-be-litter fixture suite
├── complaints/             # Output directory for all submitted complaints
│   └── loc_{lat}_{lng}_{timestamp}_{id}/
│       ├── waste_photo.jpg       # Original user photo
│       ├── metadata.json         # Telemetry, GPS, address & timestamp
│       ├── report.json           # Forensic report (items, metrics, analysis_engine)
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
   - `analyzer.run_gemini_analysis()` picks the engine and returns `(raw_output, engine_label)`.
   - With `GEMINI_API_KEY` set: Gemini Vision (`gemini-2.5-flash`, then `-lite`, then `2.0-flash`)
     reads the photo for brand-level item detection.
   - Without a key: `analyzer.generate_dynamic_image_analysis()` runs the offline colour/edge
     pipeline (local-contrast grid, blob segmentation, HSV classification).
   - If `torch` + `transformers` are installed, `backend/vision_ml.py` additionally loads
     CLIP (`openai/clip-vit-base-patch32`) as a **verifier** — it only vetoes, see below.
   - Whatever the engine returned is then passed through `normalize_model_report()`: boxes are
     clamped to 0–1000 and degenerate ones dropped, streams validated against the eight legal
     SWM values, counts/confidences bounded, and repeated item names made unique by position
     (`Clear PET Bottle (top-left)`) so no two boxes in a frame can ever share a label.
4. **Artifact Generation in the Same Folder**:
   - **`report.json`**: Multi-item enumeration with 0–1000 bounding boxes, SWM classification,
     resin codes, SUP infractions, brand/EPR audit, a `metrics` block (severity index, tonnage,
     stream breakdown, recommended action) and `analysis_engine` naming the model that answered.
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

**Without torch**, the same job falls to three pixel gates in `generate_dynamic_image_analysis()`:
a studio-backdrop rejection (one flat colour over most of the frame, no edges), a sparse-scene
rejection (low coverage, no blob big enough to be a pile), and a **vegetation-scene rejection** —
≥20 % of the frame in living green with soft, scattered flags is a lawn with a subject on it, not
a Pune dump. That last gate is what keeps an animal photo from producing 12 fake items on the
deployed site, where CLIP cannot run.

---

## 🔍 "On-device CV sweep · CLIP verifier ON" — reading the engine

The admin console's tab-bar chip is two facts joined by one dot:

| Chip text | Meaning | Source |
|---|---|---|
| `On-device CV sweep` | No Gemini key, so Pillow colour/edge maths proposed every box | `analyzer.generate_dynamic_image_analysis()` |
| `Gemini 2.5 Flash` | A key is set and the SDK imported, so a real vision model read the photo | `analyzer.run_gemini_analysis()` |
| `CV sweep — Gemini NOT answering` | A key is set but is not producing answers (SDK missing, key rejected, or every model failed) — the chip's tooltip shows the exact API error | `analyzer.GEMINI_STATUS` |
| `CLIP verifier ON` | torch is installed and the model is resident, so boxes were veto-checked | `vision_ml.py` |
| `CLIP verifier off` | No torch (Render free tier), so only the pixel gates rejected fakes | `vision_ml.py` |
| `Vision engine offline` | The backend is asleep; nothing answered yet | `/api/health` unreachable |

Proposals always come from CV **or** Gemini; CLIP never proposes, it only deletes. Each report also
carries the same information in `report.json → analysis_engine`, and the drawer prints it as an
`ENGINE:` line, so any output can be traced to the model that produced it.

---

## 🧪 Vision regression suite (`tests/vision_regression.py`)

```bash
./.venv/bin/python tests/vision_regression.py          # with the CLIP verifier
./.venv/bin/python tests/vision_regression.py --no-ml  # Render parity (pixel gates only)
```

Seven photos that must come back `0 items / CLEAN` (the project's dog/pug/clean-street filings plus
three synthetic backdrops: studio white, sky gradient, brick wall) and seven real dumps that must
yield 5–14 boxes with **no duplicate labels** and no box over 10 % of the frame. Annotated images
are written to `.test-output/`; exit code is non-zero on any failure.

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

`GET /api/health` answers with the engine actually live — not what is configured, but what really
answered the last photo:

```json
{"clip_verifier":"unavailable","gemini_key_present":true,"gemini_sdk_installed":false,
 "gemini_sdk_import_error":"ModuleNotFoundError: No module named 'google'","primary_engine":"colour/edge CV sweep",
 "gemini_last_attempt":"skipped: google-genai not importable (…)","persistent_disk":false,"python":"3.14.3"}
```

`gemini_key_present` alone is not enough: a key without an importable SDK — or one the API refuses —
still means the pixel sweep is doing the work, which is what the chip calls out as
`CV sweep — Gemini NOT answering` (hover it for the exact error). The same state lands in every
report's `analysis_engine` (e.g. `On-device CV sweep (Gemini gave no answer) + CLIP verifier`) and
the drawer prints it as an `ENGINE:` line, so any output can be traced to the model that produced it.

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
