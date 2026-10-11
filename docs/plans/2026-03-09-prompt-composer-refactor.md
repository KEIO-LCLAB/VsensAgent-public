# Prompt Composer Refactor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the single-file Python system prompt with a modular prompt registry/composer so implemented protocol features are explicitly represented in prompt modules and can be enabled consistently.

**Architecture:** Introduce a small prompt assembly layer in `VsensPython/core/prompting/` that loads core prompt sections plus feature modules declared in a manifest/registry. Update `VsensOpenAI` to consume the composed system prompt, then migrate the current monolithic prompt into core + feature files with immediate coverage for `control`, `clarification`, `proposal`, and `job`.

**Tech Stack:** Python 3, `unittest`, existing `VsensOpenAI` integration, plain text prompt assets

---

### Task 1: Add prompt composer tests before implementation

**Files:**
- Create: `VsensPython/tests/test_prompt_composer.py`
- Reference: `VsensPython/vsens_openai.py`
- Reference: `VsensPython/data/prompts/system_prompt.txt`

**Step 1: Write the failing test**

```python
import unittest

from core.prompting.composer import PromptComposer


class TestPromptComposer(unittest.TestCase):
    def test_compose_includes_core_and_enabled_features(self):
        composer = PromptComposer(project_root=".")

        prompt = composer.compose(
            enabled_features=["control", "clarification", "proposal"]
        )

        self.assertIn("You are Vsens+", prompt)
        self.assertIn("<clarification>", prompt)
        self.assertIn("<proposal>", prompt)
        self.assertIn("<control>", prompt)

    def test_compose_omits_disabled_feature_sections(self):
        composer = PromptComposer(project_root=".")

        prompt = composer.compose(enabled_features=["control"])

        self.assertIn("<control>", prompt)
        self.assertNotIn("<clarification>", prompt)
        self.assertNotIn("<proposal>", prompt)
```

**Step 2: Run test to verify it fails**

Run: `cd <repository>/VsensPython && python -m unittest tests.test_prompt_composer -v`

Expected: FAIL with `ModuleNotFoundError` for `core.prompting.composer`

**Step 3: Write minimal implementation**

Create placeholder implementations for:

- `VsensPython/core/prompting/__init__.py`
- `VsensPython/core/prompting/composer.py`
- `VsensPython/core/prompting/registry.py`

Minimal target shape:

```python
class PromptComposer:
    def __init__(self, project_root=None):
        ...

    def compose(self, enabled_features=None) -> str:
        ...
```

**Step 4: Run test to verify it passes**

Run: `cd <repository>/VsensPython && python -m unittest tests.test_prompt_composer -v`

Expected: PASS

**Step 5: Commit**

```bash
git add VsensPython/tests/test_prompt_composer.py VsensPython/core/prompting/__init__.py VsensPython/core/prompting/composer.py VsensPython/core/prompting/registry.py
git commit -m "test: add prompt composer coverage"
```

### Task 2: Add registry validation tests

**Files:**
- Modify: `VsensPython/tests/test_prompt_composer.py`
- Create: `VsensPython/data/prompts/manifests/features.json`
- Reference: `VsensPython/core/agent_core.py:351-370`
- Reference: `VsensPython/core/skills/control_parser.py:54-68`

**Step 1: Write the failing test**

Extend the test file with:

```python
from core.prompting.registry import load_feature_registry


class TestPromptRegistry(unittest.TestCase):
    def test_registry_contains_protocol_backed_features(self):
        registry = load_feature_registry(project_root=".")

        for feature_name in ("control", "clarification", "proposal", "job"):
            self.assertIn(feature_name, registry)

    def test_registry_declares_prompt_files(self):
        registry = load_feature_registry(project_root=".")

        self.assertTrue(registry["clarification"].prompt_files)
        self.assertTrue(registry["proposal"].prompt_files)
```

**Step 2: Run test to verify it fails**

Run: `cd <repository>/VsensPython && python -m unittest tests.test_prompt_composer -v`

Expected: FAIL because registry loader or manifest data is incomplete

**Step 3: Write minimal implementation**

Implement:

- `FeaturePrompt` metadata type in `VsensPython/core/prompting/registry.py`
- `load_feature_registry(...)`
- initial `VsensPython/data/prompts/manifests/features.json`

Manifest should include, at minimum:

