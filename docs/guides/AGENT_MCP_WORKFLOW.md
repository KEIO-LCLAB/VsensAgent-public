# Agent MCP Workflow

This guide is a project-local reminder for coding agents working on `VsensAgent`.

It exists to make one thing explicit:

- prefer the available MCP tools over ad-hoc shell guesses when working with Unity, C#, and Python in this repo

## Recommended Prompt Snippet

When starting a new coding session on this project, it is reasonable to include a note like:

> This repo has Unity MCP, Rider MCP, and PyCharm MCP available.  
> Prefer Unity MCP for Unity runtime actions and Unity Test Runner.  
> Prefer Rider MCP for Unity/C# code inspection and build checks.  
> Prefer PyCharm MCP for Python code inspection and project-aware navigation.  
> Use these before falling back to generic shell commands when they provide a more reliable project-aware workflow.

## Tooling Rules Of Thumb

### Unity MCP

Prefer Unity MCP when the task involves the Unity runtime or editor-facing behavior.

Use it for:

- running Unity tests through Unity's own test runner
- checking the active Unity scene/session
- querying or manipulating scene objects
- capturing validation screenshots or camera views
- validating runtime behavior that ordinary `.NET` tooling cannot verify

Good examples:

- `run_tests` / `get_test_job`
- `manage_scene`
- `manage_prefabs`
- `manage_camera`
- `manage_gameobject`
- `manage_components`

Important reminder:

- Unity code should not be considered verified only because `dotnet` or Rider build succeeds
- use Unity MCP test tools or Unity batchmode test runner for real Unity-side verification

### Rider MCP

Prefer Rider MCP when the task is primarily about Unity C# code structure rather than runtime behavior.

Use it for:

- reading C# files with IDE awareness
- checking file problems / inspections
- building changed Unity C# files
- understanding symbols and references inside the Unity project

Good examples:

- `get_file_problems`
- `build_project`
- `get_symbol_info`
- `search_in_files_by_text`
- `search_in_files_by_regex`

Rider MCP is a strong static signal, but it does not replace Unity Test Runner for runtime/editor behavior.

### PyCharm MCP

Prefer PyCharm MCP when working in `VsensPython` or Python-side docs/tests.

Use it for:

- reading Python files with project context
- finding usages and project-aware search
- checking Python-side file problems
- running Python-oriented build/test flows when useful from the IDE side

Good examples:

- `get_file_text_by_path`
- `get_file_problems`
- `search_in_files_by_text`
- `search_in_files_by_regex`
- `build_project`

## Repo-Specific Workflow

For this project, a good default sequence is:

1. Use Rider MCP or PyCharm MCP to inspect the relevant code.
2. Make code changes.
3. Use Rider MCP for Unity/C# static checks.
4. Use PyCharm or normal Python tests for `VsensPython`.
5. Use Unity MCP `run_tests` for Unity verification.
6. If the task is visual or scene-related, use Unity MCP capture/query tools before claiming the behavior is correct.

## Quick Mapping

- "Need to run Unity tests" -> Unity MCP
- "Need to inspect Unity C# errors" -> Rider MCP
- "Need to inspect Python code/tests" -> PyCharm MCP
- "Need to confirm runtime scene state or screenshots" -> Unity MCP
- "Need a fast shell fallback for plain text search" -> `rg`

## Anti-Patterns

Avoid these shortcuts when a better project-aware tool exists:

- using `dotnet test` as the primary Unity test signal
- assuming Unity runtime behavior from C# compilation alone
- using only shell grep when Rider/PyCharm can provide cleaner symbol-aware inspection
- claiming scene behavior is correct without either Unity tests or Unity runtime inspection
