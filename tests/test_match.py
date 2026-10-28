"""Correctness tests for the template matcher.

The important one is test_matches_reference_ncc: it compares the FFT
implementation against a literal, slow, window-by-window NCC over thousands
of positions. If that passes, the maths is right.
"""

from __future__ import annotations

import unittest

import numpy as np

from osprey.errors import VisionError
from osprey.vision.match import Detection, ensure_gray, match_template, ncc_map, to_uint8

try:
    import cv2
except Exception:  # pragma: no cover - optional dependency
    cv2 = None


def brute_force_ncc(image: np.ndarray, template: np.ndarray) -> np.ndarray:
    image = image.astype(np.float64)
    template = template.astype(np.float64)
    ih, iw = image.shape
    th, tw = template.shape
    centred = template - template.mean()
    tpl_norm = np.sqrt((centred * centred).sum())
    scores = np.zeros((ih - th + 1, iw - tw + 1), dtype=np.float64)
    for y in range(ih - th + 1):
        for x in range(iw - tw + 1):
            window = image[y:y + th, x:x + tw]
            window = window - window.mean()
            denom = np.sqrt((window * window).sum()) * tpl_norm
            scores[y, x] = float((window * centred).sum() / denom) if denom > 1e-12 else 0.0
    return scores


def paste(canvas: np.ndarray, patch: np.ndarray, x: int, y: int) -> None:
    canvas[y:y + patch.shape[0], x:x + patch.shape[1]] = patch


class TestNormalisedCrossCorrelation(unittest.TestCase):
    def setUp(self) -> None:
        self.rng = np.random.default_rng(20261028)

    def test_matches_reference_ncc(self) -> None:
        image = self.rng.integers(0, 256, size=(52, 67), dtype=np.uint8)
        template = image[17:27, 31:43].copy()
        expected = brute_force_ncc(image, template)
        actual = ncc_map(image, template)
        self.assertEqual(actual.shape, expected.shape)
        np.testing.assert_allclose(actual, expected, atol=1e-6, rtol=0)

    def test_matches_reference_on_noisy_scene(self) -> None:
        image = self.rng.integers(20, 90, size=(48, 64), dtype=np.uint8)
        template = self.rng.integers(0, 256, size=(9, 11), dtype=np.uint8)
        paste(image, template, 22, 13)
        expected = brute_force_ncc(image, template)
        actual = ncc_map(image, template)
        np.testing.assert_allclose(actual, expected, atol=1e-6, rtol=0)

    def test_perfect_peak_is_exactly_one(self) -> None:
        template = self.rng.integers(0, 256, size=(6, 8), dtype=np.uint8)
        image = np.zeros((30, 40), dtype=np.uint8)
        paste(image, template, 11, 7)
        scores = ncc_map(image, template)
        self.assertAlmostEqual(float(scores[7, 11]), 1.0, places=6)

    def test_flat_template_is_rejected(self) -> None:
        image = self.rng.integers(0, 256, size=(20, 20), dtype=np.uint8)
        with self.assertRaises(VisionError):
            ncc_map(image, np.full((5, 5), 77, dtype=np.uint8))

    def test_template_larger_than_image_is_rejected(self) -> None:
        image = self.rng.integers(0, 256, size=(10, 10), dtype=np.uint8)
        template = self.rng.integers(0, 256, size=(11, 4), dtype=np.uint8)
        with self.assertRaises(VisionError):
            ncc_map(image, template)

    def test_float_images_are_scaled_correctly(self) -> None:
        template = np.array([[0.1, 0.2], [0.3, 0.9]], dtype=np.float32)
        image = np.zeros((8, 8), dtype=np.float32)
        image[3:5, 4:6] = template
        uint8_image = to_uint8(image)
        uint8_template = to_uint8(template)
        self.assertTrue(np.array_equal(uint8_image, np.clip(image * 255, 0, 255).astype(np.uint8)))
        scores = ncc_map(uint8_image, uint8_template)
        self.assertAlmostEqual(float(scores[3, 4]), 1.0, places=5)


@unittest.skipUnless(cv2 is not None, "opencv-python is not installed")
class TestOpenCVBackend(unittest.TestCase):
    def test_matches_numpy_backend(self) -> None:
        rng = np.random.default_rng(31)
        image = rng.integers(0, 256, size=(180, 240), dtype=np.uint8)
        template = image[60:84, 90:118].copy()
        numpy_det = match_template(image, template, threshold=0.9, backend="numpy", downscale=1)
        opencv_det = match_template(image, template, threshold=0.9, backend="opencv", downscale=1)
        self.assertEqual(numpy_det[0].box, opencv_det[0].box)
        self.assertAlmostEqual(numpy_det[0].score, opencv_det[0].score, places=3)


