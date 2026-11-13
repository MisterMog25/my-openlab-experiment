"""Ready-made building blocks for OpenLab scenes.

Everything here is either ported from the SDK examples
(https://git.kpi.fei.tuke.sk/open-lab/tuke-openlab-sdk/-/tree/master/examples)
or is a thin, tested helper on top of them.

Usage in your own file (mark.py / andrii.py / tymofii.py):

    from helpers import flag, pulse, spectrum, rainbow, random_colors

    lights = controller.lights
    flag(lights, seconds=10)
    pulse(lights, seconds=15)
    rainbow(lights, seconds=15)

Every effect blocks for `seconds`, so they can be chained one after another.
"""

import colorsys
import random
import time

from tuke_openlab.lights import Color

ROWS, COLUMNS = 3, 27
WINDOWS = 8


# ------------------------------------------------------------------- the grid
def row(r):
    """All 27 lamps of row r (1 = top row)."""
    return [(r - 1) * COLUMNS + c for c in range(1, COLUMNS + 1)]


def column(c):
    """All 3 lamps of column c (c = 1 is the RIGHTMOST column)."""
    return [c + r * COLUMNS for r in range(ROWS)]


def half_column(i):
    """A column split in half — the SDK examples use this for gradients."""
    if i % 2 == 1:
        c = i // 2 + 1
        return [c, c + 2 * COLUMNS]
    return [i // 2 + COLUMNS]


def window(i):
    """i = 1..8, right to left: window 1 is lamps 82 and 83."""
    base = 82 + (i - 1) * 2
    return [base, base + 1]


def windows():
    """All 16 lamps inside the windows."""
    return list(range(82, 82 + WINDOWS * 2))


def grid():
    """All 81 lamps of the wall, in id order."""
    return list(range(1, ROWS * COLUMNS + 1))


# ---------------------------------------------------------------------- colors
def mix(a, b, t):
    """Blend two colors: t=0 -> a, t=1 -> b (called mixed_color() in the examples)."""
    t = max(0.0, min(1.0, t))
    return Color(*(int(getattr(a, ch) + (getattr(b, ch) - getattr(a, ch)) * t) for ch in "rgbw"))


def hsv(h, brightness=1.0):
    """A color from the color wheel: h = 0..1 (0 = red, 0.33 = green, 0.66 = blue)."""
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, 1.0, brightness)
    return Color(int(r * 255), int(g * 255), int(b * 255))


def transition(a, b, segment_start, length):
    """A gradient segment from color a to color b (ported as-is)."""
    frame = {}
    for i in range(1, 1 + length):
        for light in half_column(i + segment_start):
            frame[light] = mix(a, b, i / length)
    return frame


# --------------------------------------------------------------------- effects
def flag(lights, seconds=10, delay=0.5):
    """The flag from simple_examples.py, plus warm light in the windows."""
    frame = {}
    for i in range(1, 28):
        frame[i] = Color(w=0xFF)                # white
    for i in range(28, 55):
        frame[i] = Color(0x00, 0x4E, 0x9F)      # blue
    for i in range(55, 82):
        frame[i] = Color(0xFA, 0x1D, 0x2F)      # red
    for i in windows():
        frame[i] = Color(w=0x60)

    start = time.monotonic()
    while time.monotonic() - start < seconds:
        lights.set_colors(frame)
        time.sleep(delay)


def random_colors(lights, seconds=5, delay=0.3, brightness=255):
    """Random colors on the whole wall (random_colors() in simple_examples.py)."""
    start = time.monotonic()
    while time.monotonic() - start < seconds:
        frame = {}
        for i in grid():
            frame[i] = Color(
                random.randint(0, brightness),
                random.randint(0, brightness),
                random.randint(0, brightness),
            )
        lights.set_colors(frame)
        time.sleep(delay)


def pulse(lights, seconds=15, delay=0.25, color=None):
    """A bright column travelling along the wall, leaving a fading tail.

    Ported from more_examples.py pulse(). Note the trick: it does not draw every
    frame — it sends a few keyframes with a large `fade` and the hardware
    interpolates for us.
    """
    if color is None:
        color = Color(r=255, g=120)
    black = Color()
    pulse_length = 3

    lights.turn_off()
    start = time.monotonic()
    step = 1
    while time.monotonic() - start < seconds:
        if step > pulse_length:
            lights.set_color(column(step - pulse_length), black, 1500)
        if step <= COLUMNS:
            lights.set_color(column(step), color, 500)
        step += 1
        if step > COLUMNS + pulse_length:
            step = 1
        time.sleep(delay)


def spectrum(lights, seconds=10, colors=None):
    """A full color gradient across the wall (ported from more_examples.py spectrum()).

    It is a static picture, just held for `seconds`.
    """
    if colors is None:
        colors = [Color(r=255), Color(g=255), Color(b=255), Color(r=255), Color(g=255)]
    lights.turn_off()

    frame = {}
    segment_length = (2 * COLUMNS) // (len(colors) - 1)
    for i in range(len(colors) - 1):
        frame.update(transition(colors[i], colors[i + 1], i * segment_length, segment_length))
    lights.set_colors(frame)

    start = time.monotonic()
    while time.monotonic() - start < seconds:
        time.sleep(0.2)


def rainbow(lights, seconds=15, delay=0.06, brightness=1.0):
    """A rainbow scrolling across the wall: each column gets its own hue."""
    start = time.monotonic()
    phase = 0.0
    while time.monotonic() - start < seconds:
        frame = {}
        for i in range(1, COLUMNS + 1):
            color = hsv(i / COLUMNS + phase, brightness)
            for light in column(i):
                frame[light] = color
        lights.set_colors(frame)
        phase += 0.01
        time.sleep(delay)
