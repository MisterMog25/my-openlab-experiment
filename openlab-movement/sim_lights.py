import json
import math
import time
import argparse
from datetime import datetime
from threading import Thread
import tuke_openlab
from tuke_openlab.lights import Color
import Lamps

# Command line arguments parser
parser = argparse.ArgumentParser(description="OpenLab Green Lights Movement Tracking with Client-Side Software Fade")
parser.add_argument(
    "-P", "--production",
    action="store_true",
    help="Use production environment instead of simulation (my-test)"
)
parser.add_argument(
    "-S", "--movement_simulation",
    action="store_true",
    help="Run background thread to simulate a person walking across the lab (listens ONLY to sim topic)"
)
parser.add_argument(
    "-f", "--fade",
    type=int,
    default=1000,
    help="Fade duration in milliseconds for lights turning off/changing (default: 1000ms)"
)
parser.add_argument(
    "-r", "--rate",
    type=float,
    default=20.0,
    help="Maximum light update frequency in Hz / times per second (default: 20.0 Hz)"
)

args = parser.parse_args()

# Throttling interval for light updates (20 Hz -> 0.05s)
LIGHT_UPDATE_INTERVAL = 1.0 / args.rate if args.rate > 0 else 0.0
last_light_send_time = 0.0

# Software Fade State: Track last trigger timestamp for each light (1 to 97)
LIGHT_LAST_SEEN = {i: 0.0 for i in range(1, 98)}

# 1. Environment selection based on -P / --production flag
if args.production:
    env = tuke_openlab.production_env()
    print("[Config] Connected to PRODUCTION environment.")
else:
    env = tuke_openlab.simulation_env("nz696iv")
    print("[Config] Connected to SIMULATION environment ('nz696iv').")

openlab = tuke_openlab.Controller(env)

OFF = Color()  # Color(0, 0, 0, 0)

# 2. Build 2D Light Coordinate Map (Lights 1 to 97) with requested offsets
OFFSET_X = -2.0
OFFSET_Y = -3.0

LIGHT_POSITIONS = {}

# Main Ceiling Grid Rows (Lights 1 to 81)
for col in range(1, 28):
    x_pos = (0.8 + (col - 1) * 0.77) + OFFSET_X
    LIGHT_POSITIONS[28 - col] = (x_pos, 11.0 + OFFSET_Y)  # Row 1 (Top)
    LIGHT_POSITIONS[55 - col] = (x_pos, 9.0 + OFFSET_Y)  # Row 2 (Middle)
    LIGHT_POSITIONS[82 - col] = (x_pos, 7.0 + OFFSET_Y)   # Row 3 (Lower)

# Bottom Desk Lights (Lights 82 to 97)
bottom_desks_base = {
    97: (1.2, 0.8),  96: (1.2, 1.8),
    95: (3.5, 1.3),  94: (4.1, 1.3),
    93: (6.4, 0.8),  92: (6.4, 1.8),
    91: (8.7, 1.3),  90: (9.3, 1.3),
    89: (11.6, 0.8), 88: (11.6, 1.8),
    87: (13.9, 1.3), 86: (14.5, 1.3),
    85: (16.8, 0.8), 84: (16.8, 1.8),
    83: (19.1, 1.3), 82: (19.7, 1.3)
}

bottom_desks = {
    lid: (x + OFFSET_X, y + OFFSET_Y)
    for lid, (x, y) in bottom_desks_base.items()
}
LIGHT_POSITIONS.update(bottom_desks)


def format_timestamp():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def find_nearest_light(x: float, y: float) -> int:
    """Finds the light ID closest to 2D floor position (x, y) in meters."""
    best_id = 1
    min_dist = float('inf')
    for light_id, (lx, ly) in LIGHT_POSITIONS.items():
        dist = math.hypot(x - lx, y - ly)
        if dist < min_dist:
            min_dist = dist
            best_id = light_id
    return best_id

