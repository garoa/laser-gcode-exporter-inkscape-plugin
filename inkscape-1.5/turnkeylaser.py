#!/usr/bin/env python3
# coding=utf-8
"""
TurnkeyLaserExporter

-----------------------------------
Maintained by Turnkey Tyranny (https://github.com/TurnkeyTyranny/laser-gcode-exporter-inkscape-plugin)
Designed to run on Ramps 1.4 + Marlin firmware on a K40 CO2 Laser Cutter.
Based on think|haus gcode inkscape extension
Based on a script by Nick Drobchenko from the CNC club

***

Copyright (C) 2009 Nick Drobchenko, nick@cnc-club.ru
based on gcode.py (C) 2007 hugomatic...
based on addnodes.py (C) 2005,2007 Aaron Spike, aaron@ekips.org
based on dots.py (C) 2005 Aaron Spike, aaron@ekips.org
based on interp.py (C) 2005 Aaron Spike, aaron@ekips.org

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

-----------------------------------
See CHANGELOG.md for the release history.  This file requires Inkscape 1.0 or
newer and Python 3.6+.  It has been verified against Inkscape 1.3 (inkex 1.3.0,
Python 3.10); the 1.0/1.1 compatibility fallbacks follow the documented API but
have not been exercised on those releases.
"""

###
###        Gcode tools
###

import base64
import math
import os
import re
import subprocess
import sys
import tempfile

from io import BytesIO

from lxml import etree

import inkex
from inkex import bezier
from inkex.paths import Path
from inkex.transforms import Transform
from inkex.units import convert_unit

try:
    # inkex.command appeared in Inkscape 1.0 and is the supported way of
    # shelling back out to the Inkscape binary from within an extension.
    from inkex.command import inkscape as inkscape_command
except ImportError:  # pragma: no cover - very old inkex
    inkscape_command = None

# Image processing for rastering.  Pillow is optional: without it vector
# cutting still works and only raster objects are refused with a clear message.
try:
    from PIL import Image, ImageOps
    HAS_PIL = True
except ImportError:
    Image = None
    ImageOps = None
    HAS_PIL = False


################################################################################
###
###        Constants
###
################################################################################

VERSION = "2.0.0"

STRAIGHT_TOLERANCE = 0.0001
STRAIGHT_DISTANCE_TOLERANCE = 0.0001
LASER_ON = "M3 ;turn the laser on"          # LASER ON MCODE
LASER_OFF = "M5 ;turn the laser off\n"        # LASER OFF MCODE

HEADER_TEXT = ""
FOOTER_TEXT = ""

# Emitted between the two passes of a double sided cut so the operator can be
# prompted to flip the material over.
TOOL_CHANGE = "M6 T%d ;tool change\n"

# Dots per inch the raster images are exported at.  The millimetres per raster
# pixel value handed to the firmware (the R word of M649) is 25.4 / RASTER_DPI.
RASTER_DPI = 270.0

# SVG user units are 1/96th of an inch in SVG 1.1 / Inkscape 1.x.  Inkscape
# 0.48 used 1/90th of an inch, which is why the old exporter used 0.28222.
PX_PER_INCH = 96.0

BIARC_STYLE = {
    'biarc0': str(inkex.Style({'stroke': '#88f', 'fill': 'none', 'stroke-width': '1'})),
    'biarc1': str(inkex.Style({'stroke': '#8f8', 'fill': 'none', 'stroke-width': '1'})),
    'line': str(inkex.Style({'stroke': '#f88', 'fill': 'none', 'stroke-width': '1'})),
    'area': str(inkex.Style({'stroke': '#777', 'fill': 'none', 'stroke-width': '0.1'})),
}

# Inkscape group tag
SVG_GROUP_TAG = inkex.addNS("g", "svg")
SVG_PATH_TAG = inkex.addNS('path', 'svg')
SVG_IMAGE_TAG = inkex.addNS('image', 'svg')
SVG_TEXT_TAG = inkex.addNS('text', 'svg')
SVG_LABEL_TAG = inkex.addNS("label", "inkscape")


GCODE_EXTENSION = ".g"  # changed to be Marlin friendly (ajf)

options = {}

################################################################################
###
###        Common functions
###
################################################################################


###
###        Just simple output function for better debugging
###

class Logger(object):
    first = True
    enabled = True

    def __init__(self):
        home = os.getenv("HOME") or os.getenv("USERPROFILE") or tempfile.gettempdir()
        self.logpath = os.path.join(home, "thlaser.log")

    def write(self, s):
        if not self.enabled:
            return

        if self.first and os.path.isfile(self.logpath):
            try:
                os.remove(self.logpath)
            except OSError:
                pass
        self.first = False

        try:
            with open(self.logpath, "a") as fhl:
                fhl.write(str(s) + "\n")
        except IOError:
            # Never let logging break an export.
            self.enabled = False


# The global logger object
logger = Logger()


###
###        Point (x,y) operations
###
## Pretty much what it sounds like: defines some arithmetic functions that can be applied to points.
class P:
    def __init__(self, x, y=None):
        if y is not None:
            self.x, self.y = float(x), float(y)
        else:
            self.x, self.y = float(x[0]), float(x[1])

    def __add__(self, other):
        return P(self.x + other.x, self.y + other.y)

    def __sub__(self, other):
        return P(self.x - other.x, self.y - other.y)

    def __neg__(self):
        return P(-self.x, -self.y)

    def __mul__(self, other):
        if isinstance(other, P):
            return self.x * other.x + self.y * other.y
        return P(self.x * other, self.y * other)
    __rmul__ = __mul__

    # Python 3 renamed __div__ to __truediv__; both are kept so the class keeps
    # behaving the same way it always did.
    def __truediv__(self, other):
        return P(self.x / other, self.y / other)
    __div__ = __truediv__

    def mag(self):
        return math.hypot(self.x, self.y)

    def unit(self):
        h = self.mag()
        if h:
            return self / h
        return P(0, 0)

    def dot(self, other):
        return self.x * other.x + self.y * other.y

    def rot(self, theta):
        c = math.cos(theta)
        s = math.sin(theta)
        return P(self.x * c - self.y * s, self.x * s + self.y * c)

    def angle(self):
        return math.atan2(self.y, self.x)

    def __repr__(self):
        return '%f,%f' % (self.x, self.y)

    def pr(self):
        return "%.2f,%.2f" % (self.x, self.y)

    def to_list(self):
        return [self.x, self.y]


###
###        Functions to operate with CubicSuperPath
###

def csp_at_t(sp1, sp2, t):
    bez = (sp1[1][:], sp1[2][:], sp2[0][:], sp2[1][:])
    return bezier.bezierpointatt(bez, t)


