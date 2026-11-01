import time
import math
from helpers import *

from tuke_openlab import Controller, simulation_env
from tuke_openlab.lights import Color

TOPIC = "tymofii"

MAGENTA = Color.from_hex_string("FF007200")
CYAN = Color.from_hex_string("14E5FF00")
BLACK = Color()
CYAN_W100 = Color(CYAN.r, CYAN.g, CYAN.b, 100)
DIM_CYAN_LEVEL = 0.4
SOFT = 12
CENTER = 14

WAVE_LENGTH = 14
WAVE_SPEED = 4.0
WAVE_AMPLITUDE = 1.3

WIN_A = [window(i)[0] for i in range(1, WINDOWS + 1)]
WIN_B = [window(i)[1] for i in range(1, WINDOWS + 1)]


def scale(color, k):
    return Color(int(color.r * k), int(color.g * k), int(color.b * k), int(color.w * k))


def clamp(x):
    return max(0.0, min(1.0, x))


def row_id(r, c):
    return c + (r - 1) * COLUMNS


def column_frame(cols, color):
    return {l: color for c in cols for l in column(c)}


def window_frame(a_color, b_color):
    return {**{l: a_color for l in WIN_A}, **{l: b_color for l in WIN_B}}


def run_events(lights, events, tolerance=0.01):
    events = sorted(events, key=lambda e: e[0])
    start = time.monotonic()
    i = 0
    while i < len(events):
        now = time.monotonic() - start
        if events[i][0] > now:
            time.sleep(events[i][0] - now)
            now = time.monotonic() - start

        by_fade = {}
        while i < len(events) and events[i][0] <= now + tolerance:
            _, frame, fade = events[i]
            by_fade.setdefault(fade, {}).update(frame)
            i += 1

        for fade, frame in by_fade.items():
            lights.set_colors(frame, fade)


class Timeline:
    def __init__(self):
        self.events = []
        self.t = 0.0

    def add(self, events):
        self.events += [(self.t + t, frame, fade) for t, frame, fade in events]
        self.t += max(t for t, _, _ in events)


def ramp(events, state, ids, new, t, dt, fade, soft=SOFT):
    for i in ids:
        old = state.get(i, BLACK)
        for s in range(1, soft + 1):
            events.append((t + (s - 1) * dt, {i: mix(old, new, s / soft)}, fade))
        state[i] = new


def soft_sweep(lights, columns_at, start, end, seconds, soft=SOFT):
    n = CENTER + soft - 1
    dt = seconds / n
    fade = int(dt * 1000)
    events = []
    for k in range(n):
        frame = {}
        for d in range(max(0, k - soft + 1), min(k, CENTER - 1) + 1):
            frame.update(column_frame(columns_at(d), mix(start, end, (k - d + 1) / soft)))
        events.append((k * dt, frame, fade))
    run_events(lights, events)


def fill_from_edges(lights, color, seconds, start=BLACK):
    soft_sweep(lights, lambda d: [1 + d, COLUMNS - d], start, color, seconds)


def replace_from_center(lights, color, seconds, start=CYAN):
    soft_sweep(lights, lambda d: [CENTER - d, CENTER + d], start, color, seconds)


def brighten(lights, start, end, seconds=0.5, steps=5):
    dt = seconds / steps
    fade = int(dt * 1000)
    events = [(i * dt, {l: mix(start, end, (i + 1) / steps) for l in grid()}, fade)
              for i in range(steps)]
    run_events(lights, events)


def clash_events(offset, left, right, state, seconds=3.0, soft=SOFT):
    half = seconds / 2
    dt = half / (CENTER + soft - 1)
    fade = int(dt * 1000)
    events = []

    for d in range(CENTER - 1):
        t = offset + d * dt
        ramp(events, state, column(COLUMNS - d), left, t, dt, fade, soft)
        ramp(events, state, column(1 + d), right, t, dt, fade, soft)
    ramp(events, state, column(CENTER), mix(left, right, 0.8),
         offset + (CENTER - 1) * dt, dt, fade, soft)

    for k in range(CENTER):
        t = offset + half + k * dt
        ramp(events, state, [CENTER + k], right, t, dt, fade, soft)
        ramp(events, state, [CENTER - k + 2 * COLUMNS], left, t, dt, fade, soft)
    return events


def window_swap_events(seconds):
    return [(k, window_frame(*((MAGENTA, CYAN) if k % 2 == 0 else (CYAN, MAGENTA))), 1000)
            for k in range(int(seconds) + 1)]


def sky_events(state, seconds=3.0, soft=10):
    row_time = 1.4
    gap = (seconds - row_time) / 2
    dt = row_time / soft
    events = []
    for i, r in enumerate((3, 2, 1)):
        ramp(events, state, [row_id(r, c) for c in range(1, COLUMNS + 1)],
             MAGENTA, i * gap, dt, int(dt * 1000), soft)
    return events


