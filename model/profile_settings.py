"""Pure validation for profile fields; no storage or external requests."""
from __future__ import annotations

import base64
import binascii
from io import BytesIO
import re
import unicodedata
import warnings


MAX_AVATAR_DATA_CHARS = 200_000
MAX_AVATAR_DIMENSION = 2048
_DATA_URL = re.compile(r"data:image/(jpeg|png|webp);base64,([A-Za-z0-9+/]+={0,2})\Z")
_FORMATS = {"jpeg": "JPEG", "png": "PNG", "webp": "WEBP"}


def normalize_nickname(value: str) -> str:
    """Trim outer spaces and NFC-normalize, then enforce 1..20 code points.

No truncation. Controls, invisible formatting and markup delimiters are rejected;
normal interior spaces, punctuation and visible Unicode names are retained.
    """
    if not isinstance(value, str) or any(
        unicodedata.category(char).startswith("C") or unicodedata.category(char) in {"Zl", "Zp"}
        or char in "<>" for char in value
    ):
        raise ValueError("nickname_invalid")
    result = unicodedata.normalize("NFC", value).strip()
    if not 1 <= len(result) <= 20 or not any(unicodedata.category(c)[0] not in {"Z", "M"} for c in result):
        raise ValueError("nickname_length_invalid")
    return result


def normalize_avatar_emoji(value: str) -> str:
    """Accept bounded symbol/emoji Unicode, including existing UI choices.

Supports ordinary symbols, variation selectors, flags, skin tones and ZWJ
sequences. This is not a versioned Unicode emoji-name catalogue.
    """
    if not isinstance(value, str):
        raise ValueError("avatar_emoji_invalid")
    result = unicodedata.normalize("NFC", value)
    if not 1 <= len(result) <= 32:
        raise ValueError("avatar_emoji_length_invalid")
    if re.fullmatch(r"[#*0-9]\ufe0f?\u20e3", result):
        return result
    if any(unicodedata.category(c) not in {"So", "Sk"} and c not in {"\ufe0e", "\ufe0f", "\u200d"} for c in result):
        raise ValueError("avatar_emoji_invalid")
    # Selectors/modifiers/joiners cannot stand alone or start a sequence.
    if (unicodedata.category(result[0]) != "So" or 0x1F3FB <= ord(result[0]) <= 0x1F3FF
            or result.endswith("\u200d") or "\u200d\u200d" in result):
        raise ValueError("avatar_emoji_invalid")
    for index, char in enumerate(result):
        if char == "\u200d" and unicodedata.category(result[index + 1]) != "So":
            raise ValueError("avatar_emoji_invalid")
    return result


def normalize_avatar_data(value: str) -> str:
    """Verify a bounded static JPEG/PNG/WebP and return metadata-free pixels.

Input and returned data URLs are each limited to 200,000 characters. Dimensions
must be 1..2048 on both axes; oversized images are rejected, never silently
resized. EXIF orientation is applied before removing EXIF/ICC/text metadata.
    """
    if not isinstance(value, str) or not 1 <= len(value) <= MAX_AVATAR_DATA_CHARS:
        raise ValueError("avatar_data_size_invalid")
    match = _DATA_URL.fullmatch(value)
    if match is None:
        raise ValueError("avatar_data_format_invalid")
    subtype, encoded = match.groups()
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("avatar_data_base64_invalid") from None
    if not raw or base64.b64encode(raw).decode("ascii") != encoded:
        raise ValueError("avatar_data_base64_invalid")

    # Pillow is an existing runtime dependency. Keep text-field validation usable
    # without importing the image stack and never mutate Pillow global limits.
    from PIL import Image, ImageFile, ImageOps
    if ImageFile.LOAD_TRUNCATED_IMAGES:
        raise ValueError("avatar_data_strict_decoder_unavailable")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw), formats=list(_FORMATS.values())) as probe:
                if probe.format != _FORMATS[subtype]:
                    raise ValueError("avatar_data_mime_mismatch")
                if not all(1 <= dimension <= MAX_AVATAR_DIMENSION for dimension in probe.size):
                    raise ValueError("avatar_data_dimensions_invalid")
                if getattr(probe, "is_animated", False) or getattr(probe, "n_frames", 1) != 1:
                    raise ValueError("avatar_data_animation_not_allowed")
                probe.verify()
            # JPEG verify() itself does not decode pixels. Reject an absent EOI
            # even if another module enabled Pillow's truncated-image fallback.
            if subtype == "jpeg" and not raw.endswith(b"\xff\xd9"):
                raise ValueError("avatar_data_corrupt")
            with Image.open(BytesIO(raw), formats=[_FORMATS[subtype]]) as original:
                original.load()
                oriented = ImageOps.exif_transpose(original)
                mode = "RGBA" if subtype != "jpeg" and ("A" in oriented.getbands() or "transparency" in oriented.info) else "RGB"
                converted = oriented.convert(mode)
                # Fresh frombytes object carries pixel data only: no EXIF, ICC,
                # PNG text, comments or original encoder options can survive.
                clean = Image.frombytes(mode, converted.size, converted.tobytes())
                output = BytesIO()
                if subtype == "jpeg":
                    clean.save(output, format="JPEG", quality=90, optimize=True)
                elif subtype == "png":
                    clean.save(output, format="PNG", optimize=True)
                else:
                    clean.save(output, format="WEBP", quality=90, method=4)
                clean.close()
                converted.close()
                oriented.close()
    except ValueError as exc:
        if str(exc) in {"avatar_data_mime_mismatch", "avatar_data_dimensions_invalid",
                        "avatar_data_animation_not_allowed", "avatar_data_corrupt"}:
            raise
        raise ValueError("avatar_data_corrupt") from None
    except Exception:
        raise ValueError("avatar_data_corrupt") from None
    result = "data:image/" + subtype + ";base64," + base64.b64encode(output.getvalue()).decode("ascii")
    if len(result) > MAX_AVATAR_DATA_CHARS:
        raise ValueError("avatar_data_encoded_size_invalid")
    return result
