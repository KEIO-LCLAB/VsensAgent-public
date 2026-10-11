# Communication Overview

The project no longer has a single stable legacy WebSocket spec that fully describes the runtime.

Current communication behavior is split across:

- Python protocol builders in [messages.py](../../VsensPython/core/protocol/messages.py)
- Python user-turn helpers in [user_turns.py](../../VsensPython/core/protocol/user_turns.py)
- Python server routing in [vsens_server.py](../../VsensPython/vsens_server.py)
- Unity request/response DTOs in [Messages.cs](../../VsensAgent/Assets/VsensAgent/Network/Protocol/Messages.cs) and [Requests.cs](../../VsensAgent/Assets/VsensAgent/Network/Protocol/Requests.cs)
- Runtime handling in [WsClient.cs](../../VsensAgent/Assets/VsensAgent/Network/WsClient.cs)

## Current Message Families

- `conversation.*`
  - ordinary user/agent exchange
- `clarification.*`
  - agent asks the user to disambiguate a target or decision
- `proposal.*`
  - agent presents candidate plans before execution
- `job.*`
  - long-running work lifecycle
- Scene API methods
  - `scene.query_*`
  - `scene.validate_actions`
  - `scene.execute_actions`

## Where To Look

- For current behavior, prefer code and tests over older narrative specs.
- For scene runtime contracts, use [Scene API README](../scene_api/README.md).
- For practical tool usage docs, use [Guides](../guides/README.md).
- For historical protocol docs, use [Legacy Archive](../legacy/README.md).
