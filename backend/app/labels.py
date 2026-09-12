"""Offline barcode / QR label rendering — no network calls, no external service.

The payload is the part's MPN when it has one, else its own `id` — either
way exactly what `GET /api/parts/lookup?code=` matches, so a printed label
scans straight back to the part with the USB scanner.
"""
from __future__ import annotations

import io

import barcode as _barcode
import qrcode
from barcode.writer import ImageWriter

# Roughly how much of the total rendered height is quiet zone + the human-
# readable text row below the bars (write_text/text_distance/font_size
# below), so a caller asking for e.g. "10mm total" gets bars sized to
# roughly fill that, not 10mm of bars *plus* another ~6mm of text.
_TEXT_OVERHEAD_MM = 6.0
_MIN_MODULE_HEIGHT_MM = 2.0


def code128_png(data: str, target_height_mm: float | None = None) -> bytes:
    module_height = 9.0
    if target_height_mm is not None:
        module_height = max(_MIN_MODULE_HEIGHT_MM, target_height_mm - _TEXT_OVERHEAD_MM)
    writer = ImageWriter()
    code = _barcode.get("code128", data, writer=writer)
    buf = io.BytesIO()
    code.write(
        buf,
        options={
            "module_height": module_height,
            "quiet_zone": 2.0,
            "write_text": True,
            "font_size": 8,
            "text_distance": 3.0,
            "dpi": 300,
        },
    )
    return buf.getvalue()


def qr_png(data: str) -> bytes:
    qr = qrcode.QRCode(border=1, box_size=8, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
