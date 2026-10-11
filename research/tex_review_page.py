"""Research / review tool (not run by the build; read-only): build a self-contained HTML page of the PSP textures that
differ from the PS1, PSP and PS1 side by side, grouped by what was decided about each.

It executes the loading and pairing part of research/tex_compare.py (read as text, up to its comparison loop),
which opens both disc images, so it needs the same inputs; run tex_compare.py first for the full list.
Writes: build/analysis/tex_compare/review/texture_review.html (images embedded; the folder must exist).

The groups and captions in G below are the review as it stood on 2026-09-29, written for the person deciding, and
are kept as that record. Decisions made after it are not reflected in the captions: the MISSION START / COMPLETE
banner (GAUGE01) is now swapped together with its sprite lists; the TV-station monitors and signs and the artwork
differences are swapped with --localization=legends; and the title logo follows that option too. The authoritative
list of swaps is script/texture_swaps.json
(docs/RESEARCH.md §9).

Usage: python3 research/tex_review_page.py      (needs pycdlib + Pillow)"""
import sys, io, base64, json
src = open('research/tex_compare.py').read().split("rows = []; seen = {}")[0]
exec(src)
from PIL import Image, ImageDraw
# find: the first PSP texture with this file name and its PS1 counterpart (a given PS1 name in the same BIN, else the
# same pairing rules as tex_compare.py)
def find(name, ps1name=None):
    for (bn, nm), v in sorted(A.items()):
        if nm.split('\\')[-1].upper() == name.upper():
            if ps1name:
                m = next(((nm1, v1) for (b1, nm1), v1 in B.items() if b1 == bn and nm1.split('\\')[-1].upper() == ps1name.upper()), None)
                return bn, nm, v, m
            k = key(nm); m = Bn[bn].get(k) or Bn[bn].get(k[:-4] + 'U.TIM') or next((Bn[b][c] for b in Bn for c in (k, k[:-4]+'U.TIM') if c in Bn[b]), None)
            return bn, nm, v, m
# uri: an image, enlarged without smoothing, as a data: URI so the page needs no separate files
def uri(im, scale):
    im = im.resize((im.width*scale, im.height*scale), Image.NEAREST); b = io.BytesIO(); im.save(b, 'PNG')
    return 'data:image/png;base64,' + base64.b64encode(b.getvalue()).decode()
# pair: (BIN, PSP name, PS1 name, PSP image, PS1 image) for one texture, drawn with palette pal, optionally cropped to
# the part that differs. only: the same for a texture shown alone
def pair(name, pal=0, crop=None, scale=2, ps1name=None):
    bn, nm, (h, px), m = find(name, ps1name); a = image(h, px, pal); b = image(m[1][0], m[1][1], pal) if m else None
    if crop: a = a.crop(crop); b = b.crop(crop) if b else None
    return bn, nm, (m[0] if m else '-'), uri(a, scale), (uri(b, scale) if b else '')
def only(name, scale=1):
    bn, nm, (h, px), m = find(name); return bn, nm, '-', uri(image(h, px, 0), scale), ''
