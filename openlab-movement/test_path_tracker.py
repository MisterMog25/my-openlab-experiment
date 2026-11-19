import contextlib
import io
import json
import math
import os
import pathlib
import random
import sys
import tempfile
import threading
import time
import unittest

from tuke_openlab.lights import Color

import path_tracker as pt
from path_tracker import LIGHT_POSITIONS, PathTracker
from speech import Voice

GREEN = pt.GREEN.to_hex_string()
RED = pt.RED.to_hex_string()
FINISH = pt.FINISH.to_hex_string()
YELLOW = Color(255, 140, 0).to_hex_string()
ZONE = [1, 2, 3, 28, 29, 30, 55, 56, 57]
PATH = [4, 5, 6, 33, 60]
TOPIC = "experiments/mapPositions/unit/camera1"


class FakeLights:
    def __init__(self):
        self.state = {}

    def set_color(self, lights, color, fade=0):
        ids = lights if isinstance(lights, (list, tuple, set)) else [lights]
        self.set_colors({i: color for i in ids}, fade)

    def set_colors(self, lights, fade=0):
        for i, c in lights.items():
            self.state[i] = c.to_hex_string()

    def set_all(self, color, fade=0):
        self.state = {i: color.to_hex_string() for i in range(1, 98)}

    def turn_off(self):
        self.set_all(Color())

    def lit(self, color):
        return sorted(i for i, c in self.state.items() if c == color)


class FakeController:
    def __init__(self):
        self.lights = FakeLights()


class FakeMsg:
    def __init__(self, topic, payload):
        self.topic = topic
        self.payload = payload


def topic_matches(flt, topic):
    f, t = flt.split("/"), topic.split("/")
    for i, part in enumerate(f):
        if part == "#":
            return True
        if i >= len(t) or part not in ("+", t[i]):
            return False
    return len(f) == len(t)


class FakeMQTT:
    # same as the SDK: subscribing to the same topic again replaces the handler
    def __init__(self):
        self.handlers = {}

    def listen_on(self, topic):
        pass

    def subscribe_to(self, topic, handler):
        self.handlers[topic] = handler

    def publish(self, topic, payload):
        for flt, handler in list(self.handlers.items()):
            if topic_matches(flt, topic):
                handler(FakeMsg(topic, payload.encode()))


class FakeEnv:
    def __init__(self, simulation_topic="unit"):
        self.simulation_topic = simulation_topic
        self.mqtt = FakeMQTT()


def pos(lamp):
    return LIGHT_POSITIONS[lamp]


def walk(points, speed=1.0, hz=10.0, noise=0.0, t0=0.0, seed=None):
    rnd = random.Random(seed)
    dt = 1.0 / hz
    t, cur = t0, points[0]
    frames = [(t, *cur)]
    for p in points[1:]:
        n = max(1, int(math.dist(cur, p) / (speed * dt)))
        for i in range(1, n + 1):
            t += dt
            frames.append((t, cur[0] + (p[0] - cur[0]) * i / n + rnd.gauss(0, noise),
                           cur[1] + (p[1] - cur[1]) * i / n + rnd.gauss(0, noise)))
        cur = p
    return frames


def stand(point, seconds, hz=10.0, noise=0.0, t0=0.0, seed=None):
    rnd = random.Random(seed)
    return [(t0 + i / hz, point[0] + rnd.gauss(0, noise), point[1] + rnd.gauss(0, noise))
            for i in range(int(seconds * hz))]


def make_tracker(path=PATH, zone=ZONE, **kwargs):
    env, ctrl = FakeEnv(), FakeController()
    kwargs.setdefault("verbose", False)
    kwargs.setdefault("attempts", 1)
    kwargs.setdefault("splash", False)
    return PathTracker(env, ctrl, "P1", path, zone, **kwargs), env, ctrl


def feed(tracker, frames, pid="P1", others=()):
    for t, x, y in frames:
        result = tracker._handle_frame(t, [(pid, x, y), *others])
        if result is not None:
            return result
    return None


def publish(env, frames, pid="P1", hz=50.0):
    for _, x, y in frames:
        env.mqtt.publish(TOPIC, json.dumps([{"Id": pid, "Position": {"X": x, "Y": y}}]))
        time.sleep(1.0 / hz)


