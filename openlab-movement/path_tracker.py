"""Start zone + path tracking for the OpenLab game.

    uv run openlab-movement/path_tracker.py --simulate correct
    uv run openlab-movement/path_tracker.py --simulate wrong
"""

import argparse
import json
import math
import queue
import random
import threading
import time
import traceback
import weakref
from dataclasses import dataclass, field
from datetime import datetime

import tuke_openlab
from tuke_openlab.lights import Color

import Lamps
from speech import Voice

# 2D Light Coordinate Map (Lights 1 to 97) with offsets
OFFSET_X = -2.0
OFFSET_Y = -3.0

LIGHT_POSITIONS = {}

for col in range(1, 28):
    x_pos = (0.8 + (col - 1) * 0.77) + OFFSET_X
    LIGHT_POSITIONS[28 - col] = (x_pos, 11.0 + OFFSET_Y)  # Row 1 (Top)
    LIGHT_POSITIONS[55 - col] = (x_pos, 9.0 + OFFSET_Y)   # Row 2 (Middle)
    LIGHT_POSITIONS[82 - col] = (x_pos, 7.0 + OFFSET_Y)   # Row 3 (Lower)

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

LIGHT_POSITIONS.update({
    lid: (x + OFFSET_X, y + OFFSET_Y)
    for lid, (x, y) in bottom_desks_base.items()
})

GRID_ROWS, GRID_COLS = 3, 27

GREEN = Color(0, 255, 0)
RED = Color(255, 0, 0)
PREVIEW = Color(0, 120, 255)
FINISH = Color(255, 200, 0)  # lighter than the start zone (255, 140, 0), so they don't mix up
OFF = Color()

PRODUCTION_TOPIC = "openlab/unifiedMapPositions/output"

PHRASES = {
    "platform": "Stand on the yellow platform.",
    "memorize": "Player detected. Remember the path.",
    "go": "Go!",
    "halfway": "Halfway there!",
    "wrong": "Wrong step! Go back to the last green light.",
    "wrong_start": "Wrong step! Go back to the platform.",
    "attempts": "{n} attempts left.",
    "last_attempt": "Last attempt!",
    "back": "Good, keep going.",
    "game_over": "Wrong step! No attempts left. Game over.",
    "win": "Well done! You remembered the whole path.",
    "lost": "I can't see you anymore. Game over.",
    "timeout": "Time is up. Game over.",
}


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


def lamp_neighbors(lamp_id):
    if not 1 <= lamp_id <= GRID_ROWS * GRID_COLS:
        return []
    r, c = divmod(lamp_id - 1, GRID_COLS)
    result = []
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        if 0 <= r + dr < GRID_ROWS and 0 <= c + dc < GRID_COLS:
            result.append((r + dr) * GRID_COLS + c + dc + 1)
    return result


def dist_to_segment(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    if length2 == 0:
        return math.dist(p, a)
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2))
    return math.dist(p, (a[0] + t * dx, a[1] + t * dy))


def log(tag, msg):
    print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] [{tag}] {msg}")


def _say(voice, text, **kwargs):
    if voice is not None:
        voice.say(text, **kwargs)


def _get_topic(env, is_production=None):
    is_sim = getattr(env, "simulation_topic", None) is not None
    if is_production is None:
        is_production = not is_sim
    if not is_production and not is_sim:
        raise ValueError("is_production=False needs simulation_env()")
    if is_production:
        return PRODUCTION_TOPIC
    return f"experiments/mapPositions/{env.simulation_topic}/#"


