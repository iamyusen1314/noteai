"""Deterministic cover composition with retained photos and exact text.

The image model may supply a decorative background, never replacement pixels
for the owner's real subject. V1 keeps text outside the retained photograph;
v2 supports up to three real photos and type layers while protecting projected
subjects. Both use pinned OFL fonts and a clean base for free text re-exports.
"""
from __future__ import annotations

import hashlib
import io
import math
from pathlib import Path
from functools import lru_cache
import re
import uuid

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageStat

WIDTH, HEIGHT = 1776, 2368
MAX_IMAGE_BYTES = 10 * 1024 * 1024
FONT_PATH = Path(__file__).resolve().parents[1] / "assets/fonts/cover/SourceHanSansSC-Bold.otf"
FONT_SHA256 = "df2b90f5bcc6d01dfc964cec5f6d535d6b6aebd26ed7fd79a9c1b3f2112fcb6b"
RENDERER_VERSION = "noteai-cover-renderer-v1"
RENDERER_V2_VERSION = "noteai-cover-renderer-v2"
MAX_TEXT_LINES = 4
TEXT_PADDING = 8
FONT_CATALOG = {
    "SourceHanSansSC-Bold": {"path": FONT_PATH, "sha256": FONT_SHA256},
    "SourceHanSerifSC-Regular": {
        "path": FONT_PATH.parent / "SourceHanSerifSC-Regular.otf",
        "sha256": "78aa7a328fd974df2d688c8a9fd74a33d8334dfa84ab24d9d11efb2ffc464117",
    },
}
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


class CoverRenderError(ValueError):
    pass


def _error(code):
    raise CoverRenderError(code)


def read_image(payload: bytes, *, exact_size=None) -> Image.Image:
    if not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_IMAGE_BYTES:
        _error("COVER_IMAGE_BYTES_INVALID")
    try:
        with Image.open(io.BytesIO(payload)) as source:
            if source.format not in {"JPEG", "PNG", "WEBP"}:
                _error("COVER_IMAGE_FORMAT_INVALID")
            if not 196 <= source.width * source.height <= 36_000_000:
                _error("COVER_IMAGE_DIMENSIONS_INVALID")
            if exact_size is not None and source.size != exact_size:
                _error("COVER_IMAGE_SIZE_MISMATCH")
            source.verify()
        with Image.open(io.BytesIO(payload)) as source:
            return ImageOps.exif_transpose(source).convert("RGB")
    except CoverRenderError:
        raise
    except (OSError, ValueError, Image.DecompressionBombError):
        _error("COVER_IMAGE_INVALID")


def _rect(value, name):
    if (not isinstance(value, (list, tuple)) or len(value) != 4
            or any(isinstance(n, bool) or not isinstance(n, (int, float))
                   or not _finite(n) or not 0 <= n <= 1 for n in value)):
        _error("COVER_" + name.upper() + "_INVALID")
    x0, y0, x1, y1 = map(float, value)
    if x1 <= x0 or y1 <= y0:
        _error("COVER_" + name.upper() + "_INVALID")
    return [x0, y0, x1, y1]


def _pixels(rect):
    return tuple(round(n * (WIDTH if i % 2 == 0 else HEIGHT)) for i, n in enumerate(rect))


def _intersects(left, right):
    return left[0] < right[2] and right[0] < left[2] and left[1] < right[3] and right[1] < left[3]


def _contains(outer, inner):
    return outer[0] <= inner[0] and outer[1] <= inner[1] and outer[2] >= inner[2] and outer[3] >= inner[3]


def _color(value):
    if not isinstance(value, str) or not _COLOR.fullmatch(value):
        _error("COVER_COLOR_INVALID")
    return value.upper()


@lru_cache(maxsize=1)
def _font_file():
    if not FONT_PATH.is_file() or hashlib.sha256(FONT_PATH.read_bytes()).hexdigest() != FONT_SHA256:
        _error("COVER_FONT_UNAVAILABLE")
    return str(FONT_PATH)


@lru_cache(maxsize=64)
def _font(size):
    try:
        return ImageFont.truetype(_font_file(), size)
    except OSError:
        _error("COVER_FONT_UNAVAILABLE")


def validate_text(text):
    if (not isinstance(text, str) or not text.strip() or len(text) > 64
            or any(ord(char) < 32 and char not in "\n\t" for char in text)):
        _error("COVER_TEXT_INVALID")
    font = _font(48)
    missing = bytes(font.getmask(chr(0x10FFFF)))
    for char in text:
        if not char.isspace() and bytes(font.getmask(char)) == missing:
            _error("COVER_TEXT_GLYPH_UNSUPPORTED")
    return text.strip()


