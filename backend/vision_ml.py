"""
Optional CLIP verifier — a real vision model that decides whether a photo (or a
single bounding box inside it) actually contains litter.

The colour/edge heuristic in analyzer.py is fast but blind to meaning: a pug on a
white backdrop "pops" exactly like a pile of wrappers. CLIP reads the content, so
when this module is available the heuristic only proposes boxes and CLIP disposes
of them.

torch/transformers are deliberately NOT in requirements.txt: the Render free tier
cannot hold them, so the backend must keep working without this module.
"""

import os
import threading
from typing import List, Optional, Sequence

MODEL_ID = "openai/clip-vit-base-patch32"

LITTER_PROMPTS = [
    "a photograph of garbage and litter scattered on the ground",
    "a photograph of discarded plastic bottles and wrappers",
    "a photograph of a pile of household trash",
    "a photograph of rubbish dumped on the roadside",
    "a photograph of an overflowing garbage bin",
]

NOT_LITTER_PROMPTS = [
    "a photograph of a clean paved road",
    "a photograph of green grass and plants",
    "a photograph of soil, mud and stones",
    "a photograph of a body of water",
    "a photograph of a building or a wall",
    "a photograph of a parked vehicle",
    "a photograph of an animal",
    "a photograph of a person",
    "a photograph of a product on a plain white background",
    "a photograph of food served on a plate",
    "a photograph of trees against a clear sky",
    "a photograph of household objects arranged on a table",
    "a photograph of a tidy room interior with furniture",
]

PROMPTS = LITTER_PROMPTS + NOT_LITTER_PROMPTS
N_LITTER = len(LITTER_PROMPTS)

# Chosen from the measured spread over the project's labelled fixtures plus 12 unseen
# stock photos: every genuine garbage photo scored 0.987-0.9998, while every non-litter
# photo (pug on white, brick wall, landscape, desk flat-lay, random stock) stayed at or
# below 0.219. The threshold sits in the middle of that gap.
SCENE_LITTER_THRESHOLD = 0.50
SCENE_LITTER_RESCUE = 0.80
BOX_LITTER_THRESHOLD = 0.20

_lock = threading.Lock()
_model = None
_processor = None
_failed = False


def use_ml() -> bool:
    """Honour CV_ML=0 so the pure-heuristic path can still be tested side by side."""
    if os.environ.get("CV_ML", "1") == "0":
        return False
    return available()


def available() -> bool:
    """True once the model is loaded; attempts the load exactly once."""
    global _model, _processor, _failed
    if _model is not None:
        return True
    if _failed:
        return False
    with _lock:
        if _model is not None or _failed:
            return _model is not None
        try:
            import torch  # noqa: F401
            from transformers import CLIPModel, CLIPProcessor

            _processor = CLIPProcessor.from_pretrained(MODEL_ID)
            _model = CLIPModel.from_pretrained(MODEL_ID)
            _model.eval()
            print(f"[VISION ML] CLIP verifier ready ({MODEL_ID}).", flush=True)
            return True
        except Exception as err:
            _failed = True
            print(f"[VISION ML] Disabled ({type(err).__name__}: {err}). "
                  f"Falling back to colour/edge heuristics only.", flush=True)
            return False


def _litter_probs(images: Sequence, ) -> List[float]:
    import torch

    with torch.no_grad():
        inputs = _processor(text=[*PROMPTS], images=list(images), return_tensors="pt", padding=True)
        logits = _model(**inputs).logits_per_image          # (n_images, n_prompts)
        probs = logits.softmax(dim=-1)
        return probs[:, :N_LITTER].sum(dim=-1).tolist()


def scene_litter_score(image) -> Optional[float]:
    """P(the photo contains litter) for a whole frame, or None if ML is off."""
    if not available():
        return None
    return _litter_probs([image])[0]


def box_litter_scores(image, boxes: List[Sequence[float]], pad: float = 0.15) -> List[Optional[float]]:
    """P(litter) for each 0-1000 relative [ymin, xmin, ymax, xmax] box crop."""
    if not boxes or not available():
        return [None] * len(boxes)

    w, h = image.size
    crops = []
    for b in boxes:
        ymin, xmin, ymax, xmax = b
        x0, x1 = xmin / 1000 * w, xmax / 1000 * w
        y0, y1 = ymin / 1000 * h, ymax / 1000 * h
        pw, ph = (x1 - x0) * pad, (y1 - y0) * pad
        x0, y0 = max(0, x0 - pw), max(0, y0 - ph)
        x1, y1 = min(w, x1 + pw), min(h, y1 + ph)
        if x1 - x0 < 6 or y1 - y0 < 6:
            crops.append(None)
        else:
            crops.append(image.crop((int(x0), int(y0), int(x1), int(y1))))

    scores: List[Optional[float]] = [None] * len(boxes)
    valid = [(i, c) for i, c in enumerate(crops) if c is not None]
    if valid:
        values = _litter_probs([c for _, c in valid])
        for (i, _), v in zip(valid, values):
            scores[i] = v
    return scores