def _extract_persons(payload) -> list[tuple[str, float, float]]:
    """Parses person coordinates from MQTT payload (supports both cameras and simulator)."""
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8")
    data = json.loads(payload)
    if isinstance(data, dict) and "Position" in data:
        data = [data]

    raw = []
    if isinstance(data, list):
        # cameras: [{'Id': ..., 'Position': {'X': ..., 'Y': ...}}]
        for i, p in enumerate(data, 1):
            pos = p.get("Position") if isinstance(p, dict) else None
            if isinstance(pos, dict) and "X" in pos and "Y" in pos:
                raw.append((p.get("Id", f"Player-{i}"), pos["X"], pos["Y"]))
    elif isinstance(data, dict) and isinstance(data.get("positions"), list):
        # web simulator: {'positions': [[x, y], ...]}
        for i, p in enumerate(data["positions"], 1):
            if isinstance(p, (list, tuple)) and len(p) >= 2:
                raw.append((f"SimPlayer-{i}", p[0], p[1]))
            elif isinstance(p, dict) and "X" in p and "Y" in p:
                raw.append((p.get("Id", f"SimPlayer-{i}"), p["X"], p["Y"]))

    persons = []
    for pid, x, y in raw:
        try:
            x, y = float(x), float(y)
        except (TypeError, ValueError):
            continue
        if math.isfinite(x) and math.isfinite(y):
            persons.append((str(pid), x, y))
    return persons


class _PositionFeed:
    # subscribe_to() in the SDK replaces the previous handler for the same topic,
    # so the start zone and the tracker share one subscription
    _feeds = weakref.WeakKeyDictionary()
    _feeds_lock = threading.Lock()

    def __init__(self, env, topic):
        self._queues = []
        self._lock = threading.Lock()
        env.mqtt.listen_on(topic)
        env.mqtt.subscribe_to(topic, self._on_message)

    @classmethod
    def get(cls, env, topic):
        with cls._feeds_lock:
            feeds = cls._feeds.setdefault(env, {})
            if topic not in feeds:
                feeds[topic] = cls(env, topic)
            return feeds[topic]

    def _on_message(self, msg):
        t = time.monotonic()
        try:
            persons = _extract_persons(msg.payload)
        except Exception:
            return
        with self._lock:
            for q in self._queues:
                q.put((t, persons))

    def open(self):
        q = queue.Queue()
        with self._lock:
            self._queues.append(q)
        return q

    def close(self, q):
        with self._lock:
            if q in self._queues:
                self._queues.remove(q)


def validate_path(path, start_zone=()):
    path = [int(lamp) for lamp in path]
    if not path:
        raise ValueError("path is empty")
    unknown = [lamp for lamp in path if lamp not in LIGHT_POSITIONS]
    if unknown:
        raise ValueError(f"unknown lamps: {unknown}")
    if any(a == b for a, b in zip(path, path[1:])):
        raise ValueError("same lamp twice in a row")
    overlap = set(path) & set(start_zone)
    if overlap:
        raise ValueError(f"lamps {sorted(overlap)} are both in the start zone and in the path")
    return path


def wait_for_player_in_start_zone(env, controller, lamp=None, start_lamp=1, is_production=None, *,
                                  hw=3, dwell_s=1.0, timeout_s=None, stop_event=None,
                                  on_zone_ready=None, voice=None, verbose=True):
    """Draws the start zone and waits until someone stands in it for dwell_s seconds.
    Returns (player_id, zone_lamps)."""
    lamp = lamp or Lamps.Lamp()
    topic = _get_topic(env, is_production)

    controller.lights.turn_off()
    zone = lamp.make_start_position(controller, start=start_lamp, hw=hw)
    if verbose:
        log("Start Zone", f"zone {zone}, waiting for player on {topic}")
    _say(voice, PHRASES["platform"])
    if on_zone_ready:
        on_zone_ready(zone)

    feed = _PositionFeed.get(env, topic)
    q = feed.open()
    inside_since = {}
    player = None
    started = time.monotonic()
    try:
        while player is None:
            if stop_event is not None and stop_event.is_set():
                raise InterruptedError("stopped")
            if timeout_s is not None and time.monotonic() - started > timeout_s:
                raise TimeoutError("nobody entered the start zone")
            try:
                t, persons = q.get(timeout=0.05)
                for pid, x, y in persons:
                    if find_nearest_light(x, y) in zone:
                        inside_since.setdefault(pid, t)
                    else:
                        inside_since.pop(pid, None)
            except queue.Empty:
                pass
            # checked even without new frames, the web simulator only sends on movement
            now = time.monotonic()
            player = next((pid for pid, since in inside_since.items() if now - since >= dwell_s), None)
    finally:
        feed.close(q)

    if verbose:
        log("Start Zone", f"player '{player}' is in the zone")
    return player, list(zone)