GOOD_ROUTE = [pos(29), pos(3)] + [pos(lamp) for lamp in PATH]


class ParsingTest(unittest.TestCase):
    def test_camera_format(self):
        payload = json.dumps([{"Id": "a7", "Position": {"X": 1.5, "Y": 2}}]).encode()
        self.assertEqual(pt._extract_persons(payload), [("a7", 1.5, 2.0)])

    def test_simulator_format(self):
        payload = json.dumps({"positions": [[1, 2], {"X": 3, "Y": 4}]})
        self.assertEqual(pt._extract_persons(payload),
                         [("SimPlayer-1", 1.0, 2.0), ("SimPlayer-2", 3.0, 4.0)])

    def test_single_person_with_int_id(self):
        payload = json.dumps({"Id": 5, "Position": {"X": 0, "Y": 0}})
        self.assertEqual(pt._extract_persons(payload), [("5", 0.0, 0.0)])

    def test_garbage(self):
        self.assertEqual(pt._extract_persons(b'[{"Position": {"X": "?", "Y": 1}}, 7, null]'), [])
        with self.assertRaises(ValueError):
            pt._extract_persons(b"not json")

    def test_feed_skips_broken_messages(self):
        env = FakeEnv()
        q = pt._PositionFeed.get(env, "experiments/mapPositions/unit/#").open()
        env.mqtt.publish(TOPIC, "garbage{")
        env.mqtt.publish(TOPIC, json.dumps({"positions": [[1, 1]]}))
        self.assertEqual(q.get(timeout=1)[1], [("SimPlayer-1", 1.0, 1.0)])


class SetupTest(unittest.TestCase):
    def test_topics(self):
        sim, prod = FakeEnv("abc"), FakeEnv(None)
        self.assertEqual(pt._get_topic(sim, False), "experiments/mapPositions/abc/#")
        self.assertEqual(pt._get_topic(sim), "experiments/mapPositions/abc/#")
        self.assertEqual(pt._get_topic(sim, True), pt.PRODUCTION_TOPIC)
        self.assertEqual(pt._get_topic(prod), pt.PRODUCTION_TOPIC)
        with self.assertRaises(ValueError):
            pt._get_topic(prod, False)

    def test_bad_paths(self):
        for bad in ([], [4, 150], [4, 4], [3, 4]):
            with self.assertRaises(ValueError):
                pt.validate_path(bad, ZONE)
        self.assertEqual(pt.validate_path(("4", 5), ZONE), [4, 5])

    def test_neighbors(self):
        self.assertEqual(sorted(pt.lamp_neighbors(1)), [2, 28])
        self.assertEqual(sorted(pt.lamp_neighbors(32)), [5, 31, 33, 59])
        self.assertEqual(pt.lamp_neighbors(90), [])


