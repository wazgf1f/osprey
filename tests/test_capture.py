"""Live GDI capture checks (Windows only)."""

from __future__ import annotations

import sys
import unittest

from osprey.errors import CaptureError


@unittest.skipUnless(sys.platform == "win32", "GDI capture is Windows-only")
class TestGdiCapture(unittest.TestCase):
    def test_full_screen_capture(self) -> None:
        from osprey.capture.gdi import GdiGrabber

        with GdiGrabber() as grabber:
            frame = grabber.grab()
            self.assertEqual((frame.width, frame.height), grabber.screen_size)
            self.assertEqual(frame.bgra.shape[2], 4)
            self.assertEqual(frame.bgra.dtype.name, "uint8")
            self.assertEqual(frame.origin, (0, 0))

    def test_region_capture(self) -> None:
        from osprey.capture.gdi import GdiGrabber

        with GdiGrabber(region=(10, 20, 64, 48)) as grabber:
            frame = grabber.grab()
            self.assertEqual((frame.width, frame.height), (64, 48))
            self.assertEqual(frame.origin, (10, 20))

    def test_region_must_be_inside_screen(self) -> None:
        from osprey.capture.gdi import GdiGrabber

        with self.assertRaises(CaptureError):
            GdiGrabber(region=(0, 0, 0, 10))
        with self.assertRaises(CaptureError):
            GdiGrabber(region=(-5, 0, 10, 10))

    def test_repeated_grabs_are_stable(self) -> None:
        from osprey.capture.gdi import GdiGrabber

        with GdiGrabber() as grabber:
            first = grabber.grab()
            second = grabber.grab()
            self.assertEqual(first.bgra.shape, second.bgra.shape)
            self.assertEqual(first.gray().shape, (first.height, first.width))

    def test_screen_scale_is_plausible(self) -> None:
        from osprey.capture.gdi import screen_scale

        scale = screen_scale()
        self.assertGreater(scale, 0.5)
        self.assertLessEqual(scale, 4.0)

    def test_monitors_include_a_primary(self) -> None:
        from osprey.capture.gdi import monitors

        found = monitors()
        self.assertTrue(found)
        self.assertTrue(any(monitor["primary"] for monitor in found))
        for monitor in found:
            self.assertEqual(len(monitor["rect"]), 4)
            self.assertGreater(monitor["rect"][2], 0)

    def test_full_desktop_matches_virtual_screen(self) -> None:
        from osprey.capture.gdi import GdiGrabber, virtual_screen_rect

        vx, vy, vw, vh = virtual_screen_rect()
        with GdiGrabber(full_desktop=True) as grabber:
            frame = grabber.grab()
        self.assertEqual((frame.width, frame.height), (vw, vh))
        self.assertEqual(frame.origin, (vx, vy))

    def test_resolution_change_rebuilds_buffers(self) -> None:
        from osprey.capture.gdi import GdiGrabber

        class Resizing(GdiGrabber):
            fake = (0, 0, 320, 200)

            def _screen_metrics(self):
                return self.fake

        grabber = Resizing()
        try:
            self.assertEqual(grabber.grab().bgra.shape[:2], (200, 320))
            grabber.fake = (0, 0, 240, 160)
            frame = grabber.grab()
            self.assertEqual((frame.width, frame.height), (240, 160))
        finally:
            grabber.close()

    def test_region_that_no_longer_fits_raises(self) -> None:
        from osprey.capture.gdi import GdiGrabber

        class Shrinking(GdiGrabber):
            fake = (0, 0, 320, 200)

            def _screen_metrics(self):
                return self.fake

        grabber = Shrinking(region=(0, 0, 300, 200))
        try:
            self.assertEqual(grabber.grab().width, 300)
            grabber.fake = (0, 0, 200, 150)
            with self.assertRaises(CaptureError):
                grabber.grab()
        finally:
            grabber.close()

    def test_dpi_awareness_is_idempotent(self) -> None:
        from osprey.capture.gdi import enable_dpi_awareness

        self.assertTrue(enable_dpi_awareness())
        self.assertTrue(enable_dpi_awareness())

    def test_close_is_idempotent(self) -> None:
        from osprey.capture.gdi import GdiGrabber

        grabber = GdiGrabber(region=(0, 0, 32, 32))
        grabber.close()
        grabber.close()
        with self.assertRaises(CaptureError):
            grabber.grab()


if __name__ == "__main__":
    unittest.main()
