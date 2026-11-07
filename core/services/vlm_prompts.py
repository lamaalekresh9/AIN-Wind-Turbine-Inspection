"""Everything the VLM is told, in one editable place.

Edit CLASS_GUIDE to teach the VLM what each defect looks like (and what it must not be
confused with). Keys must match the YOLO class names. Any class without an entry falls back
to a generic description, so a new model with new classes still works.
"""

# What a wind turbine blade looks like in drone imagery, and the normal features that are NOT damage.
BLADE_CONTEXT = """\
Blade anatomy: a long, smooth composite (glass/carbon fibre) blade with a white or light-grey gelcoat or paint.
Parts: root (thick, round end near the hub), mid-span, tip (thin end), leading edge (rounded front edge that cuts
the wind; takes erosion), trailing edge (thin sharp back edge), pressure side and suction side (the two faces).

Normal features that are NOT defects (reject boxes on these unless there is visible damage on them):
- Lightning receptors: small round metal discs or bolts, usually near the tip, sometimes along the blade.
- Drain holes: a small round hole at the very tip.
- Vortex generators: rows of small triangular fins near the root on the suction side.
- Trailing-edge serrations: saw-tooth plastic strips along the trailing edge near the tip.
- Leading-edge protection tape or shells, and their straight overlapping seams.
- Paint seams, mould lines, straight factory joints, filler patches that are smooth and intact.
- Red/orange warning stripes at the tip, logos, stickers, serial numbers, markings, bolts at the root.
- A light, even film of dust or sand over the whole blade (normal in desert sites). If a "dirt" class is allowed,
  a distinct patch of dirt, oil, insect residue or droppings IS labelled "dirt" (low severity); otherwise reject it.
- Water droplets, rain, condensation, oil film that only reflects light.
- Shadows (including the drone's), glare and specular highlights, lens flare, motion blur, JPEG blocks, sensor noise.
- Anything that is not the blade: sky, clouds, tower, nacelle, hub, ground, sand, vegetation, buildings.
"""