```json
{
  "control": { "enabled_by_default": true, "prompt_files": ["features/control.txt"] },
  "clarification": { "enabled_by_default": true, "prompt_files": ["features/clarification.txt", "examples/clarification.txt"] },
  "proposal": { "enabled_by_default": true, "prompt_files": ["features/proposal.txt", "examples/proposal.txt"] },
  "job": { "enabled_by_default": true, "prompt_files": ["features/job.txt"] }
}
```

**Step 4: Run test to verify it passes**

Run: `cd <repository>/VsensPython && python -m unittest tests.test_prompt_composer -v`

Expected: PASS

**Step 5: Commit**

```bash
git add VsensPython/tests/test_prompt_composer.py VsensPython/core/prompting/registry.py VsensPython/data/prompts/manifests/features.json
git commit -m "feat: add prompt feature registry"
```

### Task 3: Migrate monolithic prompt into modular prompt assets

**Files:**
- Create: `VsensPython/data/prompts/core/identity.txt`
- Create: `VsensPython/data/prompts/core/behavior.txt`
- Create: `VsensPython/data/prompts/core/output_contract.txt`
- Create: `VsensPython/data/prompts/features/control.txt`
- Create: `VsensPython/data/prompts/features/clarification.txt`
- Create: `VsensPython/data/prompts/features/proposal.txt`
- Create: `VsensPython/data/prompts/features/job.txt`
- Create: `VsensPython/data/prompts/examples/clarification.txt`
- Create: `VsensPython/data/prompts/examples/proposal.txt`
- Reference: `VsensPython/data/prompts/system_prompt.txt`

**Step 1: Write the failing test**

Extend `VsensPython/tests/test_prompt_composer.py`:

```python
    def test_clarification_module_teaches_when_to_ask(self):
        composer = PromptComposer(project_root=".")
        prompt = composer.compose(enabled_features=["control", "clarification"])

        self.assertIn("Use <clarification>", prompt)
        self.assertIn("when the user intent is ambiguous", prompt)

    def test_proposal_module_teaches_option_generation(self):
        composer = PromptComposer(project_root=".")
        prompt = composer.compose(enabled_features=["control", "proposal"])

        self.assertIn("Use <proposal>", prompt)
        self.assertIn("\"options\"", prompt)
```

**Step 2: Run test to verify it fails**

Run: `cd <repository>/VsensPython && python -m unittest tests.test_prompt_composer -v`

Expected: FAIL because the prompt modules do not exist or do not contain the new guidance

**Step 3: Write minimal implementation**

Move content out of `system_prompt.txt` into modular files:

- `core/identity.txt`: agent identity, environment, background
- `core/behavior.txt`: response style, grounding rules, coordinate assumptions
- `core/output_contract.txt`: shared output contract and reserved tags
- `features/control.txt`: existing control actions and constraints
- `features/clarification.txt`: trigger rules, JSON shape, selection guidance
- `features/proposal.txt`: trigger rules, JSON shape, proposal option semantics
- `features/job.txt`: trigger rules for longer-running tasks and status expectations
- `examples/clarification.txt`: one or two compact examples
- `examples/proposal.txt`: one or two compact examples

Keep `system_prompt.txt` unchanged until Task 4 finishes, so migration can be diffed safely.

**Step 4: Run test to verify it passes**

Run: `cd <repository>/VsensPython && python -m unittest tests.test_prompt_composer -v`

Expected: PASS

**Step 5: Commit**

```bash
git add VsensPython/data/prompts/core VsensPython/data/prompts/features VsensPython/data/prompts/examples VsensPython/tests/test_prompt_composer.py
git commit -m "feat: split system prompt into modular assets"
```

### Task 4: Switch `VsensOpenAI` to the prompt composer

**Files:**
- Modify: `VsensPython/vsens_openai.py`
- Modify: `VsensPython/tests/test_prompt_composer.py`
- Reference: `VsensPython/data/prompts/system_prompt.txt`

**Step 1: Write the failing test**

Add:

```python
from vsens_openai import VsensOpenAI


class TestVsensOpenAIPromptLoading(unittest.TestCase):
    def test_default_system_prompt_is_composed(self):
        agent = VsensOpenAI.__new__(VsensOpenAI)
        agent_prompt = VsensOpenAI._load_system_prompt(agent, None)

        self.assertIn("You are Vsens+", agent_prompt)
        self.assertIn("<clarification>", agent_prompt)
        self.assertIn("<proposal>", agent_prompt)
```

If direct constructor setup is too heavy due to API key loading, refactor prompt-loading into a helper that is easy to test.

**Step 2: Run test to verify it fails**

Run: `cd <repository>/VsensPython && python -m unittest tests.test_prompt_composer -v`

