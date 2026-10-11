# VsensAgent

VsensAgent is a research prototype for exploring virtual sensing with a conversational agent. A Unity scene provides objects, avatars and virtual sensors; a Python server connects the scene to an AI agent over WebSocket.

Use it to inspect a scene, discuss sensor placement, request supported scene changes, and work with sensor recordings. The project is under active development: some planning, experiment and reporting workflows are still incomplete. See the [architecture overview](docs/architecture/OVERVIEW.md) for the current scope.

## What is in this repository?

| Directory | Purpose |
|---|---|
| `VsensAgent/` | Unity project, included as a Git submodule pinned to a specific commit |
| `VsensPython/` | Python agent, WebSocket server and optional monitor GUI |
| `VsensPython/data/prompts/` | Agent instructions, examples and feature definitions |
| `VsensPython/data/memory/knowledge/` | Reviewed sensor and scene knowledge templates |
| `docs/` | Architecture, scene API, development guides and historical notes |

Credentials and personal runtime data are not included. You will configure your own API access and generate your own recordings and session data.

## Requirements

- **Git**, including submodule support.
- **Unity Hub and Unity Editor `6000.3.9f1`**, the version recorded in [ProjectVersion.txt](VsensAgent/ProjectSettings/ProjectVersion.txt).
- **Conda or Miniconda**. The supplied environment creates Python 3.10 and installs the Python dependencies.
- **OpenAI API access**, an API key and a model ID available to your account, for the main agent.
- **Anthropic API access** if you want to use delegated analysis workers. It is optional for the basic main-agent workflow.
- Network access for the initial dependency downloads and for model API requests.

The Python dependency specification is [environment.yml](VsensPython/environment.yml). Review its platform notes if you are installing on an Intel Mac, particularly the LanceDB dependency.

## Quick start

The instructions below start Unity and Python on the same computer. Begin with text chat before trying voice, avatar motion or delegated recording analysis.

### 1. Get the source and the Unity submodule

Replace `REPOSITORY_URL` with this repository's Git clone URL:

```sh
git clone --recurse-submodules REPOSITORY_URL VsensAgent-public
cd VsensAgent-public
```

If you already have a local checkout, run this from its root instead:

```sh
git submodule update --init --recursive
```

Downloading a source ZIP does not initialize the Unity submodule. Use Git for the complete checkout.

### 2. Create the Python environment

From the repository root:

```sh
cd VsensPython
conda env create -f environment.yml
conda activate vsensagent
```

Keep this terminal in `VsensPython` for the remaining Python commands. If you have already created this environment, use `conda activate vsensagent` rather than creating it again.

### 3. Configure local API access

Copy the template to a local configuration file.

**macOS / Linux:**

```sh
cp .env.example .env.vsensagent
```

**Windows PowerShell:**

```powershell
Copy-Item .env.example .env.vsensagent
```

Open `.env.vsensagent` in a text editor and replace the following placeholders with your own values:

```dotenv
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL_ID=your_openai_model_id

# Optional: delegated analysis workers
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL_ID=
```

For delegated workers, also fill in the two Anthropic values. Model IDs must be available to the corresponding API account; choose them according to the features you intend to use.

The main agent and delegated workers load `.env.vsensagent` from the Python project directory. Exported environment variables take precedence. `.env.example` is a template and is not loaded at runtime; `.env.subagent` is not loaded either.

Keep actual credentials in `.env.vsensagent` or your environment. The local file is ignored by Git; never put real credentials into the committed template.

### 4. Start the Python server

For the first run, start without the monitor GUI:

```sh
python main.py --headless
```

The server uses `localhost:8765` by default. Look for this message and check that no startup error follows it:

```text
[Server] Starting WebSocket server on ws://localhost:8765
```

Keep the terminal running while using Unity. Press `Ctrl+C` to stop the server.

To use the monitor GUI later, run `python main.py --gui`. Running `python main.py` selects the GUI when its dependencies are available and otherwise uses headless mode. The monitor is separate from Unity's scene and chat interface.

### 5. Open Unity and connect