# G = (group heading, [(pair(...), caption), ...]) - the review record described in the docstring
G = [
 ('Swapped (PS1 English texture used)', [
   (pair('SUB02.TIM', 4, (0, 140, 256, 256)), 'Weapon screen labels. Shown with palette 4 (the label colours). PS1 palettes copied too, otherwise the English labels come out green. Side effect: the small hourglass icon is PS1 grey instead of PSP green (as on the US disc).'),
   (pair('intvh20.TIM', 0, (8, 26, 240, 76), 3), 'TV-station monitors: KVV becomes KTV (Kattelox TV, as in the English script), and the phone number changes.'),
   (pair('OPMOJI1.TIM', 0, None, 1, 'OPENG0.TIM'), 'Opening prologue pages 1-4. The US disc has them under different names (OPENG0-3). PSP palette kept (same pale text colours).'),
   (pair('OPMOJI2.TIM', 0, None, 1, 'OPENG1.TIM'), ''), (pair('OPMOJI3.TIM', 0, None, 1, 'OPENG2.TIM'), ''), (pair('OPMOJI4.TIM', 0, None, 1, 'OPENG3.TIM'), ''),
   (pair('MAP_A1.TIM', 0, None, 1, 'MAP_A1E.TIM'), 'Island maps: US names MAP_A1E ... MAP_B3E, identical layout and palettes. All five are swapped.'),
   (pair('MAP_A2.TIM', 0, None, 1, 'MAP_A2E.TIM'), ''), (pair('MAP_B3.TIM', 0, None, 1, 'MAP_B3E.TIM'), '')]),
 ('Needs code changes before it can be swapped', [
   (pair('GAUGE01.TIM', 0, (0, 200, 256, 256)), 'MISSION START / MISSION COMPLETE banner. The PS1 English words are laid out differently in the texture, so the sprite rectangles in the EBOOT need patching as well (like the title menu). Not swapped yet.')]),
 ('Your call: artwork differences, not text (PSP version kept)', [
   (pair('EM0000.TIM'), 'Servbot faces and props (mouth shapes, mirror/chest). Used in about 31 areas.'),
   (pair('TRUNK.TIM'), 'Same set of faces as EM0000, different props.'),
   (pair('KABUTO.TIM'), 'Plant sprite.'), (pair('INLIV00.TIM'), 'Indoor wall: the PS1 has a bottle picture here.'),
   (pair('EM6400.TIM'), 'The PS1 has an extra character in the corner.'),
   (pair('SCKO00.TIM'), 'Vending machine: PSP cans and hot-dog ad vs PS1 bottles.'), (pair('GAITOU.TIM'), 'Same vending machine, another area.'),
   (pair('st7_410.TIM'), 'Building signs: VAC (PSP) vs YAC (PS1).'), (pair('ST02BG02.TIM'), 'Sky background, small differences.')]),
 ('Staff credits (PSP credits the PSP team; PS1 credits the US cast/staff) — kept PSP', [
   (pair('STAFF%02d.TIM' % k, 0, None, 1), '') for k in range(10)]),
 ('Kept PSP on purpose', [
   (pair('ST15BG02.TIM'), 'CAPCOM logo: PSP adds ®.'), (pair('NTITLE.TIM', 0, None, 1), 'Title logo (you chose to keep it).')]),
]
css = """:root{--bg:#14141f;--fg:#e8e8f0;--mut:#9a9ab0;--card:#1f1f2e;--acc:#ffd84d}
body{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;margin:0;padding:16px;max-width:1100px}
h1{font-size:20px}h2{font-size:16px;color:var(--acc);margin-top:28px}.card{background:var(--card);border-radius:8px;padding:10px;margin:10px 0}
.row{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-start}.row figure{margin:0}.row img{image-rendering:pixelated;max-width:100%}
figcaption{color:var(--mut);font-size:12px}.note{margin:6px 0 0}.meta{color:var(--mut);font-size:12px}"""
H = ['<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Texture Review</title>',
     f'<style>{css}</style><h1>Rockman DASH PSP: textures that differ from the PS1 (USA)</h1>',
     '<p class="meta">Left = PSP (Japanese) in-game texture, right = PS1 (USA). Generated by research/tex_review_page.py. Everything else (1,650 textures) is identical on both discs. The PSP title-menu texture (NTITLE2) has no PS1 counterpart; it is built from the PS1 words (test11).</p>']
for title, items in G:
    H.append(f'<h2>{title}</h2>')
    for (bn, nm, nm1, a, b), note in items:
        H.append(f'<div class="card"><div class="meta">{bn} · PSP {nm} · PS1 {nm1}</div><div class="row"><figure><img src="{a}"><figcaption>PSP</figcaption></figure>'
                 + (f'<figure><img src="{b}"><figcaption>PS1</figcaption></figure>' if b else '') + '</div>' + (f'<p class="note">{note}</p>' if note else '') + '</div>')
__import__('os').makedirs('build/analysis/tex_compare/review', exist_ok=True); open('build/analysis/tex_compare/review/texture_review.html', 'w').write('\n'.join(H)); print('ok')
