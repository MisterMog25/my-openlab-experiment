"""OpenLab path game: stand on the platform, memorize the path, then walk it.

    uv run movement_game.py        # simulator
    uv run movement_game.py -P     # production
"""

import argparse
import json
import math
import queue
import time

import tuke_openlab
from tuke_openlab.lights import Color

import Lamps

# ---------------------------------------------------------------- settings

LEVELS = [
    list(range(31, 46)),
    [4, 5, 6, 33, 60, 61, 62, 35, 8, 9, 10, 37, 64, 65, 66, 39, 12, 13],
]

START_LAMP = 1          # the start platform is drawn around this lamp
ATTEMPTS = 3            # wrong steps allowed per level
STEP_S = 0.4            # seconds between lamps when showing the path
HOLD_S = 7.0            # seconds the path stays visible
DWELL_S = 1.0           # seconds a player must stand on the platform
TOLERANCE_M = 0.5       # how far from the route line is still OK (meters)
GRACE_S = 0.3           # a wrong position must last this long ...
CONFIRM_FRAMES = 2      # ... and for this many camera frames
LOST_TIMEOUT_S = 15.0   # game over if we don't see the player this long

GREEN = Color(0, 255, 0)
RED = Color(255, 0, 0)
PREVIEW = Color(0, 120, 255)
FINISH = Color(255, 200, 0)
OFF = Color()

PRODUCTION_TOPIC = "openlab/unifiedMapPositions/output"
AUDIO_TOPIC = "openlab/audio"
VOLUME_TOPIC = "openlab/audio/volume"
MUTE_TOPIC = "openlab/audio/volume/mute"

# ---------------------------------------------------------------- light positions


OFFSET_X, OFFSET_Y = -1.0, -3.0
LIGHT_POSITIONS = {}


for col in range(1, 28):
    x = 0.8 + (col - 1) * 0.77 + OFFSET_X
    LIGHT_POSITIONS[28 - col] = (x, 11.0 + OFFSET_Y)  # top row
    LIGHT_POSITIONS[55 - col] = (x, 9.0 + OFFSET_Y)   # middle row
    LIGHT_POSITIONS[82 - col] = (x, 7.0 + OFFSET_Y)   # lower row



# ---------------------------------------------------------------- helpers

def find_nearest_light(x, y):
    """Returns the id of the light closest to the position (x, y)."""
    return min(LIGHT_POSITIONS, key=lambda i: math.dist((x, y), LIGHT_POSITIONS[i]))


