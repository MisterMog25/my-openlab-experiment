import math
import time

from tuke_openlab import Controller, simulation_env
from tuke_openlab.lights import Color

from helpers import COLUMNS, column, hsv, mix, window, windows

# Any unique string, without MQTT wildcards (+, #) or null characters.
TOPIC = "mark"

ROWS = 3
WINDOWS = 8
SINE_WAVES = 2
FRAME_SECONDS = 0.05
SOFT = 2.0              # width of the soft edge of a moving front, in columns

SINE_SPEED_START = 6.0
SINE_SPEED_END = 16.0

WAVE_HUE_LEFT = 0.50
WAVE_HUE_RIGHT = 0.87

RIM_HUE = 0.08
RIM_WIDTH = 1.6

# Warm pastel peak (replaces white) and the soft violet the black hole leaves.
IGNITION = Color(r=255, g=224, b=180)
AFTERGLOW = Color(r=150, g=140, b=210)
BG_LEVEL = 0.15

# A dim indigo floor colour: no lamp is ever pure black.
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


def _wave_hue(col):
    position = 1 - (col - 1) / (COLUMNS - 1)
    return WAVE_HUE_LEFT + (WAVE_HUE_RIGHT - WAVE_HUE_LEFT) * position


def _sine_row(x, phase):
    return 2 - math.sin(2 * math.pi * SINE_WAVES * x / COLUMNS - phase)


def _sine_speed(progress):
    progress = min(1.0, max(0.0, progress))
    return SINE_SPEED_START + (SINE_SPEED_END - SINE_SPEED_START) * progress


def _fill_windows(frame):
    for w in range(1, WINDOWS + 1):
        color = frame[_window_column(w)]
        for light in window(w):
            frame[light] = color


def _blink_windows(frame, t, base, horizon=0.0, scale=1.0):
    center = (COLUMNS + 1) / 2
    for w in range(1, WINDOWS + 1):
        if abs(_window_column(w) - center) <= horizon:
            color = base
        elif math.sin(t * 20 + w * 1.9) > 0 and scale > 0.02:
            color = hsv((t * 0.8 + w * 0.11) % 1.0, scale)
        else:
            color = base
        for light in window(w):
            frame[light] = color


def art_star(lights, heat_seconds=20.0, bloom_seconds=3.0, fade_seconds=1.5,
             dark_seconds=1.0, sine_seconds=7.5, eat_seconds=17.0):
    bloom_end = heat_seconds + bloom_seconds
    fade_end = bloom_end + fade_seconds
    dark_end = fade_end + dark_seconds
    sine_end = dark_end + sine_seconds
    total = sine_end + eat_seconds
    center = (COLUMNS + 1) / 2
    reach = (COLUMNS - 1) / 2
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
        elif t < sine_end:
            tt = t - dark_end
            appear = _ease(tt / (sine_seconds * 0.4))
            speed = _sine_speed(_ease(tt / sine_seconds))
            base = mix(BACKGROUND, _scaled(AFTERGLOW, BG_LEVEL), appear)
            for c in range(1, COLUMNS + 1):
                row = _sine_row(c, tt * speed)
                hue = _wave_hue(c)
                for r in range(1, ROWS + 1):
                    brightness = max(0.0, 1.0 - abs(r - row)) * appear
                    frame[_lamp(r, c)] = hsv(hue, brightness) if brightness > 0.02 else base
            _blink_windows(frame, t, base, scale=appear)

        # 6
        else:
            tt = t - dark_end
            progress = _ease((t - sine_end) / eat_seconds)
            horizon = progress * (reach + 2.5)
            speed = _sine_speed(_ease(tt / sine_seconds))
            base = _scaled(AFTERGLOW, BG_LEVEL)
            hole = Color()
            for c in range(1, COLUMNS + 1):
                distance = abs(c - center)
                squeezed = center + (c - center) * (1 - progress)
                row = _sine_row(squeezed, tt * speed)
                hue = _wave_hue(c)
                for r in range(1, ROWS + 1):
                    sine = max(0.0, 1.0 - abs(r - row))
                    if distance <= horizon:
                        color = hole
                    else:
                        rim = math.exp(-((distance - horizon) / RIM_WIDTH) ** 2)
                        brightness = max(sine * (1 - progress), rim)
                        if brightness <= 0.02:
                            color = base
                        else:
                            color = hsv(RIM_HUE if rim > sine else hue, min(1.0, brightness))
                    frame[_lamp(r, c)] = color
            _blink_windows(frame, t, base, horizon)

        lights.set_colors(frame)
        time.sleep(FRAME_SECONDS)


def show(lights):
    art_star(lights)


def main():
    env = simulation_env(TOPIC)
    controller = Controller(env)
    print(f"Connected to {'simulation' if env.is_simulation else 'production'} (topic={TOPIC})")

    art_star(controller.lights)
    controller.lights.turn_off()

    print("Done.")


if __name__ == "__main__":
    main()