def wait_for_player_in_start_zone(env, controller: tuke_openlab.Controller, lamp: Lamps.Lamp, start_lamp: int = 1) -> str:
    """
    1. Будує жовто-оранжеве поле 3x3.
    2. Чекає першу людину, яка зайде в зону, і запам'ятовує її Id.
    3. По одній лампі перефарбовує зону в зелений і повертає Id гравця.
    """
    #вимкнули всі лампи
    controller.lights.turn_off()
    #зробили стартову зону й отримали номера ламп
    zone_lamps = lamp.make_start_position(controller, start=start_lamp, hw=3)
    print(f"[Start Zone] Жовто-оранжеве поле активовано. Лампи зони: {zone_lamps}")
    print("[Start Zone] Очікуємо гравця в зоні...")

    detected_player_id = None

    def on_move(msg):
        nonlocal detected_player_id
        if detected_player_id is not None:
            return

        try:
            #декодуємо дані з mqtt
            data = json.loads(msg.payload.decode("utf-8"))
            persons = []

            # Формат 1: реальні камери / симулятор скриптом [{'Id': ..., 'Position': {'X': ..., 'Y': ...}}]
            if isinstance(data, list):
                for idx, p in enumerate(data, 1):
                    pos = p.get("Position", {})
                    if "X" in pos and "Y" in pos:
                        persons.append((p.get("Id", f"Player-{idx}"), pos["X"], pos["Y"]))

            # Формат 2: веб-симулятор карти {'positions': [[x, y], ...]}
            elif isinstance(data, dict) and "positions" in data:
                for idx, p in enumerate(data["positions"], 1):
                    if isinstance(p, (list, tuple)) and len(p) >= 2:
                        persons.append((f"SimPlayer-{idx}", p[0], p[1]))
                    elif isinstance(p, dict) and "X" in p and "Y" in p:
                        persons.append((p.get("Id", f"SimPlayer-{idx}"), p["X"], p["Y"]))

            for pid, x, y in persons:
                nearest = find_nearest_light(x, y)
                if nearest in zone_lamps:
                    detected_player_id = pid
                    print(f"[Start Zone] Гравець '{pid}' увійшов у зону (X={x:.2f}, Y={y:.2f}, лампа #{nearest})!")
                    break
        except Exception as e:
            print(f"[Error] {e}")

    topic = "openlab/unifiedMapPositions/output" if args.production else f"experiments/mapPositions/{env.simulation_topic}/#"
    env.mqtt.listen_on(topic)
    env.mqtt.subscribe_to(topic, on_move)

    while detected_player_id is None:
        time.sleep(0.05)

    # По одній лампі робимо стартову зону зеленою
    for lid in zone_lamps:
        lamp.lamp_green(controller, lid)
        time.sleep(0.15)

    print(f"[Start Zone] Зона підтверджена! Повертаємо ID гравця: {detected_player_id}")
    return detected_player_id 
    

def on_position_update(msg):
    """Callback triggered on receiving tracking data, rate-limited to max 20 Hz."""
    """Callback triggered on receiving tracking data, rate-limited to max 20 Hz."""
    global last_light_send_time

    now = time.time()
    if LIGHT_UPDATE_INTERVAL > 0 and (now - last_light_send_time) < LIGHT_UPDATE_INTERVAL:
        return
    last_light_send_time = now

    try:
        raw_text = msg.payload.decode('utf-8')
        data = json.loads(raw_text)
        
        persons_info = []
        
        # Format 1: Unified tracking array [{'Id': '...', 'Position': {'X': ..., 'Y': ...}}]
        if isinstance(data, list):
            for idx, person in enumerate(data, 1):
                p_id = person.get("Id", f"Person-{idx}")
                pos = person.get("Position", {})
                if "X" in pos and "Y" in pos:
                    x, y = pos["X"], pos["Y"]
                    nearest_light = find_nearest_light(x, y)
                    persons_info.append({
                        "id": p_id,
                        "x": x,
                        "y": y,
                        "light": nearest_light
                    })
                    
        # Format 2: Camera / sim tracking dict {'positions': [[x, y], ...]}
        elif isinstance(data, dict) and "positions" in data:
            for idx, p in enumerate(data["positions"], 1):
                if isinstance(p, (list, tuple)) and len(p) >= 2:
                    x, y = p[0], p[1]
                elif isinstance(p, dict) and "X" in p and "Y" in p:
                    x, y = p["X"], p["Y"]
                else:
                    continue
                nearest_light = find_nearest_light(x, y)
                persons_info.append({
                    "id": f"SimPerson-{idx}",
                    "x": x,
                    "y": y,
                    "light": nearest_light
                })

        # Identify nearest light above each detected person & update timestamps
        active_light_ids = set()
        for p in persons_info:
            active_light_ids.add(p["light"])
            LIGHT_LAST_SEEN[p["light"]] = now

        # Compute client-side software fade brightness for all 97 lights
        fade_duration_sec = args.fade / 1000.0
        light_colors = {}

        for lid in range(1, 98):
            elapsed = now - LIGHT_LAST_SEEN[lid]
            if fade_duration_sec > 0 and elapsed < fade_duration_sec:
                intensity = max(0.0, 1.0 - (elapsed / fade_duration_sec))
                green_val = int(255 * intensity)
                if green_val > 0:
                    light_colors[lid] = Color(r=0, g=green_val, b=0)
                else:
                    light_colors[lid] = OFF
            elif lid in active_light_ids:
                light_colors[lid] = Color(r=0, g=255, b=0)
            else:
                light_colors[lid] = OFF

        # Print structured per-person multi-row logs
        ts = format_timestamp()
        if persons_info:
            print(f"[{ts}] Active Tracking - {len(persons_info)} person(s) detected:")
            for p in persons_info:
                print(f"   └─ Person ID: {p['id']} | Position: (X={p['x']:.2f}m, Y={p['y']:.2f}m) | Activated Light: #{p['light']}")
        else:
            print(f"[{ts}] Area clear. Fading lights OFF ({args.fade}ms)")
            
        openlab.lights.set_colors(light_colors, fade=0)

    except Exception as e:
        print(f"Error handling position message: {e}")