class PathTest(unittest.TestCase):
    def test_correct_path(self):
        tracker, _, ctrl = make_tracker()
        steps = []
        tracker.on_step = lambda lamp, n, total: steps.append((lamp, n, total))
        result = feed(tracker, walk(GOOD_ROUTE))
        self.assertTrue(result)
        self.assertEqual(result.reason, "completed")
        self.assertEqual(result.reached, PATH)
        self.assertEqual(ctrl.lights.lit(GREEN), sorted(PATH))
        self.assertEqual(ctrl.lights.lit(RED), [])
        self.assertEqual(steps, [(lamp, i + 1, 5) for i, lamp in enumerate(PATH)])
        self.assertFalse(tracker.wrong_step.is_set())

    def test_wrong_step(self):
        tracker, _, ctrl = make_tracker()
        result = feed(tracker, walk([pos(29), pos(3), pos(4), pos(5), pos(32)]) + stand(pos(32), 1, t0=100))
        self.assertFalse(result)
        self.assertEqual((result.reason, result.expected_lamp, result.wrong_lamp), ("wrong_step", 6, 32))
        self.assertEqual(result.reached, [4, 5])
        self.assertEqual(result.attempts_left, 0)
        self.assertEqual(ctrl.lights.lit(GREEN), [4, 5])
        self.assertTrue(tracker.wrong_step.is_set())

    def test_wrong_step_is_fast(self):
        tracker, _, _ = make_tracker()
        frames = walk([pos(29), pos(3), pos(4), pos(5), pos(32)])
        arrived = next(t for t, x, y in frames if pt.find_nearest_light(x, y) == 32)
        result = feed(tracker, frames + stand(pos(32), 2, t0=frames[-1][0] + 0.1))
        self.assertEqual(result.reason, "wrong_step")
        self.assertLessEqual(tracker._last_seen - arrived, 0.5)

    def test_wrong_step_out_of_zone(self):
        tracker, _, _ = make_tracker()
        result = feed(tracker, walk([pos(29), pos(30), pos(31)]) + stand(pos(31), 1, t0=50))
        self.assertEqual((result.reason, result.wrong_lamp, result.expected_lamp), ("wrong_step", 31, 4))

    def test_back_to_zone_is_ok_but_not_further(self):
        tracker, _, _ = make_tracker(path=[4, 5, 6, 7])
        frames = (walk([pos(29), pos(3), pos(4), pos(5)])
                  + walk([pos(5), pos(4), pos(3), pos(2)], t0=60)
                  + walk([pos(2), pos(29), pos(56), pos(57), pos(58)], t0=70)
                  + stand(pos(58), 1, t0=90))
        self.assertEqual(feed(tracker, frames).wrong_lamp, 58)

    def test_one_frame_glitch(self):
        tracker, _, _ = make_tracker()
        frames = walk(GOOD_ROUTE)
        i = len(frames) // 2
        frames[i] = (frames[i][0], *pos(70))
        self.assertTrue(feed(tracker, frames))

    def test_going_back_along_path(self):
        tracker, _, _ = make_tracker()
        route = [pos(lamp) for lamp in (29, 3, 4, 5, 6, 5, 4, 5, 6, 33, 60)]
        self.assertTrue(feed(tracker, walk(route)))

    def test_skipped_lamp(self):
        frames = [f for f in walk(GOOD_ROUTE) if pt.find_nearest_light(f[1], f[2]) != 5]
        tracker, _, ctrl = make_tracker()
        self.assertTrue(feed(tracker, frames))
        self.assertIn(5, ctrl.lights.lit(GREEN))
        strict, _, _ = make_tracker(max_skip=0)
        self.assertFalse(feed(strict, frames + stand(pos(6), 1, t0=99)))

    def test_long_straight_segment(self):
        tracker, _, _ = make_tracker(path=[4, 10])
        self.assertTrue(feed(tracker, walk([pos(29), pos(3), pos(4), pos(10)])))

    def test_other_people_ignored(self):
        tracker, _, _ = make_tracker()
        self.assertTrue(feed(tracker, walk(GOOD_ROUTE), others=[("someone", *pos(70))]))

    def test_only_platform_id_counts(self):
        tracker, _, ctrl = make_tracker()
        frames = walk(GOOD_ROUTE)
        cut = len(frames) // 2
        self.assertIsNone(feed(tracker, frames[:cut]))
        reached = list(tracker.reached)

        # player is gone, a stranger shows up exactly there, finishes the path and then walks off it
        stranger = [(t + 5, x, y) for t, x, y in frames[cut:]]
        stranger += walk([pos(60), pos(70)], t0=stranger[-1][0] + 0.1) + stand(pos(70), 2, t0=200)
        for t, x, y in stranger:
            self.assertIsNone(tracker._handle_frame(t, [("stranger", x, y)]))
        self.assertEqual(tracker.reached, reached)
        self.assertEqual(tracker.mistakes, [])
        self.assertEqual(tracker.player_id, "P1")
        self.assertEqual(ctrl.lights.lit(GREEN), sorted(reached))

        rest = [(t + 300, x, y) for t, x, y in frames[cut:]]
        self.assertTrue(feed(tracker, rest))

    def test_no_start_zone(self):
        tracker, _, _ = make_tracker(zone=())
        frames = walk([pos(70), pos(40), pos(4)]) + walk([pos(lamp) for lamp in PATH], t0=40)
        self.assertTrue(feed(tracker, frames))

    def test_noisy_tracking(self):
        rnd = random.Random(42)
        for i in range(300):
            tracker, _, _ = make_tracker()
            frames = walk(GOOD_ROUTE, noise=0.12, hz=rnd.choice([5, 10, 20]),
                          speed=rnd.uniform(0.6, 1.6), seed=i)
            self.assertTrue(feed(tracker, frames), f"run {i}: {tracker.result}")

        wrong_routes = [
            [pos(29), pos(3), pos(4), pos(5), pos(32)],
            [pos(29), pos(3), pos(4), pos(5), pos(6), pos(7)],
            [pos(29), pos(3), pos(4), pos(31)],
            [pos(29), pos(3), pos(4), pos(5), pos(6), pos(33), pos(34)],
        ]
        for i in range(300):
            route = wrong_routes[i % len(wrong_routes)]
            tracker, _, _ = make_tracker()
            frames = walk(route, noise=0.12, speed=rnd.uniform(0.6, 1.6), seed=1000 + i)
            frames += stand(route[-1], 2, noise=0.12, t0=frames[-1][0] + 0.1, seed=i)
            result = feed(tracker, frames)
            self.assertIsNotNone(result, f"route {i % 4} not caught")
            self.assertEqual(result.reason, "wrong_step")


