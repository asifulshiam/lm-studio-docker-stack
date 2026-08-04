#!/usr/bin/env python3
"""Generates the synthetic test image used by the vision prompt set.

Kept in the repo so the image can be regenerated or altered rather than being an
opaque binary. Content is invented: no real service names, no real data, nothing
copied from another interface.
"""
from PIL import Image, ImageDraw, ImageFont

W, H = 1024, 640
BG = (22, 25, 31)
PANEL = (30, 34, 42)
LINE = (52, 58, 70)
TEXT = (226, 232, 240)
MUTED = (138, 148, 166)
OK = (74, 202, 138)
WARN = (240, 178, 74)
BAD = (238, 108, 108)
ACCENT = (96, 165, 250)

MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
MONO_B = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"


def main():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    f_title = ImageFont.truetype(MONO_B, 22)
    f_head = ImageFont.truetype(MONO_B, 15)
    f_body = ImageFont.truetype(MONO, 15)
    f_small = ImageFont.truetype(MONO, 12)

    d.rectangle([0, 0, W, 52], fill=PANEL)
    d.text((24, 16), "service health  —  cluster: eu-west-2", font=f_title, fill=TEXT)
    d.text((W - 210, 20), "refreshed 04:17:52", font=f_small, fill=MUTED)

    cols = [(40, "SERVICE"), (280, "PORT"), (400, "STATUS"), (560, "LATENCY"), (720, "ERR/MIN")]
    y = 90
    for x, label in cols:
        d.text((x, y), label, font=f_head, fill=MUTED)
    d.line([(40, y + 24), (W - 40, y + 24)], fill=LINE, width=1)

    rows = [
        ("api-gateway",   "8080", "HEALTHY",  OK,   "12 ms",  "0"),
        ("cache-node-1",  "6379", "HEALTHY",  OK,   "3 ms",   "0"),
        ("cache-node-2",  "6380", "HEALTHY",  OK,   "4 ms",   "0"),
        ("worker-pool",   "9200", "DEGRADED", BAD,  "847 ms", "134"),
        ("scheduler",     "7070", "HEALTHY",  OK,   "21 ms",  "0"),
        ("object-store",  "9000", "WARNING",  WARN, "96 ms",  "7"),
    ]
    y += 40
    for name, port, status, colour, lat, err in rows:
        d.text((40, y), name, font=f_body, fill=TEXT)
        d.text((280, y), port, font=f_body, fill=TEXT)
        d.text((400, y), status, font=f_body, fill=colour)
        d.text((560, y), lat, font=f_body, fill=TEXT)
        d.text((720, y), err, font=f_body, fill=TEXT if err == "0" else colour)
        y += 34

    d.line([(40, y + 10), (W - 40, y + 10)], fill=LINE, width=1)

    cy = y + 44
    d.text((40, cy), "REQUESTS / MIN  (last 8 intervals)", font=f_head, fill=MUTED)
    bars = [42, 55, 61, 58, 74, 96, 88, 31]
    bx, by, bw, gap, scale = 40, cy + 130, 46, 22, 1.05
    for i, v in enumerate(bars):
        x0 = bx + i * (bw + gap)
        h = int(v * scale)
        d.rectangle([x0, by - h, x0 + bw, by], fill=ACCENT if v != min(bars) else BAD)
        d.text((x0 + 6, by + 8), str(v), font=f_small, fill=MUTED)

    d.text((600, cy + 40), "peak    96 req/min", font=f_body, fill=TEXT)
    d.text((600, cy + 68), "trough  31 req/min", font=f_body, fill=TEXT)
    d.text((600, cy + 96), "mean    63 req/min", font=f_body, fill=TEXT)

    img.save("dashboard.png", "PNG", optimize=True)
    print("wrote dashboard.png  {}x{}".format(W, H))


if __name__ == "__main__":
    main()
