import time
from helpers import *
import math

from tuke_openlab import Controller, simulation_env
from tuke_openlab.lights import Color

TOPIC = "tymofii_t"
ROWS, COLUMNS = 3, 27
WINDOWS = 8

MAGENTA = Color.from_hex_string("FF007200")
CYAN = Color.from_hex_string("14E5FF00")
CYAN_W100 = Color(CYAN.r, CYAN.g, CYAN.b, 100)   # cyan glow with 100 on the white channel
DIM_CYAN_LEVEL = 0.4      
SOFT = 10                       

CENTER = 14                                       # middle column (1 = rightmost, 27 = leftmost)


# ------------------------------------------------------------------ utilities
def scale(color, k):
    """Dim a color: k=1 -> unchanged, k=0 -> black."""
    return Color(int(color.r * k), int(color.g * k), int(color.b * k), int(color.w * k))


def run_events(lights, events, tolerance=0.01):
    """
    events: [(time_s, {light_id: Color}, fade_ms), ...]
    Sends ONE set_colors message per fade value per tick. If we are behind schedule,
    all overdue frames are merged (later ones win), so the wall catches up in one message
    instead of a burst.
    """
    events = sorted(events, key=lambda e: e[0])
    start = time.monotonic()
    i = 0
    while i < len(events):
        now = time.monotonic() - start
        if events[i][0] > now:
            time.sleep(events[i][0] - now)
            now = time.monotonic() - start

        by_fade = {}                                   # fade -> merged frame
        while i < len(events) and events[i][0] <= now + tolerance:
            _, frame, fade = events[i]
            by_fade.setdefault(fade, {}).update(frame)
            i += 1

        for fade, frame in by_fade.items():
            lights.set_colors(frame, fade)


def sweep(lights, steps, seconds):
    """steps: list of (columns_to_set, color). Evenly spread over `seconds`."""
    dt = seconds / len(steps)
    fade = int(dt * 1000 * 1.5)
    events = [(i * dt, column_frame(cols, color), fade)
              for i, (cols, color) in enumerate(steps)]
    run_events(lights, events)

def soft_sweep(lights, columns_at, start, end, seconds, soft=SOFT):
    """
    columns_at(d) -> columns at distance d from where the wave starts (d = 0..CENTER-1).
    Each column goes start -> end in `soft` stages as the front passes.
    Still one set_colors message per tick.
    """
    n = CENTER + soft - 1                    # extra ticks so the trailing edge finishes
    dt = seconds / n
    fade = int(dt * 1000)
    events = []
    for k in range(n):
        frame = {}
        for d in range(max(0, k - soft + 1), min(k, CENTER - 1) + 1):
            level = (k - d + 1) / soft       # 1/soft ... 1.0
            frame.update(column_frame(columns_at(d), mix(start, end, level)))
        events.append((k * dt, frame, fade))
    run_events(lights, events)

def brighten(lights, start, end, seconds=0.5, steps=5):
    dt = seconds / steps
    fade = int(dt * 1000)
    ids = grid()
    events = [(i * dt, {l: mix(start, end, (i + 1) / steps) for l in ids}, fade)
              for i in range(steps)]
    run_events(lights, events)


# --------------------------------------------------------------------- scenes
def fill_from_edges(lights, color, seconds, start=Color()):
    """Both edges -> center, with a soft front."""
    soft_sweep(lights, lambda d: [1 + d, COLUMNS - d], start, color, seconds)


def replace_from_center(lights, color, seconds, start=CYAN):
    """Center -> both edges, with a soft front. `start` is the color being replaced."""
    soft_sweep(lights, lambda d: [CENTER - d, CENTER + d], start, color, seconds)


def column_frame(cols, color):
    return {l: color for c in cols for l in column(c)}


def ramp(events, state, ids, new, t, dt, fade, soft=SOFT):
    """Fade lights from their previous color to `new` in `soft` stages, one stage per dt."""
    for i in ids:
        old = state.get(i, Color())
        for s in range(1, soft + 1):
            events.append((t + (s - 1) * dt, {i: mix(old, new, s / soft)}, fade))
        state[i] = new


