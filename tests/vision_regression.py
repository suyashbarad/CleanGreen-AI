"""
Vision regression suite — run before shipping any analyzer change.

    ./.venv/bin/python tests/vision_regression.py            # with the CLIP verifier
    ./.venv/bin/python tests/vision_regression.py --no-ml    # Render parity (heuristics only)

Fixtures are the real complaints in `complaints/`, labelled by eye:
photos of actual dumps must come back with boxes, photos of animals /
clean scenes must come back with `0 items / CLEAN`.
"""

import io
import json
import os
import random
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from analyzer import generate_dynamic_image_analysis, draw_bounding_boxes  # noqa: E402

COMPLAINTS = ROOT / "complaints"
OUT = Path(os.environ.get("REG_OUT_DIR", str(ROOT / ".test-output")))
shutil.rmtree(OUT, ignore_errors=True)
OUT.mkdir(parents=True, exist_ok=True)

LITTER_FOLDERS = [
    "loc_18.509700_73.821186_20261003_164508_0a34",
    "loc_18.511125_73.815742_20260913_154835_6902",
    "loc_18.513895_73.812055_20261003_230155_1a81",
    "loc_18.513895_73.821369_20261003_175651_794a",
    "loc_18.515075_73.822485_20261003_182331_47c8",
    "loc_18.515238_73.827678_20261003_162240_9ca3",
    "loc_18.516810_73.828176_20261003_162448_8635",
]

NOT_LITTER_FOLDERS = [
    "loc_18.515075_73.814716_20261003_230004_29b5",   # dog running with a stick
    "loc_18.515534_73.817730_20261003_230050_d4f8",   # labrador on a lawn
    "loc_18.515785_73.840534_20261003_222907_2f73",   # pug on a white backdrop
    "loc_18.517395_73.816519_20261003_162751_e0fc",   # clean street scene
]

MIN_BOXES_ON_LITTER = 5
MAX_BOX_AREA = 0.10   # one box may not cover a tenth of the frame — that is a subject, not litter


def photo(folder: str):
    matches = sorted((COMPLAINTS / folder).glob("waste_photo.*"))
    return matches[0] if matches else None


def analyse(path: Path) -> dict:
    raw = generate_dynamic_image_analysis(path)
    return json.loads(raw[raw.find("{"):raw.rfind("}") + 1])


def synthetic_cases() -> list:
    """Deterministic non-litter images: no download needed, no network in CI."""
    from PIL import Image

    cases = []
    solid = Image.new("RGB", (900, 600), (248, 248, 250))
    cases.append(("synthetic_studio_backdrop.png", solid))

    sky = Image.new("RGB", (900, 600))
    for y in range(600):                      # smooth gradient: sky over field
        t = y / 600
        sky.paste((int(120 + 60 * t), int(170 + 40 * t), int(220 - 120 * t)),
                  (0, y, 900, y + 1))
    cases.append(("synthetic_sky_gradient.png", sky))

    import random
    rnd = random.Random(7)
    brick = Image.new("RGB", (900, 600))
    px = brick.load()
    for y in range(600):                      # repeating masonry texture
        row_dark = (y % 24) < 3
        for x in range(900):
            col_dark = ((x + (18 if (y // 24) % 2 else 0)) % 48) < 3
            if row_dark or col_dark:
                px[x, y] = (150, 145, 140)
            else:
                j = rnd.randint(-8, 8)
                px[x, y] = (176 + j, 96 + j, 62 + j)
    cases.append(("synthetic_brick_wall.png", brick))

    OUT.mkdir(parents=True, exist_ok=True)
    built = []
    for name, img in cases:
        p = OUT / name
        img.save(p)
        built.append((name, p))
    return built


def box_area(box) -> float:
    ymin, xmin, ymax, xmax = box
    return max(0.0, (ymax - ymin) / 1000.0) * max(0.0, (xmax - xmin) / 1000.0)


def main() -> int:
    if "--no-ml" in sys.argv:
        os.environ["CV_ML"] = "0"
        print("[SUITE] CLIP verifier disabled (Render parity).\n")

    failures = []

    print("--- must report CLEAN (no litter in the photo) ---")
    clean_cases = [(f, photo(f)) for f in NOT_LITTER_FOLDERS] + synthetic_cases()
    for label, path in clean_cases:
        if path is None or not path.exists():
            failures.append(f"{label}: fixture missing")
            print(f"MISSING  {label}")
            continue
        rep = analyse(path)
        items = rep.get("items", [])
        ok = not items and rep.get("segregation_verdict") == "CLEAN"
        print(f"{'PASS' if ok else 'FAIL'}  {label}: items={len(items)} "
              f"verdict={rep.get('segregation_verdict')}")
        if not ok:
            failures.append(f"{label}: expected 0 items, got {len(items)}")
        elif os.environ.get("REG_ANNOTATE"):
            draw_bounding_boxes(path, rep, OUT / f"clean_{Path(label).stem}.jpg")

    print("\n--- must detect litter ---")
    for folder in LITTER_FOLDERS:
        path = photo(folder)
        if path is None:
            failures.append(f"{folder}: fixture missing")
            print(f"MISSING  {folder}")
            continue
        rep = analyse(path)
        items = rep.get("items", [])
        names = [i.get("item_name") for i in items]
        dupes = len(names) - len(set(names))
        biggest = max((box_area(i["bounding_box"]) for i in items
                       if len(i.get("bounding_box", [])) == 4), default=0.0)
        m = rep.get("metrics", {})
        ok = len(items) >= MIN_BOXES_ON_LITTER and dupes == 0 and biggest <= MAX_BOX_AREA
        print(f"{'PASS' if ok else 'FAIL'}  {folder}: items={len(items)} dupes={dupes} "
              f"biggest_box={biggest:.1%} severity={m.get('severity')} "
              f"load={m.get('estimated_weight_kg')}kg")
        if not ok:
            failures.append(f"{folder}: items={len(items)} dupes={dupes} biggest={biggest:.1%}")
        if os.environ.get("REG_ANNOTATE"):
            OUT.mkdir(parents=True, exist_ok=True)
            draw_bounding_boxes(path, rep, OUT / f"litter_{folder[-9:]}.jpg")

    print()
    if failures:
        print("FAILURES:")
        for f in failures:
            print("  -", f)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
