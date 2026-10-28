# my-openlab-experiment

Проєкт для TUKE OpenLab SDK (Python 3.14 + `uv`).

## Що вже встановлено

- `uv` (0.12.23) — менеджер пакетів і Python-версій
- CPython 3.14.8 — завантажений `uv`-ом, віртуальне середовище в `.venv/`
- `tuke-openlab==0.0.6` (з приватного індексу `https://repo.kpi.fei.tuke.sk/repository/pypi/simple`)

## Запуск

```bash
cd ~/Documents/openlab/my-openlab-experiment
uv run main.py
```

`uv run` сам активує `.venv` — окремо `source .venv/bin/activate` робити не треба.

## Симулятор vs. реальна лабораторія

У `main.py` використовується `simulation_env(TOPIC)`. SDK сам друкує посилання на симулятор:

```
https://openlab.kpi.fei.tuke.sk/simulator/light/mysterioushf-demo
```

Тема (`topic`) у браузері та в коді має збігатися. Для реального обладнання заміни на `production_env()`.

## Корисні команди

```bash
uv add <package>        # додати залежність
uv sync                 # відтворити середовище з pyproject.toml/uv.lock
uv run python -V        # 3.14.8
uv tree                 # дерево залежностей
```

## Структура

- `main.py` — приклад: світло + екрани
- `pyproject.toml` — залежності та приватний індекс `openlab`
- `.venv/` — віртуальне середовище (не комітити)
- `.vscode/settings.json` — інтерпретатор для Cursor
