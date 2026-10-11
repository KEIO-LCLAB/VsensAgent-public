# VsensAgent Documentation

This directory is organized around one rule:

- `current` documents describe the runtime and active architecture direction
- `plans` describe intended work that is not fully complete yet
- `legacy` preserves historical notes and outdated specs that should not drive new implementation

## Read This First

1. [Architecture Overview](architecture/OVERVIEW.md)
2. [Architecture Refactor Checklist](architecture/REFACTOR_CHECKLIST.md)
3. [Scene API Overview](scene_api/OVERVIEW.md)
4. [Communication Overview](communication/README.md)
5. [Plans Index](plans/README.md)
6. [Guides](guides/README.md)
7. [Agent MCP Workflow](guides/AGENT_MCP_WORKFLOW.md)

## Current Sources Of Truth

- [Architecture Overview](architecture/OVERVIEW.md)
  - Current Unity/Python split and collaboration-oriented runtime
- [Architecture Refactor Checklist](architecture/REFACTOR_CHECKLIST.md)
  - What is complete, partial, or still missing
- [Python Agent Architecture](architecture/PYTHON_AGENT.md)
  - Current Python runtime modules, prompt stack, and protocol routing
- [Scene API](scene_api/README.md)
  - Query/action/versioning contracts for the scene runtime
- [Agent MCP Workflow](guides/AGENT_MCP_WORKFLOW.md)
  - Which MCP tool to prefer for Unity runtime, C#, and Python tasks
- [Prompt Architecture](../VsensPython/docs/PROMPT_ARCHITECTURE.md)
  - Modular prompt composition and feature registration

## What Moved To Legacy

Historical material was moved out of the main reading path:

- old WebSocket and data-structure specs
- Python reconstruction plans and phase notes
- Unity reconstruction notes
- historical walkthroughs and one-off todo notes

See [Legacy Archive](legacy/README.md).

## Practical Reading Paths

For architecture work:

1. [Architecture Overview](architecture/OVERVIEW.md)
2. [Architecture Refactor Checklist](architecture/REFACTOR_CHECKLIST.md)
3. [Scene API Overview](scene_api/OVERVIEW.md)
4. [Plans Index](plans/README.md)

For Python agent work:

1. [Python Agent Architecture](architecture/PYTHON_AGENT.md)
2. [Prompt Architecture](../VsensPython/docs/PROMPT_ARCHITECTURE.md)
3. [Path Setup](../VsensPython/docs/PATH_SETUP.md)

For scene/runtime protocol work:

1. [Communication Overview](communication/README.md)
2. [Scene API Overview](scene_api/OVERVIEW.md)
3. [Scene Versioning](scene_api/SCENE_VERSIONING.md)
4. [Transaction Rules](scene_api/TRANSACTION_RULES.md)
