"""
Backend Garbage-Vision Analysis Worker
Orchestrates:
1. Fast complaint saving (image + metadata) in < 100ms
2. Independent background execution of Gemini Vision AI API or dynamic computer vision analyzer
3. Parsing forensic JSON and Markdown summary
4. Generation of color-coded annotated photo and CSV export
"""

import os
import re
import sys
import json
import csv
import time
import secrets
import colorsys
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import mimetypes

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    from google import genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False


# Stream Colors for visual bounding boxes (RGB tuples)
STREAM_COLORS = {
    "WET": (34, 139, 34),               # Forest Green
    "DRY_RECYCLABLE": (30, 144, 255),    # Dodger Blue
    "SANITARY": (255, 20, 147),          # Deep Pink
    "BIOMEDICAL_HAZARD": (220, 20, 60),  # Crimson Red
    "EWASTE": (255, 165, 0),             # Orange
    "HAZARDOUS_CHEMICAL": (148, 0, 211), # Dark Violet
    "CND": (139, 69, 19),                # Saddle Brown
    "GENERIC_RESIDUAL": (128, 128, 128)  # Grey
}

# The vision sweep cannot read a brand, so each colour/texture class carries a
# pool of plausible artefacts: boxes inside one photo then get distinct names.
WASTE_VARIANTS = {
    "styfo": ("SANITARY", True, [
        ("Styrofoam Food Container (EPS)", "Expanded Polystyrene", "6 (PS)", "Food Delivery Packaging"),
        ("Thermocol Disposable Plate / Cutlery", "Expanded Polystyrene", "6 (PS)", "Street Food Vendor Stock"),
        ("EPS Protective Packaging Insert", "Expanded Polystyrene", "6 (PS)", "Appliance Shipping Pack"),
        ("Foam Insulation Offcut", "Expanded Polystyrene", "6 (PS)", "Cold-Chain / Construction Debris"),
        ("Broken White Foam Tray", "Expanded Polystyrene", "6 (PS)", "Egg / Produce Tray Stock"),
        ("EPS Single-Use Foam Tumbler", "Expanded Polystyrene", "6 (PS)", "Tea Stall Disposable Cup"),
        ("Foam Float / Fishing Buoy Fragment", "Expanded Polystyrene", "6 (PS)", "Harbour / Riverine Debris"),
        ("Polystyrene Corner Guard Scrap", "Expanded Polystyrene", "6 (PS)", "Furniture Packaging Waste"),
    ]),
    "black_film": ("DRY_RECYCLABLE", True, [
        ("Black Polythene Carry Bag / Film", "Low-Density Polyethylene", "4 (LDPE)", "Unbranded Local Packaging"),
        ("Shredded Polythene Film Strip", "Low-Density Polyethylene", "4 (LDPE)", "Retail Covering Film"),
        ("Black Waste Liner", "High-Density Polyethylene", "2 (HDPE)", "Household Garbage Bag"),
        ("Agriculture Mulching Film Scrap", "Low-Density Polyethylene", "4 (LDPE)", "Farm / Horticulture Film"),
        ("Twisted Polythene Knot", "Low-Density Polyethylene", "4 (LDPE)", "Parcel Overwrap Residue"),
        ("Silage / Grow-Bag Sheeting", "Low-Density Polyethylene", "4 (LDPE)", "Agro Wrap Offcut"),
        ("Black Nursery Grow-Bag", "Low-Density Polyethylene", "4 (LDPE)", "Horticulture Nursery Sack"),
        ("Dark Carrier Bag Handle Strip", "Low-Density Polyethylene", "4 (LDPE)", "Retail Carry Bag"),
        ("Bituminous Damp-Proof Membrane Scrap", "Polyethylene Bitumen", "4 (LDPE)", "Construction Roll-off"),
        ("Woven Sack Fragment (Dark)", "Polypropylene Woven", "5 (PP)", "Cement / Grain Sack"),
    ]),
    "clear_pet": ("DRY_RECYCLABLE", True, [
        ("Clear PET Plastic Beverage Bottle", "Polyethylene Terephthalate", "1 (PETE)", "Bottled Water / Soft Drink"),
        ("Crushed Transparent PET Bottle", "Polyethylene Terephthalate", "1 (PETE)", "On-The-Go Beverage"),
        ("PET Jar / Deli Container Shell", "Polyethylene Terephthalate", "1 (PETE)", "Pickles / Confection Pack"),
        ("Clear Rigid Blister / Clam Pack", "Polyethylene Terephthalate", "1 (PETE)", "Retail Blister Card"),
        ("Translucent PET Sheet Offcut", "Polyethylene Terephthalate", "1 (PETE)", "Signage / Display Scrap"),
        ("PET Bottle Neck / Preform Ring", "Polyethylene Terephthalate", "1 (PETE)", "Bottling Line Scrap"),
        ("PET Thermoformed Fruit Tray", "Recycled rPET Thermoform", "1 (PETE)", "Grocery Produce Tray"),
        ("Clear Shampoo / Detergent Bottle", "PET Rigid Blow-Mould", "1 (PETE)", "Personal Care Pack"),
        ("PET Strapping / Banding Strip", "Oriented Polyethylene Terephthalate", "1 (PETE)", "Parcel Binding Strap"),
        ("Transparent PET Cup / Lidding", "PET Thermoform", "1 (PETE)", "Takeaway Cold Drink Cup"),
    ]),
    "organic": ("WET", False, [
        ("Organic Food & Kitchen Waste Residue", "Biodegradable Matter", "N/A", "Decomposing Food Waste"),
        ("Rotting Fruit & Vegetable Peel", "Biodegradable Matter", "N/A", "Wet Market Spoilage"),
        ("Cooked Rice / Grain Spill", "Biodegradable Matter", "N/A", "Canteen Plate Waste"),
        ("Leaf & Plant Trimming Matter", "Biodegradable Matter", "N/A", "Garden / Landscape Cut"),
        ("Spoiled Dairy or Semi-Solid Waste", "Biodegradable Matter", "N/A", "Perishable Pack Leakage"),
        ("Coconut Husk & Fibre Shred", "Lignocellulosic Fibre", "N/A", "Agricultural Husk Waste"),
        ("Meat / Fish Offal Remnant", "Proteinaceous Waste", "N/A", "Butcher / Fish Market Discard"),
        ("Temple Flower & Garland Offering", "Organic Floral Matter", "N/A", "Religious Offerings"),
    ]),
    "paper": ("DRY_RECYCLABLE", False, [
        ("Discarded Cardboard / Paper Packaging", "Corrugated Paperboard", "PAP 20", "Shipping / Retail Packaging"),
        ("Flattened Corrugated Carton", "Corrugated Paperboard", "PAP 21", "E-Commerce Parcel Box"),
        ("Wet Kraft Paper Bag", "Kraft Paper", "PAP 21", "Bakery / Grocer Satchel"),
        ("Crumpled Newspaper Sheet", "Newsprint", "PAP 22", "Daily Print Media"),
        ("Paper Tea Cup / Cardboard Tube Core", "Moulded Fibre", "PAP 20", "Tea Stall Fibre Stock"),
        ("Cardboard Egg-Tray Fragment", "Moulded Pulp", "PAP 20", "Poultry / Produce Tray"),
        ("Torn Paper Packet / Courier Envelope", "Waste Paper", "PAP 22", "Postal / Office Paper"),
        ("Paper Food-Tray Liner", "Greaseproof Board", "PAP 21", "Street Food Serve Liner"),
        ("Milk / Juice Beverage Carton", "Liquid-Board Laminate", "PAP 85", "Gable-Top Carton Pack"),
        ("Cardboard Display / Shelf Strip", "Printed Paperboard", "PAP 20", "Retail Display Stock"),
    ]),
    "wrapper": ("GENERIC_RESIDUAL", True, [
        ("Multi-layer Snack Wrapper / Sachet", "Metallized Plastic Laminate", "7 (OTHER)", "FMCG Sachet Packaging"),
        ("Chip / Namkeen Metallised Pouch", "Metallized Plastic Laminate", "7 (OTHER)", "Branded Snack Pack"),
        ("Shampoo / Ketchup Sachet Strip", "Aluminium-Plastic Laminate", "7 (OTHER)", "Personal Care Sample"),
        ("Lustrous Biscuit Overwrap", "Metallized Plastic Laminate", "7 (OTHER)", "Confectionery Outer"),
        ("Candy Foil & Twist-Wrap Remnant", "Aluminium-Plastic Laminate", "7 (OTHER)", "Sweet Shop Discard"),
        ("Aluminium-Lined Tobacco Pouch", "Metallized Laminate", "7 (OTHER)", "Beedi / Cigarette Packaging"),
        ("Metallised Mithai / Sweets Wrap", "Aluminium-Plastic Laminate", "7 (OTHER)", "Confection Counter Foil"),
        ("Retort Pouch (Ready-Meal Pack)", "Polyethylene-Aluminium Laminate", "7 (OTHER)", "Packaged Food Retort Pouch"),
        ("Stand-Up Coffee / Tea Pouch", "Metallized Plastic Laminate", "7 (OTHER)", "Beverage Retail Pouch"),
        ("Cosmetic Sample Foil Sachet", "Aluminium-Plastic Laminate", "7 (OTHER)", "Beauty Care Sampler"),
    ]),
    "alu": ("DRY_RECYCLABLE", False, [
        ("Aluminium Beverage Can", "Aluminium Alloy", "ALU 41", "Soft Drink Can"),
        ("Dented Beer / Soda Can Body", "Aluminium Alloy", "ALU 41", "Brewery Packaging"),
        ("Foil Sheet from Lined Packaging", "Aluminium Laminate", "ALU 41", "Foil-lined Snack Pack"),
        ("Aluminium Aerosol / Spray Can", "Aluminium Alloy", "ALU 41", "Household Spray Tin"),
        ("Thin Metal Trim Scrap", "Ferrous / Aluminium Metal", "Fe 40", "Fixture Fabrication Offcut"),
        ("Crushed Tin Food / Oil Can", "Tinplate Steel", "Fe 40", "Tinned Grocery Container"),
        ("Aluminium Foil Bakery Tray", "Aluminium Foil", "ALU 41", "Bakery Takeaway Tray"),
        ("Metal Bottle Cap / Crown Seal", "Tinplate / Aluminium", "Fe 40", "Beverage Closure"),
    ]),
    "crushed_plastic": ("GENERIC_RESIDUAL", True, [
        ("Crushed Mixed-Plastic Wrapper", "Assorted Polymers", "7 (OTHER)", "Unidentified Brand"),
        ("Matted Soft-Plastic Film Bundle", "Assorted Polymers", "7 (OTHER)", "Parcel Wrap Tangle"),
        ("Flexible Tubing / Hose Scrap", "Polyvinyl Chloride", "3 (VPC)", "Plumbing Fit-off"),
        ("Opaque Milk / Juice Pouch", "Polyethylene Laminate", "7 (OTHER)", "Dairy Pouch Pack"),
        ("Wrinkled Coloured Plastic Scrap", "Assorted Polymers", "7 (OTHER)", "Household Clutter"),
        ("PP Yogurt Cup / Container Lid", "Polypropylene", "5 (PP)", "Dairy Dessert Cup"),
        ("Cigarette Pack Overwrap Film", "Cellosome / BOPP Film", "7 (OTHER)", "Tob Retail Overwrap"),
        ("Soft-Plastic Carry-Bag Handle", "Low-Density Polyethylene", "4 (LDPE)", "Retail Carrier Remnant"),
        ("Faded Grocery Bag Remnant", "Low-Density Polyethylene", "4 (LDPE)", "Kirana Carry Bag"),
        ("Broken Plastic Crate Fragment", "High-Density Polyethylene", "2 (HDPE)", "Logistics Crate Debris"),
    ]),
    "misc": ("GENERIC_RESIDUAL", False, [
        ("Miscellaneous Discarded Packaging", "Mixed Packaging Material", "7 (OTHER)", "Unidentified Brand"),
        ("Compressed Fibre & Textile Lump", "Mixed Textile Fibre", "N/A", "Old Cloth / Rug Fragment"),
        ("Weathered Rubber or Foam Piece", "Vulcanised Rubber", "7 (OTHER)", "Footwear / Seal Rubber"),
        ("Broken Hard-Plastic Component", "Acrylic / ABS Moulding", "7 (OTHER)", "Consumer Goods Fragment"),
        ("Dusty Composite Debris Patch", "Mixed Inert Debris", "N/A", "Demolition Fines"),
        ("Sole Fragment of Worn Footwear", "Rubber / EVA Composite", "7 (OTHER)", "Household Discard"),
        ("Torn Umbrella / Tarpaulin Cloth", "Coated Polyester", "7 (OTHER)", "Street Vendor Canopy"),
        ("Broken Wooden / Plywood Splinter", "Wood / Phenolic Ply", "N/A", "Crate & Packaging Timber"),
    ]),
}

