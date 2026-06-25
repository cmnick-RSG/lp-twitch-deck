"""One-off: turn the raw game art in 'site customization/' into web-optimized
assets under site/public/assets/ (logo wordmark, favicon, side pirates)."""
from pathlib import Path
from PIL import Image

SRC = Path("site customization")
OUT = Path("site/public/assets")
OUT.mkdir(parents=True, exist_ok=True)


def save_png(im, name, **kw):
    p = OUT / name
    im.save(p, "PNG", optimize=True, **kw)
    print(f"  {name:18} {im.size}  {p.stat().st_size//1024} KB")


# 1) Logo wordmark — transparent, resized to retina height ~140
logo = Image.open(SRC / "LastPirates_1280х720logo.png").convert("RGBA")
h = 140
logo = logo.resize((round(logo.width * h / logo.height), h), Image.LANCZOS)
save_png(logo, "logo.png")

# 2) Favicon — square crop of the captain's face from Cover_1 (clean, lit)
cov = Image.open(SRC / "LPDT_Cover_1.jpg").convert("RGB")
face = cov.crop((200, 70, 670, 540))  # tricorn hat + big eyes, centered on captain
for px, nm in [(64, "favicon.png"), (180, "favicon-180.png")]:
    save_png(face.resize((px, px), Image.LANCZOS), nm)

# 3) Side pirates — transparent crew, resized for a header/footer accent
pir = Image.open(SRC / "transparent pirates on side.png").convert("RGBA")
w = 560
pir = pir.resize((w, round(pir.height * w / pir.width)), Image.LANCZOS)
save_png(pir, "pirates.png")

print("done")
