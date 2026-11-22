# Organization logos

Every organization has a logo: the `image` of its row, stored in the
`images` table like the photos. The logos are SVG, and they are made to
one convention so that they line up when shown side by side, whatever
shape the original artwork has.

## The convention

- **SVG**, served as `image/svg+xml`, named `<slug>.svg` (`schema.svg`).
- **A 1000x1000 canvas.** The root element says `width="1000"
  height="1000"`.
- **A square `viewBox`, centered on the artwork, with a 6% margin.** The
  side of the box is 1.12 times the longer side of the artwork's bounding
  box, so the artwork fills 88% of the canvas one way and is centered
  the other way. The artwork keeps its own coordinates; only the `viewBox`
  moves.
- **A transparent background.** No background rectangle, and no white or
  black surround: a bitmap's surround is keyed out before it is traced.
- **The original colors, as flat fills.** No color is changed to suit a
  theme.
- **Nothing active or external.** No `<script>`, event handler attribute,
  `<foreignObject>`, embedded `<image>` or link to another file. The
  images are served with a sandbox Content-Security-Policy anyway, but
  the files should not need it.
- **Valid XML**, clean under `xmllint --noout`.

The `logos` check (`checks.md`) tests every SVG in the database against
all of this but the margin and centering, which need a renderer.

## Where a logo comes from

In order of preference:

1. An official vector logo (a Wikimedia Commons SVG, the company's own
   press kit). Only the root element is changed, to the canvas and
   `viewBox` above.
2. A color trace of the original bitmap, when no vector logo exists.
3. A drawing by hand from the original bitmap, when tracing is not worth
   it: a wordmark of straight letters is a few rectangles and polygons,
   with the curved letters fitted by eye. Render it over the bitmap at
   the bitmap's own size and compare the two before using it. Schema's
   logo (2026-11-08) was made this way, from the 2007 press logo on
   schema.com found through the Wayback Machine.

The 120 imported logos live in `veltzer.github.io/data/logos/`, where
`organizations.yaml` records each one's `logo_kind` and `logo_source`
(see `deploy.md`). A logo added later is uploaded in the organization
dialog, which takes only SVG files: `POST /api/images` accepts an SVG,
refuses one with anything active or external (or a document type
declaration), and squares its `viewBox` (the shorter side widened, the
artwork centered) on the 1000x1000 canvas, changing only the root
element; the margin is the file's own. An organization's logo is never a
bitmap: saving an organization with a JPEG, PNG, GIF or WebP as its
`image_id` is refused, and `organization-logos` (`checks.md`) finds one
that has one.

An official vector logo that embeds bitmaps (MAFAT's Wikimedia Commons
SVG draws the shaded arms of its "A" as two clipped PNG images) has them
redrawn as vector shapes: each clipped region a polygon, filled with a
linear gradient whose stops are colors sampled from the bitmap along it.
Render the result beside the original and compare before using it.