def clash_events(offset, left, right, state, seconds=3.0, soft=SOFT):
    half = seconds / 2
    events = []

    # one tick = dt; each phase has CENTER + soft - 1 ticks so the soft tail fits in its half
    dt = half / (CENTER + soft - 1)
    fade = int(dt * 1000)

    # Phase A: approach, then the crash in the center column
    for d in range(CENTER - 1):
        t = offset + d * dt
        ramp(events, state, column(COLUMNS - d), left, t, dt, fade, soft)
        ramp(events, state, column(1 + d), right, t, dt, fade, soft)
    ramp(events, state, column(CENTER), mix(left, right, 0.5),
         offset + (CENTER - 1) * dt, dt, fade, soft)

    # Phase B: right color flows along the top row, left color along the bottom row
    t_b = offset + half
    for k in range(CENTER):
        t = t_b + k * dt
        ramp(events, state, [CENTER + k], right, t, dt, fade, soft)               
        ramp(events, state, [CENTER - k + 2 * COLUMNS], left, t, dt, fade, soft)       
    return events

    


def window_swap_events(seconds):
    a_lamps = [window(i)[0] for i in range(1, WINDOWS + 1)]
    b_lamps = [window(i)[1] for i in range(1, WINDOWS + 1)]
    events = []
    for k in range(int(seconds) + 1):
        a_col, b_col = (MAGENTA, CYAN) if k % 2 == 0 else (CYAN, MAGENTA)
        frame = {**{l: a_col for l in a_lamps}, **{l: b_col for l in b_lamps}}
        events.append((k, frame, 1000))
    return events




def row_id(r, c):
    return c + (r - 1) * COLUMNS


def sky_events(state, seconds=3.0, soft=10):
    row_time = 1.4                                  # one row's fade; rows start (seconds-row_time)/2 apart
    gap = (seconds - row_time) / 2
    dt = row_time / soft
    fade = int(dt * 1000)
    events = []
    for i, r in enumerate((3, 2, 1)):
        ids = [row_id(r, c) for c in range(1, COLUMNS + 1)]
        ramp(events, state, ids, MAGENTA, i * gap, dt, fade, soft)
    return events


