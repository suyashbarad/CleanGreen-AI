"""
Clean and Green Tech — Backend & Static Application Server
Provides:
- Static file serving for the front end (index.html, admin.html, style.css, app.js, admin.js)
- GET /admin: Serves admin.html
- GET /api/osm/bins: Returns OpenStreetMap bins in Pune
- GET /api/complaints: Returns all complaints with enriched stats and URLs
- POST /api/submit-complaint: Receives waste image & GPS, runs agy garbage-vision headlessly,
  saves annotated photo, report.json, report.csv in unique GPS-timestamped complaint folder
- GET /complaints/<folder>/<filename>: Serves complaint assets (annotated images, reports)
"""

import http.server
import socketserver
import os
import shutil
import sys
import json
import base64
import hashlib
import urllib.parse
import webbrowser
import threading
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "front end"
# Render's disk is reset on every restart/redeploy; point this at a mounted
# Persistent Disk there so filed complaints survive.
COMPLAINTS_DIR = Path(os.environ.get("COMPLAINTS_DIR") or (BASE_DIR / "complaints"))
COMPLAINTS_DIR.mkdir(parents=True, exist_ok=True)
OSM_BINS_FILE = BASE_DIR / "pune_osm_bins.json"

sys.path.insert(0, str(BACKEND_DIR))
from analyzer import save_initial_complaint, run_background_ai_analysis, build_metrics

PORT = 8000

# Maps sha256(photo bytes) -> complaint_id so the same photo can never create two reports.
_SUBMITTED_IMAGE_HASHES = {}
_HASH_LOCK = threading.Lock()


def register_existing_complaint_hashes():
    """Rebuilds the dedupe registry from disk so a server restart cannot re-report old photos."""
    if not COMPLAINTS_DIR.exists():
        return
    count = 0
    for folder in COMPLAINTS_DIR.iterdir():
        meta_file = folder / "metadata.json"
        if not meta_file.exists():
            continue
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
            image_hash = meta.get("image_hash")
            complaint_id = meta.get("complaint_id")
            if image_hash and complaint_id:
                _SUBMITTED_IMAGE_HASHES[image_hash] = complaint_id
                count += 1
        except Exception as err:
            print(f"[BACKEND] Could not read {meta_file}: {err}")
    if count:
        print(f"[BACKEND] Dedupe registry loaded {count} previously reported photo(s).")


def coverage_from_boxes(items):
    """Sum of box areas as a share of the frame, for reports saved before metrics existed.

    Bounding boxes are relative 0-1000 [ymin, xmin, ymax, xmax] rectangles.
    """
    total = 0.0
    for it in items:
        box = it.get("bounding_box") or it.get("box_2d") or []
        if len(box) == 4:
            try:
                total += max(0, int(box[2]) - int(box[0])) * max(0, int(box[3]) - int(box[1])) / 1_000_000
            except (TypeError, ValueError):
                continue
    return min(1.0, total)