def show_path_preview(controller, path, step_s=0.4, hold_s=7.0, color=PREVIEW, voice=None,
                      finish_color=FINISH):
    """Lights the path one lamp at a time from the player to the finish (step_s per lamp),
    keeps it for hold_s so the player can memorize it, then turns it off.
    The last lamp is lit in finish_color and stays on for the game."""
    path = validate_path(path)
    _say(voice, PHRASES["memorize"])
    fade = int(min(step_s * 0.75, 0.5) * 1000)
    finish = path[-1]
    for i, lid in enumerate(path):
        if i:
            time.sleep(step_s)
        is_last = i == len(path) - 1
        controller.lights.set_color(lid, finish_color if is_last else color, fade=fade)
    time.sleep(hold_s)
    # compare by id, not path[:-1]: the finish lamp may also appear earlier in the path
    controller.lights.set_colors({lid: OFF for lid in path if lid != finish}, fade=500)
    time.sleep(0.5)
    _say(voice, PHRASES["go"], interrupt=True)


def red_splash(controller, center_lamp, keep=(), speed=12.0, hold_s=0.4, color=RED):
    """Red wave from center_lamp over every lamp except `keep`, then they go back off."""
    origin = LIGHT_POSITIONS[center_lamp]
    lamps = [lid for lid in LIGHT_POSITIONS if lid not in set(keep)]
    rings = {}
    for lid in lamps:
        delay = round(math.dist(origin, LIGHT_POSITIONS[lid]) / speed, 1)
        rings.setdefault(delay, []).append(lid)

    start = time.monotonic()
    for delay in sorted(rings):
        time.sleep(max(0.0, start + delay - time.monotonic()))
        controller.lights.set_colors({lid: color for lid in rings[delay]}, fade=150)
    time.sleep(hold_s)
    controller.lights.set_colors({lid: OFF for lid in lamps}, fade=500)
    time.sleep(0.5)


@dataclass
class Mistake:
    expected_lamp: int
    wrong_lamp: int
    position: tuple
    attempts_left: int


@dataclass
class PathResult:
    success: bool
    reason: str  # completed, wrong_step (no attempts left), player_lost, timeout, stopped, error
    reached: list = field(default_factory=list)
    expected_lamp: int | None = None
    wrong_lamp: int | None = None
    position: tuple | None = None
    player_id: str | None = None
    duration_s: float = 0.0
    mistakes: list = field(default_factory=list)
    attempts_left: int = 0

    def __bool__(self):
        return self.success


