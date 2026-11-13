"""The full show: three scenes in a row.

    uv run main.py          # simulator  (topic: handsoff-show)
    uv run main.py --lab    # real lab

Everything runs in ONE process with ONE MQTT connection.
"""

import sys
import time

from tuke_openlab import Controller, production_env, simulation_env

import andrii
import mark
import tymofii

SHOW_TOPIC = "handsoff-show"


def main():
    env = production_env() if "--lab" in sys.argv else simulation_env(SHOW_TOPIC)
    controller = Controller(env)
    lights = controller.lights
    kind = "production" if not env.is_simulation else "simulation"
    print(f"Connected to {kind} (topic={SHOW_TOPIC})")

    scenes = [("Mark", mark.show), ("Andrii", andrii.show), ("Tymofii", tymofii.show)]
    for name, scene in scenes:
        print(f"--- {name} ---")
        scene(lights)
        time.sleep(0.1)

    lights.turn_off()
    print("Done.")


if __name__ == "__main__":
    main()
