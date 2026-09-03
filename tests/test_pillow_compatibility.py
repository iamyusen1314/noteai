import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageStat


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model"
sys.path.insert(0, str(MODEL_DIR))

from extract_cover_features import extract_deterministic, image_to_b64  # noqa: E402


class PillowCompatibilityTests(unittest.TestCase):
    def test_png_round_trip_and_cover_features(self):
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "cover.png"
            Image.new("RGB", (8, 4), (200, 100, 50)).save(image_path)

            with Image.open(image_path) as image:
                self.assertEqual(image.size, (8, 4))
                self.assertEqual(ImageStat.Stat(image).mean, [200.0, 100.0, 50.0])

            encoded, media_type = image_to_b64(image_path)
            features = extract_deterministic(image_path)

        self.assertEqual(media_type, "image/png")
        self.assertTrue(encoded)
        self.assertAlmostEqual(features["cover_brightness"], 0.4871, places=4)
        self.assertEqual(features["cover_warmth"], 1.0)
        self.assertAlmostEqual(features["cover_saturation"], 0.75, places=2)
        self.assertEqual(features["cover_contrast"], 0.0)
        self.assertEqual(features["cover_sharpness"], 0.0)
        self.assertEqual(features["cover_aspect_ratio"], 2.0)


if __name__ == "__main__":
    unittest.main()