class PathTracker:
    """Follows one player along `path`.

    Only player_id (the one who stood on the platform) is followed, anybody else in the
    frame is ignored. A step counts when the nearest lamp is the next one in the path (max_skip lets one
    lamp be skipped if the camera drops frames). Standing in the start zone, on reached
    lamps or within tolerance_m of the route line is fine. Anything else that lasts
    grace_s and confirm_frames frames is a wrong step.

    Every wrong step costs one attempt: red splash, lights go back, on_wrong_step(mistake)
    is called and wrong_step is set. The player has to come back to a reached lamp to
    continue. With no attempts left the game ends with False.

    The last path lamp shines in finish_color (None turns it off) until the player
    reaches it, the red splash leaves it alone.
    """

    def __init__(self, env, controller, player_id, path, start_zone_lamps=(), is_production=None, *,
                 lamp=None, attempts=3, splash=True, tolerance_m=0.5, grace_s=0.3, confirm_frames=2,
                 max_skip=1, lost_timeout_s=15.0, timeout_s=None, fade_ms=250, finish_color=FINISH,
                 on_step=None, on_wrong_step=None, on_finish=None, stop_event=None, voice=None,
                 verbose=True):
        self.env = env
        self.controller = controller
        self.lamp = lamp
        self.player_id = str(player_id)
        self.start_zone = [int(lamp_id) for lamp_id in start_zone_lamps]
        self.path = validate_path(path, self.start_zone)
        self.topic = _get_topic(env, is_production)

        self.tolerance_m = tolerance_m
        self.grace_s = grace_s
        self.confirm_frames = max(1, confirm_frames)
        self.max_skip = max(0, max_skip)
        self.lost_timeout_s = lost_timeout_s
        self.timeout_s = timeout_s
        self.attempts_left = max(1, attempts)
        self.splash = splash
        self.mistakes = []
        self.fade_ms = fade_ms
        self.finish_color = finish_color
        self.on_step = on_step
        self.on_wrong_step = on_wrong_step
        self.on_finish = on_finish
        self.voice = voice
        self.verbose = verbose

        self.wrong_step = threading.Event()
        self.finished = threading.Event()
        self.result = None
        self._stop = stop_event or threading.Event()
        self._thread = None

        # the route starts at the zone lamp closest to the first path lamp
        first = LIGHT_POSITIONS[self.path[0]]
        self._route = [LIGHT_POSITIONS[lid] for lid in self.path]
        if self.start_zone:
            exit_lamp = min(self.start_zone, key=lambda lid: math.dist(LIGHT_POSITIONS[lid], first))
            self._route.insert(0, LIGHT_POSITIONS[exit_lamp])

        self._idx = 0
        self._started = self._last_seen = time.monotonic()
        self._last_pos = None
        self._wrong_since = None
        self._wrong_frames = 0
        self._wrong_lamp = None
        self._recovering = False

    @property
    def reached(self):
        return self.path[:self._idx]

    @property
    def next_lamp(self):
        return self.path[self._idx] if self._idx < len(self.path) else None

    def run(self):
        if self.finished.is_set():
            return self.result.success
        feed = _PositionFeed.get(self.env, self.topic)
        q = feed.open()
        try:
            self._started = self._last_seen = time.monotonic()
            self._log(f"start: player '{self.player_id}', path {self.path}")
            if self.finish_color is not None and self.next_lamp is not None:
                # the finish stays lit while the player walks, it turns green when reached
                self._set(self.path[-1], self.finish_color)
            while not self.finished.is_set():
                now = time.monotonic()
                if self._stop.is_set():
                    self._finish(False, "stopped")
                elif self.timeout_s is not None and now - self._started >= self.timeout_s:
                    self._finish(False, "timeout")
                elif self.lost_timeout_s is not None and now - self._last_seen >= self.lost_timeout_s:
                    self._finish(False, "player_lost")
                else:
                    try:
                        self._handle_frame(*q.get(timeout=0.05))
                    except queue.Empty:
                        pass
                    if not self.finished.is_set():
                        self._check_quiet(time.monotonic())
        finally:
            feed.close(q)
        return self.result.success

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run_safe, daemon=True)
            self._thread.start()
        return self

    def wait(self, timeout=None):
        if not self.finished.wait(timeout):
            return None
        return self.result.success

    def stop(self):
        self._stop.set()

    def _run_safe(self):
        try:
            self.run()
        except Exception:
            traceback.print_exc()
            if not self.finished.is_set():
                self._finish(False, "error")

    def _find_player(self, persons):
        for pid, x, y in persons:
            if pid == self.player_id:
                return x, y
        return None

    def _route_distance(self, pos):
        offset = 1 if self.start_zone else 0
        points = self._route[:self._idx + 1 + offset]
        if len(points) == 1:
            return math.dist(pos, points[0])
        return min(dist_to_segment(pos, a, b) for a, b in zip(points, points[1:]))

    def _handle_frame(self, t, persons):
        if self.finished.is_set():
            return self.result
        pos = self._find_player(persons)
        if pos is None:
            return None
        self._last_seen, self._last_pos = t, pos
        nearest = find_nearest_light(*pos)
        upcoming = self.path[self._idx:self._idx + self.max_skip + 1]

        if self._recovering:
            # after a mistake wait until the player is back on the path
            if nearest not in self.reached and nearest not in self.start_zone and nearest not in upcoming:
                return None
            self._recovering = False
            self._log("player is back on the path")
            _say(self.voice, PHRASES["back"])

        for j in range(self._idx, self._idx + len(upcoming)):
            if nearest == self.path[j]:
                self._reset_wrong()
                self._advance(j, pos)
                if self._idx == len(self.path):
                    return self._finish(True, "completed")
                return None

        waiting = not self.start_zone and self._idx == 0
        if (waiting or nearest in self.start_zone or nearest in self.reached
                or self._route_distance(pos) <= self.tolerance_m):
            self._reset_wrong()
            return None

        if self._wrong_since is None:
            self._wrong_since, self._wrong_frames = t, 0
        self._wrong_frames += 1
        self._wrong_lamp = nearest
        if self._wrong_frames >= self.confirm_frames and t - self._wrong_since >= self.grace_s:
            return self._mistake(nearest)
        return None

    def _check_quiet(self, now):
        # no new frames, but the last position was a wrong one
        if (self._wrong_since is not None and now - self._last_seen >= self.grace_s
                and now - self._wrong_since >= max(2 * self.grace_s, 0.6)):
            self._mistake(self._wrong_lamp)

    def _mistake(self, wrong_lamp):
        self.attempts_left -= 1
        mistake = Mistake(self.next_lamp, wrong_lamp, self._last_pos, self.attempts_left)
        self.mistakes.append(mistake)
        self._reset_wrong()
        self._log(f"wrong step: expected #{mistake.expected_lamp}, player at #{wrong_lamp} "
                  f"({self._last_pos[0]:.2f}, {self._last_pos[1]:.2f}), attempts left: {self.attempts_left}")
        if self.attempts_left <= 0:
            phrase = PHRASES["game_over"]
        else:
            phrase = PHRASES["wrong"] if self.reached else PHRASES["wrong_start"]
            left = PHRASES["last_attempt"] if self.attempts_left == 1 else PHRASES["attempts"]
            phrase += " " + left.format(n=self.attempts_left)
        _say(self.voice, phrase, interrupt=True)
        self.wrong_step.set()
        self._call(self.on_wrong_step, mistake)
        if self.splash:
            keep = self.start_zone + self.reached
            if self.finish_color is not None:
                keep.append(self.path[-1])
            try:
                red_splash(self.controller, wrong_lamp, keep=keep)
            except Exception as e:
                self._log(f"splash failed: {e}")
        if self.attempts_left <= 0:
            return self._finish(False, "wrong_step", wrong_lamp)
        self._recovering = True
        return None

    def _reset_wrong(self):
        self._wrong_since, self._wrong_frames, self._wrong_lamp = None, 0, None

    def _advance(self, j, pos):
        for k in range(self._idx, j + 1):
            lid = self.path[k]
            self._set(lid, GREEN)
            self._idx = k + 1
            self._log(f"step {k + 1}/{len(self.path)}: #{lid} ({pos[0]:.2f}, {pos[1]:.2f})")
            self._call(self.on_step, lid, k + 1, len(self.path))
        if self._idx == len(self.path) // 2:
            _say(self.voice, PHRASES["halfway"])

    def _finish(self, success, reason, wrong_lamp=None):
        self.result = r = PathResult(
            success=success, reason=reason, reached=list(self.reached), expected_lamp=self.next_lamp,
            wrong_lamp=wrong_lamp, position=self._last_pos, player_id=self.player_id,
            duration_s=round(time.monotonic() - self._started, 2),
            mistakes=list(self.mistakes), attempts_left=self.attempts_left)
        if success:
            self._log(f"path completed in {r.duration_s}s, mistakes: {len(r.mistakes)}")
            _say(self.voice, PHRASES["win"])
        elif reason == "wrong_step":
            self._log("no attempts left")
        else:
            self._log(f"finished: {reason}, reached {r.reached}")
            if reason in ("player_lost", "timeout"):
                _say(self.voice, PHRASES["lost" if reason == "player_lost" else "timeout"], interrupt=True)
        self.finished.set()
        self._call(self.on_finish, r)
        return r

    def _set(self, lamp_id, color, fade=None):
        try:
            self.controller.lights.set_color(lamp_id, color, fade=self.fade_ms if fade is None else fade)
        except Exception as e:
            self._log(f"failed to set lamp {lamp_id}: {e}")

    def _call(self, fn, *args):
        if fn is None:
            return
        try:
            fn(*args)
        except Exception:
            traceback.print_exc()

    def _log(self, msg):
        if self.verbose:
            log("Path", msg)


