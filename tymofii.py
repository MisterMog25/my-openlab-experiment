import time
from helpers import *
import math

from tuke_openlab import Controller, simulation_env
from tuke_openlab.lights import Color

TOPIC = "tymofii"
ROWS, COLUMNS = 3, 27
WINDOWS = 8

MAGENTA = Color.from_hex_string("FF007200")
CYAN = Color.from_hex_string("14E5FF00")
BLACK = Color()
CYAN_W100 = Color(CYAN.r, CYAN.g, CYAN.b, 100)   
DIM_CYAN_LEVEL = 0.4      
SOFT = 12                       

CENTER = 14                                     


# ----- utilities
def scale(color, k):
    return Color(int(color.r * k), int(color.g * k), int(color.b * k), int(color.w * k))


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


def sweep(lights, steps, seconds):
    dt = seconds / len(steps)
    fade = int(dt * 1000 * 1.5)
    events = [(i * dt, column_frame(cols, color), fade)
              for i, (cols, color) in enumerate(steps)]
    run_events(lights, events)

def soft_sweep(lights, columns_at, start, end, seconds, soft=SOFT):
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
    soft_sweep(lights, lambda d: [1 + d, COLUMNS - d], start, color, seconds)


def replace_from_center(lights, color, seconds, start=CYAN):
    soft_sweep(lights, lambda d: [CENTER - d, CENTER + d], start, color, seconds)


def column_frame(cols, color):
    return {l: color for c in cols for l in column(c)}


def ramp(events, state, ids, new, t, dt, fade, soft=SOFT):
    for i in ids:
        old = state.get(i, Color())
        for s in range(1, soft + 1):
            events.append((t + (s - 1) * dt, {i: mix(old, new, s / soft)}, fade))
        state[i] = new


def clash_events(offset, left, right, state, seconds=3.0, soft=SOFT):
    half = seconds / 2
    events = []

    
    dt = half / (CENTER + soft - 1)
    fade = int(dt * 1000)

    # approach, then the crash in the center column
    for d in range(CENTER - 1):
        t = offset + d * dt
        ramp(events, state, column(COLUMNS - d), left, t, dt, fade, soft)
        ramp(events, state, column(1 + d), right, t, dt, fade, soft)
    ramp(events, state, column(CENTER), mix(left, right, 0.8),
         offset + (CENTER - 1) * dt, dt, fade, soft)

    # right color flows along the top row, left color along the bottom row
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
    row_time = 1.4                                  
    gap = (seconds - row_time) / 2
    dt = row_time / soft
    fade = int(dt * 1000)
    events = []
    for i, r in enumerate((3, 2, 1)):
        ids = [row_id(r, c) for c in range(1, COLUMNS + 1)]
        ramp(events, state, ids, MAGENTA, i * gap, dt, fade, soft)
    return events


