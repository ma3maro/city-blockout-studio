
"""Building profiles and their massing in local lot coordinates."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Form:
    width: tuple
    depth: tuple
    height: tuple
    colors: tuple


FORMS = {
    "MODEST": Form((6, 11), (7, 12), (4, 9), ("Clay", "Ochre", "Ivory")),
    "WESTERN": Form((7, 12), (9, 14), (6, 14), ("Brick", "Sandstone", "Brick Dark")),
    "UPSCALE": Form((10, 17), (10, 17), (8, 21), ("Limestone", "Ivory", "Sage")),
    "MODERN": Form((12, 19), (10, 17), (12, 33), ("Modern Cream", "Modern Graphite", "Sage")),
    "CORPORATE": Form((14, 21), (13, 19), (24, 56), ("Office Teal", "Office Blue", "Glass")),
    "TOWERS": Form((15, 24), (15, 22), (48, 106), ("Tower Blue", "Tower Pale", "Office Teal")),
    "INDUSTRIAL": Form((16, 27), (13, 23), (5, 13), ("Slate", "Warehouse", "Zinc")),
    "CIVIC": Form((15, 24), (12, 20), (9, 24), ("Limestone", "Sandstone", "Ivory")),
}

LABELS = {
    "MIXED": ("Mixed City", "Towers in the center, offices and apartments around them, lower buildings toward the edges"),
    "WESTERN": ("Western", "Traditional brick main streets and pitched-roof homes"),
    "MODERN": ("Modern", "Terraced apartments and clean contemporary blocks"),
    "CORPORATE": ("Corporate", "Glazed office blocks with stepped upper floors"),
    "BUSY": ("Busy Mixed Use", "Dense storefronts, apartments, and offices"),
    "QUIET": ("Quiet Residential", "Widely spaced homes and landscaped streets"),
    "EMPTY": ("Vacant", "Reserve open ground without buildings or trees"),
    "MODEST": ("Modest Residential", "Compact low-rise homes"),
    "UPSCALE": ("Upscale Residential", "Larger homes and terraced residences"),
    "TOWERS": ("Skyscrapers", "Tall stepped towers"),
    "INDUSTRIAL": ("Industrial", "Warehouses and service buildings"),
    "CIVIC": ("Civic", "Public-building massing with generous entrances"),
    "PARK": ("Park", "Open green space and trees"),
}

PALETTE = {
    "Base": "9baaa7", "Ground": "d4d0bd", "Paving": "aaa99b",
    "Avenue": "313c46", "Street": "454e54", "Lane": "f6ca73",
    "Crossing": "e6e2cf", "Lawn": "a8b68d",
    "Leaf": "617f6d", "Leaf Light": "829b74", "Bark": "63544a",
    "Clay": "bd8169", "Ochre": "c29a68", "Ivory": "dcd2b7",
    "Brick": "ae5e4e", "Brick Dark": "934f4b", "Sandstone": "cc9a73",
    "Limestone": "d1be9b", "Sage": "a5b2a1", "Modern Cream": "d3d7ca",
    "Modern Graphite": "788787", "Office Teal": "507d82", "Office Blue": "637b92",
    "Glass": "3f5b69", "Tower Blue": "4d7181", "Tower Pale": "86a6a9",
    "Slate": "7e8387", "Warehouse": "9e8376", "Zinc": "b1ad9e",
    "Roof": "858580", "Cap": "d6ccad", "Facade": "526366",
    "Lit Glass": "a89166", "Office Glazing": "739393", "Awning": "536b63",
    "Car Coral": "ba6256", "Car Cream": "ebdbc3", "Car Blue": "6c8f9b",
    "Car Yellow": "e1ad5b", "Car Window": "283b46", "Car Light": "ebe8d6",
    "Car Tail": "984844", "Rubber": "33343a", "Stone": "a09982",
    "Curb": "bab4a0", "Pole": "3f5355", "Light Shade": "d5c7a5",
}


def choose(profile, downtown, rng):
    if profile in FORMS:
        return profile
    if profile == "QUIET":
        return rng.choice(("MODEST", "MODEST", "WESTERN", "UPSCALE"))
    if profile == "BUSY":
        return rng.choice(("WESTERN", "WESTERN", "MODERN", "CORPORATE"))
    if profile == "MIXED":
        if downtown < .28:
            return rng.choice(("TOWERS", "TOWERS", "CORPORATE", "MODERN", "CIVIC"))
        if downtown < .55:
            return rng.choice(("CORPORATE", "MODERN", "MODERN", "WESTERN", "UPSCALE"))
        return rng.choice(("MODEST", "WESTERN", "UPSCALE", "INDUSTRIAL", "MODEST"))
    return None


def facade_panel(mesh, x, y, z, width, height, paint, turn=0):
    left,right = x-width*.5,x+width*.5
    face = ((left,y,z),(right,y,z),(right,y,z+height),(left,y,z+height))
    mesh.face([(-b*turn,a*turn,c) for a,b,c in face] if turn else face,paint)


def window_row(mesh, x, y, z, width, height, bays, rng, fill=.66, frame="Facade", turn=0):
    pitch = width/bays
    for i in range(bays):
        mid = x+(i+.5-bays*.5)*pitch
        glass = "Lit Glass" if rng.random() < .18 else frame
        facade_panel(mesh,mid,y,z,pitch*fill,height,glass,turn)


def massing(mesh, kind, w, d, h, rng, details=False):
    color = rng.choice(FORMS[kind].colors)

    def box(bw, bd, base, height, wall=color, roof="Cap", x=0, y=0):
        mesh.box(x, y, bw, bd, base, height, wall, roof)

    if kind == "MODEST":
        box(w, d, 0, h, color, "Roof")
        mesh.gable(w, d, h, min(2.8, w * .32), color, "Roof")
        if rng.random() < .6:
            box(w * .37, d * .33, 0, h * .56, color, "Roof", y=d * .34)
        if details:
            facade_panel(mesh,0,-d*.501,0.,.92,min(2.24,h*.52),"Facade")
            for side in (-1,1):
                facade_panel(mesh,side*w*.29,-d*.501,h*.34,w*.16,h*.23,"Office Glazing")
                window_row(mesh,0,-w*.502,h*.36,d*.62,h*.21,2,rng,turn=side)
            box(1.55,.8,.01,.17,"Stone",x=0,y=-d*.5)
    elif kind == "WESTERN":
        box(w, d, 0, h, color, "Roof")
        box(w * .83, .12, h * .08, h * .28, "Facade", "Facade", y=-d * .5)
        box(w, .64, h * .34, .24, "Cap", "Cap", y=-d * .46)
        box(w, .36, h, .75, color, "Cap", y=-d * .47)
        for x in (-w * .29, 0., w * .29):
            box(w * .11, .1, h * .53, h * .22, "Facade", "Facade", x=x, y=-d * .5)
        if details:
            if rng.random() < .67:
                box(w*.74,.98,h*.36,.17,rng.choice(("Awning","Brick Dark","Roof")),y=-d*.51)
            for x in (-w*.29,0.,w*.29):
                facade_panel(mesh,x,-d*.503-.05,h*.57,w*.071,h*.15,"Office Glazing")
            for x in (-w*.27,0.,w*.27):
                facade_panel(mesh,x,-d*.503-.06,h*.13,w*.2,h*.17,"Office Glazing")
            for side in (-1,1):
                window_row(mesh,0,-w*.502,h*.55,d*.82,h*.22,4,rng,frame="Office Glazing",turn=side)
                window_row(mesh,0,-w*.502,h*.16,d*.78,h*.16,3,rng,fill=.48,turn=side)
    elif kind == "UPSCALE":
        box(w, d, 0, h * .55)
        box(w * .78, d * .78, h * .55, h * .45, x=w * .06)
        box(w * .35, d * .28, h, .65, "Roof", x=w * .11)
        if details:
            window_row(mesh,0,-d*.502,h*.19,w*.87,h*.16,4,rng)
            window_row(mesh,w*.06,-d*.392,h*.68,w*.7,h*.16,3,rng)
    elif kind == "MODERN":
        box(w, d, 0, h * .28)
        box(w * .63, d * .85, h * .28, h * .72, x=w * .12)
        box(w * .25, d * .76, h * .28, h * .48, "Glass", x=-w * .31)
        for step in (.45, .61, .78, .94):
            box(w * .66, d * .17, h * step, .24, "Cap", x=w * .12, y=-d * .41)
        if details:
            window_row(mesh,0,-d*.502,h*.11,w*.92,h*.1,5,rng,frame="Office Glazing")
            for level in (.34,.5,.67,.83):
                window_row(mesh,w*.12,-d*.427,h*level,w*.57,h*.08,3,rng,frame="Office Glazing")
    elif kind in {"CORPORATE", "TOWERS"}:
        box(w, d, 0, h * .16, "Glass")
        narrow = rng.uniform(.74, .86)
        cut_corners = kind == "TOWERS" and rng.random() < .35
        if cut_corners:
            mesh.chamfered(w * narrow, d * narrow, h * .16, h * .77, color)
            mesh.chamfered(w * .53, d * .56, h * .93, h * .07, "Tower Pale")
        else:
            box(w * narrow, d * narrow, h * .16, h * .65)
            box(w * .67, d * .66, h * .81, h * .19)
        if rng.random() < .7:
            box(w * .27, d * .31, h, h * .044, "Glass")
        if kind == "TOWERS" and rng.random() < .35:
            box(.5, .5, h * 1.044, h * .115, "Cap")
        for level in (.31, .52, .73):
            box(w * (narrow + .009), d * .12, h * level, .31, "Glass", y=-d * narrow * .45)
        if details:
            levels = max(3,min(13,round(h/7)))
            pitch = h*.59/levels
            span = w*narrow*(.69 if cut_corners else .93)
            for i in range(levels):
                window_row(mesh,0,-d*narrow*.502,h*.18+i*pitch,span,pitch*.59,5,rng,frame="Office Glazing")
                for side in (-1,1):
                    depth = d*narrow*(.69 if cut_corners else .91)
                    window_row(mesh,0,-w*narrow*.502,h*.18+i*pitch,depth,pitch*.59,4,rng,
                               frame="Office Glazing",turn=side)
    elif kind == "INDUSTRIAL":
        box(w, d, 0, h, color, "Zinc")
        for x in (-w * .27, 0, w * .27):
            box(w * .13, d * .69, h, .62, "Roof", "Zinc", x=x)
        box(w * .56, .18, .06, h * .48, "Facade", "Zinc", y=-d * .5)
        if details:
            window_row(mesh,0,-d*.502,h*.65,w*.82,h*.14,7,rng)
    else:
        box(w, d, 0, h * .26)
        box(w * .77, d * .7, h * .26, h * .74)
        box(w * .58, d * .2, h * .52, .58, "Cap", y=-d * .4)
        for x in (-w * .22, -w * .07, w * .07, w * .22):
            box(.48, .48, h * .26, h * .26, "Ivory", x=x, y=-d * .45)
        if details:
            window_row(mesh,0,-d*.352,h*.57,w*.72,h*.13,5,rng)
