"""Computer vision primitives."""

from .io import crop_gray, draw_detections, load_gray, load_rgb, save_image
from .match import Detection, ensure_gray, match_template, ncc_map

__all__ = [
    "Detection",
    "crop_gray",
    "draw_detections",
    "ensure_gray",
    "load_gray",
    "load_rgb",
    "match_template",
    "ncc_map",
    "save_image",
]
