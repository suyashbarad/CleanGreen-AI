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
3. **Headless Antigravity (`agy`) Execution**:
   - Spawns `agy.exe` with:
     - `--dangerously-skip-permissions`
     - `--model gemini-3.8-flash-medium`
     - `--print "use garbage-vision skill to Analyze this garbage photo completely. List EVERY item you can see."`
     - Working directory: the newly created complaint folder.
     - **Hidden Window**: Executed with `CREATE_NO_WINDOW` and `SW_HIDE` so **no terminal window pops up**.
4. **Artifact Generation in the Same Folder**:
   - **`report.json`**: Multi-item enumeration with 0–1000 2D bounding boxes (`box_2d`), SWM classification, resin codes, SUP infractions, and EPR brand audit.
   - **`annotated_photo.jpg`**: Colored bounding boxes drawn over detected items with brand and stream labels.
   - **`report.csv`**: Tabular CSV spreadsheet listing all items, counts, streams, materials, and bounding boxes.
   - **`report_summary.md`**: Executive forensic audit summary.
5. **UI Update**:
   - Frontend reveals a summary modal with live preview of the annotated photo, key metrics (item count, SUP violations, estimated weight), and download links for the CSV and JSON files.

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

### Or install the dependencies into the Python you already use
```bash
python3 -m pip install --break-system-packages -r requirements.txt
python3 server.py
```

### Method 1: Double-Click (Windows)
Double-click **`start.bat`** in the project root or inside `front end/`.

Open **`http://localhost:8000`** in your browser. Admin console: **`http://localhost:8000/admin`**.
