"""
NoteAI Pro — Cover Feature Extraction Pipeline

Three-layer extraction (local dev phase):
  Layer 1: PIL/OpenCV deterministic features  — free, instant
  Layer 2: OpenCV Haar cascade face detection — free, instant
  Layer 3: Claude Haiku Vision               — ~$0.002/img, ~$20 for 10k

Output:
  data/cover_features.parquet   — 14 features per cover, indexed by note_id

Usage:
  python3 extract_cover_features.py               # full run (all 3 layers)
  python3 extract_cover_features.py --no-vision   # skip Claude (layers 1+2 only)
  python3 extract_cover_features.py --limit 100   # test on 100 images

Cost estimate: 10,000 images × $0.002 ≈ $20 (one-time)
"""

import argparse
import asyncio
import base64
import json
import os
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
from PIL import Image, ImageStat

BASE_DIR = Path(__file__).parent

# Defaults — overridden by --run-id
COVER_DIR = BASE_DIR / "data/covers"
METADATA_PATH = BASE_DIR / "data/cover_metadata.jsonl"
FEATURES_OUT = BASE_DIR / "data/cover_features.parquet"
VISION_CACHE = BASE_DIR / "data/cover_vision_cache.jsonl"


def set_run_paths(run_id: str):
    global COVER_DIR, METADATA_PATH, FEATURES_OUT, VISION_CACHE
    suffix = f"_{run_id}" if run_id != "v1" else ""
    COVER_DIR = BASE_DIR / f"data/covers{suffix}"
    METADATA_PATH = BASE_DIR / f"data/cover_metadata{suffix}.jsonl"
    FEATURES_OUT = BASE_DIR / f"data/cover_features{suffix}.parquet"
    VISION_CACHE = BASE_DIR / f"data/cover_vision_cache{suffix}.jsonl"

# OpenCV face cascade (built-in, no download needed)
CASCADE_PATH = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"

HAIKU_MODEL = "claude-haiku-4-5-20251001"
VISION_CONCURRENCY = 8   # parallel Claude requests
VISION_BATCH = 50        # save checkpoint every N images


# ── Layer 1: Deterministic features (PIL + NumPy) ─────────────────────────────

def extract_deterministic(img_path: Path) -> dict:
    """Extract color, brightness, contrast, sharpness via PIL."""
    try:
        img = Image.open(img_path).convert("RGB")
        w, h = img.size
        arr = np.array(img, dtype=np.float32)

        # Brightness (mean luminance)
        r, g, b = arr[:,:,0], arr[:,:,1], arr[:,:,2]
        luminance = 0.299*r + 0.587*g + 0.114*b
        brightness = float(luminance.mean() / 255)

        # Color warmth: warm pixels (R > B) ratio
        warmth = float((r > b).mean())

        # Saturation via HSV
        hsv = np.array(img.convert("HSV"), dtype=np.float32) if hasattr(Image, "HSV") else None
        if hsv is None:
            # Manual HSV saturation
            max_c = arr.max(axis=2)
            min_c = arr.min(axis=2)
            sat = np.where(max_c > 0, (max_c - min_c) / np.maximum(max_c, 1e-6), 0)
        else:
            sat = hsv[:,:,1] / 255
        saturation = float(sat.mean())

        # Contrast (RMS)
        contrast = float(luminance.std() / 255)

        # Sharpness: Laplacian variance via OpenCV
        gray = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var() / 10000)
        sharpness = min(sharpness, 1.0)

        # Aspect ratio (XHS is typically portrait 3:4)
        aspect_ratio = float(w / h) if h > 0 else 1.0

        return {
            "cover_brightness": round(brightness, 4),
            "cover_warmth": round(warmth, 4),
            "cover_saturation": round(saturation, 4),
            "cover_contrast": round(contrast, 4),
            "cover_sharpness": round(sharpness, 4),
            "cover_aspect_ratio": round(aspect_ratio, 4),
        }
    except Exception as e:
        return {
            "cover_brightness": None, "cover_warmth": None,
            "cover_saturation": None, "cover_contrast": None,
            "cover_sharpness": None, "cover_aspect_ratio": None,
        }


# ── Layer 2: Face detection (OpenCV Haar cascade) ─────────────────────────────

_face_cascade = None

def get_cascade():
    global _face_cascade
    if _face_cascade is None:
        _face_cascade = cv2.CascadeClassifier(CASCADE_PATH)
    return _face_cascade


def detect_faces(img_path: Path) -> dict:
    """Detect faces using OpenCV Haar cascade."""
    try:
        img = cv2.imread(str(img_path))
        if img is None:
            raise ValueError("unreadable")
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        # Scale factor for small images
        min_size = max(20, min(w, h) // 10)
        faces = get_cascade().detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=4, minSize=(min_size, min_size)
        )
        count = len(faces) if isinstance(faces, np.ndarray) else 0
        return {
            "cover_has_face": int(count > 0),
            "cover_face_count": int(count),
        }
    except Exception:
        return {"cover_has_face": None, "cover_face_count": None}


