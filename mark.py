"""Mark's experiments."""

import time

from tuke_openlab import Controller, simulation_env
from tuke_openlab.lights import Color

from helpers import COLUMNS, column, windows

# Any unique string. Must not contain MQTT wildcards (+, #) or null chars.
TOPIC = "mark"


def wave(lights, seconds=15):
    """A wave running along the wall, windows blinking in time."""
    start = time.monotonic()
    step = 0
    while time.monotonic() - start < seconds:
        frame = {}
        for i in range(1, COLUMNS + 1):
            distance = (i - step) % (COLUMNS + 4)      # distance to the crest
            if distance < 4:
                power = 1 - distance / 4               # the tail fades out
                for light in column(i):
                    frame[light] = Color(r=int(255 * power), g=int(120 * power))
            else:
                for light in column(i):
                    frame[light] = Color()             # off
        for w in windows():                            # windows blink in time
            frame[w] = Color(w=255) if step % 8 < 2 else Color()
        lights.set_colors(frame)
        step += 1
        time.sleep(0.12)


def main():
    env = simulation_env(TOPIC)
    controller = Controller(env)  # connects to the MQTT broker
    lights = controller.lights

    print(f"Connected to {'simulation' if env.is_simulation else 'production'} (topic={TOPIC})")

    wave(lights, seconds=15)

    # Ready-made effects from helpers.py — uncomment what you want to see:
    #
    #   from helpers import flag, pulse, rainbow, spectrum
    #
    #   flag(lights, seconds=10)
    #   pulse(lights, seconds=15)
    #   rainbow(lights, seconds=15)
    #   spectrum(lights, seconds=10)

    # --- screens -----------------------------------------------------------
    controller.screens.panel_2x2.set_url("https://www.tuke.sk")
    controller.screens.vertical[1].set_url("https://www.fei.tuke.sk")
    time.sleep(3)

    # return displays to their default content
    controller.screens.panel_2x2.set_default()
    controller.screens.vertical[1].set_default()

    lights.turn_off()
    print("Done.")


if __name__ == "__main__":
    main()
