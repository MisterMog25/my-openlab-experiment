"""The full show: three scenes in a row, with a colourful transition between them.

    uv run main.py          # simulator  (topic: handsoff-show)
    uv run main.py --lab    # real lab

Everything runs in ONE process with ONE MQTT connection, so the scenes share
the same wall and the transitions are smooth.
"""

import sys
import time

from tuke_openlab import Controller, production_env, simulation_env
from tuke_openlab.lights import Color

from helpers import COLUMNS, column, hsv, windows
import andrii
import mark
import tymofii

SHOW_TOPIC = "handsoff-show"


def transition(lights, seconds=3.0):
    """A colourful wave wipes across the wall, then fades out."""
    start = time.monotonic()
    while True:
        t = time.monotonic() - start
        if t >= seconds:
            break
        fade = 1.0 - max(0.0, (t - seconds * 0.5) / (seconds * 0.5))
        crest = t * 14
        frame = {}
        for c in range(1, COLUMNS + 1):
            hue = 0.5 + 0.37 * (1 - c / COLUMNS)
            power = max(0.0, 1.0 - abs(c - crest) / 5.0) * fade
            for light in column(c):
                frame[light] = hsv(hue, power) if power > 0.02 else Color()
        for w in windows():
            frame[w] = Color()
        lights.set_colors(frame)
        time.sleep(0.05)


def main():
    env = production_env() if "--lab" in sys.argv else simulation_env(SHOW_TOPIC)
    controller = Controller(env)
    lights = controller.lights
    kind = "production" if not env.is_simulation else "simulation"
    print(f"Connected to {kind} (topic={SHOW_TOPIC})")

    scenes = [("Tymofii", tymofii.scene), ("Mark", mark.show), ("Andrii", andrii.show)]
    for name, scene in scenes:
        print(f"--- {name} ---")
        scene(lights)
        transition(lights)

    lights.turn_off()
    print("Done.")


if __name__ == "__main__":
    main()
