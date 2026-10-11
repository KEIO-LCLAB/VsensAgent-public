# AGENTS

This repository has project-aware MCP tooling available. Prefer it over generic shell guesses when it gives a more reliable workflow.

## Tool Preference

### Unity MCP

Use Unity MCP for Unity runtime or editor behavior:

- run Unity tests with Unity's own test runner
- inspect the active scene/session
- query or manipulate scene objects
- capture screenshots or camera-based validation views
- validate runtime behavior that static C# tooling cannot prove

Prefer:

- `run_tests`
- `get_test_job`
- `manage_scene`
- `manage_camera`
- `manage_gameobject`
- `manage_components`
- `manage_prefabs`

Do not treat `dotnet test` as the primary Unity verification path.

### Rider MCP

Use Rider MCP for Unity/C# code inspection and static validation:

- inspect file problems
- build changed C# files
- inspect symbols and references
- search project-aware C# code

Prefer:

- `get_file_problems`
- `build_project`
- `get_symbol_info`
- `search_in_files_by_text`
- `search_in_files_by_regex`

### PyCharm MCP

Use PyCharm MCP for Python-side work in `VsensPython`:

- inspect Python files with IDE context
- search usages and code paths
- inspect file problems
- support Python-oriented test/debug workflows

Prefer:

- `get_file_text_by_path`
- `get_file_problems`
- `search_in_files_by_text`
- `search_in_files_by_regex`
- `build_project`

## Repo Workflow

A good default sequence in this repo is:

1. Inspect code with Rider MCP or PyCharm MCP.
2. Make code changes.
3. Run Python tests for `VsensPython`.
4. Run Unity verification with Unity MCP `run_tests` for Unity-side changes.
5. For visual or scene-related behavior, use Unity MCP query/capture tools before claiming correctness.

## Reference

For the longer project-local version, see:

- [docs/guides/AGENT_MCP_WORKFLOW.md](docs/guides/AGENT_MCP_WORKFLOW.md)
