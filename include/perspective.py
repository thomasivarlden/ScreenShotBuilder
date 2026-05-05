"""Perspective / 4-corner distort using Pillow.

Pillow's Image.transform(..., Image.PERSPECTIVE, coeffs) maps each
output pixel (x, y) back to a source pixel:

    src_x = (a*x + b*y + c) / (g*x + h*y + 1)
    src_y = (d*x + e*y + f) / (g*x + h*y + 1)

So we compute coefficients from 4 (output -> source) point pairs.
"""
from typing import List, Sequence, Tuple

import numpy as np
from PIL import Image

Point = Tuple[float, float]


def _find_coeffs(target: Sequence[Point], source: Sequence[Point]) -> List[float]:
    """Coefficients mapping target (output) coords back to source coords."""
    matrix = []
    for (tx, ty), (sx, sy) in zip(target, source):
        matrix.append([tx, ty, 1, 0, 0, 0, -sx * tx, -sx * ty])
        matrix.append([0, 0, 0, tx, ty, 1, -sy * tx, -sy * ty])
    A = np.array(matrix, dtype=np.float64)
    B = np.array(source, dtype=np.float64).reshape(8)
    coeffs = np.linalg.solve(A, B)
    return list(coeffs)


def warp_to_quad(
    image: Image.Image,
    canvas_size: Tuple[int, int],
    quad: Sequence[Point],
) -> Image.Image:
    """Warp `image` onto a transparent canvas so its corners land on `quad`.

    `quad` order: top_left, top_right, bottom_right, bottom_left.
    Returns an RGBA image of size `canvas_size`.
    """
    src = image.convert("RGBA")
    w, h = src.size
    source_corners: List[Point] = [(0, 0), (w, 0), (w, h), (0, h)]
    coeffs = _find_coeffs(quad, source_corners)

    warped = src.transform(
        canvas_size,
        Image.PERSPECTIVE,
        coeffs,
        resample=Image.BICUBIC,
    )
    return warped