def track_player_path(env, controller, lamp, player_id, path, start_zone_lamps=(),
                      is_production=None, **kwargs):
    """Blocks until the player finishes the path (True) or makes a wrong step (False)."""
    return PathTracker(env, controller, player_id, path, start_zone_lamps, is_production,
                       lamp=lamp, **kwargs).run()


def simulate_walk(env, zone, path, mistakes=(), player_id="sim-walker", speed=1.0, rate_hz=10.0,
                  noise=0.05, wait_in_zone_s=3.0, pause_s=3.0, linger_s=3.0, stop_event=None,
                  go_event=None):
    """Fake player for the simulator. `mistakes` are path indexes where it steps on a wrong
    lamp, waits for the splash and comes back (the same index can repeat)."""
    if getattr(env, "simulation_topic", None) is None:
        raise RuntimeError("simulate_walk only works with simulation_env")
    zone, path, mistakes = list(zone), list(path), list(mistakes)
    topic = f"experiments/mapPositions/{env.simulation_topic}/camera1"
    stop_event = stop_event or threading.Event()

    cx = sum(LIGHT_POSITIONS[lid][0] for lid in zone) / len(zone)
    cy = sum(LIGHT_POSITIONS[lid][1] for lid in zone) / len(zone)
    center = LIGHT_POSITIONS[min(zone, key=lambda lid: math.dist(LIGHT_POSITIONS[lid], (cx, cy)))]
    exit_lamp = min(zone, key=lambda lid: math.dist(LIGHT_POSITIONS[lid], LIGHT_POSITIONS[path[0]]))

    plan = [(exit_lamp, 0)]
    for k, lid in enumerate(path):
        for _ in range(mistakes.count(k)):
            here = plan[-1][0]
            candidates = [n for n in lamp_neighbors(here) if n not in path and n not in zone]
            if not candidates:
                raise ValueError(f"no wrong neighbour next to #{here}")
            wrong = max(candidates, key=lambda n: math.dist(LIGHT_POSITIONS[n], LIGHT_POSITIONS[lid]))
            log("Simulator", f"walker will go to #{wrong} instead of #{lid}")
            plan += [(wrong, pause_s), (here, 0)]
        plan.append((lid, 0))

    dt = 1.0 / rate_hz

    def send(x, y):
        x, y = x + random.gauss(0, noise), y + random.gauss(0, noise)
        env.mqtt.publish(topic, json.dumps([{"Id": player_id, "Position": {"X": round(x, 3), "Y": round(y, 3)}}]))
        time.sleep(dt)

    def stand(p, seconds):
        for _ in range(int(seconds * rate_hz)):
            if stop_event.is_set():
                return
            send(*p)

    if go_event is None:
        stand(center, wait_in_zone_s)
    else:
        while not go_event.is_set() and not stop_event.is_set():
            send(*center)
    pos = center
    for lid, pause in plan:
        target = LIGHT_POSITIONS[lid]
        steps = max(1, int(math.dist(pos, target) / (speed * dt)))
        for i in range(1, steps + 1):
            if stop_event.is_set():
                return
            send(pos[0] + (target[0] - pos[0]) * i / steps, pos[1] + (target[1] - pos[1]) * i / steps)
        pos = target
        stand(pos, pause)
    stand(pos, linger_s)


