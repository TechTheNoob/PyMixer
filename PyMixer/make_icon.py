"""Generate Discord-dark multi-size tray icon.ico / icon.png. Run from PyMixer/: python make_icon.py"""
from pathlib import Path
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent

def make_base(size=256):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    grad = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(grad)
    for y in range(size):
        t = y / max(1, size - 1)
        r = int(26 + 62 * t)
        g = int(28 + 73 * t)
        b = int(40 + 180 * t)
        gdraw.line([(0, y), (size, y)], fill=(r, g, b, 255))
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    cx, cy = int(size * 0.55), int(size * 0.42)
    gr = int(size * 0.42)
    for i in range(gr, 0, -1):
        a = int(70 * (1 - i / gr) ** 1.5)
        gd.ellipse([cx - i, cy - i, cx + i, cy + i], fill=(88, 101, 242, a))
    grad = Image.alpha_composite(grad, glow)
    pad = int(size * 0.06)
    radius = int(size * 0.22)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [pad, pad, size - pad - 1, size - pad - 1], radius=radius, fill=255
    )
    rounded = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    rounded.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(rounded)
    track_w = max(2, size // 28)
    span = size * 0.46
    start_x = (size - span) / 2
    gap = span / 2
    top, bot = size * 0.28, size * 0.72
    knob_r = max(3, size // 16)
    for i, lvl in enumerate([0.62, 0.28, 0.78]):
        x = start_x + i * gap
        d.rounded_rectangle([x - track_w / 2, top, x + track_w / 2, bot], radius=track_w / 2, fill=(30, 31, 34, 220))
        fy = bot - (bot - top) * lvl
        d.rounded_rectangle([x - track_w / 2, fy, x + track_w / 2, bot], radius=track_w / 2, fill=(148, 156, 247, 255))
        d.ellipse([x - knob_r, fy - knob_r, x + knob_r, fy + knob_r], fill=(255, 255, 255, 255), outline=(88, 101, 242, 200), width=max(1, size // 64))
    d.rounded_rectangle([pad, pad, size - pad - 1, size - pad - 1], radius=radius, outline=(255, 255, 255, 28), width=max(1, size // 64))
    return rounded

def main():
    base = make_base(256)
    base.save(HERE / "icon.png")
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    imgs = [base.resize(s, Image.Resampling.LANCZOS) for s in sizes]
    imgs[-1].save(HERE / "icon.ico", format="ICO", sizes=[(im.width, im.height) for im in imgs])
    print("wrote", HERE / "icon.ico", "and icon.png")

if __name__ == "__main__":
    main()