class AttemptsTest(unittest.TestCase):
    MISTAKE = walk([pos(29), pos(3), pos(4), pos(5), pos(32)])

    def mistake_and_back(self, t0):
        frames = [(t + t0, x, y) for t, x, y in self.MISTAKE[-12:]]
        frames += stand(pos(32), 1, t0=frames[-1][0] + 0.1)
        return frames + walk([pos(32), pos(5)], t0=frames[-1][0] + 0.1)

    def test_mistake_costs_one_attempt_and_game_goes_on(self):
        mistakes = []
        tracker, _, ctrl = make_tracker(attempts=3, on_wrong_step=mistakes.append)
        frames = self.MISTAKE + stand(pos(32), 1, t0=100)
        frames += walk([pos(32), pos(5), pos(6), pos(33), pos(60)], t0=200)
        result = feed(tracker, frames)
        self.assertTrue(result)
        self.assertEqual(result.attempts_left, 2)
        self.assertEqual([(m.expected_lamp, m.wrong_lamp, m.attempts_left) for m in mistakes], [(6, 32, 2)])
        self.assertEqual(ctrl.lights.lit(GREEN), sorted(PATH))
        self.assertTrue(tracker.wrong_step.is_set())

    def test_runs_out_of_attempts(self):
        mistakes = []
        tracker, _, _ = make_tracker(attempts=3, on_wrong_step=mistakes.append)
        frames = self.MISTAKE + stand(pos(32), 1, t0=100)
        frames += walk([pos(32), pos(5)], t0=200) + self.mistake_and_back(300) + self.mistake_and_back(400)
        result = feed(tracker, frames)
        self.assertFalse(result)
        self.assertEqual((result.reason, result.attempts_left, len(result.mistakes)), ("wrong_step", 0, 3))
        self.assertEqual([m.attempts_left for m in mistakes], [2, 1, 0])
        self.assertEqual(result.reached, [4, 5])

    def test_splash_keeps_zone_and_reached_lamps(self):
        calls = []
        original = pt.red_splash
        pt.red_splash = lambda controller, lamp, keep=(): calls.append((lamp, sorted(keep)))
        try:
            tracker, _, _ = make_tracker(attempts=2, splash=True)
            self.assertIsNone(feed(tracker, self.MISTAKE + stand(pos(32), 1, t0=100)))
        finally:
            pt.red_splash = original
        self.assertEqual(calls, [(32, sorted(ZONE + [4, 5, PATH[-1]]))])

    def test_red_splash_wave(self):
        ctrl = FakeController()
        keep = ZONE + [4, 5]
        for lid in keep:
            ctrl.lights.state[lid] = GREEN
        batches = []
        set_colors = ctrl.lights.set_colors

        def record(lights, fade=0):
            batches.append(dict(lights))
            set_colors(lights, fade)

        ctrl.lights.set_colors = record
        pt.red_splash(ctrl, 32, keep=keep, speed=100, hold_s=0.1)

        wave, off = batches[:-1], batches[-1]
        self.assertIn(32, wave[0])
        dists = [max(math.dist(pos(32), pos(lid)) for lid in batch) for batch in wave]
        self.assertEqual(dists, sorted(dists))
        lit = {lid for batch in wave for lid in batch}
        self.assertEqual(lit, set(LIGHT_POSITIONS) - set(keep))
        self.assertEqual(set(off), lit)
        self.assertEqual(ctrl.lights.lit(RED), [])
        self.assertEqual(ctrl.lights.lit(GREEN), sorted(keep))


