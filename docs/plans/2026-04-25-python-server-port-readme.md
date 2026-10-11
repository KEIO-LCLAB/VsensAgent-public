# Python Server Port And README Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow the Python server main entry point to accept a custom WebSocket port and document server setup.

**Architecture:** Keep `VsensPython/main.py` as the single startup entry point. Add a small `argparse` parser that preserves existing `--gui` and `--headless` behavior while passing an optional port into `VsensWebSocketServer`.

**Tech Stack:** Python 3.10, `unittest`, `asyncio`, `websockets`, conda environment from `VsensPython/environment.yml`.

---

### Task 1: Startup CLI Port

**Files:**
- Modify: `VsensPython/main.py`
- Test: `VsensPython/tests/test_main_startup.py`

**Step 1: Write the failing test**

Add tests proving `--port 9001` parses to `9001` and `_run_server(9001)` constructs `VsensWebSocketServer(port=9001)`.

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_main_startup.py -q` from `VsensPython`.

Expected: FAIL because `main._parse_args` does not exist yet.

**Step 3: Write minimal implementation**

Add `argparse`, parse `--port`, `--gui`, and `--headless`, pass the parsed port to `_run_server`.

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_main_startup.py -q` from `VsensPython`.

Expected: PASS.

### Task 2: Server Setup README

**Files:**
- Create: `VsensPython/README.md`

**Step 1: Write the docs**

Document environment creation, activation, required `.env` values, headless and GUI startup commands, custom port usage, and Unity WebSocket URL.

**Step 2: Review for accuracy**

Check the README against `environment.yml`, `main.py`, and the default `VsensWebSocketServer` host/port.
