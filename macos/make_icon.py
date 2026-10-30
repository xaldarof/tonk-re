# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow>=10"]
# ///
"""Render the retro CRT app icon to a 1024px PNG: python make_icon.py out.png"""
import sys
from PIL import Image, ImageDraw, ImageFilter, ImageFont

S, INSET, R = 1024, 100, 185
GREEN = (57, 255, 106)


def font(size):
    for f in ("/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Monaco.ttf"):
        try:
            return ImageFont.truetype(f, size, index=1 if f.endswith(".ttc") else 0)  # bold
        except OSError:
            continue
    return ImageFont.load_default(size)


img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
box = (INSET, INSET, S - INSET, S - INSET)

# bezel + screen
bez = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(bez)
d.rounded_rectangle(box, R, fill=(22, 26, 22, 255))
d.rounded_rectangle((box[0] + 34, box[1] + 34, box[2] - 34, box[3] - 34), R - 40, fill=(3, 10, 4, 255))
img.alpha_composite(bez)

# phosphor text with glow
txt = Image.new("RGBA", (S, S), (0, 0, 0, 0))
t = ImageDraw.Draw(txt)
bb = t.textbbox((215, 230), ">", font=font(320))
t.text((215, 230), ">", font=font(320), fill=GREEN + (255,))
t.rectangle((bb[2] + 40, bb[1], bb[2] + 190, bb[3]), fill=GREEN + (255,))  # block cursor
t.text((205, 630), "TONK-RE", font=font(128), fill=GREEN + (255,))
glow = txt.filter(ImageFilter.GaussianBlur(22))
img.alpha_composite(glow)
img.alpha_composite(glow)
img.alpha_composite(txt)

# scanlines + vignette, clipped to the screen
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle((box[0] + 34, box[1] + 34, box[2] - 34, box[3] - 34), R - 40, fill=255)
fx = Image.new("RGBA", (S, S), (0, 0, 0, 0))
f = ImageDraw.Draw(fx)
for y in range(0, S, 8):
    f.rectangle((0, y, S, y + 3), fill=(0, 0, 0, 90))
vig = Image.radial_gradient("L").resize((S, S)).point(lambda v: max(0, v - 120) * 1.4)
fx.alpha_composite(Image.merge("RGBA", (Image.new("L", (S, S), 0),) * 3 + (vig,)))
clip = Image.new("RGBA", (S, S), (0, 0, 0, 0))
clip.paste(fx, mask=mask)
img.alpha_composite(clip)

# glass highlight
hl = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(hl).ellipse((60, -380, 964, 330), fill=(255, 255, 255, 9))
hl2 = Image.new("RGBA", (S, S), (0, 0, 0, 0))
hl2.paste(hl, mask=mask)
img.alpha_composite(hl2)

img.save(sys.argv[1])
