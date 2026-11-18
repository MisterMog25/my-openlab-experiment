import json
import math
import time
from threading import Event
import tuke_openlab
import Lamps

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


def _get_topic(env, is_production: bool) -> str:
    if is_production:
        return "openlab/unifiedMapPositions/output"
    return f"experiments/mapPositions/{env.simulation_topic}/#"


def _extract_persons(payload_bytes: bytes) -> list[tuple[str, float, float]]:
    """Parses person coordinates from MQTT payload (supports both cameras and simulator)."""
    data = json.loads(payload_bytes.decode("utf-8"))