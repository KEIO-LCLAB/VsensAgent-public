# Plans

This directory contains design documents and implementation plans that explain the intended direction of the project or capture how a refactor was staged.

Plans are not the same thing as the current runtime reference:

- use [docs/architecture](../architecture) for current architecture state
- use [docs/scene_api](../scene_api) for scene contracts
- use [docs/legacy](../legacy/README.md) for historical material

## Current Reading Order

1. [2026-03-07-collaborative-virtual-sensing-design.md](2026-03-07-collaborative-virtual-sensing-design.md)
   - collaboration workflow, protocol taxonomy, and staged roadmap
2. [2026-03-07-protocol-convergence-mvp.md](2026-03-07-protocol-convergence-mvp.md)
   - the first implementation slice for protocol/runtime convergence
3. [2026-03-09-prompt-composer-refactor.md](2026-03-09-prompt-composer-refactor.md)
   - modular prompt architecture refactor and migration notes
4. [2026-03-12-query-first-loop-design.md](2026-03-12-query-first-loop-design.md)
   - approved design for a minimal query-first orchestration loop
5. [2026-03-12-query-first-loop-mvp.md](2026-03-12-query-first-loop-mvp.md)
   - implementation checklist for the query-first runtime slice
   - current status: the MVP runtime loop has landed; use current architecture docs for the latest behavior
6. [2026-03-24-agent-visual-review-design.md](2026-03-24-agent-visual-review-design.md)
   - approved design for replacing Unity-side screenshot judgment with a Python-led multimodal review pass
7. [2026-03-24-agent-visual-review-loop.md](2026-03-24-agent-visual-review-loop.md)
   - implementation checklist for Python-led screenshot review and retry orchestration

## Notes

- A plan may mention file paths or runtime assumptions that were true when it was written.
- If a plan conflicts with the current runtime docs, prefer the current runtime docs.
- The older 2026-03-23 avatar visual retry plans were archived because they describe a Unity-side
  screenshot-scoring pipeline that is no longer the active runtime path.