# ── Layer 3: Vision API (Claude Haiku or Kimi Vision) ─────────────────────────

VISION_PROMPT = """分析这张小红书封面图片。
只返回以下格式的JSON，不要解释，不要Markdown：
{
  "has_text_overlay": true/false,
  "text_prominence": 0.0-1.0 (0=无文字, 1=文字占主导),
  "composition_score": 0.0-1.0 (构图质量),
  "aesthetic_score": 0.0-1.0 (整体视觉吸引力),
  "emotion_intensity": 0.0-1.0 (0=平静, 1=强烈情绪),
  "visual_clarity": 0.0-1.0 (0=杂乱, 1=简洁清晰)
}"""

KIMI_MODEL = "moonshot-v1-8k-vision-preview"
KIMI_API_URL = "https://api.moonshot.cn/v1/chat/completions"


def image_to_b64(img_path: Path) -> tuple[str, str]:
    with open(img_path, "rb") as f:
        data = f.read()
    b64 = base64.standard_b64encode(data).decode("utf-8")
    # Detect actual format from magic bytes (XHS serves WebP despite .jpg extension)
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        media_type = "image/webp"
    elif data[:3] == b"\xff\xd8\xff":
        media_type = "image/jpeg"
    elif data[:8] == b"\x89PNG\r\n\x1a\n":
        media_type = "image/png"
    else:
        media_type = "image/jpeg"
    return b64, media_type


def _parse_vision_response(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    data = json.loads(raw)
    return {
        "cover_has_text": int(bool(data.get("has_text_overlay", False))),
        "cover_text_prominence": float(data.get("text_prominence", 0)),
        "cover_composition_score": float(data.get("composition_score", 0.5)),
        "cover_aesthetic_score": float(data.get("aesthetic_score", 0.5)),
        "cover_emotion_intensity": float(data.get("emotion_intensity", 0.5)),
        "cover_visual_clarity": float(data.get("visual_clarity", 0.5)),
    }


_VISION_NULL = {
    "cover_has_text": None, "cover_text_prominence": None,
    "cover_composition_score": None, "cover_aesthetic_score": None,
    "cover_emotion_intensity": None, "cover_visual_clarity": None,
}


async def call_claude_vision(client, img_path: Path) -> dict:
    try:
        b64, media_type = await asyncio.get_event_loop().run_in_executor(
            None, image_to_b64, img_path
        )
        resp = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: client.messages.create(
                model=HAIKU_MODEL,
                max_tokens=256,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {
                            "type": "base64", "media_type": media_type, "data": b64
                        }},
                        {"type": "text", "text": VISION_PROMPT},
                    ],
                }],
            )
        )
        return _parse_vision_response(resp.content[0].text)
    except Exception:
        return dict(_VISION_NULL)


async def call_kimi_vision(session, img_path: Path) -> dict:
    import aiohttp
    try:
        b64, media_type = await asyncio.get_event_loop().run_in_executor(
            None, image_to_b64, img_path
        )
        payload = {
            "model": KIMI_MODEL,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {
                        "url": f"data:{media_type};base64,{b64}"
                    }},
                    {"type": "text", "text": VISION_PROMPT},
                ],
            }],
            "max_tokens": 256,
        }
        async with session.post(KIMI_API_URL, json=payload) as resp:
            data = await resp.json()
            raw = data["choices"][0]["message"]["content"]
            return _parse_vision_response(raw)
    except Exception:
        return dict(_VISION_NULL)


async def run_vision_batch(
    img_paths: list[Path],
    done_ids: set,
    backend: str = "kimi",
) -> dict[str, dict]:
    """Process all images through vision API with concurrency + resume."""
    pending = [p for p in img_paths if p.stem not in done_ids]
    total = len(pending)
    results: dict[str, dict] = {}
    sem = asyncio.Semaphore(VISION_CONCURRENCY)

    if backend == "kimi":
        api_key = os.environ.get("MOONSHOT_API_KEY")
        if not api_key:
            print("  MOONSHOT_API_KEY not set — skipping vision layer")
            return {}
        cost_est = total * 0.001
        print(f"  Kimi Vision: {total:,} images (est. cost ~¥{cost_est:.0f})")

        import aiohttp
        headers = {"Authorization": f"Bearer {api_key}"}
        connector = aiohttp.TCPConnector(limit=VISION_CONCURRENCY)

        async def process_one_kimi(path: Path, sess) -> tuple[str, dict]:
            async with sem:
                feats = await call_kimi_vision(sess, path)
                return path.stem, feats

        async with aiohttp.ClientSession(headers=headers, connector=connector) as sess:
            tasks = [asyncio.create_task(process_one_kimi(p, sess)) for p in pending]
            completed = 0
            with open(VISION_CACHE, "a") as cache_f:
                for coro in asyncio.as_completed(tasks):
                    note_id, feats = await coro
                    results[note_id] = feats
                    cache_f.write(json.dumps({"note_id": note_id, **feats}) + "\n")
                    completed += 1
                    if completed % VISION_BATCH == 0:
                        cache_f.flush()
                        print(f"    vision: {completed:,}/{total:,} done")

    else:  # claude
        import anthropic as _anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print("  ANTHROPIC_API_KEY not set — skipping vision layer")
            return {}
        client = _anthropic.Anthropic(api_key=api_key)
        print(f"  Claude Haiku Vision: {total:,} images (est. cost ~${total*0.002:.0f})")

        async def process_one_claude(path: Path) -> tuple[str, dict]:
            async with sem:
                feats = await call_claude_vision(client, path)
                return path.stem, feats

        tasks = [asyncio.create_task(process_one_claude(p)) for p in pending]
        completed = 0
        with open(VISION_CACHE, "a") as cache_f:
            for coro in asyncio.as_completed(tasks):
                note_id, feats = await coro
                results[note_id] = feats
                cache_f.write(json.dumps({"note_id": note_id, **feats}) + "\n")
                completed += 1
                if completed % VISION_BATCH == 0:
                    cache_f.flush()
                    print(f"    vision: {completed:,}/{total:,} done")

    return results


