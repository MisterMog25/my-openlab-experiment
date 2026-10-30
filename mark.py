import math
import random
import time

from tuke_openlab import Controller, simulation_env
from tuke_openlab.lights import Color

from helpers import COLUMNS, column, hsv, mix, window, windows

# Any unique string, without MQTT wildcards (+, #) or null characters.
TOPIC = "mark"

ROWS = 3
WINDOWS = 8
FRAME_SECONDS = 0.05
SOFT = 2.0

RIM_HUE = 0.08
RIM_WIDTH = 1.6

IGNITION = Color(r=255, g=224, b=180)
AFTERGLOW = Color(r=150, g=140, b=210)
BG_LEVEL = 0.15
BACKGROUND = Color(r=18, g=16, b=40)

COOL_STOPS = [
    (0.00, (0, 0, 90)),
    (0.30, (0, 130, 255)),
    (0.55, (255, 220, 0)),
    (0.75, (255, 110, 0)),
    (1.00, (255, 224, 180)),
]

WALL = list(range(1, COLUMNS * ROWS + 1))
ALL_LIGHTS = WALL + windows()


def _ease(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def _scaled(color, scale):
    return Color(r=int(color.r * scale), g=int(color.g * scale), b=int(color.b * scale))


def _heat_color(x):
    x = min(1.0, max(0.0, x))
    for i in range(len(COOL_STOPS) - 1):
        pos0, (r0, g0, b0) = COOL_STOPS[i]
        pos1, (r1, g1, b1) = COOL_STOPS[i + 1]
        if x <= pos1:
            k = (x - pos0) / (pos1 - pos0)
            return Color(
                r=int(r0 + (r1 - r0) * k),
                g=int(g0 + (g1 - g0) * k),
                b=int(b0 + (b1 - b0) * k),
            )
    return IGNITION


def _window_column(w):
    step = (COLUMNS - 1) / (WINDOWS - 1)
    return 1 + round((w - 1) * step)


def _lamp(row, col):
    return (row - 1) * COLUMNS + col


def _fill_windows(frame):
    for w in range(1, WINDOWS + 1):
        color = frame[_window_column(w)]
        for light in window(w):
            frame[light] = color


def _party_windows(frame, t, base, horizon=0.0, scale=1.0):
    center = (COLUMNS + 1) / 2
    for w in range(1, WINDOWS + 1):
        if abs(_window_column(w) - center) <= horizon:
            color = Color()
        else:
            hue = (w / WINDOWS + t * 0.6) % 1.0
            bright = scale * (0.4 + 0.6 * abs(math.sin(t * 8 + w * 1.3)))
            color = hsv(hue, bright) if bright > 0.02 else base
        for light in window(w):
            frame[light] = color


def art_star(lights, heat_seconds=20.0, bloom_seconds=3.0, fade_seconds=1.5,
             dark_seconds=1.0, explosion_seconds=4.0, eat_seconds=11.0):
    bloom_end = heat_seconds + bloom_seconds
    fade_end = bloom_end + fade_seconds
    dark_end = fade_end + dark_seconds
    boom_end = dark_end + explosion_seconds
    total = boom_end + eat_seconds
    center = (COLUMNS + 1) / 2
    reach = (COLUMNS - 1) / 2
    base = _scaled(AFTERGLOW, BG_LEVEL)
    start = time.monotonic()

    while True:
        t = time.monotonic() - start
        if t >= total:
            break
        frame = {}

        # 1
        if t < heat_seconds:
            progress = _ease(t / heat_seconds)
            front = reach * (1 - progress)
            for c in range(1, COLUMNS + 1):
                distance = abs(c - center)
                inner = 1 - distance / reach
                glow = min(1.0, max(0.0, (distance - front) / SOFT))
                heat = _heat_color(progress * (0.35 + 0.65 * inner))
                color = mix(BACKGROUND, heat, glow)
                for light in column(c):
                    frame[light] = color
            _fill_windows(frame)

        # 2
        elif t < bloom_end:
            progress = _ease((t - heat_seconds) / bloom_seconds)
            white_front = progress * (reach + 3.0)
            for c in range(1, COLUMNS + 1):
                distance = abs(c - center)
                inner = 1 - distance / reach
                glow = min(1.0, max(0.0, distance / SOFT))
                rest = mix(BACKGROUND, _heat_color(0.35 + 0.65 * inner), glow)
                blend = min(1.0, max(0.0, (white_front - distance) / SOFT))
                color = mix(rest, IGNITION, blend)
                for light in column(c):
                    frame[light] = color
            _fill_windows(frame)

        # 3
        elif t < fade_end:
            fade = 1.0 - _ease((t - bloom_end) / fade_seconds)
            for light in ALL_LIGHTS:
                frame[light] = mix(BACKGROUND, IGNITION, fade)

        # 4
        elif t < dark_end:
            for light in ALL_LIGHTS:
                frame[light] = BACKGROUND

        # 5
        elif t < boom_end:
            tt = t - dark_end
            p = tt / explosion_seconds
            fade = 1.0 - 0.7 * _ease(p)
            for c in range(1, COLUMNS + 1):
                distance = abs(c - center)
                core = max(0.0, 1.0 - distance / (2 + tt * 16)) * fade
                ring = 0.0
                for speed, width in ((110, 2.5), (78, 3.5), (50, 5.0)):
                    ring = max(ring, max(0.0, 1.0 - abs(distance - tt * speed) / width) * fade)
                spark = 1.0 if random.random() < 0.7 * fade else 0.0
                bright = min(1.0, core + ring + spark)
                hue = (c / COLUMNS + tt * 1.8) % 1.0
                for r in range(1, ROWS + 1):
                    frame[_lamp(r, c)] = hsv(hue, bright) if bright > 0.02 else base
            _party_windows(frame, t, base, scale=fade)

        # 6
        else:
            tt = t - boom_end
            x = min(1.0, tt / eat_seconds)
            progress = 1 - (1 - x) ** 2                 # ease-out: the hole bursts out
            horizon = progress * (reach + 2.5)
            for c in range(1, COLUMNS + 1):
                distance = abs(c - center)
                for r in range(1, ROWS + 1):
                    if distance <= horizon:
                        color = Color()
                    else:
                        rim = math.exp(-((distance - horizon) / RIM_WIDTH) ** 2)
                        ember = (1 - progress) * 0.35 * (0.5 + 0.5 * math.sin(c * 1.3 + t * 6))
                        if random.random() < 0.12 * (1 - progress):
                            ember = 1.0
                        bright = min(1.0, max(ember, rim))
                        hue = (c / COLUMNS + t * 0.6) % 1.0
                        color = hsv(RIM_HUE if rim > ember else hue, bright) if bright > 0.02 else base
                    frame[_lamp(r, c)] = color
            _party_windows(frame, t, base, horizon=horizon, scale=1 - progress)

        lights.set_colors(frame)
        time.sleep(FRAME_SECONDS)


def main():
    env = simulation_env(TOPIC)
    controller = Controller(env)
    print(f"Connected to {'simulation' if env.is_simulation else 'production'} (topic={TOPIC})")

    art_star(controller.lights)
    controller.lights.turn_off()

    print("Done.")


if __name__ == "__main__":
    main()
