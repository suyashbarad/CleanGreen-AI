"""
Backend Garbage-Vision Analysis Worker
Orchestrates:
1. Fast complaint saving (image + metadata) in < 100ms
2. Headless asynchronous background execution of agy CLI with garbage-vision skill
3. Parsing forensic JSON and Markdown summary
4. Generation of color-coded annotated photo and CSV export
"""

import os
import re
import sys
import json
import csv
import time
import subprocess
import secrets
from pathlib import Path
from typing import Dict, Any, Optional
import mimetypes
from google import genai

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


# Stream Colors for visual bounding boxes
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


def create_complaint_folder(base_dir: Path, lat: float, lng: float) -> tuple[Path, str]:
    """Creates a unique complaint folder based on GPS coords, timestamp, and random hex."""
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    rand_hex = secrets.token_hex(2)
    folder_name = f"loc_{lat:.6f}_{lng:.6f}_{timestamp}_{rand_hex}"
    folder_path = base_dir / folder_name
    folder_path.mkdir(parents=True, exist_ok=True)
    complaint_id = f"CMP-{timestamp}-{rand_hex.upper()}"
    return folder_path, complaint_id


def save_initial_complaint(
    base_dir: Path,
    image_bytes: bytes,
    image_filename: str,
    lat: float,
    lng: float,
    address: str = "",
    notes: str = ""
) -> tuple[Path, str, Path]:
    """
    Instantly writes the photo and initial metadata.json to disk in < 50ms.
    Returns: (folder_path, complaint_id, image_file_path)
    """
    folder_path, complaint_id = create_complaint_folder(base_dir, lat, lng)

    ext = os.path.splitext(image_filename)[1].lower() or ".jpg"
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
        "image_file": image_file_path.name
    }

    with open(folder_path / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    return folder_path, complaint_id, image_file_path


def run_background_ai_analysis(folder_path: Path, image_file_path: Path):
    """
    Runs in a background worker thread.
    Executes agy CLI with garbage-vision headlessly, creates annotated_photo.jpg,
    report.json, and report.csv.
    """
    try:
        print(f"[AI WORKER] Starting background Vision AI for: {folder_path.name}")
        prompt = "use garbage-vision skill to Analyze this garbage photo completely. List EVERY item you can see."
        raw_output = run_agy_analysis(folder_path, prompt)

        report_json, markdown_summary = extract_json_and_markdown(raw_output)

        # Save summary markdown
        with open(folder_path / "report_summary.md", "w", encoding="utf-8") as f:
            f.write(markdown_summary)

        # Save report.json
        report_json_path = folder_path / "report.json"
        if not report_json:
            report_json = {"items": [], "raw_output": raw_output}
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


def run_agy_analysis(folder_path: Path, prompt: str) -> str:
    """
    Runs Gemini Vision directly through the Gemini API.

    This replaces the old local agy.exe / Antigravity dependency.
    The image is sent from the Render server directly to Gemini.
    """

    api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY environment variable is not configured."
        )

    image_files = list(folder_path.glob("waste_photo.*"))

    if not image_files:
        raise FileNotFoundError(
            f"No complaint image found in {folder_path}"
        )

    image_path = image_files[0]

    mime_type, _ = mimetypes.guess_type(str(image_path))

    if not mime_type or not mime_type.startswith("image/"):
        mime_type = "image/jpeg"

    client = genai.Client(api_key=api_key)

    analysis_prompt = """
You are the Garbage-Vision analysis engine for CleanGreen AI.

Analyze the provided garbage/waste photograph carefully.

Identify EVERY clearly visible waste item.

Return ONLY valid JSON. Do not use markdown fences.
Do not add explanations before or after the JSON.

Use exactly this structure:

{
  "items": [
    {
      "item_id": "ITEM-001",
      "item_name": "plastic bottle",
      "count": 1,
      "stream": "DRY_RECYCLABLE",
      "material": "plastic",
      "resin_code": "",
      "sup_violation": false,
      "brand": "unidentified",
      "condition": "used",
      "bounding_box": [ymin, xmin, ymax, xmax]
    }
  ],
  "summary": "Brief description of the waste scene."
}

IMPORTANT RULES:

1. Identify every clearly visible waste item.
2. Do not invent objects that are not visible.
3. If several identical objects are clearly visible, either list them separately or use count when appropriate.
4. "bounding_box" MUST use normalized coordinates from 0 to 1000.
5. Bounding box order MUST be:
   [ymin, xmin, ymax, xmax]
6. Make the bounding boxes as tight as reasonably possible around each item.
7. Use one of these stream values:
   - WET
   - DRY_RECYCLABLE
   - SANITARY
   - BIOMEDICAL_HAZARD
   - EWASTE
   - HAZARDOUS_CHEMICAL
   - CND
   - GENERIC_RESIDUAL
8. Use "CND" for construction/demolition waste.
9. Use "DRY_RECYCLABLE" for commonly recyclable dry waste such as plastic bottles, cans, paper and cardboard.
10. Set "sup_violation" to true only when the item is clearly identifiable as a prohibited/single-use plastic item according to the project's intended classification.
11. If a field cannot be determined, use an empty string rather than inventing information.
12. If no waste items can be reliably identified, return:
    {"items": [], "summary": "No clearly identifiable waste items."}

Return ONLY the JSON object.
"""

    print(f"[AI WORKER] Sending {image_path.name} to Gemini...")

    with open(image_path, "rb") as f:
        image_bytes = f.read()

    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=[
            analysis_prompt,
            genai.types.Part.from_bytes(
                data=image_bytes,
                mime_type=mime_type
            )
        ]
    )

    result = response.text.strip()

    if not result:
        raise RuntimeError("Gemini returned an empty response.")

    print("[AI WORKER] Gemini analysis received.")

    # Keep compatibility with the existing JSON parser.
    return result


def extract_json_and_markdown(raw_output: str) -> tuple[Optional[Dict[str, Any]], str]:
    """Extracts the structured JSON payload and markdown narrative from the agy output."""
    json_data = None
    markdown_narrative = raw_output

    json_block_regex = re.search(r"```json\s*(\{.*?\})\s*```", raw_output, re.DOTALL)
    if json_block_regex:
        json_str = json_block_regex.group(1).strip()
        try:
            json_data = json.loads(json_str)
        except json.JSONDecodeError:
            pass

    if not json_data:
        brace_regex = re.search(r"(\{[\s\S]*\"items\"[\s\S]*\})", raw_output)
        if brace_regex:
            json_str = brace_regex.group(1).strip()
            try:
                json_data = json.loads(json_str)
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
            for item in items:
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

                for offset in range(3):
                    draw.rectangle(
                        [xmin - offset, ymin - offset, xmax + offset, ymax + offset],
                        outline=color
                    )

                label_text = f"{item.get('item_name', 'Item')}"
                if item.get("sup_violation"):
                    label_text += " [SUP BAN]"

                text_bbox = draw.textbbox((xmin, max(0, ymin - 18)), label_text, font=font)
                draw.rectangle(text_bbox, fill=color)
                draw.text((xmin + 2, max(0, ymin - 18)), label_text, fill=(255, 255, 255), font=font)

            img.save(output_path, "JPEG", quality=90)
            return True

    except Exception as e:
        print(f"[WARN] Failed to draw bounding boxes: {e}")
        return False


def export_report_csv(report_json: Dict[str, Any], output_path: Path):
    """Exports items from report_json to a standard CSV file."""
    items = report_json.get("items", [])
    if not items:
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["item_id", "item_name", "count", "stream", "material", "resin_code", "sup_violation", "brand", "condition"])
        return

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
