import time
import random
import math
import sys

from tuke_openlab import Controller, simulation_env
from tuke_openlab.lights import Color
from helpers import COLUMNS, ROWS, WINDOWS, rainbow, hsv, mix, window

# Any unique string. Must not contain MQTT wildcards (+, #) or null chars.
TOPIC = "andrii"
IS_LAB = "--lab" in sys.argv

def ripples(lights, seconds=20, delay=0.04, spawn_interval=0.4, wave_speed=8.0, ring_width=1.2):
    start_time = time.monotonic()
    last_spawn_time = 0
    active_ripples = []

    ROW_ASPECT_RATIO = 2.5  

    while time.monotonic() - start_time < seconds:
        now = time.monotonic()
        frame = {}

        if now - last_spawn_time >= spawn_interval:
            active_ripples.append({
                "r": random.randint(1, ROWS),
                "c": random.randint(1, COLUMNS),
                "spawn_time": now,
                "hue": random.random()
            })
            last_spawn_time = now

        for c in range(1, COLUMNS + 1):
            for r in range(1, ROWS + 1):
                max_brightness = 0.0
                selected_hue = 0.0

                for ripple in active_ripples:
                    age = now - ripple["spawn_time"]
                    radius = age * wave_speed

                    dist = math.sqrt((c - ripple["c"]) ** 2 + ((r - ripple["r"]) * ROW_ASPECT_RATIO) ** 2)

                    distance_to_ring = abs(dist - radius)

                    if distance_to_ring < ring_width:
                        ring_intensity = max(0.0, 1.0 - (distance_to_ring / ring_width) ** 2)
                        
                        brightness = ring_intensity

                        if brightness > max_brightness:
                            max_brightness = brightness
                            selected_hue = ripple["hue"]

                if max_brightness > 0.02:
                    lamp_id = c + (r - 1) * COLUMNS
                    frame[lamp_id] = hsv(selected_hue, max_brightness)

        active_ripples = [r for r in active_ripples if (now - r["spawn_time"]) * wave_speed < 35.0]

        for w in range(1, WINDOWS + 1):
            col_idx = 1 + round((w - 1) * (COLUMNS - 1) / (WINDOWS - 1))
            top_lamp_in_col = col_idx + COLUMNS  # row 2
            win_color = frame.get(top_lamp_in_col, Color())
            for win_lamp in window(w):
                frame[win_lamp] = win_color

        # 5. Отправка кадра на контроллер
        lights.set_colors(frame)
        time.sleep(delay)


def show(lights):
    rainbow(lights, seconds=3, delay=0.01, brightness=1.0)
    ripples(lights, ring_width=4.0, spawn_interval=round(random.uniform(0.8, 1.2), 2),
            delay=0.04, wave_speed=10.0)


def main():

    env = production_env() if IS_LAB else simulation_env(TOPIC)
    controller = Controller(env)  # connects to the MQTT broker

    print(f"Connected to {'simulation' if env.is_simulation else 'production'} (topic={TOPIC})")

    rainbow(controller.lights, seconds=3, delay=0.01, brightness=1.0)
    ripples(controller.lights, ring_width=4.0, spawn_interval=round(random.uniform(0.8, 1.2), 2), delay=0.04, wave_speed=10.0)

    controller.lights.turn_off()


if __name__ == "__main__":
    main()