# Per-class guidance. "looks_like": positive visual cues. "not": look-alikes to reject or relabel.
CLASS_GUIDE = {
    "crack": {
        "looks_like": [
            "a thin, dark, continuous line with a clear direction, usually jagged or zig-zag, sometimes branching",
            "edges of the line may be slightly raised, chipped or show a lighter halo of exposed filler/laminate",
            "often runs across (chordwise) or along (spanwise) the blade, at the trailing edge, root or near repairs",
            "it cuts THROUGH the surface: the line keeps its shape when the light changes",
        ],
        "not": [
            "a straight, perfectly regular line = paint seam, tape edge or mould line (reject)",
            "a soft-edged dark band that follows the blade curvature = shadow (reject)",
            "a fine NETWORK of many short hairlines = craze (clearly visible) or hide_craze (faint, under the coating) (relabel)",
            "a hair, cable, or the tower/sky edge seen behind the blade (reject)",
        ],
        "severity_hint": "long, wide, branching or open cracks, or cracks at the root / trailing edge bond line = high",
    },
    "craze": {
        "looks_like": [
            "a clearly VISIBLE web or mesh of fine hairline cracks on the coating surface, like crazed glaze on pottery",
            "the lines are sharp and easy to see in normal light; the coating may look dull or slightly raised along them",
            "covers a patch area rather than a single line",
        ],
        "not": [
            "the same mesh but faint, only visible at a low light angle, under a glossy intact coating = hide_craze (relabel)",
            "one dominant dark line = crack (relabel)",
            "parallel scratches or sanding marks (reject, or surface_injure if the coating is broken)",
        ],
        "severity_hint": "small patch = low/medium; large area or flaking coating = medium/high",
    },
    "hide_craze": {
        "looks_like": [
            "a web or mesh of many very fine hairline cracks, like crazed glaze on pottery or a spider web",
            "lines are faint, short and interconnected, often only visible at a low light angle",
            "partly under or within the coating: the surface still looks continuous and glossy",
            "covers a patch area rather than a single line",
        ],
        "not": [
            "one dominant dark line = crack (relabel)",
            "a clearly visible, sharp mesh on the surface = craze (relabel)",
            "scratches that are all parallel = handling scratches / sanding marks (reject unless coating is broken)",
            "dirt streaks or water marks that wipe-off-looking, with no crack pattern (reject)",
        ],
        "severity_hint": "small isolated patch = low/medium; large area or turning into open cracks = medium/high",
    },
    "surface_eye": {
        "looks_like": [
            "small round or oval point defects: pinholes, pits, voids, craters or blisters in the coating",
            "usually dark centres (a hole) or a light ring (a broken bubble), from a pinhead up to a few millimetres",
            "often appear in clusters or scattered over an area",
        ],
        "not": [
            "a single round METAL disc with a smooth rim = lightning receptor (reject)",
            "the drain hole at the very tip (reject)",
            "insect splats or dirt dots sitting on top of the surface (reject unless pitting is visible)",
            "water droplets: round, glossy, with bright reflections (reject)",
            "a hole with ragged material loss along the leading edge = erosion if that class exists",
        ],
        "severity_hint": "a few pinholes = low; dense clusters or pits that expose laminate = medium",
    },
    "corrosion": {
        "looks_like": [
            "rough, pitted, matt or flaking coating, most often along the leading edge, sometimes exposing grey/yellow laminate",
            "irregular patches of material loss with ragged edges, not a clean line",
            "can be spread over a band along the edge rather than a single spot",
        ],
        "not": [
            "dirt or insect build-up sitting on an intact leading edge = dirt (relabel) or reject",
            "leading-edge protection tape seams or overlaps that are straight and intact (reject)",
            "a few isolated tiny round pits = surface_eye (relabel)",
            "a fresh mechanical gouge, chip or scratch = surface_injure (relabel)",
        ],
        "severity_hint": "coating only = low/medium; exposed fibres or laminate = high",
    },
    "dirt": {
        "looks_like": [
            "a distinct patch or streak of dirt, mud, oil, insect residue or bird droppings ON the surface",
            "the coating underneath is intact: no material loss, no cracks, no raised edges",
            "often darker or brownish, with soft blotchy edges",
        ],
        "not": [
            "a light even film of dust over the whole blade (reject: normal in desert sites)",
            "shadows, reflections or water droplets (reject)",
            "dark material with rough edges or missing coating = corrosion (relabel)",
            "black scorch marks near a lightning receptor = thunderstrike (relabel)",
        ],
        "severity_hint": "almost always low; medium if it looks like an oil leak from the hub/pitch system",
    },
    "surface_injure": {
        "looks_like": [
            "mechanical surface damage: a chip, gouge, dent, deep scratch, scrape or a patch of peeled/missing coating",
            "usually a single localized area with sharp edges, where lighter filler or laminate may show",
        ],
        "not": [
            "rough pitted material loss along the leading edge = corrosion (relabel)",
            "a thin continuous fracture line = crack (relabel)",
            "dirt or stains with no broken surface = dirt (relabel) or reject",
            "painted markings, stickers or tape (reject)",
        ],
        "severity_hint": "coating only = low/medium; laminate exposed or large area = high",
    },
    "thunderstrike": {
        "looks_like": [
            "burn marks, black or brown scorching, soot, melted or delaminated material",
            "often near the tip or around a lightning receptor; can come with cracks or a split trailing edge",
        ],
        "not": [
            "a clean, intact metal lightning receptor disc (reject)",
            "dark dirt or oil streaks with no burn or material damage = dirt (relabel)",
            "a shadow or the warning-stripe paint at the tip (reject)",
        ],
        "severity_hint": "almost always high: hidden internal damage is likely",
    },
    "erosion": {
        "looks_like": ["roughened, pitted or missing coating along the leading edge, sometimes exposing laminate"],
        "not": ["dirt or insect build-up on an intact leading edge (reject)"],
        "severity_hint": "exposed fibres = high",
    },
    "lightning_strike": {
        "looks_like": ["burn marks, scorching, black soot, molten or delaminated material, often near a receptor"],
        "not": ["clean, intact lightning receptor disc (reject)"],
        "severity_hint": "almost always high",
    },
    "oil_leakage": {
        "looks_like": ["dark streaks or a film running radially from the root/hub area"],
        "not": ["general dirt evenly over the blade (reject)"],
        "severity_hint": "medium",
    },
}

GENERIC_GUIDE = {
    "looks_like": ["a visible defect of this type on the blade surface"],
    "not": ["normal blade features, background, shadows, reflections or dirt (reject)"],
    "severity_hint": "",
}

