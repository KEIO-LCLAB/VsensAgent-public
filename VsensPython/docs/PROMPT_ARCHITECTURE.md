# Prompt Architecture

This backend no longer relies on a single editable `system_prompt.txt` as the primary runtime prompt source.

## Runtime Model

`VsensOpenAI` now loads the default system prompt through:

- [composer.py](../core/prompting/composer.py)
- [registry.py](../core/prompting/registry.py)

The composer builds one final system prompt string from modular assets under `data/prompts/`.

## Prompt Layout

```text
VsensPython/data/prompts/
├── core/                  # identity, behavior, decision policy, output contract
├── features/              # capability-specific instructions
├── examples/              # few-shot examples for selected features
├── manifests/
│   └── features.json      # feature registry and default enablement
└── system_prompt.txt      # legacy reference snapshot only
```

## Current Prompt Features

The prompt registry currently includes:

- `control`
- `clarification`
- `proposal`
- `job`
- `scene_query`

These features are enabled by default in `features.json`.

## Decision Policy

The core prompt stack now includes a dedicated decision-policy section.

Its job is to teach the model:

- choose exactly one primary response mode per turn
- prefer `clarification` over `proposal` when intent is ambiguous
- prefer `proposal` over `control` when the user is exploring options first
- prefer `control` only for immediate scene mutations
- use query-first reasoning before inventing scene facts
- treat long-running tasks with job-oriented language

This keeps routing strategy in one place instead of scattering it across feature files.

## Rule For New Features

When adding a new protocol or agent capability, update all of these together:

1. Runtime implementation
2. Prompt module in `data/prompts/features/`
3. Registry entry in `data/prompts/manifests/features.json`
4. Example prompt in `data/prompts/examples/` if the feature needs stronger activation
5. Prompt composition or protocol regression tests

If you only implement runtime support and skip the prompt module, the model may never reliably use the feature.

## Legacy File

`data/prompts/system_prompt.txt` remains in the repo as a migration reference. It is not the default runtime prompt entrypoint anymore.