def sea_events(state, seconds=1.0, soft=3, group=3):
    n_groups = -(-COLUMNS // group)                 # ceil
    dt = seconds / (n_groups + soft - 1)
    fade = int(dt * 1000)
    events = []
    for g in range(n_groups):
        cols = [COLUMNS - g * group - j for j in range(group) if COLUMNS - g * group - j >= 1]
        ids = [row_id(3, c) for c in cols]
        ramp(events, state, ids, CYAN, g * dt, dt, fade, soft)
    return events







WAVE_LEVEL = 0.6        #lower = darker
WAVE_LENGTH = 14             # columns per full sine period (27 columns -> ~2 waves on screen)
WAVE_SPEED = 4.0             # columns per second
WAVE_AMPLITUDE = 1.3         # how far the water surface swings (0..1)
WAVE_MAGENTA = scale(MAGENTA, WAVE_LEVEL)

def sin_wave(seconds=10, dt=0.05):

    fade = int(dt * 1000)
    events = []
    for i in range(int(seconds / dt)):
        t = i * dt
        amp = min(1.0, t / 2.0)       
        frame = {}
        for c in range(1, COLUMNS + 1):
            phase = 2 * math.pi * (c + WAVE_SPEED * t) / WAVE_LENGTH 
            h = 1.5 + WAVE_AMPLITUDE * math.sin(phase)                  
            cover3 = max(0.0, min(1.0, h))                                      
            cover2 = max(0.0, min(1.0, h - 1))
            cover1 = max(0.0, min(1.0, h - 2))
            frame[row_id(3, c)] = mix(CYAN, MAGENTA, cover3 * amp)
            frame[row_id(2, c)] = mix(CYAN, MAGENTA, cover2 * amp)
            frame[row_id(1, c)] = mix(CYAN, MAGENTA, cover1 * amp)
        events.append((t, frame, fade))
    return events

 
def smooth_lines(seconds=10, dt=0.05, wave_len = 15, wave_amp = 2, row1_lead=4, row3_lead=4):

    fade = int(dt * 1000)
    events = []


    def height(c, shift, t):
        phase = 2 * math.pi * (c + shift + WAVE_SPEED * t) / wave_len
        return 1.0 + wave_amp * math.sin(phase)



    for i in range(int(seconds / dt)):
        t = i * dt
        amp = min(1.0, t / 2.0) * .9                                  # wave fades in over the first 2 s
        frame = {}
        for c in range(1, COLUMNS + 1):

            h1 = height(c, -row1_lead, t)              # behind
            h2 = height(c, 0, t)                      
            h3 = height(c, +row3_lead, t)               # ahead

            phase = 2 * math.pi * (c + WAVE_SPEED * t) / wave_len 
            h = 1.0 + wave_amp * math.sin(phase)  

            cover3 = max(0.0, min(1.0, h3))                                    
            cover2 = max(0.0, min(1.0, h2 - 1))
            cover1 = max(0.0, min(1.0, h1))

            frame[row_id(3, c)] = mix(CYAN, MAGENTA, cover3 * amp)

            frame[row_id(2, c)] = mix(CYAN, MAGENTA, cover2 * amp)

            frame[row_id(1, c)] = mix(CYAN, MAGENTA, cover1 * amp )
        events.append((t, frame, fade))
    return events


def show(lights):
    """
    # 1. windows instantly full cyan (they stay lit through the next steps)
    lights.set_color(windows(), CYAN, 0)

    # 2. faded cyan from both sides to the center (4 s)
    fill_from_edges(lights, scale(CYAN, DIM_CYAN_LEVEL), 4.0)

    # 3. full brightness cyan on the whole grid (0.75 s)
    brighten(lights, scale(CYAN, DIM_CYAN_LEVEL), CYAN, seconds=0.5)
    time.sleep(1.5)

    # 4. magenta replaces cyan from the center outwards (2 s),
    #    windows: 100w cyan glow slowly turns into magenta at the same time
    lights.set_color(windows(), CYAN_W100, 0)
    time.sleep(0.1)
    lights.set_color(windows(), MAGENTA, 2000)
    replace_from_center(lights, MAGENTA, 3.0)

    # 5. turn off (0.25 s)
    lights.turn_off()
    time.sleep(0.25)

    # 6 + 7. two clashes back-to-back (3 s each), windows cross-fading meanwhile
    a = [window(i)[0] for i in range(1, WINDOWS + 1)]
    b = [window(i)[1] for i in range(1, WINDOWS + 1)]
    lights.set_colors({**{l: CYAN for l in a}, **{l: MAGENTA for l in b}}, 0)
    time.sleep(0.1)

    events = []
    state = {}                                   # last color per wall light, so fades start from the real previous color
    for i in range(2):                           # 4 clashes x 3 s = 12 s
        left, right = (MAGENTA, CYAN) if i % 2 == 0 else (CYAN, MAGENTA)
        events += clash_events(i * 3.0, left, right, state, seconds=3.0)
    events += window_swap_events(6)             # windows cross-fade for the whole 12 s
    run_events(lights, events)
    time.sleep(0.5)
    
    run_events(lights, events)
    time.sleep(0.5)

    # 8. turn off (0.75 s)
    lights.turn_off()
    state.clear()                                   # everything is dark again
    time.sleep(0.75)

    # 9. magenta sky appears from the bottom until it fills the screen (3 s)
    run_events(lights, sky_events(state, seconds=3.0))

    # 10. cyan sea fills the bottom row (1 s)
    run_events(lights, sea_events(state, seconds=1.0))
    """
    # 12. waves appear and move to the right 
    events = []
    run_events(lights, smooth_lines())
    run_events(lights, sin_wave())

   

    # END OF SCENE


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