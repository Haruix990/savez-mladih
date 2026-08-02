from PIL import Image, ImageDraw, ImageFont
import os

out = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'assets', 'husnija-kapo.jpg')
W, H = 1200, 700
img = Image.new('RGB', (W, H), (10,14,10))
d = ImageDraw.Draw(img)
# background gradient
for i in range(H):
    r = int(10 + (40 - 10) * (i / H))
    g = int(14 + (80 - 14) * (i / H))
    b = int(10 + (30 - 10) * (i / H))
    d.line([(0,i),(W,i)], fill=(r,g,b))
# placeholder portrait (circle)
cx, cy = W//2, H//2 - 40
r = 180
d.ellipse((cx-r, cy-r, cx+r, cy+r), fill=(46,94,47))
# beret
d.pieslice((cx-r, cy-r-90, cx+r, cy+r-30), -30, 110, fill=(29,115,69))
# face
d.ellipse((cx-70, cy-20, cx+70, cy+90), fill=(236,216,180))
# smile
d.arc((cx-40, cy+30, cx+40, cy+90), 190, 350, fill=(120,80,50), width=8)
# name box
d.rectangle((40,H-140,W-40,H-40), fill=(18,18,18,180))

try:
    font_path = None
    possible = [
        'C:/Windows/Fonts/arial.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    ]
    for p in possible:
        if os.path.exists(p):
            font_path = p
            break
    if font_path:
        f1 = ImageFont.truetype(font_path, 48)
        f2 = ImageFont.truetype(font_path, 28)
    else:
        f1 = ImageFont.load_default()
        f2 = ImageFont.load_default()
    d.text((W//2, H-110), 'Husnija Kapo', font=f1, fill=(255,255,255), anchor='mm')
    d.text((W//2, H-70), 'Komandant', font=f2, fill=(200,160,80), anchor='mm')
except Exception:
    pass

img.save(out, quality=90)
print('Written', out)