class FakeVoice:
    def __init__(self):
        self.said = []

    def say(self, text, interrupt=False, skip_if_busy=False):
        self.said.append((text, interrupt))

    def texts(self):
        return [text for text, _ in self.said]


class VoiceTest(unittest.TestCase):
    TTS = ("import sys, time; open(sys.argv[1], 'a').write(sys.argv[2] + '\\n'); "
           "time.sleep(2 if sys.argv[2].startswith('slow') else 0.2)")

    def make_voice(self):
        log_file = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
        log_file.close()
        self.addCleanup(os.remove, log_file.name)
        voice = Voice(command=[sys.executable, "-c", self.TTS, log_file.name], verbose=False)
        spoken = lambda: pathlib.Path(log_file.name).read_text().split()
        return voice, spoken

    def test_phrases_are_queued_in_order(self):
        voice, spoken = self.make_voice()
        voice.say("one")
        voice.say("two")
        voice.wait(5)
        self.assertEqual(spoken(), ["one", "two"])
        self.assertFalse(voice.busy)

    def test_minor_phrase_skipped_when_busy(self):
        voice, spoken = self.make_voice()
        voice.say("one")
        voice.say("correct", skip_if_busy=True)
        voice.wait(5)
        self.assertEqual(spoken(), ["one"])

    def test_interrupt(self):
        voice, spoken = self.make_voice()
        start = time.monotonic()
        voice.say("slow")
        voice.say("queued")
        time.sleep(0.5)
        voice.say("wrong", interrupt=True)
        voice.wait(5)
        self.assertLess(time.monotonic() - start, 1.8)
        self.assertEqual(spoken(), ["slow", "wrong"])

    def test_disabled(self):
        voice = Voice(enabled=False, verbose=False)
        voice.say("hello")
        self.assertFalse(voice.busy)

    def test_game_phrases(self):
        tracker, _, _ = make_tracker(voice=FakeVoice())
        self.assertTrue(feed(tracker, walk(GOOD_ROUTE)))
        self.assertEqual(tracker.voice.texts(), [pt.PHRASES["halfway"], pt.PHRASES["win"]])

        voice = FakeVoice()
        test = AttemptsTest()
        tracker, _, _ = make_tracker(attempts=3, voice=voice)
        frames = test.MISTAKE + stand(pos(32), 1, t0=100)
        frames += walk([pos(32), pos(5)], t0=200) + test.mistake_and_back(300) + test.mistake_and_back(400)
        self.assertFalse(feed(tracker, frames))
        self.assertEqual(voice.said, [
            (pt.PHRASES["halfway"], False),
            ("Wrong step! Go back to the last green light. 2 attempts left.", True),
            (pt.PHRASES["back"], False),
            ("Wrong step! Go back to the last green light. Last attempt!", True),
            (pt.PHRASES["back"], False),
            (pt.PHRASES["game_over"], True),
        ])

    def test_wrong_step_right_off_the_platform(self):
        voice = FakeVoice()
        tracker, _, _ = make_tracker(attempts=3, voice=voice)
        feed(tracker, walk([pos(29), pos(30), pos(31)]) + stand(pos(31), 1, t0=50))
        self.assertEqual(voice.texts(), ["Wrong step! Go back to the platform. 2 attempts left."])

    def test_preview_phrases(self):
        voice = FakeVoice()
        pt.show_path_preview(FakeController(), PATH, step_s=0, hold_s=0, voice=voice)
        self.assertEqual(voice.said, [(pt.PHRASES["memorize"], False), (pt.PHRASES["go"], True)])