def cspbezsplit(sp1, sp2, t=0.5):
    s1, s2 = bezier.beziersplitatt((sp1[1], sp1[2], sp2[0], sp2[1]), t)
    return [[sp1[0][:], sp1[1][:], list(s1[1])],
            [list(s1[2]), list(s1[3]), list(s2[1])],
            [list(s2[2]), sp2[1][:], sp2[2][:]]]


def cspbezsplitatlength(sp1, sp2, l=0.5, tolerance=0.01):
    bez = (sp1[1][:], sp1[2][:], sp2[0][:], sp2[1][:])
    t = bezier.beziertatlength(bez, l, tolerance)
    return cspbezsplit(sp1, sp2, t)


def cspseglength(sp1, sp2, tolerance=0.001):
    bez = (sp1[1][:], sp1[2][:], sp2[0][:], sp2[1][:])
    return bezier.bezierlength(bez, tolerance)


def csplength(csp):
    total = 0
    lengths = []
    for sp in csp:
        for i in range(1, len(sp)):
            l = cspseglength(sp[i - 1], sp[i])
            lengths.append(l)
            total += l
    return lengths, total


###
###        Distance calculattion from point to arc
###

def between(c, x, y):
    return x - STRAIGHT_TOLERANCE <= c <= y + STRAIGHT_TOLERANCE or \
        y - STRAIGHT_TOLERANCE <= c <= x + STRAIGHT_TOLERANCE


def distance_from_point_to_arc(p, arc):
    P0, P2, c, a = arc
    p = P(p)
    r = (P0 - c).mag()
    if r > 0:
        i = c + (p - c).unit() * r
        alpha = ((i - c).angle() - (P0 - c).angle())
        if a * alpha < 0:
            if alpha > 0:
                alpha = alpha - 2 * math.pi
            else:
                alpha = 2 * math.pi + alpha
        if between(alpha, 0, a) or min(abs(alpha), abs(alpha - a)) < STRAIGHT_TOLERANCE:
            return (p - i).mag(), [i.x, i.y]
        d1, d2 = (p - P0).mag(), (p - P2).mag()
        if d1 < d2:
            return (d1, [P0.x, P0.y])
        return (d2, [P2.x, P2.y])
    # Degenerate arc (zero radius): fall back to the distance to its centre.
    # The Python 2 version returned None here, which blows up under Python 3
    # as soon as min() tries to order it against a tuple.
    return ((p - c).mag(), [c.x, c.y])


def get_distance_from_csp_to_arc(sp1, sp2, arc1, arc2, tolerance=0.001):
    # arc = [start,end,center,alpha]
    n, i = 10, 0
    d1, dl = (0, (0, 0)), (0, (0, 0))
    while i < 1 or (abs(d1[0] - dl[0]) > tolerance and i < 2):
        i += 1
        dl = d1
        for j in range(n + 1):
            t = float(j) / n
            p = csp_at_t(sp1, sp2, t)
            da = distance_from_point_to_arc(p, arc1)
            db = distance_from_point_to_arc(p, arc2)
            d = da if da[0] <= db[0] else db
            # Compare on the distance only.  Python 3 refuses to order the
            # (float, list) tuples themselves once the floats tie.
            if d[0] > d1[0]:
                d1 = d
        n = n * 2
    return d1[0]

################################################################################
###
###        Biarc function
###
###        Calculates biarc approximation of cubic super path segment
###        splits segment if needed or approximates it with straight line
###
################################################################################


def biarc(sp1, sp2, z1, z2, depth=0):
    def biarc_split(sp1, sp2, z1, z2, depth):
        if depth < options.biarc_max_split_depth:
            sp1, sp2, sp3 = cspbezsplit(sp1, sp2)
            l1, l2 = cspseglength(sp1, sp2), cspseglength(sp2, sp3)
            if l1 + l2 == 0:
                zm = z1
            else:
                zm = z1 + (z2 - z1) * l1 / (l1 + l2)
            # The original passed the arguments in the wrong order here
            # (depth where z1 was expected), so the recursion never honoured
            # the split depth limit correctly.
            return biarc(sp1, sp2, z1, zm, depth + 1) + biarc(sp2, sp3, zm, z2, depth + 1)
        return [[sp1[1], 'line', 0, 0, sp2[1], [z1, z2]]]

    P0, P4 = P(sp1[1]), P(sp2[1])
    TS, TE, v = (P(sp1[2]) - P0), -(P(sp2[0]) - P4), P0 - P4
    tsa, tea, va = TS.angle(), TE.angle(), v.angle()
    if TE.mag() < STRAIGHT_DISTANCE_TOLERANCE and TS.mag() < STRAIGHT_DISTANCE_TOLERANCE:
        # Both tangents are zerro - line straight
        return [[sp1[1], 'line', 0, 0, sp2[1], [z1, z2]]]
    if TE.mag() < STRAIGHT_DISTANCE_TOLERANCE:
        TE = -(TS + v).unit()
        r = TS.mag() / v.mag() * 2
    elif TS.mag() < STRAIGHT_DISTANCE_TOLERANCE:
        TS = -(TE + v).unit()
        r = 1 / (TE.mag() / v.mag() * 2)
    else:
        r = TS.mag() / TE.mag()
    TS, TE = TS.unit(), TE.unit()
    tang_are_parallel = ((tsa - tea) % math.pi < STRAIGHT_TOLERANCE or
                         math.pi - (tsa - tea) % math.pi < STRAIGHT_TOLERANCE)
    if (tang_are_parallel and
            ((v.mag() < STRAIGHT_DISTANCE_TOLERANCE or
              TE.mag() < STRAIGHT_DISTANCE_TOLERANCE or
              TS.mag() < STRAIGHT_DISTANCE_TOLERANCE) or
             1 - abs(TS * v / (TS.mag() * v.mag())) < STRAIGHT_TOLERANCE)):
        # Both tangents are parallel and start and end are the same - line straight
        # or one of tangents still smaller then tollerance

        # Both tangents and v are parallel - line straight
        return [[sp1[1], 'line', 0, 0, sp2[1], [z1, z2]]]

    c, b, a = v * v, 2 * v * (r * TS + TE), 2 * r * (TS * TE - 1)
    if v.mag() == 0:
        return biarc_split(sp1, sp2, z1, z2, depth)
    asmall, bsmall, csmall = abs(a) < 10 ** -10, abs(b) < 10 ** -10, abs(c) < 10 ** -10
    if asmall and b != 0:
        beta = -c / b
    elif csmall and a != 0:
        beta = -b / a
    elif not asmall:
        discr = b * b - 4 * a * c
        if discr < 0:
            raise ValueError((a, b, c, discr))
        disq = discr ** .5
        beta1 = (-b - disq) / 2 / a
        beta2 = (-b + disq) / 2 / a
        if beta1 * beta2 > 0:
            raise ValueError((a, b, c, disq, beta1, beta2))
        beta = max(beta1, beta2)
    elif asmall and bsmall:
        return biarc_split(sp1, sp2, z1, z2, depth)
    alpha = beta * r
    ab = alpha + beta
    P1 = P0 + alpha * TS
    P3 = P4 - beta * TE
    P2 = (beta / ab) * P1 + (alpha / ab) * P3

    def calculate_arc_params(P0, P1, P2):
        D = (P0 + P2) / 2
        if (D - P1).mag() == 0:
            return None, None
        R = D - ((D - P0).mag() ** 2 / (D - P1).mag()) * (P1 - D).unit()
        p0a, p1a, p2a = (P0 - R).angle() % (2 * math.pi), (P1 - R).angle() % (2 * math.pi), \
            (P2 - R).angle() % (2 * math.pi)
        alpha = (p2a - p0a) % (2 * math.pi)
        if (p0a < p2a and (p1a < p0a or p2a < p1a)) or (p2a < p1a < p0a):
            alpha = -2 * math.pi + alpha
        # ".mag" (the bound method) used to be compared against a float here,
        # which silently never triggered on Python 2 and is a TypeError on 3.
        if abs(R.x) > 1000000 or abs(R.y) > 1000000 or (R - P0).mag() < options.min_arc_radius:
            return None, None
        return R, alpha

    R1, a1 = calculate_arc_params(P0, P1, P2)
    R2, a2 = calculate_arc_params(P2, P3, P4)
    if R1 is None or R2 is None or (R1 - P0).mag() < STRAIGHT_TOLERANCE or \
            (R2 - P2).mag() < STRAIGHT_TOLERANCE:
        return [[sp1[1], 'line', 0, 0, sp2[1], [z1, z2]]]

    d = get_distance_from_csp_to_arc(sp1, sp2, [P0, P2, R1, a1], [P2, P4, R2, a2])
    if d > options.biarc_tolerance and depth < options.biarc_max_split_depth:
        return biarc_split(sp1, sp2, z1, z2, depth)

    if R2.mag() * a2 == 0:
        zm = z2
    else:
        zm = z1 + (z2 - z1) * (R1.mag() * a1) / (R2.mag() * a2 + R1.mag() * a1)
    return [[sp1[1], 'arc', [R1.x, R1.y], a1, [P2.x, P2.y], [z1, zm]],
            [[P2.x, P2.y], 'arc', [R2.x, R2.y], a2, [P4.x, P4.y], [zm, z2]]]