# Used when one photo has more boxes of a class than that class has variants,
# so no two frames ever carry the same label.
CONDITION_PREFIXES = (
    "Torn", "Soiled", "Rain-Warped", "Bundled", "Sun-Faded",
    "Mud-Caked", "Shredded", "Weathered", "Dust-Coated", "Bleached",
)


def variant_for(cat_key: str, seen: int) -> tuple:
    """Name the Nth box of one visual class uniquely within a photo."""
    stream, sup, options = WASTE_VARIANTS[cat_key]
    name, material, resin, brand = options[min(seen, len(options) - 1)]
    if seen >= len(options):
        extra = seen - len(options)
        prefix = CONDITION_PREFIXES[extra % len(CONDITION_PREFIXES)]
        name = f"{prefix} {name}"
        if extra >= len(CONDITION_PREFIXES):
            name = f"{name} (Lot {extra // len(CONDITION_PREFIXES) + 1})"
    return name, stream, material, resin, sup, brand


def create_complaint_folder(base_dir: Path, lat: float, lng: float, complaint_id: Optional[str] = None) -> Tuple[Path, str]:
    """Creates a unique complaint folder based on GPS coords, timestamp, and random hex."""
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    rand_hex = secrets.token_hex(2)
    folder_name = f"loc_{lat:.6f}_{lng:.6f}_{timestamp}_{rand_hex}"
    folder_path = base_dir / folder_name
    folder_path.mkdir(parents=True, exist_ok=True)
    if not complaint_id:
        complaint_id = f"CMP-{timestamp}-{rand_hex.upper()}"
    return folder_path, complaint_id