def wait_connected(env, timeout_s=5.0):
    client = getattr(env.mqtt, "_client", None)
    deadline = time.monotonic() + timeout_s
    while client is not None and not client.is_connected() and time.monotonic() < deadline:
        time.sleep(0.05)
    if client is None or not client.is_connected():
        time.sleep(1.5)


# goes up and down between the rows until about the middle of the lab
TEST_PATH = [4, 5, 6, 33, 60, 61, 62, 35, 8, 9, 10, 37, 64, 65, 66, 39, 12, 13]


def main():
    parser = argparse.ArgumentParser(description="OpenLab path game demo")
    parser.add_argument("-P", "--production", action="store_true", help="real lights and cameras")
    parser.add_argument("--real-cameras", action="store_true",
                        help="real cameras, lights only on the simulator page")
    parser.add_argument("--topic", default="nz696iv", help="simulator topic")
    parser.add_argument("--path", default=",".join(map(str, TEST_PATH)))
    parser.add_argument("--start-lamp", type=int, default=1)
    parser.add_argument("--simulate", choices=["correct", "wrong", "fail"],
                        help="fake player: no mistakes / one mistake / runs out of attempts")
    parser.add_argument("--mistake-at", type=int, help="step of the mistake, middle of the path by default")
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--step", type=float, default=0.4, help="seconds per lamp when showing the path")
    parser.add_argument("--hold", type=float, default=7.0, help="seconds to keep the path visible")
    parser.add_argument("--mute", action="store_true", help="no voice")
    parser.add_argument("--voice", help="system voice name, e.g. Samantha or Daniel on macOS")
    args = parser.parse_args()

    if args.simulate and (args.production or args.real_cameras):
        parser.error("--simulate can't be used with -P or --real-cameras")
    cameras = args.production or args.real_cameras
    path = [int(p) for p in args.path.split(",") if p.strip()]
    if args.mistake_at is None:
        args.mistake_at = len(path) // 2

    env = tuke_openlab.production_env() if args.production else tuke_openlab.simulation_env(args.topic)
    openlab = tuke_openlab.Controller(env)
    wait_connected(env)
    if not args.production:
        print(f"lights: https://openlab.kpi.fei.tuke.sk/simulator/light/{args.topic}")
        print(f"map:    https://openlab.kpi.fei.tuke.sk/simulator/map/{args.topic}")

    stop = threading.Event()
    go = threading.Event()
    lamp_ctrl = Lamps.Lamp()
    voice = Voice(enabled=not args.mute, voice=args.voice)
    try:
        def on_zone_ready(zone):
            if args.simulate:
                count = {"correct": 0, "wrong": 1, "fail": args.attempts}[args.simulate]
                threading.Thread(target=simulate_walk, args=(env, zone, path, [args.mistake_at] * count),
                                 kwargs={"stop_event": stop, "go_event": go}, daemon=True).start()

        player_id, start_zone = wait_for_player_in_start_zone(
            env, openlab, lamp_ctrl, args.start_lamp, cameras,
            on_zone_ready=on_zone_ready, voice=voice)

        log("Game", f"showing the path ({len(path)} lamps), memorize it")
        show_path_preview(openlab, path, args.step, args.hold, voice=voice)
        log("Game", "go!")

        tracker = PathTracker(env, openlab, player_id, path, start_zone, cameras,
                              lamp=lamp_ctrl, attempts=args.attempts, voice=voice)
        go.set()
        success = tracker.run()
        r = tracker.result
        print(f"result: {success} ({r.reason}, mistakes {len(r.mistakes)}, attempts left {r.attempts_left})")

        if success:
            for _ in range(2):
                openlab.lights.set_color(path, Color(w=255), fade=150)
                time.sleep(0.3)
                openlab.lights.set_color(path, GREEN, fade=150)
                time.sleep(0.3)
        time.sleep(2.0)
        voice.wait(timeout=10)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        voice.stop()
        openlab.lights.turn_off()
        time.sleep(0.3)


if __name__ == "__main__":
    main()
