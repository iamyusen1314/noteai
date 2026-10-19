"""Deterministic cover composition with a retained photo and exact text.

The image model may supply a decorative background, never replacement pixels
for the owner's real subject. The selected original is pasted by Pillow after
background generation; text is kept outside that photo and drawn with a pinned
OFL font. This is a small renderer, not a general-purpose image editor.
"""
from __future__ import annotations

import hashlib
import io
import math
from pathlib import Path
from functools import lru_cache
import re

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

WIDTH, HEIGHT = 1776, 2368
MAX_IMAGE_BYTES = 10 * 1024 * 1024
FONT_PATH = Path(__file__).resolve().parents[1] / "assets/fonts/cover/SourceHanSansSC-Bold.otf"
FONT_SHA256 = "df2b90f5bcc6d01dfc964cec5f6d535d6b6aebd26ed7fd79a9c1b3f2112fcb6b"
RENDERER_VERSION = "noteai-cover-renderer-v1"
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
                   or not math.isfinite(n) or not 0 <= n <= 1 for n in value)):
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
