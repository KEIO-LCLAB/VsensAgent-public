# Portable Python Paths

Run the server from `VsensPython` after creating the environment described in
[the setup guide](../README.md).

Copy `.env.example` to `.env.vsensagent`, then set your API keys and model IDs.
The main agent and delegated workers load that local file relative to the Python
project directory. Existing environment variables take precedence.

Prompts and knowledge templates are included in the repository. Runtime logs,
recordings, voices, keys, caches, tasks and episode databases are local data and
are excluded from Git. They are not required in the initial source checkout.
