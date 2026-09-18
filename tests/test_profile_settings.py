import ast
import base64
import importlib.util
from io import BytesIO
from pathlib import Path
import random
import re
import unittest
from unittest import mock

from PIL import Image, ImageFile, PngImagePlugin


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("profile_settings", ROOT / "model/profile_settings.py")
profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)


def data_url(raw, kind="png"):
    return "data:image/" + kind + ";base64," + base64.b64encode(raw).decode("ascii")


def image_bytes(fmt="PNG", size=(12, 8), **kwargs):
    image = Image.new("RGBA" if fmt in {"PNG", "WEBP"} else "RGB", size, "red")
    output = BytesIO()
    image.save(output, format=fmt, **kwargs)
    image.close()
    return output.getvalue()


class ProfileSettingsTests(unittest.TestCase):
    def test_nickname_normalizes_without_truncation(self):
        self.assertEqual(profile.normalize_nickname("  小陶 咖啡☕  "), "小陶 咖啡☕")
        self.assertEqual(profile.normalize_nickname("Cafe\u0301"), "Café")
        self.assertEqual(profile.normalize_nickname("名" * 20), "名" * 20)
        with self.assertRaises(ValueError):
            profile.normalize_nickname("名" * 21)

    def test_nickname_rejects_control_invisible_and_empty(self):
        for value in (None, "", "  ", "\n合法", "昵称\t", "a\x00b", "a\x7fb", "a\u202eb", "a\u200bb", "a\u2028b", "<b>昵称</b>", "\u0301"):
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                profile.normalize_nickname(value)

    def test_all_existing_ui_emoji_choices_are_compatible(self):
        html = (ROOT / "NoteAI_Pro_Demo_Framer.html").read_text()
        choices = ast.literal_eval(re.search(r"const _AVATAR_EMOJIS = (\[[\s\S]*?\]);", html)[1])
        self.assertEqual(len(choices), 40)
        self.assertTrue(all(profile.normalize_avatar_emoji(value) == value for value in choices))

    def test_compound_emoji_and_flags(self):
        for value in ("👩🏽‍💻", "🏳️‍🌈", "🇨🇳", "1️⃣", "❤️", "🧑‍🚀"):
            with self.subTest(value=value):
                self.assertEqual(profile.normalize_avatar_emoji(value), value)

    def test_emoji_rejects_markup_text_control_and_broken_joiner(self):
        for value in (None, "", "abc", "<img>", "&#x1f338;", "🌸\n", "🌸\u202e", "\u200d🌸", "🌸\u200d", "🌸\u200d\u200d☀", "🌸\u200d\ufe0f", "\ufe0f", "🏽", "🌸" * 33):
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                profile.normalize_avatar_emoji(value)

    def test_static_jpeg_png_webp_verify_and_reencode(self):
        for mime, fmt in (("jpeg", "JPEG"), ("png", "PNG"), ("webp", "WEBP")):
            with self.subTest(mime=mime):
                result = profile.normalize_avatar_data(data_url(image_bytes(fmt), mime))
                with Image.open(BytesIO(base64.b64decode(result.split(",", 1)[1]))) as checked:
                    self.assertEqual((checked.format, checked.size), (fmt, (12, 8)))
                    checked.verify()
                self.assertLessEqual(len(result), profile.MAX_AVATAR_DATA_CHARS)

    def test_png_text_icc_and_exif_are_removed(self):
        text = PngImagePlugin.PngInfo()
        text.add_text("Comment", "PRIVATE_METADATA")
        exif = Image.Exif()
        exif[315] = "PRIVATE_AUTHOR"
        raw = image_bytes(pnginfo=text, icc_profile=b"PRIVATE_ICC", exif=exif, dpi=(300, 300))
        result = profile.normalize_avatar_data(data_url(raw))
        encoded = base64.b64decode(result.split(",", 1)[1])
        self.assertNotIn(b"PRIVATE", encoded)
        with Image.open(BytesIO(encoded)) as checked:
            self.assertFalse(checked.getexif())
            self.assertFalse(set(checked.info) & {"Comment", "icc_profile", "exif", "dpi"})

    def test_jpeg_orientation_applied_before_metadata_removal(self):
        exif = Image.Exif()
        exif[274] = 6
        exif[315] = "PRIVATE_AUTHOR"
        result = profile.normalize_avatar_data(data_url(image_bytes("JPEG", exif=exif), "jpeg"))
        with Image.open(BytesIO(base64.b64decode(result.split(",", 1)[1]))) as checked:
            self.assertEqual(checked.size, (8, 12))
            self.assertFalse(checked.getexif())

    def test_alpha_pixels_survive_png_reencoding(self):
        image = Image.new("RGBA", (2, 2), (255, 0, 0, 0))
        stream = BytesIO()
        image.save(stream, format="PNG")
        result = profile.normalize_avatar_data(data_url(stream.getvalue()))
        with Image.open(BytesIO(base64.b64decode(result.split(",", 1)[1]))) as checked:
            self.assertEqual(checked.getpixel((0, 0)), (255, 0, 0, 0))

    def test_rejects_svg_gif_and_mime_mismatch(self):
        for value in (data_url(b"<svg></svg>", "svg+xml"), data_url(image_bytes("GIF"), "gif"),
                      data_url(image_bytes("GIF"), "png"), data_url(image_bytes("JPEG"), "png")):
            with self.subTest(prefix=value[:30]), self.assertRaises(ValueError):
                profile.normalize_avatar_data(value)

    def test_rejects_animated_png_and_webp(self):
        first, second = Image.new("RGB", (8, 8), "red"), Image.new("RGB", (8, 8), "blue")
        for fmt, mime in (("PNG", "png"), ("WEBP", "webp")):
            stream = BytesIO()
            first.save(stream, format=fmt, save_all=True, append_images=[second], duration=100, loop=0)
            with self.subTest(fmt=fmt), self.assertRaisesRegex(ValueError, "animation_not_allowed"):
                profile.normalize_avatar_data(data_url(stream.getvalue(), mime))

    def test_rejects_corrupt_or_truncated_pixels(self):
        for mime, fmt in (("jpeg", "JPEG"), ("png", "PNG"), ("webp", "WEBP")):
            for raw in (b"not an image", image_bytes(fmt)[:40], image_bytes(fmt)[:-10]):
                with self.subTest(mime=mime, size=len(raw)), self.assertRaises(ValueError):
                    profile.normalize_avatar_data(data_url(raw, mime))

    def test_rejects_invalid_base64_and_noncanonical_data_urls(self):
        for value in ("data:image/png;base64,@@@", "data:image/png;base64,AB==", "data:image/png;base64,", "data:image/png;foo=x;base64,AAAA", "data:image/png;base64,AAAA\n", "http://example.invalid/a.png"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                profile.normalize_avatar_data(value)

    def test_rejects_input_size_and_dimension_limits_before_pixel_decode(self):
        with self.assertRaisesRegex(ValueError, "size_invalid"):
            profile.normalize_avatar_data("data:image/png;base64," + "A" * 200000)
        with self.assertRaisesRegex(ValueError, "dimensions_invalid"):
            profile.normalize_avatar_data(data_url(image_bytes(size=(2049, 2))))
        # Exactly 2048 pixels is supported, with no silent resize.
        result = profile.normalize_avatar_data(data_url(image_bytes(size=(2048, 1))))
        with Image.open(BytesIO(base64.b64decode(result.split(",", 1)[1]))) as checked:
            self.assertEqual(checked.size, (2048, 1))

    def test_reencoded_size_limit_rejects_without_silent_quality_loop(self):
        pixels = random.Random(42).randbytes(512 * 512 * 3)
        image = Image.frombytes("RGB", (512, 512), pixels)
        stream = BytesIO()
        image.save(stream, format="JPEG", quality=50)
        original = data_url(stream.getvalue(), "jpeg")
        self.assertLess(len(original), 200000)
        with self.assertRaisesRegex(ValueError, "encoded_size_invalid"):
            profile.normalize_avatar_data(original)

    def test_does_not_mutate_global_truncated_image_policy(self):
        with mock.patch.object(ImageFile, "LOAD_TRUNCATED_IMAGES", True):
            with self.assertRaisesRegex(ValueError, "strict_decoder_unavailable"):
                profile.normalize_avatar_data(data_url(image_bytes()))
            self.assertTrue(ImageFile.LOAD_TRUNCATED_IMAGES)


if __name__ == "__main__":
    unittest.main()