def load_vision_cache() -> dict[str, dict]:
    """Load previously computed vision features from cache."""
    cache: dict[str, dict] = {}
    if VISION_CACHE.exists():
        with open(VISION_CACHE) as f:
            for line in f:
                try:
                    d = json.loads(line.strip())
                    nid = d.pop("note_id")
                    cache[nid] = d
                except Exception:
                    continue
    return cache


# ── Main pipeline ──────────────────────────────────────────────────────────────

def run(no_vision: bool, limit: int | None, backend: str = "kimi"):
    # Load image list from metadata (preserves order + liked_count)
    meta: dict[str, dict] = {}
    with open(METADATA_PATH) as f:
        for line in f:
            d = json.loads(line.strip())
            meta[d["note_id"]] = {"liked_count": d["liked_count"],
                                  "channel": d["channel"]}

    img_paths = sorted(COVER_DIR.glob("*.jpg"))
    if limit:
        img_paths = img_paths[:limit]

    total = len(img_paths)
    print(f"Cover images to process: {total:,}")

    # ── Layer 1 + 2: Deterministic (fast batch) ────────────────────────────────
    print("\n[Layer 1+2] Deterministic + face detection...")
    det_rows: list[dict] = []
    for i, path in enumerate(img_paths):
        row = {"note_id": path.stem}
        row.update(extract_deterministic(path))
        row.update(detect_faces(path))
        if path.stem in meta:
            row["liked_count"] = meta[path.stem]["liked_count"]
            row["channel"] = meta[path.stem]["channel"]
        det_rows.append(row)
        if (i + 1) % 1000 == 0:
            print(f"  {i+1:,}/{total:,}")

    df_det = pd.DataFrame(det_rows).set_index("note_id")
    print(f"  Done. Shape: {df_det.shape}")

    # ── Layer 3: Vision API ────────────────────────────────────────────────────
    if no_vision:
        print("\n[Layer 3] Skipped (--no-vision)")
        df_vision = pd.DataFrame()
    else:
        print(f"\n[Layer 3] Vision features (backend={backend})...")
        cached = load_vision_cache()
        cached_ids = set(cached.keys())
        print(f"  Already cached: {len(cached_ids):,}")

        vision_results = asyncio.run(
            run_vision_batch(img_paths, done_ids=cached_ids, backend=backend)
        )
        cached.update(vision_results)

        vision_rows = [{"note_id": k, **v} for k, v in cached.items()
                       if k in {p.stem for p in img_paths}]
        df_vision = pd.DataFrame(vision_rows).set_index("note_id")
        print(f"  Done. Shape: {df_vision.shape}")

    # ── Merge & save ───────────────────────────────────────────────────────────
    if not df_vision.empty:
        df = df_det.join(df_vision, how="left")
    else:
        df = df_det

    df.to_parquet(FEATURES_OUT)
    print(f"\n{'='*55}")
    print(f"Saved → {FEATURES_OUT}")
    print(f"Shape  : {df.shape[0]:,} rows × {df.shape[1]} features")
    print(f"\nFeature columns:")
    for col in df.columns:
        non_null = df[col].notna().sum()
        sample = df[col].dropna().iloc[0] if non_null > 0 else "N/A"
        print(f"  {col:<30} {non_null:>6,} non-null  sample={sample!r:.20}")
    print(f"{'='*55}")


def main():
    parser = argparse.ArgumentParser(description="Extract cover features")
    parser.add_argument("--no-vision", action="store_true",
                        help="Skip vision layer (layers 1+2 only)")
    parser.add_argument("--backend", choices=["kimi", "claude"], default="kimi",
                        help="Vision API backend (default: kimi)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process only first N images (for testing)")
    parser.add_argument("--run-id", default="v1", metavar="ID",
                        help="Run identifier, must match download --run-id (default: v1)")
    args = parser.parse_args()
    set_run_paths(args.run_id)
    run(no_vision=args.no_vision, limit=args.limit, backend=args.backend)


if __name__ == "__main__":
    main()