def row_fill_events(state, seconds=1.0, soft=3, group=3, row = 1, color=CYAN):
    n_groups = -(-COLUMNS // group)    
    dt = seconds / (n_groups + soft - 1)
    fade = int(dt * 1000)
    events = []
    for g in range(n_groups):
        cols = [COLUMNS - g * group - j for j in range(group) if COLUMNS - g * group - j >= 1]
        ids = [row_id(row, c) for c in cols]
        ramp(events, state, ids, color, g * dt, dt, fade, soft)
    return events








WAVE_LEVEL = 0.6     
WAVE_LENGTH = 14             
WAVE_SPEED = 4.0           
WAVE_AMPLITUDE = 1.3         
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
            frame[row_id(3, c)] = mix(MAGENTA, CYAN, cover3 * amp)
            frame[row_id(2, c)] = mix(MAGENTA, CYAN, cover2 * amp)
            frame[row_id(1, c)] = mix(MAGENTA, CYAN, cover1 * amp)
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
        amp = min(1.0, t / 2.0) * .9                                 
        frame = {}
        for c in range(1, COLUMNS + 1):

            h1 = height(c, -row1_lead, t)            
            h2 = height(c, 0, t)                      
            h3 = height(c, +row3_lead, t)              

            phase = 2 * math.pi * (c + WAVE_SPEED * t) / wave_len 
           #h = 1.0 + wave_amp * math.sin(phase)  

            cover3 = max(0.0, min(1.0, h3))                                    
            cover2 = max(0.0, min(1.0, h2 - 1))
            cover1 = max(0.0, min(1.0, h1))

            frame[row_id(3, c)] = mix(CYAN, MAGENTA, cover3 * amp)

            frame[row_id(2, c)] = mix(CYAN, MAGENTA, cover2 * amp)

            frame[row_id(1, c)] = mix(CYAN, MAGENTA, cover1 * amp )
        events.append((t, frame, fade))
    return events

def id_to_row_col(light_id):
    return (light_id - 1) // COLUMNS + 1, (light_id - 1) % COLUMNS + 1


def move_lights(items, direction="right", seconds=5.0, speed=3.0,background=None, wrap=False, offset=0.0, dt=0.05):
    if background is None:
        background = Color()
    sign = -1 if direction == "right" else +1  
    fade = int(dt * 1000)

    sources = []                                    
    for light_id, color in items.items():
        row, col = id_to_row_col(light_id)
        sources.append((row, col, color))
    rows = sorted({r for r, _, _ in sources})

    events = []
    for i in range(int(seconds / dt) + 1):
        t = i * dt
        shift = speed * t * sign

        acc = {}                               
        for row, col, color in sources:
            x = col + shift
            if wrap:
                x = (x - 1) % COLUMNS + 1
            lo = math.floor(x)
            frac = x - lo
            for c, weight in ((lo, 1 - frac), (lo + 1, frac)):
                if wrap:
                    c = (c - 1) % COLUMNS + 1
                if not (1 <= c <= COLUMNS) or weight <= 0:
                    continue                    
                a = acc.setdefault(row_id(row, c), [0.0, 0.0, 0.0, 0.0])
                for k, ch in enumerate("rgbw"):
                    a[k] += weight * (getattr(color, ch) - getattr(background, ch))

        frame = {}
        for row in rows:                           
            for c in range(1, COLUMNS + 1):     
                lid = row_id(row, c)
                a = acc.get(lid)
                if a is None:
                    frame[lid] = background
                else:
                    frame[lid] = Color(*(
                        max(0, min(255, int(getattr(background, ch) + a[k])))
                        for k, ch in enumerate("rgbw")))
        events.append((offset + t, frame, fade))
    return events

class Connect_windows:
    def __init__(self):
        self.events = []
        self.t = 0.0

    def add(self, events):
        if not events:
            return
        self.events += [(self.t + t, frame, fade) for t, frame, fade in events]
        self.t += max(t for t, _, _ in events)


def show(lights):
    
    # 1. windows cyan 
    lights.set_color(windows(), CYAN, 0)

    arrow = {
    row_id(1, 27): MAGENTA,
    row_id(2, 26): MAGENTA,
    row_id(3, 26): MAGENTA,
    row_id(1, 26): MAGENTA,
    row_id(2, 25): MAGENTA,
    row_id(3, 25): MAGENTA,
    }

    back_arrow = {
    row_id(1, 1): MAGENTA,
    row_id(2, 1): MAGENTA,
    row_id(3, 2): MAGENTA,
    row_id(1, 2): MAGENTA,
    row_id(2, 2): MAGENTA,
    row_id(3, 3): MAGENTA,
    }

    # 2. cyan from both sides to the center
    fill_from_edges(lights, scale(CYAN, DIM_CYAN_LEVEL), 4.0)

    # 3. full brightness cyan 
    brighten(lights, scale(CYAN, DIM_CYAN_LEVEL), CYAN, seconds=0.5)
    time.sleep(1.5)

    # 4. magenta replaces cyan from the center
    #    windows:  cyan into magenta 
    lights.set_color(windows(), CYAN_W100, 0)
    time.sleep(0.1)
    lights.set_color(windows(), MAGENTA, 2000)
    replace_from_center(lights, MAGENTA, 3.0)

    # 5. turn off
    lights.turn_off()
    time.sleep(0.25)

    # 6 + 7. two clashes 
    a = [window(i)[0] for i in range(1, WINDOWS + 1)]
    b = [window(i)[1] for i in range(1, WINDOWS + 1)]
    lights.set_colors({**{l: CYAN for l in a}, **{l: MAGENTA for l in b}}, 0)
    time.sleep(0.1)

    events = []
    state = {}                                   
    for i in range(4):                           
        left, right = (MAGENTA, CYAN) if i % 2 == 0 else (CYAN, MAGENTA)
        events += clash_events(i * 3.0, left, right, state, seconds=3.0)

    events += window_swap_events(12)               
    run_events(lights, events)

    time.sleep(0.5)
    
   # run_events(lights, events)
   # time.sleep(0.5)

    # 8. turn off
    lights.turn_off()
    state.clear()
    time.sleep(0.75)


    lights.set_colors({**{l: CYAN for l in a}, **{l: MAGENTA for l in b}}, 0) 
    time.sleep(0.1)

    tl = Connect_windows()

    # 9. magenta appears from the bottom and fills the screen
    tl.add(sky_events(state, seconds=3.0))

    # 10. cyan fill
    tl.add(row_fill_events(state, seconds=1.0, row=3))
    tl.add(row_fill_events(state, seconds=1.0, row=2))
    tl.add(row_fill_events(state, seconds=1.0, row=1))

    # 11. two slashes
    tl.add(move_lights(arrow, direction="right", seconds=2.1, speed=15, background=CYAN))
    tl.add(move_lights(back_arrow, direction="left", seconds=2.1, speed=15, background=CYAN))

    # 12. waves to the right, magenta fill and sine wave
    tl.add(smooth_lines())
    tl.add(row_fill_events(state, seconds=1.0, row=1, color=MAGENTA))
    tl.add(row_fill_events(state, seconds=1.0, row=2, color=MAGENTA))
    tl.add(row_fill_events(state, seconds=1.0, row=3, color=MAGENTA))
    tl.t += 0.5
    tl.add(sin_wave())

    # windows
    tl.events += window_swap_events(math.ceil(tl.t))

    run_events(lights, tl.events)

    lights.set_color(windows(), BLACK, 0)
    fill_from_edges(lights, scale(BLACK, DIM_CYAN_LEVEL), 4.0)

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