1. In Unity Hub, add the **`VsensAgent` subdirectory** as the project. Do not open the repository root as a Unity project.
2. Open it with Unity `6000.3.9f1`. Allow the initial asset import and package resolution to finish, and resolve any Console compilation errors before entering Play mode.
3. Open **`Assets/Scenes/VsensAgent/Room Test.unity`**, the scene currently configured in the project's build settings.
4. Enter **Play** mode. In the login panel, set the server address to **`localhost:8765`**, without `ws://`, and fill in the name and participant/study fields as appropriate for your local session.
5. Click **Login**. A successful connection switches from the login panel to the main interface; the Unity Console also reports `[WS]` connection messages.

**Enter the server address explicitly.** The pinned Unity submodule has an upstream remote address as its fallback. Leaving the field empty does not select your local Python server. Unity adds `ws://` itself, so entering the full URL in that field would produce an invalid address.

### 6. Try a first interaction

In the scene's chat interface, start with a read-only request such as:

> Describe the objects and sensors currently in the scene.

Then try a sensing question:

> Suggest where to place an IMU to observe the door opening and closing.

These are example requests, not guaranteed scripted results. Watch the scene, chat response and server logs together. Start with scene inspection and supported actions before moving to longer experiments; proposals, jobs and reporting are still evolving.

## Local data and privacy

The public source includes prompts and knowledge templates, but excludes API keys, prior conversations, episode databases, logs, voices, recordings, tasks and motion caches. Runtime directories are populated as you use the relevant features and are ignored by the main repository's Git rules.

Your local configuration and generated data can remain on your computer while you develop and commit code. The Unity submodule has its own Git repository and ignore rules; check both repositories before committing new Unity assets or recordings.

The agent sends relevant requests and context to the configured model providers. Use scene content and recordings that you are authorized to process, and review what you share before using personal or confidential data.

## Troubleshooting

| Symptom | What to check |
|---|---|
| The Unity project is missing or empty | Run `git submodule update --init --recursive` from the repository root. |
| Unity cannot import or compile the project | Confirm the editor version, allow package downloads to finish, and inspect the first Console error. |
| Unity cannot connect to Python | Confirm that the server is still running and that the login field contains `localhost:8765`, without `ws://`. Inspect both terminals for errors. |
| The default port is already in use | Run `python main.py --headless --port 9001`, then enter `localhost:9001` in Unity. |
| `OPENAI_API_KEY` or `OPENAI_MODEL_ID` is not set | Fill in `.env.vsensagent`, or export the variables. Editing `.env.example` does not configure the runtime. |
| Authentication or model access fails | Check the API key, the selected model ID and the provider account's access. Connection to Unity alone does not validate API access. |
| Delegated analysis fails | Configure Anthropic credentials and its model ID; confirm the Python environment includes the Anthropic SDK. |
| The Python monitor GUI will not open | Use `--headless` to continue with Unity, then check the PySide6 installation and desktop GUI support. |
| A recording or cached motion is missing | The public checkout contains no personal runtime recordings or caches. Collect or supply the inputs required by that feature. |

For separate computers, the server can bind to a reachable network interface using `--host`, and Unity must use that computer's address. See [Python server setup](VsensPython/README.md) for details. Start with the local setup above; network deployment requires separate access-control planning.

## Further reading and development

- [Documentation index](docs/README.md): navigation through the project documentation.
- [Architecture overview](docs/architecture/OVERVIEW.md): Unity/Python responsibilities and current limitations.
- [Python server setup](VsensPython/README.md): environment, startup modes and network configuration.
- [Scene API overview](docs/scene_api/OVERVIEW.md): scene queries, actions and versioning.
- [Prompt architecture](VsensPython/docs/PROMPT_ARCHITECTURE.md): how agent instructions are assembled.
- [Development workflow](docs/guides/AGENT_MCP_WORKFLOW.md): project tooling and verification.

To run the Python startup tests, activate the environment and run this from `VsensPython`:

```sh
python -m unittest tests.test_main_startup -v
```

The Unity project is pinned for reproducibility. Use `git submodule update --init --recursive` after pulling changes to the main repository to check out its recorded Unity revision. Changing files inside `VsensAgent` changes the submodule's working tree; those changes must be managed in that repository separately.

## License

The main repository is distributed under the [MIT License](LICENSE).

The Unity project is an independent [Vsens submodule](https://github.com/Yefancy/Vsens) with its original licenses preserved. Third-party plugins, models and assets retain their own license terms; the main repository's MIT License does not replace those terms.