def row_fill_events(state, seconds=1.0, soft=3, group=3, row=1, color=CYAN):
    n_groups = -(-COLUMNS // group)
    dt = seconds / (n_groups + soft - 1)
    events = []
    for g in range(n_groups):
        cols = [COLUMNS - g * group - j for j in range(group) if COLUMNS - g * group - j >= 1]
        ramp(events, state, [row_id(row, c) for c in cols], color, g * dt, dt, int(dt * 1000), soft)
    return events


def sin_wave(seconds=10, dt=0.05):
    fade = int(dt * 1000)
    events = []
    for i in range(int(seconds / dt)):
        t = i * dt
        amp = min(1.0, t / 2.0)
        frame = {}
        for c in range(1, COLUMNS + 1):
            h = 1.5 + WAVE_AMPLITUDE * math.sin(2 * math.pi * (c + WAVE_SPEED * t) / WAVE_LENGTH)
            for r in (1, 2, 3):
                frame[row_id(r, c)] = mix(MAGENTA, CYAN, clamp(h - (3 - r)) * amp)
        events.append((t, frame, fade))
    return events


def smooth_lines(seconds=10, dt=0.05, wave_len=15, wave_amp=2, row1_lead=4, row3_lead=4):
    fade = int(dt * 1000)
    events = []
    for i in range(int(seconds / dt)):
        t = i * dt
        amp = min(1.0, t / 2.0) * 0.9
        frame = {}
        for c in range(1, COLUMNS + 1):
            for r, shift, base in ((1, -row1_lead, 0), (2, 0, 1), (3, row3_lead, 0)):
                h = 1.0 + wave_amp * math.sin(2 * math.pi * (c + shift + WAVE_SPEED * t) / wave_len)
                frame[row_id(r, c)] = mix(CYAN, MAGENTA, clamp(h - base) * amp)
        events.append((t, frame, fade))
    return events


def blend(background, parts):
    return Color(*(
        max(0, min(255, int(getattr(background, ch) +
                            sum(w * (getattr(color, ch) - getattr(background, ch)) for w, color in parts))))
        for ch in "rgbw"))


def move_lights(items, direction="right", seconds=5.0, speed=3.0, background=BLACK, dt=0.05):
    sign = -1 if direction == "right" else 1
    fade = int(dt * 1000)
    sources = [((i - 1) // COLUMNS + 1, (i - 1) % COLUMNS + 1, color) for i, color in items.items()]
    rows = {r for r, _, _ in sources}

    events = []
    for i in range(int(seconds / dt) + 1):
        t = i * dt
        parts = {}
        for row, col, color in sources:
            x = col + speed * t * sign
            lo = math.floor(x)
            frac = x - lo
            for c, weight in ((lo, 1 - frac), (lo + 1, frac)):
                if 1 <= c <= COLUMNS and weight > 0:
                    parts.setdefault(row_id(row, c), []).append((weight, color))

        frame = {row_id(r, c): blend(background, parts.get(row_id(r, c), []))
                 for r in rows for c in range(1, COLUMNS + 1)}
        events.append((t, frame, fade))
    return events


def show(lights):
    arrow = {row_id(r, c): MAGENTA for r, c in
             [(1, 27), (2, 26), (3, 26), (1, 26), (2, 25), (3, 25)]}
    back_arrow = {row_id(r, c): MAGENTA for r, c in
                  [(1, 1), (2, 1), (3, 2), (1, 2), (2, 2), (3, 3)]}

    lights.set_color(windows(), CYAN, 0)

    fill_from_edges(lights, scale(CYAN, DIM_CYAN_LEVEL), 4.0)

    brighten(lights, scale(CYAN, DIM_CYAN_LEVEL), CYAN)
    time.sleep(1.5)

    lights.set_color(windows(), CYAN_W100, 0)
    time.sleep(0.1)
    lights.set_color(windows(), MAGENTA, 2000)
    replace_from_center(lights, MAGENTA, 3.0)

    lights.turn_off()
    time.sleep(0.25)

    lights.set_colors(window_frame(CYAN, MAGENTA), 0)
    time.sleep(0.1)

    state = {}
    events = []
    for i in range(4):
        left, right = (MAGENTA, CYAN) if i % 2 == 0 else (CYAN, MAGENTA)
        events += clash_events(i * 3.0, left, right, state)
    events += window_swap_events(12)
    run_events(lights, events)
    time.sleep(0.5)

    lights.turn_off()
    state.clear()
    time.sleep(0.75)

    lights.set_colors(window_frame(CYAN, MAGENTA), 0)
    time.sleep(0.1)

    tl = Timeline()
    tl.add(sky_events(state))

    for r in (3, 2, 1):
        tl.add(row_fill_events(state, row=r))

    tl.add(move_lights(arrow, "right", seconds=2.1, speed=15, background=CYAN))
    tl.add(move_lights(back_arrow, "left", seconds=2.1, speed=15, background=CYAN))

    tl.add(smooth_lines())
    for r in (1, 2, 3):
        tl.add(row_fill_events(state, row=r, color=MAGENTA))
    tl.t += 0.5
    tl.add(sin_wave())

    tl.events += window_swap_events(math.ceil(tl.t))
    run_events(lights, tl.events)

    lights.set_color(windows(), BLACK, 0)
    fill_from_edges(lights, scale(BLACK, DIM_CYAN_LEVEL), 5.0)


def main():
    env = simulation_env(TOPIC)
    controller = Controller(env)
    controller.lights.turn_off()

    print(f"Connected to {'simulation' if env.is_simulation else 'production'} (topic={TOPIC})")

    show(controller.lights)

    controller.lights.turn_off()
    print("Done.")


if __name__ == "__main__":
    main()