def validate_plan(plan: dict) -> dict:
    if not isinstance(plan, dict):
        _error("COVER_DESIGN_INVALID")
    if plan.get("schema_version") == 2:
        return _validate_v2_plan(plan)
    if "schema_version" in plan and (type(plan["schema_version"]) is not int or plan["schema_version"] != 1):
        _error("COVER_DESIGN_VERSION_INVALID")
    route = plan.get("route")
    if route not in {"photo", "seedream_background"}:
        _error("COVER_ROUTE_INVALID")
    crop = _rect(plan.get("crop"), "crop")
    subject = _rect(plan.get("subject_bbox"), "subject")
    photo = _rect(plan.get("photo_bbox"), "photo")
    text = _rect(plan.get("text_bbox"), "text")
    if not _contains(crop, subject):
        _error("COVER_SUBJECT_CROPPED")
    if (photo[2] - photo[0]) * (photo[3] - photo[1]) < .35:
        _error("COVER_PHOTO_TOO_SMALL")
    if _intersects(photo, text):
        _error("COVER_TEXT_OVER_SUBJECT")
    size = plan.get("font_size")
    if type(size) is not int or not 48 <= size <= 160:
        _error("COVER_FONT_SIZE_INVALID")
    if plan.get("align") not in {"left", "center"}:
        _error("COVER_TEXT_ALIGN_INVALID")
    return {
        "route": route, "source_ref": plan.get("source_ref"), "crop": crop,
        "subject_bbox": subject, "photo_bbox": photo, "text_bbox": text,
        "text": validate_text(plan.get("text")), "font_size": size, "align": plan["align"],
        "background_color": _color(plan.get("background_color")),
        "text_color": _color(plan.get("text_color")),
        "panel_color": _color(plan.get("panel_color", plan.get("background_color"))),
    }


def _png(image):
    stream = io.BytesIO()
    image.save(stream, format="PNG", optimize=True)
    payload = stream.getvalue()
    if len(payload) > MAX_IMAGE_BYTES:
        _error("COVER_OUTPUT_TOO_LARGE")
    return payload


