# OpenLab Light Show — TUKE Hands-Off

Controlling the lights and screens of [OpenLab](https://kpi.fei.tuke.sk/openlab) at FEI TUKE
through the [`tuke-openlab`](https://git.kpi.fei.tuke.sk/open-lab/tuke-openlab-sdk) SDK.

## Authors

| Name | GitHub |
| --- | --- |
| Mark | [@MisterMog25](https://github.com/MisterMog25) |
| Andrii | [@AndrewPryladyshev](https://github.com/AndrewPryladyshev) |
| Tymofei | _GitHub handle to be added_ |

## Requirements

- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) — installs Python and the dependencies
- Access to the OpenLab MQTT broker: **TUKE VPN** is needed outside the university network
  ([Check Point VPN](https://uvt.tuke.sk/sk/vzdialeny-pristup-cez-vpn), server `remote.tuke.sk`)

`uv` downloads the right Python and puts everything into `.venv/`. No manual Python install,
no manual `pip`, no need to activate the virtual environment.

## Getting started

```bash
git clone https://github.com/MisterMog25/my-openlab-experiment.git
cd my-openlab-experiment
uv sync          # creates .venv/ from uv.lock — the same versions for everyone
uv run main.py   # opens the menu
```

Ready-made SDK examples (flags, pulse, spectrum, interpolation helpers) are in
`~/Documents/openlab/tuke-openlab-sdk/examples/` or
[on GitLab](https://git.kpi.fei.tuke.sk/open-lab/tuke-openlab-sdk/-/tree/master/examples).

## Project structure

One file per person. Everybody writes their own scene in their own file:

```
.
├── main.py       # menu: launches one of the scripts below, or all of them
├── mark.py       # Mark's experiments
├── andrii.py     # Andrii's experiments
├── tymofii.py    # Tymofii's experiments
├── pyproject.toml / uv.lock   # dependencies (commit uv.lock)
└── README.md
```

```bash
uv run main.py      # menu: [1] Tymofii  [2] Mark  [3] Andrii
uv run mark.py      # or run your own file directly
```

> `main.py` starts every scene as a **separate process** with `subprocess.run`, so only one
> scene runs at a time. For the final show we will glue the scenes into one program.

## Which environment and which topic

```python
import tuke_openlab

openlab = tuke_openlab.Controller(tuke_openlab.simulation_env("your-topic"))  # simulator
openlab = tuke_openlab.Controller(tuke_openlab.production_env())              # REAL lamps
```

The **same code** drives both — only the topic differs. The simulator is a web page that
subscribes to the same MQTT topic, so you see exactly what the lamps would show:

```
https://openlab.kpi.fei.tuke.sk/simulator/light/<your-topic>
```

> ⚠️ **Every person must use their own topic.** Right now `mark.py`, `andrii.py` and
> `tymofii.py` all contain the same `TOPIC = "mysterioushf-demo"` — that is Mark's simulator.
> Change it to your own unique ID (your TUKE login is a good choice). Topics must not contain
> MQTT wildcards (`+`, `#`) or null characters.

Only use `production_env()` when the lab is free. One laptop, one process — two scripts
publishing to the same topic overwrite each other.

## What you can control

Everything hangs off the `Controller` object returned above:

| Attribute | What it does |
| --- | --- |
| `openlab.lights` | colors of the 97 lamps (`set_all`, `set_colors`, `set_color`, `turn_on`, `turn_off`) |
| `openlab.screens` | content of the displays (`panel_2x2`, `vertical[1..5]`) |
| `openlab.voice_recognition` | react to spoken words (`on_recognized`) |
| `openlab.movement_tracker`, `openlab.kinect` | react to movement (`on_movement`) |

The lights grid: **3 rows × 27 columns = ids 1–81** (column 1 is the rightmost one),
plus **8 windows × 2 lamps = ids 82–97**.

```python
from tuke_openlab.lights import Color

lights.set_all(Color(r=255), fade=1000)          # all lamps red, 1 s fade
lights.set_colors({1: Color(r=255), 28: Color(b=255)}, fade=500)
lights.turn_off()
```

## Writing your own scene

A scene is an infinite loop that builds a frame and sends it:

```python
import time

import tuke_openlab
from tuke_openlab.lights import Color

openlab = tuke_openlab.Controller(tuke_openlab.simulation_env("your-topic"))
lights = openlab.lights

ROWS, COLUMNS = 3, 27


def column(c):
    """All 3 lamps of column c (c=1 is the rightmost column)."""
    return [c + r * COLUMNS for r in range(ROWS)]


def wave(seconds=15):
    start = time.monotonic()
    step = 0
    while time.monotonic() - start < seconds:
        frame = {}
        for i in range(1, COLUMNS + 1):
            distance = (i - step) % (COLUMNS + 4)
            if distance < 4:
                power = 1 - distance / 4            # tail fades out
                for light in column(i):
                    frame[light] = Color(r=int(255 * power), g=int(120 * power))
            else:
                for light in column(i):
                    frame[light] = Color()          # off
        lights.set_colors(frame)                    # one frame = one MQTT message
        step += 1
        time.sleep(0.12)
```

Two ways to animate, and they can be mixed:

- **draw every frame yourself** (`fade=0`) — full control, needed for fast effects;
- **send rare keyframes with a large `fade`** (e.g. `fade=1500`) — the hardware interpolates,
  which looks very smooth for slow transitions and costs almost no traffic.

## Useful commands

```bash
uv run main.py            # the menu
uv run mark.py            # run one script in the project environment
uv add <package>          # add a dependency (updates pyproject.toml and uv.lock)
uv sync                   # reinstall the environment from uv.lock
```

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| `TimeoutError` / hangs on start | no access to the TUKE network — connect the VPN |
| `ValueError: Invalid light ID specified: 98` | ids 98–199 do not exist (the wall is 1–81, windows 82–97) |
| The lights stopped reacting to your edits | an old process is still running — press `Ctrl+C` |
| `python mark.py` does nothing useful | always use `uv run mark.py` |

## Contributing

Dependencies are added through `uv add`, which edits `pyproject.toml` and `uv.lock`. Two people
editing them at the same time means a Git conflict, so **do not add dependencies in parallel** —
one person adds, everyone else runs `uv sync`.

We push directly to `main` (no pull requests), which means one rule before every push:

```bash
git pull --rebase          # always, otherwise the push is rejected
git add mark.py            # only your own file
git commit -m "feat: my scene"
git push origin main
```

## Resources

- [Hands-Off: controlling the lights](https://pages.kpi.fei.tuke.sk/kpi/hands-off/02/) — the assignment
- [Lights API](https://pages.kpi.fei.tuke.sk/kpi/hands-off/02/api.html) — services, colors, examples
- [tuke-openlab SDK](https://git.kpi.fei.tuke.sk/open-lab/tuke-openlab-sdk) — source, `docs/`, `examples/`
- [OpenLab platform](https://kpi.fei.tuke.sk/openlab)