class LongPathTest(unittest.TestCase):
    PATH = pt.TEST_PATH
    ROUTE = [pos(29), pos(3)] + [pos(lamp) for lamp in pt.TEST_PATH]

    def test_long_path_is_valid_and_connected(self):
        self.assertEqual(pt.validate_path(self.PATH, ZONE), self.PATH)
        for a, b in zip(self.PATH, self.PATH[1:]):
            self.assertIn(b, pt.lamp_neighbors(a))
        self.assertIn(self.PATH[0], pt.lamp_neighbors(3))

    def test_long_path_correct(self):
        tracker, _, ctrl = make_tracker(path=self.PATH)
        result = feed(tracker, walk(self.ROUTE))
        self.assertTrue(result)
        self.assertEqual(ctrl.lights.lit(GREEN), sorted(self.PATH))

    def test_long_path_mistake_at_every_step(self):
        for k in range(1, len(self.PATH)):
            here, expected = self.PATH[k - 1], self.PATH[k]
            for wrong in pt.lamp_neighbors(here):
                if wrong in self.PATH or wrong in ZONE:
                    continue
                with self.subTest(step=k, wrong=wrong):
                    tracker, _, ctrl = make_tracker(path=self.PATH)
                    route = self.ROUTE[:k + 2] + [pos(wrong)]
                    result = feed(tracker, walk(route) + stand(pos(wrong), 1, t0=500))
                    self.assertEqual((result.reason, result.expected_lamp, result.wrong_lamp),
                                     ("wrong_step", expected, wrong))
                    self.assertEqual(ctrl.lights.lit(GREEN), sorted(self.PATH[:k]))

    def test_long_path_noisy(self):
        rnd = random.Random(7)
        for i in range(100):
            tracker, _, _ = make_tracker(path=self.PATH)
            frames = walk(self.ROUTE, noise=0.12, hz=rnd.choice([5, 10, 20]),
                          speed=rnd.uniform(0.6, 1.6), seed=i)
            self.assertTrue(feed(tracker, frames), f"run {i}: {tracker.result}")


class ThreadTest(unittest.TestCase):
    def test_wait_for_wrong_step_from_another_thread(self):
        got = {}
        tracker, env, _ = make_tracker(on_wrong_step=lambda r: got.setdefault("callback", r))
        tracker.start()
        seen = threading.Event()

        def watcher():
            tracker.wrong_step.wait()
            got["lamp"] = tracker.result.wrong_lamp
            seen.set()

        threading.Thread(target=watcher, daemon=True).start()
        publish(env, walk([pos(29), pos(3), pos(4), pos(31)], hz=25) + stand(pos(31), 1, hz=25))
        self.assertTrue(seen.wait(3))
        self.assertIs(tracker.wait(1), False)
        self.assertEqual(got["lamp"], 31)
        self.assertEqual((got["callback"].wrong_lamp, got["callback"].expected_lamp), (31, 5))

    def test_track_player_path_blocking(self):
        env, ctrl = FakeEnv(), FakeController()
        out = {}
        th = threading.Thread(target=lambda: out.setdefault("ok", pt.track_player_path(
            env, ctrl, None, "P1", PATH, ZONE, False, verbose=False)))
        th.start()
        time.sleep(0.1)
        publish(env, walk(GOOD_ROUTE, hz=25))
        th.join(3)
        self.assertIs(out.get("ok"), True)

    def test_finish_is_lit_until_reached(self):
        tracker, env, ctrl = make_tracker()
        tracker.start()
        time.sleep(0.1)
        self.assertEqual(ctrl.lights.lit(FINISH), [PATH[-1]])
        publish(env, walk(GOOD_ROUTE, hz=25))
        self.assertIs(tracker.wait(2), True)
        self.assertEqual(ctrl.lights.lit(FINISH), [])
        self.assertEqual(ctrl.lights.lit(GREEN), sorted(PATH))

    def test_no_finish_color(self):
        tracker, _, ctrl = make_tracker(finish_color=None, lost_timeout_s=0.2)
        tracker.run()
        self.assertEqual(ctrl.lights.lit(FINISH), [])

    def test_wrong_step_without_new_frames(self):
        tracker, env, _ = make_tracker()
        tracker.start()
        publish(env, walk([pos(29), pos(3), pos(4), pos(31)], hz=25))
        self.assertIs(tracker.wait(2), False)
        self.assertEqual(tracker.result.wrong_lamp, 31)

    def test_lost_and_stop(self):
        tracker, _, _ = make_tracker(lost_timeout_s=0.3)
        self.assertIs(tracker.run(), False)
        self.assertEqual(tracker.result.reason, "player_lost")

        tracker, _, _ = make_tracker()
        tracker.start()
        tracker.stop()
        self.assertIs(tracker.wait(2), False)
        self.assertEqual(tracker.result.reason, "stopped")

    def test_timeout(self):
        tracker, env, _ = make_tracker(timeout_s=0.4)
        tracker.start()
        publish(env, stand(pos(29), 0.2, hz=20))
        self.assertIs(tracker.wait(2), False)
        self.assertEqual(tracker.result.reason, "timeout")

    def test_broken_callback(self):
        def boom(*args):
            raise RuntimeError("boom")

        tracker, env, _ = make_tracker(on_step=boom)
        with contextlib.redirect_stderr(io.StringIO()):
            tracker.start()
            publish(env, walk(GOOD_ROUTE, hz=25))
            self.assertIs(tracker.wait(2), True)


