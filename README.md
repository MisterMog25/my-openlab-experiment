# OpenLab Light Show — TUKE Hands-Off

Controlling the lights of [OpenLab](https://kpi.fei.tuke.sk/openlab) at FEI TUKE
through the [`tuke-openlab`](https://git.kpi.fei.tuke.sk/open-lab/tuke-openlab-sdk) SDK.
The goal of the project is a **light show** built on top of this starter experiment.

## Authors

| Name | GitHub |
| --- | --- |
| Mark | [@MisterMog25](https://github.com/MisterMog25) |
| Andrii | [@AndrewPryladyshev](https://github.com/AndrewPryladyshev) |
| Tymofei | _GitHub handle to be added_ |

## Requirements

- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) — handles Python and dependencies
- Access to the OpenLab MQTT broker: **TUKE VPN** is required outside the university network

`uv` downloads the correct Python (3.14) and installs everything into `.venv/`.
There is no need to install Python or pip manually, and no need to activate the
virtual environment by hand.

## Getting started

```bash
git clone https://github.com/MisterMog25/my-openlab-experiment.git
cd my-openlab-experiment
uv sync          # creates .venv/ from uv.lock — exact same versions for everyone
uv run main.py   # first run
```

`uv run` executes the script inside the project environment, so
`source .venv/bin/activate` is never needed.

## Simulation vs. production

The SDK can talk to two environments:

| Environment | Code | What it does |
| --- | --- | --- |
| Simulation | `tuke_openlab.simulation_env("<topic>")` | nothing physical moves; the state is rendered in a browser simulator |
| Production | `tuke_openlab.production_env()` | **drives the real lights in the OpenLab** |

For development, always use the simulation. The SDK prints the URL of the matching
browser simulator when the script starts, for example:

```
https://openlab.kpi.fei.tuke.sk/simulator/light/<topic>
```

The same `<topic>` must be used in the code and in the browser. Use a unique topic ID
to avoid interfering with other people's experiments — your TUKE login is a good choice.
Topic IDs must not contain MQTT wildcards (`+`, `#`) or null characters.

Only use `production_env()` when the lab is free, and never run it while somebody
else is testing. Switch back to the simulation afterwards.

## Project layout

```
.
├── main.py          # entry point: connects, then drives lights and screens
├── pyproject.toml   # dependencies + the TUKE package index
├── uv.lock          # exact resolved versions — commit this
├── .python-version  # Python version used by uv
└── .venv/           # virtual environment, created by uv (never committed)
```

## Useful commands

```bash
uv run main.py            # run a script in the project environment
uv add <package>          # add a dependency (updates pyproject.toml and uv.lock)
uv sync                   # reinstall the environment from uv.lock
uv tree                   # show the dependency tree
```

## Contributing

Dependencies are added through `uv add`, which edits `pyproject.toml` and `uv.lock`.
If two people edit these files at the same time, Git will report a conflict, so
**try not to add dependencies in parallel** — one person adds, everyone else runs `uv sync`.

Workflow for every change:

```bash
git switch main && git pull          # start from the latest state
git switch -c feat/your-feature      # one branch per piece of work
git add <files> && git commit -m "feat: what you did"
git push -u origin feat/your-feature
```

Then open a pull request on GitHub and let one of the other two review it before merging.

## Resources

- [Hands-Off: controlling the lights](https://pages.kpi.fei.tuke.sk/kpi/hands-off/02/) — assignment page
- [Lights API](https://pages.kpi.fei.tuke.sk/kpi/hands-off/02/api.html) — services, colors, examples
- [tuke-openlab SDK](https://git.kpi.fei.tuke.sk/open-lab/tuke-openlab-sdk) — source, `docs/`, `examples/`
- [OpenLab platform](https://kpi.fei.tuke.sk/openlab)