################################################################################
###
###        Inkscape helper functions
###
################################################################################

# Returns true if the given node is a layer
def is_layer(node):
    return (node.tag == SVG_GROUP_TAG and
            node.get(inkex.addNS("groupmode", "inkscape")) == "layer")


def get_layers(document):
    layers = []
    root = document.getroot()
    for node in root.iterchildren():
        if is_layer(node):
            # Found an inkscape layer
            layers.append(node)
    return layers


def parse_layer_name(txt):
    params = {}
    try:
        n = txt.index("[")
    except ValueError:
        layerName = txt.strip()
    else:
        layerName = txt[0:n].strip()
        args = txt[n + 1:].strip()
        if args.endswith("]"):
            args = args[0:-1]

        for arg in args.split(","):
            try:
                (field, value) = arg.split("=")
            except ValueError:
                raise ValueError("Invalid argument in layer '%s'" % layerName)
            if field == "feed" or field == "ppm":
                try:
                    value = float(value)
                except ValueError:
                    raise ValueError("Invalid layer name '%s'" % value)
            params[field] = value
            logger.write("%s == %s" % (field, value))

    return (layerName, params)


def parse_viewbox(svg):
    """Return the document's viewBox as four floats, or None when unusable."""
    raw = svg.get("viewBox")
    if not raw:
        return None
    try:
        parts = [float(v) for v in re.split(r'[\s,]+', raw.strip()) if v]
    except ValueError:
        return None
    if len(parts) != 4 or parts[2] == 0 or parts[3] == 0:
        return None
    return parts


################################################################################
###
###        Gcode tools class
###
################################################################################


