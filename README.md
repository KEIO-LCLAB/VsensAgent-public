# VsensAgent

A Unity virtual sensing environment with a Python WebSocket agent server.

## Get started

Initialize the Unity project dependency:

```sh
git submodule update --init --recursive
```

Open `VsensAgent` in Unity using the editor version in
`VsensAgent/ProjectSettings/ProjectVersion.txt`.
Follow [Python server setup](VsensPython/README.md) to create the Conda environment,
copy `VsensPython/.env.example` to `VsensPython/.env.vsensagent`, and configure your
own API keys and model IDs. Start the Python server and connect Unity to
`ws://localhost:8765`.

[Architecture and API documentation](docs/README.md) describe the system.

## Local data

The source checkout intentionally omits credentials, session histories, voices,
recordings, caches and episode databases. Keep these on your machine; Git ignores
the local runtime directories. Use newly issued credentials in local configuration.
Prompts and reviewed sensor knowledge templates are included.

## License and dependencies

The main repository is distributed under the [MIT License](LICENSE).
The Unity project is an independent [Vsens submodule](https://github.com/Yefancy/Vsens)
pinned to a fixed commit, with its original licenses preserved. Third-party
plugins, models and assets retain their own licenses, which must be reviewed
before redistributing or using those assets beyond their authorized scope.