def simulate_movement_worker():
    """Background thread that simulates a person walking across the lab floor."""
    time.sleep(1.5)  # Wait for connection initialization
    print("\n[Simulator] Starting movement simulation thread...")
    
    sim_pub_topic = (
        f"experiments/mapPositions/{env.simulation_topic}/camera1"
        if getattr(env, "is_simulation", True)
        else "openlab/unifiedMapPositions/output"
    )

    x_steps = [i * 0.5 for i in range(-4, 42)] 
    steps = [ {'Position': {'X': round(x, 2), 'Y': round(1.0 + (idx / (len(x_steps) - 1)) * 8.5, 2)}} for idx, x in enumerate(x_steps) ]

   # steps = [{'Position': {'X': x_val, 'Y': 3.0}} for x_val in [i * 0.5 for i in range(-4, 42)]]

    print(f"[Simulator] Publishing trajectory steps to '{sim_pub_topic}'...")
    for step in steps:
        payload = [step]
        env.mqtt.publish(sim_pub_topic, json.dumps(payload))
        time.sleep(0.4)

    print("[Simulator] Movement simulation trajectory finished.\n")


def main():
    unified_topic = "openlab/unifiedMapPositions/output"
    sim_topic = f"experiments/mapPositions/{env.simulation_topic}/#"
    
    print("==================================================")
    print("   OpenLab Green Lights Tracking & Fade Controller")
    print(f"   Environment:        {'PRODUCTION' if args.production else 'SIMULATION (my-test)'}")
    print(f"   Max Update Rate:    {args.rate} Hz (every {LIGHT_UPDATE_INTERVAL:.3f}s)")
    print(f"   Software Fade:      {args.fade} ms (Timestamp-based trail buffer)")
    print(f"   Coordinate Offsets: OFFSET_X = {OFFSET_X}, OFFSET_Y = {OFFSET_Y}")
    print("==================================================")
    
    if args.movement_simulation:
        print(f"[-S Active] Listening ONLY to simulation topic: {sim_topic}")
        env.mqtt.listen_on(sim_topic)
        env.mqtt.subscribe_to(sim_topic, on_position_update)
    elif args.production:
        print(f"[-P Active] Listening ONLY to production unified topic: {unified_topic}")
        env.mqtt.listen_on(unified_topic)
        env.mqtt.subscribe_to(unified_topic, on_position_update)
    else:
        print(f"Listening on unified topic: {unified_topic}")
        print(f"Listening on sim topic:     {sim_topic}")
        env.mqtt.listen_on(unified_topic)
        env.mqtt.listen_on(sim_topic)
        env.mqtt.subscribe_to(unified_topic, on_position_update)
        env.mqtt.subscribe_to(sim_topic, on_position_update)

    if args.movement_simulation:
        sim_thread = Thread(target=simulate_movement_worker, daemon=True)
        sim_thread.start()
    
    print("\nThrottling light commands to 20 Hz... (Press Ctrl+C to stop)")
    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nStopping controller.")


if __name__ == "__main__":
    time.sleep(1.5)  # Чекаємо, поки MQTT-клієнт повністю підключиться до сервера

    if args.movement_simulation:
        Thread(target=simulate_movement_worker, daemon=True).start()
    
    lamp_controller = Lamps.Lamp()
    player_id = wait_for_player_in_start_zone(env, openlab, lamp_controller, start_lamp=1)
    print(f"Старт гри для гравця: {player_id}")
    time.sleep(1.5)
    main()