class TestResolutionIndependence(unittest.TestCase):
    """The same template must match after Windows scales the UI."""

    def _card(self) -> np.ndarray:
        from PIL import Image, ImageDraw

        image = Image.new("RGB", (160, 80), (20, 30, 40))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle([2, 2, 157, 77], radius=8, outline=(0, 220, 255), width=3)
        draw.rectangle([16, 16, 70, 64], fill=(220, 60, 60))
        draw.text((84, 32), "OK", fill=(255, 255, 255))
        return np.asarray(image.convert("L"))

    def test_detects_at_common_windows_scales(self) -> None:
        from PIL import Image

        base = self._card()
        rng = np.random.default_rng(3)
        for scale in (0.75, 1.0, 1.25, 1.5, 2.0):
            with self.subTest(scale=scale):
                width = int(round(160 * scale))
                height = int(round(80 * scale))
                card = np.asarray(Image.fromarray(base).resize((width, height), Image.BILINEAR))
                scene = rng.integers(0, 70, size=(600, 900), dtype=np.uint8)
                x0, y0 = 140, 220
                scene[y0:y0 + height, x0:x0 + width] = card
                detections = match_template(
                    scene, base, threshold=0.8, scales=(scale,), downscale=1
                )
                self.assertTrue(detections, "no match at scale %.2f" % scale)
                top = detections[0]
                self.assertLessEqual(abs(top.x - x0), 1)
                self.assertLessEqual(abs(top.y - y0), 1)
                self.assertAlmostEqual(top.scale, scale, places=6)