def dist_to_segment(p, a, b):
    """Distance from point p to the line segment a-b."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    if length2 == 0:
        return math.dist(p, a)
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2
    t = max(0.0, min(1.0, t))
    return math.dist(p, (a[0] + t * dx, a[1] + t * dy))


class Voice:

    def __init__(self, env, enabled):
        self.env = env
        self.enabled = enabled
        if enabled:
            env.mqtt.publish(MUTE_TOPIC, "off")  
            env.mqtt.publish(VOLUME_TOPIC, "55")  

    def say(self, text):
        print(f"[Voice] {text}")
        if self.enabled:
            message = {"play": text, "input-mode": "say", "lang": "en-US"}
            self.env.mqtt.publish(AUDIO_TOPIC, json.dumps(message))


def wait_connected(env, timeout_s=5.0):
    """Waits until the MQTT client is connected."""
    client = getattr(env.mqtt, "_client", None)
    deadline = time.monotonic() + timeout_s
    while client is not None and not client.is_connected() and time.monotonic() < deadline:
        time.sleep(0.05)


# ---------------------------------------------------------------- player positions

def parse_players(payload):
    """Turns an MQTT message into {player_id: (x, y)}."""
    data = json.loads(payload)
    players = {}
    try:
        if isinstance(data, dict) and "positions" in data:
            # simulator: {"positions": [[x, y], ...]}
            for i, (x, y) in enumerate(data["positions"], 1):
                players[f"SimPlayer-{i}"] = (float(x), float(y))
        else:
            # cameras: [{"Id": ..., "Position": {"X": ..., "Y": ...}}]
            if isinstance(data, dict):
                data = [data]
            for i, person in enumerate(data, 1):
                pos = person["Position"]
                players[str(person.get("Id", f"Player-{i}"))] = (float(pos["X"]), float(pos["Y"]))
    except (KeyError, TypeError, ValueError):
        return {}
    return players


class PositionFeed:
    """Listens to the positions topic and keeps the newest frames in a queue."""

    def __init__(self, env, topic):
        self.frames = queue.Queue()
        env.mqtt.listen_on(topic)
        env.mqtt.subscribe_to(topic, self._on_message)

    def _on_message(self, msg):
        try:
            players = parse_players(msg.payload)
        except ValueError:  # broken JSON
            return
        self.frames.put((time.monotonic(), players))

    def get(self, timeout=0.05):
        try:
            return self.frames.get(timeout=timeout)
        except queue.Empty:
            return None

    def clear(self):
        """Throws away old frames."""
        while not self.frames.empty():
            self.frames.get_nowait()


# ---------------------------------------------------------------- game steps

def wait_for_player(openlab, voice, feed, lamp_ctrl):
    openlab.lights.turn_off()
    zone = list(lamp_ctrl.make_start_position(openlab, start=START_LAMP, hw=3))
    voice.say("Stand on the yellow platform.")
    feed.clear()

    inside_since = {}  # player_id -> time when they stepped on the platform
    while True:
        frame = feed.get()
        if frame:
            t, players = frame
            # keep only players who are on the platform right now
            inside_since = {pid: inside_since.get(pid, t)
                            for pid, (x, y) in players.items()
                            if find_nearest_light(x, y) in zone}
        for pid, since in inside_since.items():
            if time.monotonic() - since >= DWELL_S:
                return pid, zone


def show_path(openlab, voice, path):
    voice.say("Player detected. Remember the path.")
    finish = path[-1]
    for lamp in path:
        color = FINISH if lamp == finish else PREVIEW
        openlab.lights.set_color(lamp, color, fade=300)
        time.sleep(STEP_S)
    time.sleep(HOLD_S)
    openlab.lights.set_colors({lamp: OFF for lamp in path if lamp != finish}, fade=500)
    time.sleep(0.5)
    voice.say("Go!")


def splash(openlab, center_lamp, color, keep=()):
    """Wave of `color` that spreads from center_lamp over all lamps except `keep`."""
    origin = LIGHT_POSITIONS[center_lamp]
    lamps = [lamp for lamp in LIGHT_POSITIONS if lamp not in keep]

    waves = {}
    for lamp in lamps:
        delay = round(math.dist(origin, LIGHT_POSITIONS[lamp]) / 12.0, 1)
        waves.setdefault(delay, []).append(lamp)

    start = time.monotonic()
    openlab.lights.set_colors({lamp: color for lamp in range(82, 98)}, fade=150)
    for delay in sorted(waves):
        time.sleep(max(0.0, start + delay - time.monotonic()))
        openlab.lights.set_colors({lamp: color for lamp in waves[delay]}, fade=150)
    time.sleep(0.4)
    openlab.lights.set_colors({lamp: OFF for lamp in lamps}, fade=500)
    openlab.lights.set_colors({lamp: OFF for lamp in range(82, 98)}, fade=500)  
    openlab.lights.set_colors({lamp: OFF for lamp in range(82, 98)}, fade=500)  
    time.sleep(0.5)


def walk_path(openlab, voice, feed, player_id, path, start_zone):
    """Follows the player along the path. Returns True if they finish, False if they lose."""
    finish = path[-1]
    reached = 0                 # how many lamps of the path are done
    attempts = ATTEMPTS
    wrong_since = None          # when the player first stood on a wrong spot
    wrong_frames = 0            # how many frames in a row were wrong
    must_return = False         # after a mistake: wait until the player is back on the path

    exit_lamp = min(start_zone,
                    key=lambda i: math.dist(LIGHT_POSITIONS[i], LIGHT_POSITIONS[path[0]]))
    route = [LIGHT_POSITIONS[exit_lamp]] + [LIGHT_POSITIONS[lamp] for lamp in path]

    openlab.lights.set_color(finish, FINISH, fade=250)
    feed.clear()
    last_seen = time.monotonic()

    while True:
        frame = feed.get()
        if frame is None or player_id not in frame[1]:
            if time.monotonic() - last_seen > LOST_TIMEOUT_S:
                voice.say("I can't see you anymore. Game over.")
                return False
            continue

        last_seen, players = frame[0], frame[1]
        x, y = players[player_id]
        nearest = find_nearest_light(x, y)
        done = path[:reached]
        upcoming = path[reached:reached + 2]  

        # After a mistake ignore everything until the player is back on a safe lamp.
        if must_return:
            if nearest not in done + start_zone + upcoming:
                continue
            must_return = False
            voice.say("Good, keep going.")

        # Correct step
        if nearest in upcoming:
            new_reached = reached + upcoming.index(nearest) + 1
            for lamp in path[reached:new_reached]:
                openlab.lights.set_color(lamp, GREEN, fade=250)
            reached = new_reached
            wrong_since, wrong_frames = None, 0
            print(f"step {reached}/{len(path)}: lamp {nearest}")
            if reached == len(path):
                voice.say("Well done! You remembered the whole path.")
                return True
            if reached == len(path) // 2:
                voice.say("Halfway there!")
            continue

        # Harmless position
        points = route[:reached + 2]
        off_route = min(dist_to_segment((x, y), a, b) for a, b in zip(points, points[1:]))
        if nearest in start_zone or nearest in done or off_route <= TOLERANCE_M:
            wrong_since, wrong_frames = None, 0
            continue

        # Wrong position
        if wrong_since is None:
            wrong_since, wrong_frames = last_seen, 0
        wrong_frames += 1
        if wrong_frames < CONFIRM_FRAMES or last_seen - wrong_since < GRACE_S:
            continue

        # Mistake
        attempts -= 1
        wrong_since, wrong_frames = None, 0
        print(f"wrong step: expected {path[reached]}, player at {nearest}, attempts left {attempts}")

        if attempts <= 0:
            text = "Wrong step! No attempts left. Game over."
        else:
            text = "Wrong step! Go back to the last green light." if reached else "Wrong step! Go back to the platform."
            text += " Last attempt!" if attempts == 1 else f" {attempts} attempts left."
        voice.say(text)
        splash(openlab, nearest, RED, keep=start_zone + done + [finish])

        if attempts <= 0:
            return False
        must_return = True
        feed.clear()
        last_seen = time.monotonic()


# ---------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser(description="OpenLab path game")
    parser.add_argument("-P", "--production", action="store_true", help="real lights and cameras")
    parser.add_argument("--topic", default="nz696iv", help="simulator topic")
    parser.add_argument("--mute", action="store_true", help="no sound in production")
    args = parser.parse_args()

    use_cameras = args.production
    env = tuke_openlab.production_env() if args.production else tuke_openlab.simulation_env(args.topic)
    openlab = tuke_openlab.Controller(env)
    wait_connected(env)

    if not args.production:
        print(f"lights: https://openlab.kpi.fei.tuke.sk/simulator/light/{args.topic}")

    voice = Voice(env, enabled=args.production and not args.mute)

    topic = PRODUCTION_TOPIC if use_cameras else f"experiments/mapPositions/{args.topic}/#"
    feed = PositionFeed(env, topic)
    lamp_ctrl = Lamps.Lamp()


    try:
        for number, path in enumerate(LEVELS, 1):
            print(f"=== Level {number} ===")
            voice.say(f"Level {number}.")

            player_id, start_zone = wait_for_player(openlab, voice, feed, lamp_ctrl)
            show_path(openlab, voice, path)

            if not walk_path(openlab, voice, feed, player_id, path, start_zone):
                print("game over")
                break

            # level done: green wave from the finish lamp, the path stays green
            splash(openlab, path[-1], GREEN, keep=path)
            openlab.lights.turn_off()

            # then the path flashes white and green for about 2 seconds
            for _ in range(4):
                openlab.lights.set_color(path, Color(w=255), fade=150)
                time.sleep(0.33)
                openlab.lights.set_color(path, GREEN, fade=150)
                time.sleep(0.33)
        else:
            voice.say("You finished all levels. Congratulations!")

        time.sleep(4.0)  # let the last sentence finish
    except KeyboardInterrupt:
        pass
    finally:
        openlab.lights.turn_off()
        time.sleep(0.3)


if __name__ == "__main__":
    main()