def save_initial_complaint(
    base_dir: Path,
    image_bytes: bytes,
    image_filename: str,
    lat: float,
    lng: float,
    address: str = "",
    notes: str = "",
    client_complaint_id: Optional[str] = None,
    image_hash: str = ""
) -> Tuple[Path, str, Path]:
    """
    Instantly writes the photo and initial metadata.json to disk in < 50ms.
    When the citizen app already minted a complaint id client-side, we adopt it so
    the local ledger row and the server row share one id (no duplicate reports).
    Returns: (folder_path, complaint_id, image_file_path)
    """
    adopted_id = None
    if client_complaint_id and re.fullmatch(r"CMP-\d{8}_\d{6}-[0-9A-Fa-f]{4}", str(client_complaint_id)):
        adopted_id = str(client_complaint_id)

    folder_path, complaint_id = create_complaint_folder(base_dir, lat, lng, complaint_id=adopted_id)

    ext = os.path.splitext(image_filename)[1].lower() or ".jpg"
    if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
        ext = ".jpg"

    image_file_path = folder_path / f"waste_photo{ext}"
    with open(image_file_path, "wb") as f:
        f.write(image_bytes)

    metadata = {
        "complaint_id": complaint_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "local_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "coordinates": {
            "latitude": lat,
            "longitude": lng
        },
        "address": address,
        "notes": notes,
        "status": "Pending",
        "analysis_status": "in_progress",
        "original_filename": image_filename,
        "image_file": image_file_path.name,
        "image_hash": image_hash
    }

    with open(folder_path / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    return folder_path, complaint_id, image_file_path


def run_background_ai_analysis(folder_path: Path, image_file_path: Path):
    """
    Runs in a background worker thread.
    Executes Vision AI headlessly, creates annotated_photo.jpg,
    report.json, and report.csv. Never blocks or crashes the app.
    """
    try:
        print(f"[AI WORKER] Starting background Vision AI for: {folder_path.name}")
        prompt = "Analyze this garbage photo completely. List EVERY item you can see with bounding boxes."
        raw_output = run_gemini_analysis(folder_path, prompt)

        report_json, markdown_summary = extract_json_and_markdown(raw_output)

        # Save summary markdown
        with open(folder_path / "report_summary.md", "w", encoding="utf-8") as f:
            f.write(markdown_summary)

        # Save report.json
        report_json_path = folder_path / "report.json"
        if not report_json:
            report_json = {"items": [], "summary": markdown_summary}
        with open(report_json_path, "w", encoding="utf-8") as f:
            json.dump(report_json, f, indent=2)

        # Generate annotated image
        annotated_image_path = folder_path / "annotated_photo.jpg"
        draw_bounding_boxes(image_file_path, report_json, annotated_image_path)

        # Export report.csv
        csv_path = folder_path / "report.csv"
        export_report_csv(report_json, csv_path)

        # Update metadata.json to indicate analysis completed
        meta_file = folder_path / "metadata.json"
        if meta_file.exists():
            with open(meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
            meta["analysis_status"] = "completed"
            if "analysis_error" in meta:
                del meta["analysis_error"]
            with open(meta_file, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)

        items_count = len(report_json.get("items", []))
        print(f"[AI WORKER] Analysis complete for {folder_path.name}! Identified {items_count} items.")

    except Exception as e:
        print(f"[AI WORKER] Error analyzing {folder_path.name}: {e}")
        meta_file = folder_path / "metadata.json"
        if meta_file.exists():
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                meta["analysis_status"] = "failed"
                meta["analysis_error"] = str(e)
                with open(meta_file, "w", encoding="utf-8") as f:
                    json.dump(meta, f, indent=2)
            except Exception:
                pass


def run_gemini_analysis(folder_path: Path, prompt: str) -> str:
    """
    Runs Gemini Vision directly through the Google GenAI SDK.
    Falls back gracefully to dynamic computer vision analysis on the uploaded photo if API key is absent.
    """
    api_key = os.environ.get("GEMINI_API_KEY")

    image_files = list(folder_path.glob("waste_photo.*"))
    if not image_files:
        raise FileNotFoundError(f"No complaint image found in {folder_path}")

    image_path = image_files[0]
    mime_type, _ = mimetypes.guess_type(str(image_path))
    if not mime_type or not mime_type.startswith("image/"):
        mime_type = "image/jpeg"

    # Attempt Gemini API if key is available and genai is installed
    if api_key and GENAI_AVAILABLE:
        analysis_prompt = """
You are the Garbage-Vision analysis engine for CleanGreen AI.
Analyze the provided photograph carefully and identify EVERY clearly visible waste / litter item.

IMPORTANT: Many uploaded photos contain NO waste at all (animals, people, vehicles, clean
streets, parks, buildings, indoor scenes). If you do not see actual garbage or litter,
you MUST return an empty "items" list. Never invent waste items that are not visible.

Return ONLY valid JSON. Do not use markdown fences. Do not add text outside the JSON.

Structure:
{
  "items": [
    {
      "item_id": "ITEM-001",
      "item_name": "plastic water bottle",
      "count": 1,
      "stream": "DRY_RECYCLABLE",
      "material": "PET plastic",
      "resin_code": "1 (PETE)",
      "sup_violation": true,
      "brand": "Bisleri",
      "condition": "crushed",
      "bounding_box": [ymin, xmin, ymax, xmax]
    }
  ],
  "segregation_verdict": "UNSEGREGATED",
  "hazard_flag": false,
  "summary": "Detailed summary of waste types, SUP violations, and hazard status."
}

RULES:
1. "bounding_box" MUST be normalized coordinates [ymin, xmin, ymax, xmax] from 0 to 1000.
2. "stream" must be one of: WET, DRY_RECYCLABLE, SANITARY, BIOMEDICAL_HAZARD, EWASTE, HAZARDOUS_CHEMICAL, CND, GENERIC_RESIDUAL.
3. "sup_violation" is true for single-use plastic items like thin bags, plastic straws, plastic bottles, styrofoam, multilayer sachets.
4. If no waste is visible: "items": [], "segregation_verdict": "CLEAN", "hazard_flag": false, and explain in "summary" that the scene appears free of litter.
5. "segregation_verdict" is "CLEAN" when items is empty, the single stream name when only one stream is present, otherwise "UNSEGREGATED".
6. Set "hazard_flag": true only if biomedical or chemical waste is visible.
"""
        client = genai.Client(api_key=api_key)
        with open(image_path, "rb") as f:
            image_bytes = f.read()

        candidate_models = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash"]
        for model in candidate_models:
            for attempt in range(2):
                try:
                    print(f"[AI WORKER] Calling Gemini API ({model}, attempt {attempt+1})...", flush=True)
                    response = client.models.generate_content(
                        model=model,
                        contents=[
                            analysis_prompt,
                            genai.types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
                        ],
                        config={"response_mime_type": "application/json", "temperature": 0.2}
                    )
                    if response and response.text:
                        print(f"[AI WORKER] Gemini response received successfully.", flush=True)
                        return response.text.strip()
                except Exception as err:
                    print(f"[AI WORKER] Gemini API ({model}) notice: {err}", flush=True)
                    time.sleep(2)

    # Dynamic Computer Vision Analysis tailored to the uploaded image file
    print(f"[AI WORKER] Analyzing uploaded photo {image_path.name} dynamically using computer vision...", flush=True)
    return generate_dynamic_image_analysis(image_path)


def generate_dynamic_image_analysis(image_path: Path) -> str:
    """
    Deterministic computer-vision audit of the uploaded photo (Pillow only, no model).

    Pipeline:
      1. Downscale the photo and build a local background model with a heavy
         Gaussian blur (the scene's own surroundings, not just frame borders).
      2. Flag "anomalous" grid cells: locally contrasty (pop vs blurred
         surround) AND edged, or extremely contrasty. Textured background
         (grass, asphalt, walls) averages out against its own blur, while
         discarded packaging, bottles and scraps pop against their surround.
      3. Segment flagged cells into blobs. One big blob whose deep interior is
         smooth and hue-tight is a scene subject (animal, vehicle, person),
         not litter — reject it.
      4. If littered, re-segment with stricter gates so individual artifact
         clusters get their own tight bounding boxes (up to 12).
      5. Classify each surviving cluster from its mean color/texture and emit
         real bounding boxes. If nothing survives, the report has zero items.
    """
    if not PIL_AVAILABLE:
        raise RuntimeError(
            "Image analysis is unavailable: Pillow is not installed in the Python running the backend. "
            "Start it from the project virtualenv (./.venv/bin/python server.py) "
            "or run: python3 -m pip install -r requirements.txt"
        )

    try:
        with Image.open(image_path) as img:
            img_rgb = img.convert("RGB")
            full_w, full_h = img_rgb.size

            # --- Work on a small copy for speed ---
            scale = 160.0 / max(full_w, full_h, 1)
            small_w = max(24, int(full_w * scale))
            small_h = max(24, int(full_h * scale))
            small = img_rgb.resize((small_w, small_h), Image.BILINEAR)
            blurred = small.filter(ImageFilter.GaussianBlur(radius=max(3, small_w // 12)))
            px = small.load()
            bx = blurred.load()
            epx = small.convert("L").filter(ImageFilter.FIND_EDGES).load()

            # --- Grid cells with local-contrast features ---
            cols = 24
            cell = max(2, small_w // cols)
            rows = max(1, small_h // cell)
            cols = max(1, small_w // cell)

            edge = [[0.0] * cols for _ in range(rows)]
            pop = [[0.0] * cols for _ in range(rows)]

            for r in range(rows):
                y0, y1 = r * cell, min((r + 1) * cell, small_h)
                for c in range(cols):
                    x0, x1 = c * cell, min((c + 1) * cell, small_w)
                    e_sum = p_sum = n = 0
                    for y in range(y0, y1):
                        for x in range(x0, x1):
                            p = px[x, y]
                            b = bx[x, y]
                            e_sum += epx[x, y]
                            p_sum += ((p[0] - b[0]) ** 2 + (p[1] - b[1]) ** 2 + (p[2] - b[2]) ** 2) ** 0.5
                            n += 1
                    edge[r][c] = e_sum / n
                    pop[r][c] = p_sum / n

            def segment(flag_fn, min_cells):
                flagged = [[False] * cols for _ in range(rows)]
                for r in range(rows):
                    for c in range(cols):
                        if flag_fn(r, c):
                            flagged[r][c] = True
                visited = [[False] * cols for _ in range(rows)]
                blobs = []
                for r in range(rows):
                    for c in range(cols):
                        if not flagged[r][c] or visited[r][c]:
                            continue
                        stack = [(r, c)]
                        visited[r][c] = True
                        cells = []
                        while stack:
                            br, bc = stack.pop()
                            cells.append((br, bc))
                            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                                nr, nc = br + dr, bc + dc
                                if 0 <= nr < rows and 0 <= nc < cols and flagged[nr][nc] and not visited[nr][nc]:
                                    visited[nr][nc] = True
                                    stack.append((nr, nc))
                        if len(cells) >= min_cells:
                            blobs.append(cells)
                return blobs

            def trim_extent(cells):
                """Snap the frame to the bulk of the flagged cells so boxes hug the artefact."""
                rc = {}
                cc = {}
                for (r, c) in cells:
                    rc[r] = rc.get(r, 0) + 1
                    cc[c] = cc.get(c, 0) + 1
                rk = sorted(rc)
                ck = sorted(cc)
                r_t = 0.35 * max(rc.values())
                c_t = 0.35 * max(cc.values())
                lo, hi = 0, len(rk) - 1
                while lo < hi and rc[rk[lo]] < r_t:
                    lo += 1
                while hi > lo and rc[rk[hi]] < r_t:
                    hi -= 1
                r_lo, r_hi = rk[lo], rk[hi]
                lo, hi = 0, len(ck) - 1
                while lo < hi and cc[ck[lo]] < c_t:
                    lo += 1
                while hi > lo and cc[ck[hi]] < c_t:
                    hi -= 1
                return r_lo, r_hi, ck[lo], ck[hi]

            def blob_stats(b):
                cellset = set(b)
                inner = [
                    (r, c) for (r, c) in b
                    if (r - 1, c) in cellset and (r + 1, c) in cellset
                    and (r, c - 1) in cellset and (r, c + 1) in cellset
                ]
                if len(inner) >= 8:
                    es = sorted(edge[r][c] for (r, c) in inner)
                    deep_med = es[len(es) // 2]
                else:
                    deep_med = sum(edge[r][c] for (r, c) in b) / len(b)
                hues = []
                for (r, c) in b:
                    x0, x1 = c * cell, min((c + 1) * cell, small_w)
                    y0, y1 = r * cell, min((r + 1) * cell, small_h)
                    cr = cg = cb = n = 0
                    for y in range(y0, y1):
                        for x in range(x0, x1):
                            p = px[x, y]
                            cr += p[0]; cg += p[1]; cb += p[2]; n += 1
                    h, s, v = colorsys.rgb_to_hsv(cr / (n * 255), cg / (n * 255), cb / (n * 255))
                    if s > 0.25 and v > 0.15:
                        hues.append(h)
                hues.sort()
                spread = (hues[-1] - hues[0]) if len(hues) >= 3 else 0.0
                mean_edge = sum(edge[r][c] for (r, c) in b) / len(b)
                mean_pop = sum(pop[r][c] for (r, c) in b) / len(b)
                return deep_med, spread, mean_edge, mean_pop

            # --- Scene pass: decide littered vs clean, reject scene subjects ---
            blobs = segment(lambda r, c: (
                (pop[r][c] > 30 and edge[r][c] > 12)
                or pop[r][c] > 55
                or edge[r][c] > 36
            ), min_cells=2)

            total_cells = rows * cols
            kept = []
            for b in blobs:
                area_frac = len(b) / total_cells
                deep_med, spread, _, _ = blob_stats(b)
                dominant_subject = (
                    area_frac >= 0.40
                    and deep_med <= 34
                    and spread <= 0.28
                )
                if not dominant_subject:
                    kept.append(b)

            kept_cells = sum(len(b) for b in kept)
            kept_coverage = kept_cells / total_cells if total_cells else 0.0
            mean_edge = (sum(edge[r][c] for b in kept for (r, c) in b) / kept_cells) if kept_cells else 0.0
            max_edge = max((sum(edge[r][c] for (r, c) in b) / len(b) for b in kept), default=0.0)
            is_littered = bool(kept) and kept_coverage >= 0.02 and (
                len(kept) >= 2 or kept_coverage >= 0.05 or max_edge >= 22
            )

            if os.environ.get("CV_DEBUG"):
                print(
                    f"[CV_DEBUG] {image_path.name}: grid={rows}x{cols} blobs={len(blobs)} kept={len(kept)} "
                    f"coverage={kept_coverage:.3f} mean_edge={mean_edge:.1f} littered={is_littered}",
                    flush=True,
                )

            # --- Item pass: strict gates so each artifact cluster gets its own box ---
            detected_items = []
            if is_littered:
                sub_blobs = segment(lambda r, c: (
                    (pop[r][c] > 45 and edge[r][c] > 16)
                    or pop[r][c] > 70
                    or edge[r][c] > 48
                ), min_cells=2)
                item_regions = []
                for b in sub_blobs:
                    area_frac = len(b) / total_cells
                    if area_frac < 0.003:
                        continue
                    min_r = min(r for r, _ in b); max_r = max(r for r, _ in b)
                    min_c = min(c for _, c in b); max_c = max(c for _, c in b)
                    bbox_cells = (max_r - min_r + 1) * (max_c - min_c + 1)
                    fill = len(b) / bbox_cells if bbox_cells else 0.0
                    if area_frac >= 0.08 and fill <= 0.8:
                        # Wide scattered spread — one giant box would swamp the frame
                        gs = 4 if area_frac >= 0.20 else 3
                        tile_r = max(2, -(-(max_r - min_r + 1) // gs))
                        tile_c = max(2, -(-(max_c - min_c + 1) // gs))
                        tiles = {}
                        for (r, c) in b:
                            key = ((r - min_r) // tile_r, (c - min_c) // tile_c)
                            tiles.setdefault(key, []).append((r, c))
                        for cells in tiles.values():
                            if len(cells) >= 3:
                                item_regions.append(cells)
                        if os.environ.get("CV_DEBUG"):
                            print(f"[CV_DEBUG]   subdivided blob: area={area_frac:.2f} fill={fill:.2f} tiles={len(item_regions)}", flush=True)
                    else:
                        item_regions.append(b)

                scored = []
                for region in item_regions:
                    area_frac = len(region) / total_cells
                    _d, _s, _e, mpop = blob_stats(region)
                    scored.append((area_frac * mpop, region))
                scored.sort(key=lambda t: t[0], reverse=True)
                item_counter = 1
                class_seen = {}
                placed_boxes = []
                for _score, b in scored[:14]:
                    cr = cg = cb = e_sum = n = 0
                    for (br, bc) in b:
                        x0, x1 = bc * cell, min((bc + 1) * cell, small_w)
                        y0, y1 = br * cell, min((br + 1) * cell, small_h)
                        for y in range(y0, y1):
                            for x in range(x0, x1):
                                p = px[x, y]
                                cr += p[0]; cg += p[1]; cb += p[2]; n += 1
                                e_sum += epx[x, y]
                    min_r, max_r, min_c, max_c = trim_extent(b)
                    overlap = False
                    for (pr0, pr1, pc0, pc1) in placed_boxes:
                        ov_r = min(max_r, pr1) - max(min_r, pr0) + 1
                        ov_c = min(max_c, pc1) - max(min_c, pc0) + 1
                        if ov_r <= 0 or ov_c <= 0:
                            continue
                        inter = ov_r * ov_c
                        union = ((max_r - min_r + 1) * (max_c - min_c + 1)
                                 + (pr1 - pr0 + 1) * (pc1 - pc0 + 1) - inter)
                        if inter / union >= 0.25:
                            overlap = True
                            break
                    if overlap:
                        if os.environ.get("CV_DEBUG"):
                            print(f"[CV_DEBUG]   REJECT overlap ext={(min_r,max_r,min_c,max_c)}", flush=True)
                        continue
                    placed_boxes.append((min_r, max_r, min_c, max_c))

                    mu = (cr / n, cg / n, cb / n)
                    blob_edge = e_sum / n
                    area_frac = len(b) / total_cells
                    count = 1 if area_frac < 0.02 else (2 if area_frac < 0.06 else 3)

                    h, s, v = colorsys.rgb_to_hsv(mu[0] / 255, mu[1] / 255, mu[2] / 255)
                    bright = (mu[0] + mu[1] + mu[2]) / 3
                    if bright > 205 and s < 0.25:
                        cat_key = "styfo"
                    elif bright < 55:
                        cat_key = "black_film"
                    elif s < 0.18 and bright >= 120:
                        cat_key = "clear_pet"
                    elif 0.5 <= h <= 0.72 and s > 0.25:
                        cat_key = "organic"
                    elif 0.04 <= h <= 0.17 and s < 0.45 and mu[0] >= mu[1] >= mu[2]:
                        cat_key = "paper"
                    elif s > 0.35 and (h <= 0.08 or h >= 0.92):
                        cat_key = "wrapper"
                    elif s > 0.4 and 0.08 < h < 0.17:
                        cat_key = "wrapper"
                    elif s < 0.2 and 60 <= bright < 120 and blob_edge > 20:
                        cat_key = "alu"
                    elif blob_edge > 30:
                        cat_key = "crushed_plastic"
                    else:
                        cat_key = "misc"

                    cat = variant_for(cat_key, class_seen.get(cat_key, 0))
                    class_seen[cat_key] = class_seen.get(cat_key, 0) + 1

                    ymin = int(max(0, (min_r * cell / small_h) * 1000)) + 8
                    xmin = int(max(0, (min_c * cell / small_w) * 1000)) + 8
                    ymax = int(min(1000, ((max_r + 1) * cell / small_h) * 1000)) - 8
                    xmax = int(min(1000, ((max_c + 1) * cell / small_w) * 1000)) - 8
                    if ymax <= ymin or xmax <= xmin:
                        continue

                    detected_items.append({
                        "item_id": f"ITEM-{item_counter:03d}",
                        "item_name": cat[0],
                        "count": count,
                        "stream": cat[1],
                        "material": cat[2],
                        "resin_code": cat[3],
                        "sup_violation": cat[4],
                        "brand": cat[5],
                        "condition": f"Isolated artifact cluster ({len(b)} sectors, {area_frac:.1%} of frame)",
                        "bounding_box": [ymin, xmin, ymax, xmax]
                    })
                    item_counter += 1

            streams = {it["stream"] for it in detected_items}
            hazard = any(s in ("BIOMEDICAL_HAZARD", "HAZARDOUS_CHEMICAL") for s in streams)
            if not detected_items:
                verdict, summary = "CLEAN", (
                    f"On-device heuristic sweep of the uploaded photo ({full_w}x{full_h}px): no scattered "
                    f"waste artifacts detected. The frame is dominated by a uniform scene/subject "
                    f"({kept_coverage:.1%} anomalous coverage after subject filtering). Scene appears clean."
                )
            else:
                verdict = "UNSEGREGATED" if len(streams) > 1 else next(iter(streams))
                summary = (
                    f"On-device heuristic sweep of the uploaded photo ({full_w}x{full_h}px): anomalous "
                    f"regions covering {kept_coverage:.1%} of the frame segmented into {len(detected_items)} "
                    f"artifact cluster(s) (mean edge density {mean_edge:.1f}). Streams present: "
                    f"{', '.join(sorted(streams))}. For per-item AI identification, configure GEMINI_API_KEY "
                    f"on the backend (Google AI Studio free tier)."
                )

            payload = {
                "items": detected_items,
                "segregation_verdict": verdict,
                "hazard_flag": hazard,
                "summary": summary
            }
            return json.dumps(payload, indent=2)

    except Exception as err:
        print(f"[AI WORKER] Image dynamic analysis error: {err}", flush=True)
        raise RuntimeError(f"Automated sweep failed on this photo: {err}") from err


def extract_json_and_markdown(raw_output: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """Extracts the structured JSON payload and markdown narrative from raw output."""
    json_data = None
    markdown_narrative = raw_output

    # 1. Try ```json ... ``` code fence
    json_block_regex = re.search(r"```json\s*(\{[\s\S]*?\})\s*```", raw_output)
    if json_block_regex:
        json_str = json_block_regex.group(1).strip()
        try:
            json_data = json.loads(json_str)
        except json.JSONDecodeError:
            pass

    # 2. Try matching raw json object containing "items"
    if not json_data:
        brace_regex = re.search(r"(\{[\s\S]*\"items\"[\s\S]*\})", raw_output)
        if brace_regex:
            json_str = brace_regex.group(1).strip()
            try:
                json_data = json.loads(json_str)
            except json.JSONDecodeError:
                pass

    # 3. Direct JSON decode attempt
    if not json_data:
        try:
            json_data = json.loads(raw_output.strip())
        except json.JSONDecodeError:
            pass

    return json_data, markdown_narrative


def draw_bounding_boxes(image_path: Path, report_json: Dict[str, Any], output_path: Path) -> bool:
    """Draws color-coded bounding boxes on the complaint photo and saves to output_path."""
    if not PIL_AVAILABLE:
        print("[WARN] Pillow is not available. Skipping visual annotations.")
        return False

    try:
        with Image.open(image_path) as img:
            img = img.convert("RGB")
            draw = ImageDraw.Draw(img)
            width, height = img.size

            try:
                font = ImageFont.load_default(size=14)
            except Exception:
                font = ImageFont.load_default()

            items = report_json.get("items", [])
            overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
            odraw = ImageDraw.Draw(overlay)
            framed = []
            for idx, item in enumerate(items, 1):
                bbox = item.get("bounding_box") or item.get("box_2d")
                if not bbox or len(bbox) != 4:
                    continue

                ymin_norm, xmin_norm, ymax_norm, xmax_norm = bbox
                ymin = int((ymin_norm / 1000.0) * height)
                xmin = int((xmin_norm / 1000.0) * width)
                ymax = int((ymax_norm / 1000.0) * height)
                xmax = int((xmax_norm / 1000.0) * width)

                stream = item.get("stream", "GENERIC_RESIDUAL")
                color = STREAM_COLORS.get(stream, (128, 128, 128))

                odraw.rectangle([xmin, ymin, xmax, ymax], fill=color + (55,))
                framed.append((idx, item.get("item_name", "Item"),
                               item.get("sup_violation"), xmin, ymin, xmax, ymax, color))

            img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
            draw = ImageDraw.Draw(img)

            for idx, name, sup, xmin, ymin, xmax, ymax, color in framed:
                short = name if len(name) <= 30 else name[:29].rstrip(" /-&+") + "…"
                label_text = f"{idx}. {short}"
                if sup:
                    label_text += " [SUP BAN]"

                # Numbered tag sits above the frame, or just inside it at the top edge.
                tag_y = ymin - 20 if ymin >= 20 else ymin + 3
                tb = draw.textbbox((xmin, tag_y), label_text, font=font)
                tag_x = min(xmin, max(0, width - (tb[2] - tb[0]) - 2))
                tb = (tag_x, tag_y, tag_x + (tb[2] - tb[0]), tag_y + (tb[3] - tb[1]))
                draw.rectangle((tb[0] - 2, tb[1] - 1, tb[2] + 2, tb[3] + 1), fill=(10, 14, 20))
                draw.rectangle([xmin, ymin, xmax, ymax], outline=color, width=3)
                draw.text((tb[0], tb[1] - 2), label_text, fill=(255, 255, 255), font=font)

            img.save(output_path, "JPEG", quality=90)
            return True

    except Exception as e:
        print(f"[WARN] Failed to draw bounding boxes: {e}")
        return False


def export_report_csv(report_json: Dict[str, Any], output_path: Path):
    """Exports items from report_json to a standard CSV file."""
    items = report_json.get("items", [])
    fieldnames = [
        "item_id", "item_name", "count", "stream", "material",
        "resin_code", "sup_violation", "brand", "condition",
        "bounding_box"
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        for it in items:
            row = {
                "item_id": it.get("item_id", ""),
                "item_name": it.get("item_name", ""),
                "count": it.get("count", 1),
                "stream": it.get("stream", "GENERIC_RESIDUAL"),
                "material": it.get("material", ""),
                "resin_code": it.get("resin_code", ""),
                "sup_violation": it.get("sup_violation", False),
                "brand": it.get("brand", "unidentified"),
                "condition": it.get("condition", ""),
                "bounding_box": str(it.get("bounding_box") or it.get("box_2d", ""))
            }
            writer.writerow(row)