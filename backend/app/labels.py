"""Offline barcode / QR label rendering — no network calls, no external service.

The payload is always the part's own `id` (short, stable, unique — never
changes if the MPN or name is later edited), which is exactly what
`GET /api/parts/lookup?code=` already matches first, so a printed label
scans straight back to the part with the USB scanner.
"""
from __future__ import annotations

import io

import barcode as _barcode
import qrcode
from barcode.writer import ImageWriter


def code128_png(data: str) -> bytes:
    writer = ImageWriter()
    code = _barcode.get("code128", data, writer=writer)
    buf = io.BytesIO()
    code.write(
        buf,
        options={
            "module_height": 9.0,
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