class CleanGreenRequestHandler(http.server.SimpleHTTPRequestHandler):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        url_parsed = urllib.parse.urlparse(self.path)
        path = url_parsed.path
        # 0. Health / Ping endpoint (Keep-Alive)
        if path in ("/api/ping", "/api/health"):
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "message": "CleanGreen AI Backend active"}).encode('utf-8'))
            return

        # 1. Admin redirect
        if path in ("/admin", "/admin/"):
            admin_file = FRONTEND_DIR / "admin.html"
            if admin_file.exists():
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(admin_file.stat().st_size))
                self.end_headers()
                with open(admin_file, "rb") as f:
                    self.copyfile(f, self.wfile)
                return

        # 2. API: OSM Waste Bins in Pune
        if path == "/api/osm/bins":
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            bins_data = []
            if OSM_BINS_FILE.exists():
                try:
                    with open(OSM_BINS_FILE, "r", encoding="utf-8") as f:
                        bins_data = json.load(f)
                except Exception as e:
                    print("Error loading OSM bins file:", e)
            self.wfile.write(json.dumps({"bins": bins_data, "count": len(bins_data)}).encode('utf-8'))
            return

        # 3. API: List all complaints with enriched data
        if path == "/api/complaints":
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            complaints = []
            if COMPLAINTS_DIR.exists():
                for folder in sorted(COMPLAINTS_DIR.iterdir(), reverse=True):
                    if folder.is_dir():
                        meta_file = folder / "metadata.json"
                        report_file = folder / "report.json"
                        ann_file = folder / "annotated_photo.jpg"
                        csv_file = folder / "report.csv"
                        
                        if meta_file.exists():
                            try:
                                with open(meta_file, "r", encoding="utf-8") as f:
                                    item = json.load(f)
                                
                                # Folder reference
                                item["folder_name"] = folder.name
                                item["folder_path"] = str(folder)
                                item["status"] = item.get("status", "Pending")

                                # Relative URLs
                                item["urls"] = {
                                    "original_image": f"/complaints/{folder.name}/{item.get('image_file', 'waste_photo.jpg')}",
                                    "annotated_image": f"/complaints/{folder.name}/annotated_photo.jpg" if ann_file.exists() else None,
                                    "json_report": f"/complaints/{folder.name}/report.json" if report_file.exists() else None,
                                    "csv_report": f"/complaints/{folder.name}/report.csv" if csv_file.exists() else None
                                }

                                if report_file.exists():
                                    item["analysis_status"] = "completed"
                                    try:
                                        with open(report_file, "r", encoding="utf-8") as rf:
                                            report_content = json.load(rf)
                                            items = report_content.get("items", [])
                                            # Reports saved before the metrics engine get it computed on read.
                                            metrics = report_content.get("metrics") or build_metrics(
                                                items, coverage=coverage_from_boxes(items))
                                            item["stats"] = {
                                                "item_count": len(items),
                                                "sup_violations": sum(1 for it in items if it.get("sup_violation") is True),
                                                "hazard_flag": report_content.get("hazard_flag", False),
                                                "segregation_verdict": report_content.get("segregation_verdict", "unsegregated"),
                                                **metrics
                                            }
                                            item["report"] = report_content
                                    except Exception:
                                        pass
                                else:
                                    if item.get("analysis_status") != "failed":
                                        item["analysis_status"] = "in_progress"
                                    item["stats"] = {
                                        "item_count": 0,
                                        "sup_violations": 0,
                                        "hazard_flag": False,
                                        "segregation_verdict": "Analyzing..."
                                    }

                                complaints.append(item)
                            except Exception as err:
                                print(f"Error reading complaint folder {folder.name}: {err}")
            
            complaints.sort(key=lambda c: str(c.get("timestamp") or ""), reverse=True)
            self.wfile.write(json.dumps({"complaints": complaints, "total": len(complaints)}).encode('utf-8'))
            return

        # 4. Serve files from complaints/ directory
        if path.startswith("/complaints/"):
            rel_path = path[len("/complaints/"):]
            target_file = COMPLAINTS_DIR / rel_path
            try:
                target_file = target_file.resolve()
                if str(target_file).startswith(str(COMPLAINTS_DIR.resolve())) and target_file.is_file():
                    self.send_response(200)
                    mime_type = self.guess_type(str(target_file))
                    self.send_header('Content-Type', mime_type or 'application/octet-stream')
                    self.send_header('Content-Length', str(target_file.stat().st_size))
                    self.end_headers()
                    with open(target_file, "rb") as f:
                        self.copyfile(f, self.wfile)
                    return
            except Exception as e:
                print(f"Error serving complaint file: {e}")

            self.send_error(404, "Complaint file not found")
            return

        # Default static file serving from front end directory
        super().do_GET()

    def do_POST(self):
        url_parsed = urllib.parse.urlparse(self.path)
        path = url_parsed.path

        # 1. Update Complaint Status
        if path.startswith("/api/complaints/") and path.endswith("/status"):
            content_length = int(self.headers.get('Content-Length', 0))
            post_body = self.rfile.read(content_length)
            try:
                data = json.loads(post_body.decode('utf-8'))
                new_status = data.get("status", "Pending")
                # path format: /api/complaints/<complaint_id>/status
                parts = path.strip("/").split("/")
                complaint_id = parts[2]

                # Find folder
                updated = False
                for folder in COMPLAINTS_DIR.iterdir():
                    if folder.is_dir():
                        meta_file = folder / "metadata.json"
                        if meta_file.exists():
                            with open(meta_file, "r", encoding="utf-8") as f:
                                meta = json.load(f)
                            if meta.get("complaint_id") == complaint_id:
                                meta["status"] = new_status
                                with open(meta_file, "w", encoding="utf-8") as f:
                                    json.dump(meta, f, indent=2)
                                updated = True
                                break

                self.send_response(200 if updated else 404)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"success": updated, "status": new_status}).encode('utf-8'))
                return
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
                return

        # 1.4. Delete Complaint (and its analysis reports) — POST variant
        if path.startswith("/api/complaints/") and path.endswith("/delete"):
            parts = path.strip("/").split("/")
            complaint_id = parts[2]
            deleted = self._delete_complaint_folder(complaint_id)

            self.send_response(200 if deleted else 404)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": deleted,
                "deleted": complaint_id if deleted else None
            }).encode('utf-8'))
            return

        # 1.5. Retry AI Analysis on Complaint
        if path.startswith("/api/complaints/") and path.endswith("/retry"):
            parts = path.strip("/").split("/")
            complaint_id = parts[2]
            target_folder = None
            target_img = None
            
            for folder in COMPLAINTS_DIR.iterdir():
                if folder.is_dir():
                    meta_file = folder / "metadata.json"
                    if meta_file.exists():
                        try:
                            with open(meta_file, "r", encoding="utf-8") as f:
                                meta = json.load(f)
                            if meta.get("complaint_id") == complaint_id:
                                target_folder = folder
                                target_img = folder / meta.get("image_file", "waste_photo.jpg")
                                meta["analysis_status"] = "in_progress"
                                if "analysis_error" in meta:
                                    del meta["analysis_error"]
                                with open(meta_file, "w", encoding="utf-8") as f:
                                    json.dump(meta, f, indent=2)
                                break
                        except Exception:
                            pass

            if target_folder and target_img and target_img.exists():
                threading.Thread(
                    target=run_background_ai_analysis,
                    args=(target_folder, target_img),
                    daemon=True
                ).start()

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": True,
                    "complaint_id": complaint_id,
                    "message": "AI analysis retry started in background."
                }).encode('utf-8'))
                return
            else:
                self.send_response(404)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Complaint not found or image missing"}).encode('utf-8'))
                return

        # 2. Submit Complaint
        if path == "/api/submit-complaint":
            content_length = int(self.headers.get('Content-Length', 0))
            post_body = self.rfile.read(content_length)

            try:
                content_type = self.headers.get('Content-Type', '')

                if 'application/json' in content_type:
                    data = json.loads(post_body.decode('utf-8'))
                    image_base64 = data.get('image_base64', '').strip()
                    if ',' in image_base64:
                        image_base64 = image_base64.split(',', 1)[1]
                    missing_padding = len(image_base64) % 4
                    if missing_padding:
                        image_base64 += '=' * (4 - missing_padding)
                    image_bytes = base64.b64decode(image_base64)
                    filename = data.get('filename', 'waste_photo.jpg')
                    lat = float(data.get('latitude', 18.5178))
                    lng = float(data.get('longitude', 73.8151))
                    address = data.get('address', 'MIT-WPU Kothrud, Pune')
                    notes = data.get('notes', '')
                    client_complaint_id = data.get('client_complaint_id') or None
                    client_local_time = data.get('client_local_time') or None
                else:
                    self.send_error(400, "Content-Type must be application/json")
                    return

                image_hash = hashlib.sha256(image_bytes).hexdigest()

                # 0. Refuse to register the exact same photo twice (client retry / double submit)
                with _HASH_LOCK:
                    existing_id = _SUBMITTED_IMAGE_HASHES.get(image_hash)

                if existing_id:
                    print(f"[BACKEND] Duplicate photo submission ignored for {existing_id}!")
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "status": "duplicate",
                        "complaint_id": existing_id,
                        "message": "This photo was already reported."
                    }, indent=2).encode('utf-8'))
                    return

                # 1. Instantly save complaint folder and photo in < 50ms!
                folder_path, complaint_id, image_file_path = save_initial_complaint(
                    base_dir=COMPLAINTS_DIR,
                    image_bytes=image_bytes,
                    image_filename=filename,
                    lat=lat,
                    lng=lng,
                    address=address,
                    notes=notes,
                    client_complaint_id=client_complaint_id,
                    image_hash=image_hash,
                    client_local_time=client_local_time
                )

                with _HASH_LOCK:
                    _SUBMITTED_IMAGE_HASHES[image_hash] = complaint_id

                print(f"[BACKEND] Complaint {complaint_id} saved instantly in {folder_path.name}!")

                # 2. Spawn headless Vision AI analysis in a background daemon thread
                ai_thread = threading.Thread(
                    target=run_background_ai_analysis,
                    args=(folder_path, image_file_path),
                    daemon=True
                )
                ai_thread.start()

                # 3. Immediately return response to citizen (< 100ms response time!)
                resp_payload = {
                    "status": "success",
                    "complaint_id": complaint_id,
                    "folder_name": folder_path.name,
                    "address": address,
                    "coordinates": {"latitude": lat, "longitude": lng},
                    "message": "Complaint registered successfully! Sanitation operations dispatched."
                }

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(resp_payload, indent=2).encode('utf-8'))
                return

            except Exception as e:
                import traceback
                traceback.print_exc()
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
                return

        self.send_error(404, "Endpoint not found")

    def do_DELETE(self):
        url_parsed = urllib.parse.urlparse(self.path)
        path = url_parsed.path

        # DELETE /api/complaints/<complaint_id>
        if path.startswith("/api/complaints/"):
            parts = path.strip("/").split("/")
            if len(parts) == 3:
                complaint_id = parts[2]
                deleted = self._delete_complaint_folder(complaint_id)

                self.send_response(200 if deleted else 404)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": deleted,
                    "deleted": complaint_id if deleted else None
                }).encode('utf-8'))
                return

        self.send_error(404, "Endpoint not found")

    @staticmethod
    def _delete_complaint_folder(complaint_id: str) -> bool:
        """Finds the complaint folder by ID and permanently removes it with all reports."""
        if not complaint_id or any(ch in complaint_id for ch in ("/", "\\", "..")):
            return False
        if not COMPLAINTS_DIR.exists():
            return False
        for folder in COMPLAINTS_DIR.iterdir():
            if not folder.is_dir():
                continue
            meta_file = folder / "metadata.json"
            if meta_file.exists():
                try:
                    with open(meta_file, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    if meta.get("complaint_id") == complaint_id:
                        image_hash = meta.get("image_hash")
                        shutil.rmtree(folder)
                        if image_hash:
                            with _HASH_LOCK:
                                _SUBMITTED_IMAGE_HASHES.pop(image_hash, None)
                        print(f"[BACKEND] Complaint {complaint_id} deleted with folder {folder.name}")
                        return True
                except Exception as err:
                    print(f"[BACKEND] Error deleting complaint {complaint_id}: {err}")
        return False


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _ensure_image_libraries():
    """Vision analysis needs Pillow. If this interpreter lacks it but the project .venv has it,
    relaunch under the venv so `python3 server.py` works regardless of which Python is used."""
    try:
        import PIL  # noqa: F401
        return
    except ImportError:
        pass

    venv_python = BASE_DIR / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    already_in_venv = sys.prefix != sys.base_prefix

    if not venv_python.exists() or already_in_venv:
        print("!! WARNING: Pillow is NOT installed in this Python interpreter.")
        print("!! Waste photos cannot be analysed until it is available.")
        print("!! Fix:  ./.venv/bin/python server.py   or   python3 -m pip install -r requirements.txt")
        return

    script = BASE_DIR / "server.py"
    print(f"[SETUP] This Python has no Pillow - restarting under {venv_python}", flush=True)
    os.execv(str(venv_python), [str(venv_python), str(script)] + sys.argv[1:])


def _warm_vision_model():
    """Load the CLIP verifier in the background so the first upload is not billed for it.

    Hosts without torch (the Render free tier cannot hold it) print the reason once and
    keep running on the colour/edge heuristics.
    """
    if os.environ.get("CV_ML", "1") == "0":
        print("[VISION ML] CV_ML=0 - colour/edge heuristics only.", flush=True)
        return
    import threading

    def load():
        try:
            import vision_ml
            vision_ml.use_ml()
        except Exception as err:
            print(f"[VISION ML] Disabled ({type(err).__name__}: {err}).", flush=True)

    threading.Thread(target=load, daemon=True).start()


def run():
    _ensure_image_libraries()
    register_existing_complaint_hashes()
    _warm_vision_model()
    server_address = ('', PORT)
    httpd = ThreadedHTTPServer(server_address, CleanGreenRequestHandler)
    url = f"http://localhost:{PORT}"
    print("=" * 70)
    print(" CLEAN AND GREEN TECH — BACKEND & VISION AI SERVER")
    print(f" Citizen Web App:          {url}")
    print(f" Admin Dashboard:          {url}/admin")
    print(f" OSM Bins Tracked (Pune):  {OSM_BINS_FILE}")
    print(f" Complaints Directory:     {COMPLAINTS_DIR}")
    print("=" * 70)

    try:
        if not os.environ.get("NO_BROWSER"):
            webbrowser.open(url)
    except Exception:
        pass

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer shutting down...")
        httpd.shutdown()


if __name__ == "__main__":
    run()