class PreviewTest(unittest.TestCase):
    def test_path_appears_one_by_one_then_disappears(self):
        ctrl = FakeController()
        snapshots = []
        set_colors = ctrl.lights.set_colors

        def record(lights, fade=0):
            set_colors(lights, fade)
            snapshots.append((time.monotonic(), ctrl.lights.lit(pt.PREVIEW.to_hex_string()),
                              ctrl.lights.lit(FINISH)))

        ctrl.lights.set_colors = record
        pt.show_path_preview(ctrl, PATH, step_s=0.2, hold_s=0.5)

        reveal = snapshots[:len(PATH)]
        for i, (_, lit, finish) in enumerate(reveal[:-1]):
            self.assertEqual(lit, sorted(PATH[:i + 1]))
            self.assertEqual(finish, [])
        # the finish comes last and in its own colour
        self.assertEqual(reveal[-1][1:], (sorted(PATH[:-1]), [PATH[-1]]))
        for (t1, *_), (t2, *_) in zip(reveal, reveal[1:]):
            self.assertAlmostEqual(t2 - t1, 0.2, delta=0.05)
        end_time, lit, finish = snapshots[-1]
        self.assertEqual(lit, [])
        self.assertEqual(finish, [PATH[-1]])
        self.assertAlmostEqual(end_time - reveal[-1][0], 0.5, delta=0.1)


class StartZoneTest(unittest.TestCase):
    def test_zone_then_path(self):
        env, ctrl = FakeEnv(), FakeController()
        out = {}

        def game():
            pid, zone = pt.wait_for_player_in_start_zone(env, ctrl, None, 1, False, dwell_s=0.5,
                                                         verbose=False)
            out.update(pid=pid, zone=zone, zone_yellow=ctrl.lights.lit(YELLOW))
            out["ok"] = pt.track_player_path(env, ctrl, None, pid, PATH, zone, False, verbose=False)

        def send(people):
            env.mqtt.publish(TOPIC, json.dumps(
                [{"Id": pid, "Position": {"X": x, "Y": y}} for pid, (x, y) in people]))

        th = threading.Thread(target=game)
        th.start()
        time.sleep(0.5)
        send([("passer", pos(2))])
        send([("passer", pos(10))])
        for _ in range(12):
            send([("player", pos(29)), ("passer", pos(12))])
            time.sleep(0.05)
        time.sleep(0.3)
        for _, x, y in walk(GOOD_ROUTE, hz=25):
            send([("player", (x, y))])
            time.sleep(0.02)
        th.join(5)

        self.assertEqual(out.get("pid"), "player")
        self.assertEqual(out["zone"], ZONE)
        self.assertEqual(out["zone_yellow"], ZONE)
        self.assertIs(out["ok"], True)
        self.assertEqual(len(env.mqtt.handlers), 1)

    def test_timeout(self):
        with self.assertRaises(TimeoutError):
            pt.wait_for_player_in_start_zone(FakeEnv(), FakeController(), timeout_s=0.3, verbose=False)


if __name__ == "__main__":
    unittest.main()