Expected: FAIL because `VsensOpenAI` still reads `system_prompt.txt` directly

**Step 3: Write minimal implementation**

Update `VsensPython/vsens_openai.py` to:

- use `PromptComposer` when `prompt_path is None`
- retain `prompt_path` override for debugging/manual experiments
- centralize prompt loading so tests can verify the composed output without calling OpenAI

Target shape:

```python
if prompt_path is None:
    composer = PromptComposer(project_root=project_root)
    return composer.compose()
```

**Step 4: Run test to verify it passes**

Run: `cd <repository>/VsensPython && python -m unittest tests.test_prompt_composer -v`

Expected: PASS

**Step 5: Commit**

```bash
git add VsensPython/vsens_openai.py VsensPython/tests/test_prompt_composer.py
git commit -m "feat: load composed prompt by default"
```

### Task 5: Add prompt regression coverage for current protocol tests

**Files:**
- Modify: `VsensPython/tests/test_agent_core_protocol.py`
- Modify: `VsensPython/tests/test_protocol_messages.py`
- Modify: `VsensPython/tests/test_vsens_server_protocol.py`
- Test: `VsensPython/tests/test_prompt_composer.py`

**Step 1: Write the failing test**

Add one regression test in `VsensPython/tests/test_agent_core_protocol.py` that asserts the active system prompt includes both `clarification` and `proposal` instructions when the default agent wiring is used.

Example:

```python
    def test_default_prompt_stack_includes_structured_collaboration_features(self):
        from core.prompting.composer import PromptComposer

        prompt = PromptComposer(project_root=".").compose()

        self.assertIn("<clarification>", prompt)
        self.assertIn("<proposal>", prompt)
```

**Step 2: Run test to verify it fails**

Run: `cd <repository>/VsensPython && python -m unittest tests.test_agent_core_protocol tests.test_prompt_composer -v`

Expected: FAIL if any expected feature module is missing from the default composition

**Step 3: Write minimal implementation**

Adjust registry defaults or composer ordering so:

- `control`, `clarification`, `proposal`, and `job` are enabled by default
- examples are included in the final prompt in a stable order
- prompt output is deterministic for tests

**Step 4: Run test to verify it passes**

Run: `cd <repository>/VsensPython && python -m unittest tests.test_agent_core_protocol tests.test_prompt_composer tests.test_protocol_messages tests.test_protocol_user_turns tests.test_vsens_server_protocol tests.test_job_manager test_phase3 -v`

Expected: PASS for the full Python protocol suite

**Step 5: Commit**

```bash
git add VsensPython/tests/test_agent_core_protocol.py VsensPython/tests/test_prompt_composer.py VsensPython/core/prompting VsensPython/data/prompts VsensPython/vsens_openai.py
git commit -m "test: add prompt regression coverage"
```

### Task 6: Document prompt architecture and deprecate the monolith

**Files:**
- Modify: `VsensPython/docs/INTERACTION_WALKTHROUGH.md`
- Modify: `VsensPython/docs/RECONSTRUCT_PLAN.md`
- Modify: `docs/README.md`
- Modify: `VsensPython/data/prompts/system_prompt.txt`

**Step 1: Write the failing test**

No automated test required. Use documentation acceptance criteria:

- docs mention `PromptComposer`
- docs explain where to add new feature prompts
- legacy `system_prompt.txt` clearly marked as compatibility/deprecated reference or reduced to a generated stub if desired

**Step 2: Run verification to show docs are stale before update**

Run: `cd <repository> && rg -n "system_prompt.txt|PromptComposer|features.json" VsensPython/docs docs/README.md`

Expected: existing docs reference only the monolithic prompt path

**Step 3: Write minimal implementation**

Update docs to explain:

- prompt asset layout
- registry/composer flow
- how to add a new feature prompt when adding a new protocol capability

Then either:

- keep `system_prompt.txt` as a deprecated note pointing to modular files, or
- regenerate it as a compatibility snapshot with a header warning

Choose the lower-risk option that avoids breaking any manual workflows.

**Step 4: Run verification to confirm docs are updated**

Run: `cd <repository> && rg -n "PromptComposer|features.json|clarification|proposal" VsensPython/docs docs/README.md`

Expected: updated docs mention the new architecture

**Step 5: Commit**

```bash
git add VsensPython/docs/INTERACTION_WALKTHROUGH.md VsensPython/docs/RECONSTRUCT_PLAN.md docs/README.md VsensPython/data/prompts/system_prompt.txt
git commit -m "docs: describe modular prompt architecture"
```