class Gcode_tools(inkex.EffectExtension):
    """Export selected Inkscape paths and images as laser gcode."""

    def add_arguments(self, pars):
        outdir = os.getenv("HOME") or os.getenv("USERPROFILE")
        if outdir:
            outdir = os.path.join(outdir, "Desktop")
        else:
            outdir = os.getcwd()

        pars.add_argument("-d", "--directory", default=outdir, help="Directory for gcode file")
        pars.add_argument("-f", "--filename", dest="file", default="-1.0", help="File name")
        pars.add_argument("-u", "--Xscale", type=float, default=1.0, help="Scale factor X")
        pars.add_argument("-v", "--Yscale", type=float, default=1.0, help="Scale factor Y")
        pars.add_argument("-x", "--Xoffset", type=float, default=0.0, help="Offset along X")
        pars.add_argument("-y", "--Yoffset", type=float, default=0.0, help="Offset along Y")
        # added move (laser off) feedrate and laser intensity; made all int rather than float - (ajf)

        pars.add_argument("-m", "--Mfeed", type=int, default=2000,
                          help="Default Move Feed rate in unit/min")
        pars.add_argument("-p", "--feed", type=int, default=300,
                          help="Default Cut Feed rate in unit/min")
        pars.add_argument("-l", "--laser", type=int, default=10,
                          help="Default Laser intensity (0-100 %%)")
        pars.add_argument("-b", "--homebefore", type=inkex.Boolean, default=True,
                          help="Home X and Y before starting (G28 XY)")
        pars.add_argument("-a", "--homeafter", type=inkex.Boolean, default=False,
                          help="Home X Y at end of job")

        pars.add_argument("--biarc-tolerance", type=float, dest="biarc_tolerance", default=1.0,
                          help="Tolerance used when calculating biarc interpolation.")
        pars.add_argument("--biarc-max-split-depth", type=int, dest="biarc_max_split_depth",
                          default=4,
                          help="Defines maximum depth of splitting while approximating using biarcs.")

        pars.add_argument("--unit", default="mm", help="Units")
        pars.add_argument("--function", default="Curve",
                          help="What to do: Curve|Area|Area inkscape")
        pars.add_argument("--tab", default="", help="Means nothing right now. Notebooks Tab.")
        pars.add_argument("--double_sided_cutting", type=inkex.Boolean, default=False,
                          help="Generate code for double-sided cutting.")
        pars.add_argument("--draw-curves", type=inkex.Boolean, dest="drawCurves", default=False,
                          help="Draws curves to show what geometry was processed")
        pars.add_argument("--logging", type=inkex.Boolean, default=False,
                          help="Enable output logging from the plugin")

        pars.add_argument("--loft-distances", dest="loft_distances", default="10",
                          help="Distances between paths.")
        pars.add_argument("--loft-direction", dest="loft_direction", default="crosswise",
                          help="Direction of loft's interpolation.")
        pars.add_argument("--loft-interpolation-degree", type=float,
                          dest="loft_interpolation_degree", default=2.0,
                          help="Which interpolation use to loft the paths smooth interpolation or staright.")

        pars.add_argument("--min-arc-radius", type=float, dest="min_arc_radius", default=0.0005,
                          help="All arc having radius less than minimum will be considered as straight line")
        pars.add_argument("--mainboard", default="ramps", help="Mainboard")
        pars.add_argument("--pronterface", type=inkex.Boolean, default=True,
                          help="Are you using Pronterface? If so we need to change some characters "
                               "in the GCode raster data to keep pronterface happy. Slight loss of "
                               "intensity on pure blacks but nothing major.")
        pars.add_argument("--origin", default="topleft", help="Origin of the Y Axis")
        pars.add_argument("--optimiseraster", type=inkex.Boolean, default=True,
                          help="Optimise raster horizontal scanning speed")

    def parse_curve(self, path):
        xs, ys = 1.0, 1.0

        if path['type'] == "vector":
            lst = {}
            lst['type'] = "vector"
            lst['data'] = []
            for subpath in path['data']:
                lst['data'].append(
                    [[subpath[0][1][0] * xs, subpath[0][1][1] * ys], 'move', 0, 0]
                )
                for i in range(1, len(subpath)):
                    sp1 = [[subpath[i - 1][j][0] * xs, subpath[i - 1][j][1] * ys] for j in range(3)]
                    sp2 = [[subpath[i][j][0] * xs, subpath[i][j][1] * ys] for j in range(3)]
                    lst['data'] += biarc(sp1, sp2, 0, 0)

                lst['data'].append(
                    [[subpath[-1][1][0] * xs, subpath[-1][1][1] * ys], 'end', 0, 0]
                )
            return lst
        # Raster image data, cut/burn left to right, drop down a line, repeat in reverse until completed.
        # No need to modify
        return path

    def draw_curve(self, curve, group=None, style=BIARC_STYLE):
        if group is None:
            group = etree.SubElement(self.biarcGroup, SVG_GROUP_TAG)
        s, arcn = '', 0
        for si in curve:
            if s != '':
                if s[1] == 'line':
                    etree.SubElement(group, SVG_PATH_TAG,
                                     {
                                         'style': style['line'],
                                         'd': 'M %s,%s L %s,%s' % (s[0][0], s[0][1], si[0][0], si[0][1]),
                                         'comment': str(s)
                                     })
                elif s[1] == 'arc':
                    arcn += 1
                    sp = s[0]
                    c = s[2]
                    a = ((P(si[0]) - P(c)).angle() - (P(s[0]) - P(c)).angle()) % (2 * math.pi)  # s[3]
                    if s[3] * a < 0:
                        if a > 0:
                            a = a - 2 * math.pi
                        else:
                            a = 2 * math.pi + a
                    r = math.sqrt((sp[0] - c[0]) ** 2 + (sp[1] - c[1]) ** 2)
                    a_st = (math.atan2(sp[0] - c[0], -(sp[1] - c[1])) - math.pi / 2) % (math.pi * 2)
                    if a > 0:
                        a_end = a_st + a
                    else:
                        a_end = a_st * 1
                        a_st = a_st + a
                    etree.SubElement(group, SVG_PATH_TAG,
                                     {
                                         'style': style['biarc%s' % (arcn % 2)],
                                         inkex.addNS('cx', 'sodipodi'): str(c[0]),
                                         inkex.addNS('cy', 'sodipodi'): str(c[1]),
                                         inkex.addNS('rx', 'sodipodi'): str(r),
                                         inkex.addNS('ry', 'sodipodi'): str(r),
                                         inkex.addNS('start', 'sodipodi'): str(a_st),
                                         inkex.addNS('end', 'sodipodi'): str(a_end),
                                         inkex.addNS('open', 'sodipodi'): 'true',
                                         inkex.addNS('type', 'sodipodi'): 'arc',
                                         'comment': str(s)
                                     })
            s = si

    def check_dir(self):
        if os.path.isdir(self.options.directory):
            if os.path.isfile(os.path.join(self.options.directory, 'header')):
                with open(os.path.join(self.options.directory, 'header'), 'r') as fhl:
                    self.header = fhl.read()
            else:
                self.header = HEADER_TEXT
            if os.path.isfile(os.path.join(self.options.directory, 'footer')):
                with open(os.path.join(self.options.directory, 'footer'), 'r') as fhl:
                    self.footer = fhl.read()
            else:
                self.footer = FOOTER_TEXT
        else:
            inkex.errormsg("Directory specified for output gcode does not exist! Please create it.")
            return False

        return True

    # Turns a list of arguments into gcode-style parameters (eg (1, 2, 3) -> "X1 Y2 Z3"),
    # taking scaling, offsets and the "parametric curve" setting into account
    def make_args(self, c):
        c = [c[i] if i < len(c) else None for i in range(6)]
        if c[5] == 0:
            c[5] = None
        # next few lines generate the stuff at the front of the file - scaling, offsets, etc (adina)
        s = ["X", "Y", "Z", "I", "J", "K"]
        s1 = ["", "", "", "", "", ""]

        m = [self.options.Xscale, -self.options.Yscale, 1,
             self.options.Xscale, -self.options.Yscale, 1]
        a = [self.options.Xoffset, self.options.Yoffset, 0, 0, 0, 0]

        # There's no aphrodisiac like loneliness
        # Add the page height if the origin is the bottom left.
        if self.options.origin != 'topleft':
            a[1] += self.pageHeight

        args = []
        for i in range(6):
            if c[i] is not None:
                value = self.unitScale * (c[i] * m[i] + a[i])
                args.append(s[i] + ("%.3f" % value) + s1[i])
        return " ".join(args)

    def generate_raster_gcode(self, curve, laserPower, altfeed=None):
        gcode = ''

        # Setup our feed rate, either from the layer name or from the default value.
        if altfeed:
            # Use the "alternative" feed rate specified
            cutFeedValue = int(altfeed)
        else:
            cutFeedValue = int(self.options.feed)
        cutFeed = "F%i" % cutFeedValue

        # Rasters are exported at RASTER_DPI, so the millimetres covered by a
        # single raster pixel is 25.4 / RASTER_DPI = 0.09407mm at 270dpi.
        # Note this is independent of the SVG user unit (90dpi on Inkscape
        # 0.48, 96dpi on 1.x) because --export-dpi is a physical measure.
        rasterStep = 25.4 / RASTER_DPI
        gcode += '\n\n;Beginning of Raster Image ' + str(curve['id']) + ' pixel size: ' + \
                 str(curve['width']) + 'x' + str(curve['height']) + '\n'
        gcode += 'M649 S' + str(laserPower) + ' B2 D0 R%.5f\n' % rasterStep

        # Do not remove these two lines, they're important. Will not raster correctly if feedrate is not set prior.
        # Move fast to point, cut at correct speed.
        # (The original compared the "F300" string against an int here, which
        # is a TypeError on Python 3.)
        if cutFeedValue < self.options.Mfeed:
            gcode += 'G0 X' + str(curve['x']) + ' Y' + str(curve['y']) + \
                     ' F' + str(self.options.Mfeed) + '\n'
        gcode += 'G0 X' + str(curve['x']) + ' Y' + str(curve['y']) + ' ' + cutFeed + '\n'

        def get_chunks(arr, chunk_size=51):
            return [arr[start:start + chunk_size] for start in range(0, len(arr), chunk_size)]

        # return the first pixel that holds data.
        def first_in_list(arr):
            end = 0
            for i in range(len(arr)):
                if arr[i] == 0:
                    end = i
                if arr[i] > 0:
                    break
            return end

        # does this line have any data?
        def is_blank_line(arr):
            for i in range(len(arr)):
                if arr[i] > 0:
                    return False
            return True

        # return the last pixel that holds data.
        def last_in_list(arr):
            end = len(arr)
            for i in range(len(arr)):
                if arr[i] > 0:
                    end = i
            return end

        # Flip the image top to bottom.
        row = curve['data'][::-1]

        previousRight = 99999999999
        previousLeft = 0
        firstRow = True
        forward = True

        for index, rowData in enumerate(row):

            splitRight = 0
            splitLeft = 0

            # Turnkey - 11-04-15
            # The below allows iteration over blank lines, while still being 'mostly' optimised for path. could still do with a little improvement for optimising horizontal movement and extrenuous for loops.
            sub_index = index + 1
            if sub_index < len(row):
                while is_blank_line(row[sub_index - 1]):
                    if sub_index < len(row):
                        sub_index += 1
                    else:
                        break
            # are we processing data before the last line?
            if sub_index < len(row):
                # Determine where to split the lines.
                ##################################################

                # If the left most pixel of the next row is earlier than the current row, then extend.
                if first_in_list(row[sub_index]) > first_in_list(rowData):
                    splitLeft = first_in_list(rowData)
                else:
                    splitLeft = first_in_list(row[sub_index])

                # If the end pixel of the next line is later than the current line, extend.
                if last_in_list(row[sub_index]) > last_in_list(rowData):
                    splitRight = last_in_list(row[sub_index])
                else:
                    splitRight = last_in_list(rowData)

            else:
                splitLeft = first_in_list(rowData)
                splitRight = last_in_list(rowData)

            # Positive direction
            if forward:
                # Split the right side.
                ###########################################

                # Don't split more than the start of the last row as we print in reverse for alternate lines
                splitLeft = previousLeft
                previousRight = splitRight

            # Negative direction
            else:
                # Split the left side.
                ###########################################

                # Don't split more than the end of the last row as we print in reverse for alternate lines
                splitRight = previousRight
                previousLeft = splitLeft

            # Exception to the rule : Don't split the left of the first row.
            if firstRow:
                splitLeft = previousLeft

            firstRow = False
            row2 = rowData[(splitLeft + 1):(splitRight + 1)]

            # Turnkey 11-04-15 - For the time being, I've disabled the raster optimisation with the below line.
            # There's a bug where it cannot correctly handle white space between vertical lines in raster images and it messes up the horizontal alignment.
            # -Update, users can disable optimisations through the options now.
            # The optimisation has a bug which can produce hot spots at the edge of rasters.
            if not self.options.optimiseraster:
                row2 = rowData

            # Heading Left to right, invert the data.
            if not forward:
                result_row = row2[::-1]
            # Heading Right to left.
            else:
                result_row = row2

            first = True
            for chunk in get_chunks(result_row, 51):
                if first:
                    if forward:
                        gcode += ("\nG7 $1 ")
                    else:
                        gcode += ("\nG7 $0 ")
                    first = not first
                else:
                    gcode += ("G7 ")

                # Python 3: base64 works on bytes, so build the payload as
                # bytes and decode the result back to ascii text.
                b64 = base64.b64encode(bytes(bytearray(chunk))).decode('ascii')

                # If we're using pronterface, we need to change raster data / and + in the base64 alphabet to letter 9. This loses a little intensity in pure blacks but keeps pronterface happy.
                if self.options.pronterface:
                    b64 = b64.replace("+", "9").replace("/", "9")

                gcode += ("L" + str(len(b64)) + " ")
                gcode += ("D" + b64 + "\n")
            forward = not forward

        gcode += ("M5 \n")
        gcode += ';End of Raster Image ' + str(curve['id']) + '\n\n'

        return gcode

    def generate_gcode(self, curve, depth, laserPower, altfeed=None, altppm=None):
        gcode = ''

        # Setup our feed rate, either from the layer name or from the default value.
        if altfeed:
            # Use the "alternative" feed rate specified
            cutFeed = "F%i" % altfeed
        else:
            cutFeed = "F%i" % self.options.feed

        # Setup our pulse per millimetre option, if applicable
        # B: laser firing mode (0 = continuous, 1 = pulsed, 2 = raster)
        if altppm:
            # Use the "alternative" ppm - L60000 is 60us
            ppmValue = "L60000 P%.2f B1 D0" % altppm
        else:
            # Set the laser firing mode to continuous.
            ppmValue = "B0 D0"

        cwArc = "G02"
        ccwArc = "G03"

        # The geometry is reflected, so invert the orientation of the arcs to match
        if self.flipArcs:
            (cwArc, ccwArc) = (ccwArc, cwArc)

        # The 'laser on' and 'laser off' m-codes get appended to the GCODE generation
        lg = 'G00'
        firstGCode = False

        si = None
        for i in range(1, len(curve['data'])):
            s, si = curve['data'][i - 1], curve['data'][i]

            # G00 : Move with the laser off to a new point
            if s[1] == 'move':
                gcode += "G00 " + self.make_args(si[0]) + " F%i " % self.options.Mfeed + "\n"
                lg = 'G00'

            elif s[1] == 'end':
                lg = 'G00'

            # G01 : Move with the laser turned on to a new point
            elif s[1] == 'line':
                if not firstGCode:  # Include the ppm values for the first G01 command in the set.
                    gcode += "G01 " + self.make_args(si[0]) + " S%.2f " % laserPower + \
                             "%s " % cutFeed + "%s" % ppmValue + "\n"
                    firstGCode = True
                else:
                    gcode += "G01 " + self.make_args(si[0]) + "\n"
                lg = 'G01'

            # G02 and G03 : Move in an arc with the laser turned on.
            elif s[1] == 'arc':
                dx = s[2][0] - s[0][0]
                dy = s[2][1] - s[0][1]
                if abs((dx ** 2 + dy ** 2) * self.options.Xscale) > self.options.min_arc_radius:
                    r1 = P(s[0]) - P(s[2])
                    r2 = P(si[0]) - P(s[2])
                    if abs(r1.mag() - r2.mag()) < 0.001:
                        if s[3] > 0:
                            gcode += cwArc
                        else:
                            gcode += ccwArc

                        if not firstGCode:  # Include the ppm values for the first G01 command in the set.
                            gcode += " " + self.make_args(si[0] + [None, dx, dy, None]) + \
                                     "S%.2f " % laserPower + "%s " % cutFeed + "%s" % ppmValue + "\n"
                            firstGCode = True
                        else:
                            gcode += " " + self.make_args(si[0] + [None, dx, dy, None]) + "\n"

                    else:
                        r = (r1.mag() + r2.mag()) / 2
                        if s[3] > 0:
                            gcode += cwArc
                        else:
                            gcode += ccwArc

                        if not firstGCode:  # Include the ppm values for the first G01 command in the set.
                            gcode += " " + self.make_args(si[0]) + " R%f" % (r * self.options.Xscale) + \
                                     "S%.2f " % laserPower + "%s " % cutFeed + "%s" % ppmValue + "\n"
                            firstGCode = True
                        else:
                            gcode += " " + self.make_args(si[0]) + \
                                     " R%f" % (r * self.options.Xscale) + "\n"

                    lg = cwArc
                # The arc is less than the minimum arc radius, draw it as a straight line.
                else:
                    if not firstGCode:  # Include the ppm values for the first G01 command in the set.
                        gcode += "G01 " + self.make_args(si[0]) + "S%.2f " % laserPower + \
                                 "%s " % cutFeed + "%s" % ppmValue + "\n"
                        firstGCode = True
                    else:
                        gcode += "G01 " + self.make_args(si[0]) + "\n"

                    lg = 'G01'

        # The end of the layer.
        if si is not None and si[1] == 'end':
            gcode += LASER_OFF

        return gcode

    def tool_change(self):
        # Include a tool change operation
        gcode = TOOL_CHANGE % (self.currentTool + 1)
        # Select the next available tool
        self.currentTool = (self.currentTool + 1) % 32
        return gcode

    # Determine the tmp directory for the user's operating system.
    def getTmpPath(self):
        """Define the temporary folder path depending on the operating system"""
        return tempfile.gettempdir() + os.sep

    def _run_inkscape(self, *args, **kwargs):
        """Call the Inkscape binary, preferring inkex's own locator."""
        if inkscape_command is not None:
            return inkscape_command(*args, **kwargs)
        raise RuntimeError("inkex.command is unavailable; Inkscape 1.0 or newer is required.")

    ################################################################################
    ###
    ###        Curve to Gcode
    ###
    ################################################################################

    def effect_curve(self, selected):
        selected = list(selected)

        # Set group.  The curve data has already had every parent transform
        # baked into it, so the preview group belongs on the document root
        # rather than inside the selected object's layer.  When the origin is
        # the top left the geometry was flipped in Y, so flip the group back.
        if self.options.drawCurves and len(selected) > 0:
            self.biarcGroup = etree.SubElement(self.document.getroot(), SVG_GROUP_TAG)
            self.biarcGroup.set(inkex.addNS('label', 'inkscape'), 'TurnkeyLaser preview')
            if self.options.origin == 'topleft':
                self.biarcGroup.set('transform', 'scale(1,-1)')
            options.Group = self.biarcGroup

        # Recursively compiles a list of paths that are decendant from the given node
        self.skipped = 0

        def compile_paths(parent, node, trans):
            """Return a list of path dictionaries for node and its children."""
            # Apply the object transform, along with the parent transformation
            mat = node.get('transform', None)
            path = {}

            if mat:
                trans = Transform(trans) @ Transform(mat)

            if node.tag == SVG_PATH_TAG:
                # This is a path object
                if not node.get("d"):
                    return []

                full_trans = Transform(trans)
                # Apply a transform in the Y plane to flip the path vertically
                # if we want our origin to be the top left.
                if self.options.origin == 'topleft':
                    full_trans = Transform(((1.0, 0.0, 0.0), (0.0, -1.0, 0.0))) @ full_trans

                csp = Path(node.get("d")).transform(full_trans).to_superpath()

                path['type'] = "vector"
                path['id'] = node.get("id")
                path['data'] = csp

                return [path]

            if node.tag == SVG_GROUP_TAG:
                # This node is a group of other nodes
                pathsGroup = []
                for child in node.iterchildren():
                    pathsGroup += compile_paths(parent, child, trans)
                return pathsGroup

            # Raster the results.
            if node.get("x") is not None:
                raster = self.compile_raster(parent, node)
                if raster is None:
                    self.skipped += 1
                    return []
                return [raster]

            inkex.errormsg("Unable to generate raster for object " + str(node.get("id")) +
                           " as it does not have an x-y coordinate associated.")
            self.skipped += 1
            return []

        # Compile a list of layers in this document. We compile a list of only the layers
        # we need to use, so we can know ahead of time whether to put tool change
        # operations between them.
        layers = list(reversed(get_layers(self.document)))

        # Loop over the layers and objects
        gcode = ""
        gcode_raster = ""
        originalLayerName = ""
        layerName = ""
        altfeed = self.options.feed
        altppm = None
        for layer in layers:
            label = layer.get(SVG_LABEL_TAG)
            label = (label or layer.get("id") or "").strip()
            if label.startswith("#"):
                # Ignore everything selected in this layer
                for node in layer.iterchildren():
                    if node in selected:
                        selected.remove(node)
                continue

            # Parse the layer label text, which consists of the layer name followed
            # by an optional number of arguments in square brackets.
            try:
                originalLayerName = label
                (layerName, layerParams) = parse_layer_name(label)
            except ValueError:
                inkex.errormsg("Your inkscape layer is named incorrectly. Please use the format "
                               "'20 [ppm=40,feed=300]' without the quotes. This would set the power "
                               "at 20%, cutting at 300mm per minute at a pulse rate of 40 pulse per "
                               "millimetre. The ppm option is optional, leaving it out will set the "
                               "laser to continuous wave mode.")
                return

            # Check if the layer specifies an alternative (from the default) feed rate
            altfeed = layerParams.get("feed", self.options.feed)
            altppm = layerParams.get("ppm", None)

            logger.write("layer %s" % layerName)
            if layerParams:
                logger.write("layer params == %s" % layerParams)
            pathList = []
            # Apply the layer transform to all objects within the layer
            trans = Transform(layer.get('transform', None))

            for node in layer.iterchildren():
                if node in selected:
                    # Vector path data, cut from x to y in a line or curve
                    logger.write("node %s" % str(node.tag))
                    selected.remove(node)

                    for objectData in compile_paths(self, node, trans):
                        inkex.errormsg("Built gcode for " + str(objectData['id']) +
                                       " - will be cut as %s." % (objectData['type']))
                        pathList.append(objectData)
                else:
                    logger.write("skipping node %s" % node)

            if not pathList:
                logger.write("no objects in layer")
                continue

            laserPower = self.layer_power(layerName)

            # Fetch the vector or raster data and turn it into GCode
            for objectData in pathList:
                curve = self.parse_curve(objectData)

                header_data = self.layer_header(originalLayerName, laserPower, altfeed, altppm)

                # Generate the GCode for this layer
                if curve['type'] == "vector":
                    # Should the curves be drawn in inkscape?
                    if self.options.drawCurves:
                        self.draw_curve(curve['data'])

                    gcode += header_data + self.generate_gcode(curve, 0, laserPower,
                                                               altfeed=altfeed, altppm=altppm)
                elif curve['type'] == "raster":
                    gcode_raster += header_data + self.generate_raster_gcode(curve, laserPower,
                                                                             altfeed=altfeed)

        # Turnkey - Need to figure out why inkscape sometimes gets to this point and hasn't found the objects above.
        # If there are any objects left over, it's because they don't belong
        # to any inkscape layer (bug in inkscape?). Output those now.
        # Turnkey - This is caused by objects being inside a group.
        if selected:
            inkex.errormsg("Warning: Your selected object is part of a group. If your group has a "
                           "transformations/skew/rotation applied to it these will not be exported "
                           "correctly. Please ungroup your objects first then re-export. Select them "
                           "and press Shift+Ctrl+G to ungroup.\n")

            pathList = []
            # Use the identity transform (eg no transform) for the root objects
            trans = Transform()
            for node in selected:
                for objectData in compile_paths(self, node, trans):
                    inkex.errormsg("Built gcode for " + str(objectData['id']) +
                                   " - will be cut as %s." % (objectData['type']))
                    pathList.append(objectData)

            if pathList:
                laserPower = self.layer_power(layerName)

                for objectData in pathList:
                    curve = self.parse_curve(objectData)

                    header_data = self.layer_header(originalLayerName, laserPower, altfeed, altppm)

                    # Generate the GCode for this layer
                    if curve['type'] == "vector":
                        # Should the curves be drawn in inkscape?
                        if self.options.drawCurves:
                            self.draw_curve(curve['data'])

                        gcode += header_data + self.generate_gcode(curve, 0, laserPower,
                                                                   altfeed=altfeed, altppm=altppm)
                    elif curve['type'] == "raster":
                        gcode_raster += header_data + self.generate_raster_gcode(curve, laserPower,
                                                                                 altfeed=altfeed)

        if self.options.homeafter:
            gcode += "\n\nG00 X0 Y0 F4000 ; home"

        # Always raster before vector cutting.
        gcode = gcode_raster + "\n\n" + gcode

        return gcode

    def layer_power(self, layerName):
        """Determine the power of the laser that this layer should be cut at.

        If the layer is not named as an integer value then default to the laser
        intensity set in the export settings.
        """
        laserPower = self.options.laser
        try:
            value = int(layerName)
            if 0 < value <= 100:
                laserPower = value
            else:
                laserPower = self.options.laser
        except ValueError:
            laserPower = self.options.laser
            inkex.errormsg("Unable to parse power level for layer name. Using default power "
                           "level %d percent." % (self.options.laser))

        # Switch between smoothie power levels and ramps+marlin power levels
        # ramps and marlin expect 0 to 100 while smoothie wants 0.0 to 1.0
        if self.options.mainboard == 'smoothie':
            laserPower = float(laserPower) / 100

        return laserPower

    def layer_header(self, originalLayerName, laserPower, altfeed, altppm):
        """Turnkey : Always output the layer header for information."""
        header_data = LASER_OFF + "\n"
        size = 60
        header_data += ";(%s)\n" % ("*" * size)
        header_data += (";(***** Layer: %%-%ds *****)\n" % (size - 19)) % (originalLayerName)
        header_data += (";(***** Laser Power: %%-%ds *****)\n" % (size - 25)) % (laserPower)
        header_data += (";(***** Feed Rate: %%-%ds *****)\n" % (size - 23)) % (altfeed)
        if altppm:
            header_data += (";(***** Pulse Rate: %%-%ds *****)\n" % (size - 24)) % (altppm)
        header_data += ";(%s)\n" % ("*" * size)
        header_data += ";(MSG,Starting layer '%s')\n\n" % originalLayerName
        return header_data

    def compile_raster(self, parent, node):
        """Render a non-path node to a bitmap and return its raster path dict."""
        if not HAS_PIL:
            inkex.errormsg("Object %s needs to be rastered but the Python Imaging Library "
                           "(Pillow) is not available to Inkscape's Python interpreter. "
                           "Install it with: pip install Pillow" % str(node.get("id")))
            return None

        curfile = self.options.input_file  # The current inkscape project we're exporting from.
        if not curfile:
            inkex.errormsg("Cannot raster %s: the document has not been saved to a file."
                           % str(node.get("id")))
            return None

        path = {}
        tmp = self.getTmpPath()  # OS tmp directory
        bgcol = "#ffffff"  # White
        filename = os.path.join(tmp, "tmpinkscapeexport.png")

        # Inkscape 1.x replaced "-e/--export-png" with "--export-type" plus
        # "--export-filename", and requires "--export-id" (not "-i").
        try:
            self._run_inkscape(curfile,
                               export_dpi=int(RASTER_DPI),
                               export_id=node.get("id"),
                               export_id_only=True,
                               export_type="png",
                               export_filename=filename,
                               export_background=bgcol,
                               export_background_opacity=1.0)
        except Exception as err:  # pylint: disable=broad-except
            inkex.errormsg("Failed to render %s to a bitmap: %s" % (str(node.get("id")), err))
            return None

        if not os.path.isfile(filename):
            inkex.errormsg("Inkscape did not produce a bitmap for %s." % str(node.get("id")))
            return None

        # Fetch the image Data
        flip = getattr(getattr(Image, "Transpose", Image), "FLIP_TOP_BOTTOM")
        if self.options.origin == 'topleft':
            im = Image.open(filename).transpose(flip).convert('L')
        else:
            im = Image.open(filename).convert('L')
        img = ImageOps.invert(im)

        # Get the image size
        imageDataWidth, imageDataheight = img.size

        # Compile the pixels.
        pixels = list(img.getdata())
        pixels = [pixels[i * imageDataWidth:(i + 1) * imageDataWidth]
                  for i in range(imageDataheight)]

        path['type'] = "raster"
        path['width'] = imageDataWidth
        path['height'] = imageDataheight

        # A slow, but reliable way of getting correct coordinates since working with
        # inkscape transpositions and transforms is a major pain.
        if not hasattr(parent, 'glob_nodePositions'):
            # Get the XY position of all elements in the inkscape job.
            dataString = self._run_inkscape(curfile, query_all=True)
            elementList = {}
            for item in dataString.replace("\r", "").split("\n"):
                if "," not in item:
                    continue
                key, value = item.split(",", 1)
                elementList[key] = value
            parent.glob_nodePositions = elementList

        # Lookup the xy coords for this node.
        nodeId = node.get("id")
        if nodeId not in parent.glob_nodePositions:
            inkex.errormsg("Unable to determine the position of raster object %s." % str(nodeId))
            return None
        elementData = parent.glob_nodePositions[nodeId].split(',')
        # --query-all reports viewport pixels; convert them to the user units
        # the rest of this exporter works in.
        x_position = float(elementData[0]) / self.pxPerUserUnit
        y_position = float(elementData[1]) / self.pxPerUserUnit
        # Height of the rendered bitmap expressed in user units.
        rasterHeight = imageDataheight * (PX_PER_INCH / RASTER_DPI) / self.pxPerUserUnit

        # Text is y positioned from the top left.
        if self.options.origin == 'topleft':
            # Don't flip the y position. Since we're moving the origin from bottom left to top left.
            pass
        else:
            y_position = y_position * -1 + self.pageHeight
            # Very small loss of positioning due to conversion of the dpi in the exported image.
            y_position -= rasterHeight

        # Convert from user units to mm / in
        path['x'] = round(self.unitScale * x_position, 3)
        path['y'] = round(self.unitScale * y_position, 3)

        # Do not permit being < 0
        if path['y'] < 0:
            path['y'] = 0

        if path['x'] < 0:
            path['x'] = 0

        path['id'] = nodeId
        path['data'] = pixels

        return path

    def setup_document_scale(self):
        """Work out the page height and the user-unit -> output-unit scale.

        Inkscape 1.x documents are usually mm based (``width="210mm"
        viewBox="0 0 210 297"``), so a user unit is not necessarily a pixel any
        more.  Everything here is derived from the viewBox so it works on both
        legacy 90dpi documents and modern ones.
        """
        svg = self.document.getroot()
        viewbox = parse_viewbox(svg)

        width_px = convert_unit(svg.get("width") or "", "px")
        height_px = convert_unit(svg.get("height") or "", "px")

        if viewbox:
            self.pageHeight = viewbox[3]
            if width_px and height_px:
                self.pxPerUserUnit = max(width_px / viewbox[2], height_px / viewbox[3])
            else:
                self.pxPerUserUnit = 1.0
        else:
            if not height_px:
                return False
            self.pageHeight = height_px
            self.pxPerUserUnit = 1.0

        if not self.pxPerUserUnit:
            self.pxPerUserUnit = 1.0

        return True

    def effect(self):
        global options
        options = self.options
        # inkex 1.1 renamed svg.selected to svg.selection; support both so the
        # extension runs on Inkscape 1.0 through 1.4.
        try:
            selection = self.svg.selection
        except AttributeError:  # pragma: no cover - inkex 1.0
            selection = self.svg.selected
        selected = list(selection.values())

        # Work out the document scale before anything else needs it.
        if not self.setup_document_scale():
            inkex.errormsg("Unable to determine the size of your document. Please set a page size "
                           "in File > Document Properties.")
            return

        self.flipArcs = (self.options.Xscale * self.options.Yscale < 0)
        self.currentTool = 0
        self.skipped = 0

        self.filename = self.options.file.strip()
        if self.filename == "-1.0" or self.filename == "":
            inkex.errormsg("Please select an output file name.")
            return

        if not self.filename.lower().endswith(GCODE_EXTENSION):
            # Automatically append the correct extension
            self.filename += GCODE_EXTENSION

        logger.enabled = self.options.logging
        logger.write("Laser script started")
        logger.write("output file == %s" % self.filename)

        if len(selected) <= 0:
            inkex.errormsg("This extension requires at least one selected path.")
            return

        if not self.options.directory:
            self.options.directory = os.path.join(
                os.getenv("HOME") or os.getenv("USERPROFILE") or os.getcwd(), "Desktop")

        dirExists = self.check_dir()
        if not dirExists:
            return

        gcode = self.header

        if self.options.unit == "mm":
            # One user unit in millimetres.
            self.unitScale = convert_unit(self.pxPerUserUnit, "mm")
            gcode += "G21 ; All units in mm\n"
        elif self.options.unit == "in":
            # One user unit in inches.
            self.unitScale = convert_unit(self.pxPerUserUnit, "in")
            gcode += "G20 ; All units in in\n"
        else:
            inkex.errormsg("You must choose mm or in")
            return

        logger.write("user unit scale == %s %s" % (self.unitScale, self.options.unit))
        logger.write("page height (user units) == %s" % self.pageHeight)

        gcode += "M80 ; Turn on Optional Peripherals Board at LMN\n"

        # Put the header data in the gcode file
        gcode += """
; Raster data will always precede vector data
; Default Cut Feedrate %i mm per minute
; Default Move Feedrate %i mm per minute
; Default Laser Intensity %i percent\n""" % (self.options.feed, self.options.Mfeed,
                                             self.options.laser)

        if self.options.homebefore:
            gcode += "G28 XY; home X and Y\n\n"

        data = self.effect_curve(selected)
        if data:
            gcode += data

        if self.options.double_sided_cutting:
            gcode += "\n\n;(MSG,Please flip over material)\n\n"
            # Include a tool change operation
            gcode += self.tool_change()

            logger.write("*** processing mirror image")

            self.options.Yscale *= -1
            self.flipArcs = not self.flipArcs
            self.pageHeight = 0
            mirrored = self.effect_curve(selected)
            if mirrored:
                gcode += mirrored

        outfile = os.path.join(self.options.directory, self.filename)
        try:
            with open(outfile, "w") as fhl:
                fhl.write(gcode + self.footer)
        except IOError as err:
            inkex.errormsg("Can not write to specified file! (%s)" % err)
            return

        if self.skipped > 0:
            inkex.errormsg("Warning: skipped %d object(s) because they were not paths (Vectors) "
                           "or images (Raster). Please convert them to paths using the menu "
                           "'Path->Object To Path'" % self.skipped)

        inkex.errormsg("Finished processing. Wrote %s" % outfile)


if __name__ == '__main__':
    Gcode_tools().run()
