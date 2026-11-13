import json
import math
import time
import argparse
from datetime import datetime
from threading import Thread
import tuke_openlab
from tuke_openlab.lights import Color

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
    env = tuke_openlab.simulation_env("my-test")
    print("[Config] Connected to SIMULATION environment ('my-test').")

openlab = tuke_openlab.Controller(env)

OFF = Color()  # Color(0, 0, 0, 0)

# 2. Build 2D Light Coordinate Map (Lights 1 to 97) with requested offsets
OFFSET_X = -3.0
OFFSET_Y = -4.0

LIGHT_POSITIONS = {}

# Main Ceiling Grid Rows (Lights 1 to 81)
for col in range(1, 28):
    x_pos = (0.8 + (col - 1) * 0.77) + OFFSET_X
    LIGHT_POSITIONS[28 - col] = (x_pos, 13.0 + OFFSET_Y)  # Row 1 (Top)
    LIGHT_POSITIONS[55 - col] = (x_pos, 10.0 + OFFSET_Y)  # Row 2 (Middle)
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


def on_position_update(msg):
    """Callback triggered on receiving tracking data, rate-limited to max 20 Hz."""
    global last_light_send_time

    now = time.time()
    if LIGHT_UPDATE_INTERVAL > 0 and (now - last_light_send_time) < LIGHT_UPDATE_INTERVAL:
        return
    last_light_send_time = now

    try:
        raw_text = msg.payload.decode('utf-8')
        data = json.loads(raw_text)
        
        active_coords = []
        
        # Format 1: Unified tracking array [{'Position': {'X': ..., 'Y': ...}}]
        if isinstance(data, list):
            for person in data:
                pos = person.get("Position", {})
                if "X" in pos and "Y" in pos:
                    active_coords.append((pos["X"], pos["Y"]))
                    
        # Format 2: Camera / sim tracking dict {'positions': [[x, y], ...]}
        elif isinstance(data, dict) and "positions" in data:
            for p in data["positions"]:
                if isinstance(p, (list, tuple)) and len(p) >= 2:
                    active_coords.append((p[0], p[1]))
                elif isinstance(p, dict) and "X" in p and "Y" in p:
                    active_coords.append((p["X"], p["Y"]))

        # Identify nearest light above each detected person
        active_light_ids = set()
        for px, py in active_coords:
            nearest_id = find_nearest_light(px, py)
            active_light_ids.add(nearest_id)

        # Update timestamps for active lights
        for lid in active_light_ids:
            LIGHT_LAST_SEEN[lid] = now

        # Compute client-side software fade brightness for all 97 lights
        fade_duration_sec = args.fade / 1000.0
        light_colors = {}
        active_g_count = 0

        for lid in range(1, 98):
            elapsed = now - LIGHT_LAST_SEEN[lid]
            if fade_duration_sec > 0 and elapsed < fade_duration_sec:
                # Linear software decay from 1.0 down to 0.0
                intensity = max(0.0, 1.0 - (elapsed / fade_duration_sec))
                green_val = int(255 * intensity)
                if green_val > 0:
                    light_colors[lid] = Color(r=0, g=green_val, b=0)
                    active_g_count += 1
                else:
                    light_colors[lid] = OFF
            elif lid in active_light_ids:
                light_colors[lid] = Color(r=0, g=255, b=0)
                active_g_count += 1
            else:
                light_colors[lid] = OFF

        ts = format_timestamp()
        if active_light_ids:
            print(f"[{ts}] Person detected ({len(active_coords)} pos). Active Green Lights: {active_g_count} (fade={args.fade}ms, rate={args.rate}Hz)")
        else:
            print(f"[{ts}] Area clear. Fading lights ({active_g_count} illuminated, fade={args.fade}ms)")
            
        # Send colors with hardware fade=0 so software-calculated steps are applied instantly without transition conflict
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

    x_steps = [i * 0.5 for i in range(-4, 32)] 
    steps = [ {'Position': {'X': round(x, 2), 'Y': round(1.0 + (idx / (len(x_steps) - 1)) * 8.5, 2)}} for idx, x in enumerate(x_steps) ]

   # steps = [{'Position': {'X': x_val, 'Y': 3.0}} for x_val in [i * 0.5 for i in range(-4, 32)]]

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
    main()