def compose_base(source: bytes, plan: dict, *, background: bytes | None = None) -> tuple[bytes, dict]:
    if isinstance(plan, dict) and plan.get("schema_version") == 2:
        safe = validate_plan(plan)
        if background is not None or len(safe["photos"]) != 1:
            _error("COVER_SOURCES_REQUIRED")
        return compose_sources([{"media_ref": safe["photos"][0]["source_ref"], "payload": source}], safe)
    safe = validate_plan(plan)
    photo = read_image(source)
    if background is None:
        canvas = Image.new("RGB", (WIDTH, HEIGHT), safe["background_color"])
    else:
        # Heavy blur and a solid wash turn model pixels into nonfactual decor.
        # The real subject is then pasted from the original source, never AI.
        decor = read_image(background, exact_size=(WIDTH, HEIGHT)).filter(ImageFilter.GaussianBlur(54))
        canvas = Image.blend(decor, Image.new("RGB", (WIDTH, HEIGHT), safe["background_color"]), .78)
    cx0, cy0, cx1, cy1 = safe["crop"]
    crop_pixels = (math.floor(cx0 * photo.width), math.floor(cy0 * photo.height),
                   math.ceil(cx1 * photo.width), math.ceil(cy1 * photo.height))
    cropped = photo.crop(crop_pixels)
    target = _pixels(safe["photo_bbox"])
    fitted = ImageOps.contain(cropped, (target[2] - target[0], target[3] - target[1]), Image.Resampling.LANCZOS)
    origin = (target[0] + (target[2] - target[0] - fitted.width) // 2,
              target[1] + (target[3] - target[1] - fitted.height) // 2)
    canvas.paste(fitted, origin)
    # Keep the base entirely free of typography/panels. Every later export
    # paints only its current panel, so moving text leaves no old panel behind.
    layout = {
        **safe, "width": WIDTH, "height": HEIGHT, "renderer_version": RENDERER_VERSION,
        "font_id": "SourceHanSansSC-Bold", "font_sha256": FONT_SHA256,
        "source_sha256": hashlib.sha256(source).hexdigest(), "photo_pixels": [
            origin[0], origin[1], origin[0] + fitted.width, origin[1] + fitted.height],
        "crop_pixels": list(crop_pixels),
    }
    return _png(canvas), layout


def _luminance(color):
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    channels = [n / 12.92 if n <= .04045 else ((n + .055) / 1.055) ** 2.4 for n in channels]
    return sum(n * weight for n, weight in zip(channels, (.2126, .7152, .0722)))


def _lines(text, font, available_width):
    result = []
    for paragraph in text.split("\n"):
        if not paragraph:
            result.append("")
            continue
        current = ""
        for char in paragraph:
            if current and font.getlength(current + char) > available_width:
                result.append(current)
                current = char
            else:
                current += char
        result.append(current)
    return result


def render_text(base: bytes, layout: dict, *, text: str | None = None,
                lines: list[str] | None = None, position: list[float] | None = None) -> tuple[bytes, dict]:
    """Re-export text, line breaks or a safe position without any model call."""
    if isinstance(layout, dict) and layout.get("schema_version") == 2:
        return _render_v2(base, layout, text=text, lines=lines, position=position)
    safe = validate_plan({**layout, **({"text": text} if text is not None else {})})
    if position is not None:
        if not isinstance(position, (list, tuple)) or len(position) != 2:
            _error("COVER_TEXT_POSITION_INVALID")
        old = safe["text_bbox"]
        safe["text_bbox"] = _rect([position[0], position[1],
            position[0] + old[2] - old[0], position[1] + old[3] - old[1]], "text")
        if _intersects(safe["text_bbox"], safe["photo_bbox"]):
            _error("COVER_TEXT_OVER_SUBJECT")
    if lines is not None:
        if (not isinstance(lines, list) or not 1 <= len(lines) <= 4
                or any(not isinstance(line, str) for line in lines)
                or "".join("".join(lines).split()) != "".join(safe["text"].split())):
            _error("COVER_LINEBREAK_CONTENT_MISMATCH")
        safe["text"] = validate_text("\n".join(lines))
    canvas = read_image(base, exact_size=(WIDTH, HEIGHT))
    draw = ImageDraw.Draw(canvas)
    # Repaint only the current text panel; base is always the retained no-text
    # artifact so repeated edits cannot accumulate old text.
    box = _pixels(safe["text_bbox"])
    padding = 24
    width, height = box[2] - box[0] - padding * 2, box[3] - box[1] - padding * 2
    if width < 96 or height < 72:
        _error("COVER_TEXT_BOX_TOO_SMALL")
    text_lines, selected_font = None, None
    for size in range(safe["font_size"], 47, -2):
        font = _font(size)
        candidates = _lines(safe["text"], font, width)
        line_height = math.ceil(size * 1.30)
        if len(candidates) <= 4 and line_height * len(candidates) <= height and all(font.getlength(line) <= width for line in candidates):
            text_lines, selected_font = candidates, font
            break
    if text_lines is None:
        _error("COVER_TEXT_OVERFLOW")
    dark, light = sorted((_luminance(safe["text_color"]), _luminance(safe["panel_color"])))
    text_color = safe["text_color"]
    if (light + .05) / (dark + .05) < 4.5:
        # Deterministic local contrast correction; never a new paid render.
        text_color = "#111111" if _luminance(safe["panel_color"]) > .3 else "#FFFFFF"
    draw.rectangle(box, fill=safe["panel_color"])
    line_height = math.ceil(selected_font.size * 1.30)
    y = box[1] + (box[3] - box[1] - line_height * len(text_lines)) // 2
    text_pixels = []
    for line in text_lines:
        x = box[0] + padding if safe["align"] == "left" else box[0] + (box[2] - box[0] - selected_font.getlength(line)) / 2
        bbox = draw.textbbox((x, y), line, font=selected_font, anchor="lt")
        if not _contains(box, bbox):
            _error("COVER_TEXT_OVERFLOW")
        draw.text((x, y), line, font=selected_font, fill=text_color, anchor="lt")
        text_pixels.append(list(bbox))
        y += line_height
    result_layout = {**layout, **safe, "text_color": text_color, "font_size": selected_font.size,
                     "rendered_lines": text_lines, "text_pixels": text_pixels}
    return _png(canvas), result_layout


def validate_artifact(payload: bytes, layout: dict) -> dict:
    if isinstance(layout, dict) and layout.get("schema_version") == 2:
        return _validate_v2_artifact(payload, layout)
    image = read_image(payload, exact_size=(WIDTH, HEIGHT))
    safe = validate_plan(layout)
    box = _pixels(safe["text_bbox"])
    if (layout.get("font_sha256") != FONT_SHA256 or not layout.get("rendered_lines")
            or "".join("".join(layout["rendered_lines"]).split()) != "".join(safe["text"].split())
            or any(not _contains(box, bbox) for bbox in layout.get("text_pixels", []))):
        _error("COVER_ARTIFACT_TEXT_INVALID")
    image.close()
    return {"valid": True, "width": WIDTH, "height": HEIGHT, "content_type": "image/png",
            "sha256": hashlib.sha256(payload).hexdigest(), "size_bytes": len(payload),
            "deterministic_checks": ["file", "dimensions", "exact_text", "glyphs", "overflow", "subject_box", "text_photo_separation"]}


def _finite(value):
    try:
        return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
    except OverflowError:
        return False


def design_capabilities():
    """The design prompt consumes this catalog instead of inventing effects."""
    return {"schema_version": 2, "route": "photo", "width": WIDTH, "height": HEIGHT,
            "photo_count": [1, 3], "text_layer_count": [1, 3],
            "font_ids": list(FONT_CATALOG), "font_size": [48, 260],
            "align": ["left", "center", "right"], "line_height": [1, 1.6],
            "stroke_width": [0, 8], "panel_opacity": [0, 1],
            "effects": ["stroke", "solid_panel"], "coordinates": "normalized_xyxy",
            "text_layout": {"max_rendered_lines_per_layer": MAX_TEXT_LINES,
                            "max_explicit_line_breaks": MAX_TEXT_LINES - 1,
                            "padding_px": TEXT_PADDING, "padding_adds_stroke_width": True,
                            "auto_wrap": True, "font_size_is_fixed": True,
                            "fit_checks": ["advance_width", "actual_glyph_ink_with_stroke",
                                           "ink_inside_bbox", "no_overlapping_line_ink"]},
            "text_contract": "top text equals newline-joined layers; only newlines may differ"}


def _source_ref(value):
    try:
        if not isinstance(value, str) or str(uuid.UUID(value)) != value:
            raise ValueError
    except (ValueError, AttributeError):
        _error("COVER_SOURCE_REF_INVALID")
    return value


def _plain(text):
    return text.replace("\n", "")


def _v2_text(text):
    if (not isinstance(text, str) or not text.strip() or len(_plain(text)) > 64 or text.count("\n") > 11
            or any(ord(c) < 32 and c != "\n" for c in text)):
        _error("COVER_TEXT_INVALID")
    # Do not strip, normalize spaces, or silently replace the approved wording.
    return text


def _v2_font_file(font_id):
    item = FONT_CATALOG.get(font_id)
    if item is None:
        _error("COVER_FONT_ID_INVALID")
    path = item["path"]
    try:
        available = path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
    except OSError:
        available = False
    if not available:
        _error("COVER_FONT_UNAVAILABLE")
    return str(path)


@lru_cache(maxsize=8)
def _v2_face(path, size):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        _error("COVER_FONT_UNAVAILABLE")


def _v2_font(font_id, size):
    return _v2_face(_v2_font_file(font_id), size)


def _v2_glyphs(text, font_id):
    font = _v2_font(font_id, 48)
    missing = bytes(font.getmask(chr(0x10FFFF)))
    if any(not c.isspace() and bytes(font.getmask(c)) == missing for c in text):
        _error("COVER_TEXT_GLYPH_UNSUPPORTED")


def _validate_v2_plan(plan):
    if type(plan.get("schema_version")) is not int or plan.get("route") != "photo":
        _error("COVER_ROUTE_INVALID")
    photos, layers = plan.get("photos"), plan.get("text_layers")
    if not isinstance(photos, list) or not 1 <= len(photos) <= 3:
        _error("COVER_PHOTOS_INVALID")
    if not isinstance(layers, list) or not 1 <= len(layers) <= 3:
        _error("COVER_TEXT_LAYERS_INVALID")
    safe_photos, refs = [], set()
    for photo in photos:
        if not isinstance(photo, dict):
            _error("COVER_PHOTOS_INVALID")
        ref = _source_ref(photo.get("source_ref"))
        if ref in refs:
            _error("COVER_SOURCE_DUPLICATED")
        refs.add(ref)
        crop = _rect(photo.get("crop"), "crop")
        subject = _rect(photo.get("subject_bbox"), "subject")
        bbox = _rect(photo.get("bbox"), "photo")
        if not _contains(crop, subject):
            _error("COVER_SUBJECT_CROPPED")
        if min(_pixels(bbox)[2] - _pixels(bbox)[0], _pixels(bbox)[3] - _pixels(bbox)[1]) < 2:
            _error("COVER_PHOTO_TOO_SMALL")
        safe_photos.append({"source_ref": ref, "crop": crop, "subject_bbox": subject, "bbox": bbox})
    safe_layers = []
    for layer in layers:
        if not isinstance(layer, dict):
            _error("COVER_TEXT_LAYERS_INVALID")
        text = _v2_text(layer.get("text"))
        font_id, size = layer.get("font_id"), layer.get("font_size")
        if not isinstance(font_id, str) or font_id not in FONT_CATALOG:
            _error("COVER_FONT_ID_INVALID")
        if type(size) is not int or not 48 <= size <= 260:
            _error("COVER_FONT_SIZE_INVALID")
        if layer.get("align") not in {"left", "center", "right"}:
            _error("COVER_TEXT_ALIGN_INVALID")
        height, stroke, opacity = layer.get("line_height", 1.15), layer.get("stroke_width", 0), layer.get("panel_opacity", 0)
        if not _finite(height) or not 1 <= height <= 1.6:
            _error("COVER_LINE_HEIGHT_INVALID")
        if type(stroke) is not int or not 0 <= stroke <= 8:
            _error("COVER_STROKE_INVALID")
        if not _finite(opacity) or not 0 <= opacity <= 1:
            _error("COVER_PANEL_OPACITY_INVALID")
        _v2_glyphs(text, font_id)
        safe_layers.append({"text": text, "bbox": _rect(layer.get("bbox"), "text"),
            "font_id": font_id, "font_size": size, "align": layer["align"],
            "color": _color(layer.get("color")), "line_height": float(height),
            "stroke_width": stroke, "stroke_color": _color(layer.get("stroke_color", "#111111")),
            "panel_color": _color(layer.get("panel_color", "#FFFFFF")), "panel_opacity": float(opacity)})
    text = _v2_text(plan.get("text"))
    if _plain(text) != _plain("\n".join(layer["text"] for layer in safe_layers)):
        _error("COVER_LAYER_TEXT_MISMATCH")
    return {"schema_version": 2, "route": "photo", "text": "\n".join(p["text"] for p in safe_layers),
            "photos": safe_photos, "text_layers": safe_layers,
            "background_color": _color(plan.get("background_color"))}


def _photo_geometry(photo, source_size):
    if (not isinstance(source_size, (list, tuple)) or len(source_size) != 2
            or any(type(n) is not int or n < 1 for n in source_size)
            or not 196 <= source_size[0] * source_size[1] <= 36_000_000):
        _error("COVER_SOURCE_DIMENSIONS_INVALID")
    width, height = source_size
    crop = photo["crop"]
    cp = [math.floor(crop[0] * width), math.floor(crop[1] * height),
          math.ceil(crop[2] * width), math.ceil(crop[3] * height)]
    target = _pixels(photo["bbox"])
    cw, ch, tw, th = cp[2] - cp[0], cp[3] - cp[1], target[2] - target[0], target[3] - target[1]
    if cw / ch > tw / th:
        fw, fh = tw, round(ch / cw * tw)
    else:
        fw, fh = round(cw / ch * th), th
    if fw < 1 or fh < 1:
        _error("COVER_PHOTO_TOO_SMALL")
    x, y = target[0] + (tw - fw) // 2, target[1] + (th - fh) // 2
    subject = photo["subject_bbox"]
    projected = [math.floor(x + (subject[0] * width - cp[0]) * fw / cw),
                 math.floor(y + (subject[1] * height - cp[1]) * fh / ch),
                 math.ceil(x + (subject[2] * width - cp[0]) * fw / cw),
                 math.ceil(y + (subject[3] * height - cp[1]) * fh / ch)]
    return {"source_size": list(source_size), "crop_pixels": cp,
            "photo_pixels": [x, y, x + fw, y + fh], "subject_pixels": projected}


def _union(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]


def _v2_layer_geometry(layer):
    font = _v2_font(layer["font_id"], layer["font_size"])
    box, stroke = _pixels(layer["bbox"]), layer["stroke_width"]
    # Padding also keeps a stroked glyph's actual ink within its declared box.
    padding = TEXT_PADDING + stroke
    width = box[2] - box[0] - padding * 2
    height = box[3] - box[1] - padding * 2
    if width <= 0 or height <= 0:
        _error("COVER_TEXT_BOX_TOO_SMALL")
    lines = _lines(layer["text"], font, width - stroke * 2)
    if len(lines) > MAX_TEXT_LINES:
        _error("COVER_TEXT_OVERFLOW")
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    line_step = math.ceil(layer["font_size"] * layer["line_height"])
    pixels, origins = [], []
    for index, line in enumerate(lines):
        length = font.getlength(line)
        if length > width - stroke * 2:
            _error("COVER_TEXT_OVERFLOW")
        x = box[0] + padding
        if layer["align"] == "center":
            x = box[0] + (box[2] - box[0] - length) / 2
        elif layer["align"] == "right":
            x = box[2] - padding - length
        x = round(x)
        y = box[1] + padding + index * line_step
        ink = list(draw.textbbox((x, y), line, font=font, anchor="lt", stroke_width=stroke))
        if not _contains(box, ink):
            _error("COVER_TEXT_OVERFLOW")
        if line:
            if any(_intersects(ink, old) for old in pixels):
                _error("COVER_TEXT_OVERFLOW")
            pixels.append(ink)
        origins.append((x, y))
    if not pixels:
        _error("COVER_TEXT_INVALID")
    # Actual ink and any visible panel, not the entire text allocation, protect subjects.
    paint = [list(box)] if layer["panel_opacity"] > 0 else pixels
    return {"font_sha256": FONT_CATALOG[layer["font_id"]]["sha256"],
            "rendered_lines": lines, "text_pixels": pixels, "paint_pixels": paint}, origins


def _v2_geometry(safe, photos):
    actual_photos = []
    for expected, actual in zip(safe["photos"], photos):
        geometry = _photo_geometry(expected, actual.get("source_size"))
        if any(_intersects(geometry["photo_pixels"], old["subject_pixels"]) for old in actual_photos):
            _error("COVER_PHOTO_OVER_SUBJECT")
        actual_photos.append({**expected, **geometry, "source_sha256": actual.get("source_sha256")})
    layers = []
    prior_paint = []
    for layer in safe["text_layers"]:
        geometry, _ = _v2_layer_geometry(layer)
        paint = geometry["paint_pixels"]
        if any(_intersects(ink, photo["subject_pixels"]) for ink in paint for photo in actual_photos):
            _error("COVER_TEXT_OVER_SUBJECT")
        if any(_intersects(ink, old) for ink in paint for old in prior_paint):
            _error("COVER_TEXT_LAYERS_OVERLAP")
        prior_paint.extend(paint)
        layers.append({**layer, **geometry})
    group = _union([p["bbox"] for p in layers])
    return {**safe, "photos": actual_photos, "text_layers": layers,
            "width": WIDTH, "height": HEIGHT, "renderer_version": RENDERER_V2_VERSION,
            "text_bbox": group, "rendered_lines": [line for p in layers for line in p["rendered_lines"]],
            "text_pixels": [box for p in layers for box in p["text_pixels"]]}


def compose_sources(sources: list[dict], plan: dict) -> tuple[bytes, dict]:
    """Paste 1–3 real images; no synthesis, stretching, or model call."""
    safe = validate_plan(plan)
    if safe.get("schema_version") != 2 or not isinstance(sources, list):
        _error("COVER_SOURCES_INVALID")
    by_ref = {}
    for source in sources:
        if not isinstance(source, dict):
            _error("COVER_SOURCES_INVALID")
        ref = _source_ref(source.get("media_ref"))
        if ref in by_ref:
            _error("COVER_SOURCES_INVALID")
        by_ref[ref] = source
    canvas = Image.new("RGB", (WIDTH, HEIGHT), safe["background_color"])
    photos, source_hashes = [], {}
    for photo in safe["photos"]:
        source = by_ref.get(photo["source_ref"])
        if source is None:
            _error("COVER_SOURCE_MISSING")
        payload = source.get("payload")
        image = read_image(payload)
        sha = hashlib.sha256(payload).hexdigest()
        if source.get("sha256") is not None and source["sha256"] != sha:
            _error("COVER_SOURCE_HASH_MISMATCH")
        geometry = _photo_geometry(photo, image.size)
        cp, fp = geometry["crop_pixels"], geometry["photo_pixels"]
        fitted = image.crop(cp).resize((fp[2] - fp[0], fp[3] - fp[1]), Image.Resampling.LANCZOS)
        canvas.paste(fitted, (fp[0], fp[1]))
        photos.append({**geometry, "source_sha256": sha})
        source_hashes[photo["source_ref"]] = sha
        image.close()
    layout = _v2_geometry(safe, photos)
    base = _png(canvas)
    return base, {**layout, "source_hashes": source_hashes, "base_sha256": hashlib.sha256(base).hexdigest()}


def validate_layout_metadata(layout: dict) -> dict:
    """Recompute stored geometry; this is not proof of source ownership/storage."""
    if not isinstance(layout, dict) or layout.get("schema_version") != 2:
        # Existing v1 storage keeps its original contract.
        return validate_plan(layout)
    safe = validate_plan(layout)
    photos = layout.get("photos")
    calculated = _v2_geometry(safe, photos)
    hashes = layout.get("source_hashes")
    if not isinstance(hashes, dict) or set(hashes) != {p["source_ref"] for p in photos}:
        _error("COVER_LAYOUT_SOURCE_INVALID")
    for photo in photos:
        sha = photo.get("source_sha256")
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha) or hashes[photo["source_ref"]] != sha:
            _error("COVER_LAYOUT_SOURCE_INVALID")
    if layout.get("base_sha256") is None or not re.fullmatch(r"[0-9a-f]{64}", str(layout["base_sha256"])):
        _error("COVER_BASE_HASH_INVALID")
    if "final_sha256" in layout and (not isinstance(layout["final_sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", layout["final_sha256"])):
        _error("COVER_ARTIFACT_HASH_MISMATCH")
    for key in ("photos", "text_layers", "width", "height", "renderer_version", "text_bbox", "rendered_lines", "text_pixels"):
        if layout.get(key) != calculated[key]:
            _error("COVER_LAYOUT_METADATA_INVALID")
    return {**calculated, "source_hashes": dict(hashes), "base_sha256": layout["base_sha256"],
            **({"final_sha256": layout["final_sha256"]} if "final_sha256" in layout else {})}


def _redistribute_v2(safe, new_text):
    """Preserve typographic hierarchy while replacing every character exactly once."""
    new_text = _v2_text(new_text)
    remaining, result = new_text, []
    for index, layer in enumerate(safe["text_layers"]):
        if index == len(safe["text_layers"]) - 1:
            part, remaining = remaining, ""
        else:
            count, end = len(_plain(layer["text"])), 0
            while end < len(remaining) and count:
                count -= remaining[end] != "\n"
                end += 1
            part, remaining = remaining[:end], remaining[end:]
            remaining = remaining.lstrip("\n")
        # A shorter title may remove trailing layers, but never invent filler.
        if part.strip():
            result.append({**layer, "text": part.rstrip("\n")})
    if not result:
        _error("COVER_TEXT_INVALID")
    if _plain("\n".join(p["text"] for p in result)) != _plain(new_text):
        _error("COVER_LAYER_TEXT_MISMATCH")
    safe["text_layers"] = result
    safe["text"] = "\n".join(p["text"] for p in result)


def _move_v2(safe, position):
    if (not isinstance(position, (list, tuple)) or len(position) != 2
            or any(not _finite(n) for n in position)):
        _error("COVER_TEXT_POSITION_INVALID")
    group = _union([p["bbox"] for p in safe["text_layers"]])
    dx, dy = position[0] - group[0], position[1] - group[1]
    for layer in safe["text_layers"]:
        box = layer["bbox"]
        layer["bbox"] = _rect([box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy], "text")


def _v2_readable_color(canvas, layer, origins, font):
    # Inspect the actual pixels behind glyphs, including a blended panel. A
    # declared panel/background color need not be the background of this text.
    mask = Image.new("L", canvas.size)
    ink = ImageDraw.Draw(mask)
    for line, origin in zip(layer["rendered_lines"], origins):
        ink.text(origin, line, font=font, fill=255, anchor="lt")
    if mask.getbbox() is None:
        mask.close()
        _error("COVER_TEXT_NOT_VISIBLE")
    background = "#" + "".join(f"{round(value):02X}" for value in ImageStat.Stat(canvas, mask).mean)
    mask.close()

    def contrast(color):
        dark, light = sorted((_luminance(color), _luminance(background)))
        return (light + .05) / (dark + .05)

    if (contrast(layer["color"]) >= 4.5
            or layer["stroke_width"] >= 2 and contrast(layer["stroke_color"]) >= 4.5):
        return layer["color"]
    # Same bounded local correction as v1; never change wording, geometry,
    # source pixels, fonts, or trigger a model call. Persist the actual color.
    return max(("#111111", "#FFFFFF"), key=contrast)


def _render_v2(base, layout, *, text=None, lines=None, position=None):
    previous = validate_layout_metadata(layout)
    if hashlib.sha256(base).hexdigest() != previous["base_sha256"]:
        _error("COVER_BASE_HASH_MISMATCH")
    safe = validate_plan(previous)
    if text is not None:
        _redistribute_v2(safe, text)
    if lines is not None:
        if (not isinstance(lines, list) or not 1 <= len(lines) <= 12
                or any(not isinstance(line, str) or "\n" in line for line in lines)
                or "".join(lines) != _plain(safe["text"])):
            _error("COVER_LINEBREAK_CONTENT_MISMATCH")
        _redistribute_v2(safe, "\n".join(lines))
    if position is not None:
        _move_v2(safe, position)
    safe = validate_plan(safe)
    result = _v2_geometry(safe, previous["photos"])
    canvas = read_image(base, exact_size=(WIDTH, HEIGHT))
    for layer in result["text_layers"]:
        box = _pixels(layer["bbox"])
        if layer["panel_opacity"] > 0:
            # Use exact half-open pixel bounds consistently with collision checks.
            panel = Image.new("RGB", (box[2] - box[0], box[3] - box[1]), layer["panel_color"])
            canvas.paste(Image.blend(canvas.crop(box), panel, layer["panel_opacity"]), (box[0], box[1]))
        _, origins = _v2_layer_geometry(layer)
        font = _v2_font(layer["font_id"], layer["font_size"])
        readable_color = _v2_readable_color(canvas, layer, origins, font)
        if "final_sha256" in previous and readable_color != layer["color"]:
            # Free edits retain the saved typography. Reject an unreadable
            # placement before storage rather than changing an immutable style.
            canvas.close()
            _error("COVER_TEXT_CONTRAST_INVALID")
        layer["color"] = readable_color
        before_text = canvas.copy()
        draw = ImageDraw.Draw(canvas)
        for line, origin in zip(layer["rendered_lines"], origins):
            draw.text(origin, line, font=font, fill=layer["color"], anchor="lt",
                      stroke_width=layer["stroke_width"], stroke_fill=layer["stroke_color"])
        difference = ImageChops.difference(before_text, canvas)
        visible = difference.getbbox() is not None
        difference.close()
        before_text.close()
        if not visible:
            _error("COVER_TEXT_NOT_VISIBLE")
    payload = _png(canvas)
    return payload, {**layout, **result, "source_hashes": previous["source_hashes"],
                     "base_sha256": previous["base_sha256"], "final_sha256": hashlib.sha256(payload).hexdigest()}


def position_options(layout):
    """Only expose placements that pass the same actual geometry checks."""
    if layout.get("schema_version") != 2:
        safe = validate_plan(layout)
        box = safe["text_bbox"]
        return [name for name, y in (("top", .025), ("bottom", .975 - box[3] + box[1]))
                if not _intersects([box[0], y, box[2], y + box[3] - box[1]], safe["photo_bbox"])]
    previous = validate_layout_metadata(layout)
    group = previous["text_bbox"]
    result = []
    for name, y in (("top", .025), ("bottom", .975 - group[3] + group[1])):
        try:
            safe = validate_plan(previous)
            _move_v2(safe, [group[0], y])
            _v2_geometry(safe, previous["photos"])
            result.append(name)
        except CoverRenderError:
            pass
    return result


def _validate_v2_artifact(payload, layout):
    image = read_image(payload, exact_size=(WIDTH, HEIGHT))
    image.close()
    validate_layout_metadata(layout)
    sha = hashlib.sha256(payload).hexdigest()
    if layout.get("final_sha256") != sha:
        _error("COVER_ARTIFACT_HASH_MISMATCH")
    # A verified RGB PNG is the only renderer output; JPEG/WebP cannot masquerade.
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        _error("COVER_IMAGE_FORMAT_INVALID")
    with Image.open(io.BytesIO(payload)) as source:
        if source.mode != "RGB":
            _error("COVER_IMAGE_FORMAT_INVALID")
    return {"valid": True, "width": WIDTH, "height": HEIGHT, "content_type": "image/png",
            "sha256": sha, "size_bytes": len(payload), "deterministic_checks": [
                "file", "dimensions", "exact_text", "pinned_fonts", "glyphs", "overflow",
                "projected_subjects", "photo_occlusion", "layer_geometry", "base_and_final_hashes"]}
