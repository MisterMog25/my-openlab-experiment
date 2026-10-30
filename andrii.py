import time


from tuke_openlab import Controller, simulation_env
from tuke_openlab.lights import Color

# Any unique string. Must not contain MQTT wildcards (+, #) or null chars.
TOPIC = "andrii"


def main():
    env = simulation_env(TOPIC)
    controller = Controller(env)  # connects to the MQTT broker

    print(f"Connected to {'simulation' if env.is_simulation else 'production'} (topic={TOPIC})")

    # --- lights ------------------------------------------------------------
    controller.lights.set_all(Color(r=0, g=0, b=255), fade=500)
    time.sleep(1)

    # individual lights (1..N), different colors, 1s fade
    controller.lights.set_colors(
        {
            1: Color(r=255, g=0, b=0),
            2: Color(r=0, g=255, b=0),
            3: Color(r=0, g=0, b=255),
        },
        fade=1000,
    )
    time.sleep(1)

    # --- screens -----------------------------------------------------------
    controller.screens.panel_2x2.set_url("https://www.tuke.sk")
    controller.screens.vertical[1].set_url("https://www.fei.tuke.sk")
    time.sleep(3)

    # return displays to their default content
    controller.screens.panel_2x2.set_default()
    controller.screens.vertical[1].set_default()

    controller.lights.turn_off()
    print("Done.")


if __name__ == "__main__":
    main()