# Worked examples that show the expected judgement and JSON style (text only).
EXAMPLES = """\
Example judgements (illustrative, not about the current image):
- #1 proposed crack: thin dark zig-zag line about 15 cm long crossing the gelcoat at mid-span, chipped edges
  -> {"id": 1, "verdict": "confirmed", "class": "crack", "confidence": 0.92, "location": "mid-span, suction side",
      "reason": "Jagged dark line cutting through the coating with chipped edges."}
- #2 proposed surface_eye: one shiny round metal disc near the tip
  -> {"id": 2, "verdict": "rejected", "class": "surface_eye", "confidence": 0.88, "location": "near tip",
      "reason": "Intact lightning receptor, not a pit."}
- #3 proposed hide_craze: a single long dark line, no network
  -> {"id": 3, "verdict": "relabeled", "class": "crack", "confidence": 0.75, "location": "trailing edge",
      "reason": "One continuous line rather than a web of hairlines."}
- #4 proposed crack: straight soft dark band following the curve of the blade
  -> {"id": 4, "verdict": "rejected", "class": "crack", "confidence": 0.85, "location": "leading edge",
      "reason": "Shadow of the blade edge; no break in the surface."}
- missed: cluster of 6 tiny dark pits left of box #1 with no box
  -> {"class": "surface_eye", "box": [610, 220, 660, 300], "confidence": 0.72, "location": "mid-span",
      "reason": "Cluster of pinholes in the coating."}
"""

PROCEDURE = """\
How to work:
1. Find the blade in Image 1 and its orientation (root vs tip, leading vs trailing edge). Ignore everything that is not blade.
2. For each numbered box: look at Image 2 to find it, then at its zoom crop (if provided) for detail.
   Compare the inside of the box with the surrounding surface. Decide confirmed / relabeled / rejected using the
   class guide and the list of normal features. The box only needs to cover the defect roughly.
3. If two boxes cover the same defect, judge both the same way.
4. Then scan the whole blade systematically (root to tip, edge to edge) for CLEAR defects with no box.
   Report only defects you would bet on; when in doubt, leave them out.
5. Confidence = how sure you are of YOUR verdict:
   0.9-1.0 unmistakable, 0.7-0.9 clear, 0.5-0.7 plausible but the image is limited, below 0.5 guessing.
   Lower your confidence for blurry, distant, over-exposed or tiny regions instead of guessing a verdict.
6. Never invent classes. Use exactly the class names given.
"""


def class_section(classes):
    lines = []
    for c in classes:
        g = CLASS_GUIDE.get(c, GENERIC_GUIDE)
        lines.append(f'"{c}"')
        lines += [f"  + {x}" for x in g["looks_like"]]
        lines += [f"  - not: {x}" for x in g["not"]]
        if g.get("severity_hint"):
            lines.append(f"  severity: {g['severity_hint']}")
    return "\n".join(lines)


def system_prompt(classes, extra=""):
    out = (
        "You are a senior wind turbine blade inspection engineer (GWO/IEC 61400 experience) reviewing drone photos.\n"
        "An object detector (YOLO) proposed defect boxes. Your job is a careful second opinion: confirm real defects,\n"
        "correct the class when the detector chose the wrong one, reject false alarms, and point out clear defects it missed.\n\n"
        f"Allowed defect classes: {', '.join(classes)}\n\n"
        f"Class guide:\n{class_section(classes)}\n\n"
        f"{BLADE_CONTEXT}\n{PROCEDURE}\n{EXAMPLES}\n"
    )
    if extra and extra.strip():
        out += f"\nAdditional instructions from the inspection team:\n{extra.strip()}\n"
    out += (
        "\nReturn JSON only, no prose, in exactly this shape:\n"
        '{"boxes": [{"id": 1, "verdict": "confirmed|relabeled|rejected", "class": "<allowed class>", '
        '"confidence": 0.0, "location": "<part of the blade>", "reason": "<what you see, max 25 words>"}],\n'
        ' "missed": [{"class": "<allowed class>", "box": [ymin, xmin, ymax, xmax], "confidence": 0.0, '
        '"location": "<part of the blade>", "reason": "<what you see>"}]}\n'
        "Boxes use [ymin, xmin, ymax, xmax] normalized to 0-1000 on Image 1. Give every proposed id exactly one entry."
    )
    return out
