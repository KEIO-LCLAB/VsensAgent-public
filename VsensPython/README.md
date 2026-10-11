# VsensAgent Python Server Setup

This directory contains the Python WebSocket server used by the Unity side of VsensAgent.

## Prerequisites

- Conda or Miniconda
- Python 3.10 through the provided conda environment
- Network access for the first dependency install

## Create The Environment

From the repository root:

```powershell
cd VsensPython
conda env create -f environment.yml
conda activate vsensagent
```

If the environment already exists and dependencies changed:

```powershell
conda env update -f environment.yml --prune
conda activate vsensagent
```

## Configure Secrets

Copy `.env.example` to `.env.vsensagent`, then set your own API keys and model IDs.
Environment variables take precedence over the local file. The example file is not loaded at runtime.

Use this single file for both the main OpenAI client and delegated subagent workers:

```text
# main agent
OPENAI_API_KEY=your_api_key_here
OPENAI_MODEL_ID=gpt-5.4

# for subagent
ANTHROPIC_API_KEY=your_anthropic_key_here
ANTHROPIC_MODEL_ID=claude-sonnet-4-6
```

Keep this file local. It should not be committed.

Both clients use `.env.vsensagent`; `.env.subagent` is not loaded.

## Start The Server

Headless server only:

```powershell
python main.py --headless
```

Start with the monitor GUI when available:

```powershell
python main.py --gui
```

Auto mode starts the GUI when PySide6 and GUI runtime support are available, otherwise it falls back to headless mode:

```powershell
python main.py
```

By default, the WebSocket server listens on:

```text
ws://localhost:8765
```

Use `--port` to run on a different port:

```powershell
python main.py --headless --port 9001
```

Unity or other clients should connect to the matching URL:

```text
ws://localhost:9001
```

## Accept External Connections

The server binds to `localhost` by default, so only the same machine can connect.

To accept connections from other machines on the network, bind to all interfaces:

```powershell
python main.py --headless --host 0.0.0.0 --port 9001
```

Other clients should connect with this machine's LAN IP or public host name, not `localhost`:

```text
ws://192.168.x.x:9001
```

For public internet access, you also need firewall and router/cloud network rules that allow the selected port. Do not expose this server publicly unless you trust the network path and understand the runtime permissions it gives connected clients.

## Run Startup Tests

The startup tests can run with the standard library test runner:

```powershell
python -m unittest tests.test_main_startup -v
```

If `pytest` is installed in your environment, this also works:

```powershell
python -m pytest tests/test_main_startup.py -q
```