class TestMatchTemplate(unittest.TestCase):
    def setUp(self) -> None:
        self.rng = np.random.default_rng(7)

    def _scene(self) -> tuple:
        image = self.rng.integers(0, 80, size=(120, 160), dtype=np.uint8)
        template = self.rng.integers(100, 256, size=(18, 22), dtype=np.uint8)
        paste(image, template, 91, 44)
        return image, template

    def test_finds_exact_location(self) -> None:
        image, template = self._scene()
        detections = match_template(image, template, threshold=0.9)
        self.assertTrue(detections)
        top = detections[0]
        self.assertEqual((top.x, top.y), (91, 44))
        self.assertEqual((top.w, top.h), (22, 18))
        self.assertGreater(top.score, 0.999)

    def test_coordinates_reported_in_image_space(self) -> None:
        image, template = self._scene()
        top = match_template(image, template, threshold=0.9)[0]
        cx, cy = top.center
        self.assertAlmostEqual(cx, 91 + 11)
        self.assertAlmostEqual(cy, 44 + 9)

    def test_threshold_filters_weak_matches(self) -> None:
        image = self.rng.integers(0, 80, size=(60, 60), dtype=np.uint8)
        template = self.rng.integers(100, 256, size=(10, 10), dtype=np.uint8)
        self.assertEqual(match_template(image, template, threshold=0.95), [])

    def test_multiple_occurrences_are_separated(self) -> None:
        image = np.zeros((100, 200), dtype=np.uint8)
        template = self.rng.integers(60, 256, size=(16, 16), dtype=np.uint8)
        paste(image, template, 10, 10)
        paste(image, template, 120, 60)
        detections = match_template(image, template, threshold=0.95, nms_iou=0.2)
        self.assertGreaterEqual(len(detections), 2)
        locations = {(d.x, d.y) for d in detections[:2]}
        self.assertEqual(locations, {(10, 10), (120, 60)})

    def test_degenerate_scale_is_skipped(self) -> None:
        image = self.rng.integers(0, 90, size=(200, 260), dtype=np.uint8)
        template = self.rng.integers(80, 256, size=(24, 28), dtype=np.uint8)
        paste(image, template, 90, 60)
        detections = match_template(
            image, template, threshold=0.9, scales=(1.0, 0.001), downscale=1
        )
        self.assertTrue(detections)
        self.assertEqual((detections[0].x, detections[0].y), (90, 60))

    def test_multiscale_finds_scaled_template(self) -> None:
        base = self.rng.integers(0, 256, size=(14, 16), dtype=np.uint8)
        scaled = np.asarray(
            __import__("PIL.Image", fromlist=["Image"]).fromarray(base).resize((24, 21))
        )
        image = self.rng.integers(0, 70, size=(140, 180), dtype=np.uint8)
        paste(image, scaled, 60, 40)
        detections = match_template(
            image, base, threshold=0.85, scales=(1.0, 1.25, 1.5, 1.75)
        )
        self.assertTrue(detections)
        self.assertAlmostEqual(detections[0].scale, 1.5, places=6)
        self.assertLessEqual(abs(detections[0].x - 60), 1)
        self.assertLessEqual(abs(detections[0].y - 40), 1)

    def test_pyramid_matches_full_resolution(self) -> None:
        image = self.rng.integers(0, 90, size=(480, 640), dtype=np.uint8)
        template = self.rng.integers(80, 256, size=(40, 44), dtype=np.uint8)
        paste(image, template, 301, 207)
        full = match_template(image, template, threshold=0.9, downscale=1)
        coarse = match_template(image, template, threshold=0.9, downscale=2)
        self.assertTrue(full and coarse)
        self.assertEqual(coarse[0].box, full[0].box)
        self.assertGreater(coarse[0].score, 0.99)

    def test_pyramid_finds_two_targets(self) -> None:
        image = np.zeros((300, 500), dtype=np.uint8)
        template = self.rng.integers(60, 256, size=(36, 36), dtype=np.uint8)
        paste(image, template, 40, 30)
        paste(image, template, 330, 180)
        detections = match_template(image, template, threshold=0.95, downscale=2, nms_iou=0.2)
        locations = {(d.x, d.y) for d in detections}
        self.assertIn((40, 30), locations)
        self.assertIn((330, 180), locations)

    def test_pyramid_falls_back_for_tiny_templates(self) -> None:
        image = np.zeros((120, 160), dtype=np.uint8)
        template = self.rng.integers(60, 256, size=(9, 9), dtype=np.uint8)
        paste(image, template, 50, 40)
        detections = match_template(image, template, threshold=0.95, downscale=2)
        self.assertTrue(detections)
        self.assertEqual((detections[0].x, detections[0].y), (50, 40))

    def test_invalid_downscale(self) -> None:
        image = np.zeros((40, 40), dtype=np.uint8)
        template = self.rng.integers(0, 256, size=(8, 8), dtype=np.uint8)
        for bad in (0, -2, True):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    match_template(image, template, downscale=bad)

    def test_no_scale_fits_raises(self) -> None:
        image = np.zeros((20, 20), dtype=np.uint8)
        template = self.rng.integers(0, 256, size=(10, 10), dtype=np.uint8)
        with self.assertRaises(VisionError):
            match_template(image, template, scales=(5.0,))

    def test_invalid_arguments(self) -> None:
        image = np.zeros((30, 30), dtype=np.uint8)
        template = self.rng.integers(0, 256, size=(4, 4), dtype=np.uint8)
        with self.assertRaises(ValueError):
            match_template(image, template, threshold=2.0)
        with self.assertRaises(ValueError):
            match_template(image, template, scales=(0.0,))
        with self.assertRaises(ValueError):
            match_template(image, template, scales=())
        with self.assertRaises(ValueError):
            match_template(image, template, backend="magic")
        self.assertEqual(match_template(image, template, max_results=0), [])

    def test_bgr_input_is_converted(self) -> None:
        gray = self.rng.integers(0, 80, size=(80, 90), dtype=np.uint8)
        bgr = np.dstack([gray, gray, gray])
        template = bgr[20:30, 25:38].copy()
        detections = match_template(bgr, template, threshold=0.9)
        self.assertEqual((detections[0].x, detections[0].y), (25, 20))

    def test_detection_iou(self) -> None:
        a = Detection(0, 0, 10, 10, 1.0)
        b = Detection(5, 0, 10, 10, 1.0)
        self.assertAlmostEqual(a.iou(b), 50 / 150)
        self.assertEqual(a.iou(a), 1.0)
        self.assertEqual(a.iou(Detection(50, 50, 5, 5, 0.5)), 0.0)

    def test_ensure_gray_weights(self) -> None:
        pixel = np.array([[[255, 0, 0]]], dtype=np.uint8)  # blue
        gray = ensure_gray(pixel)
        # uint8 conversion truncates, so allow the sub-one-level remainder.
        self.assertAlmostEqual(float(gray[0, 0]), 0.114 * 255, delta=0.51)


if __name__ == "__main__":
    unittest.main()
