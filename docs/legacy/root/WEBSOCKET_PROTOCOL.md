# WebSocket Communication Protocol

> Historical document. This file describes the older single-path protocol and is preserved for reference only.
>
> For the current runtime, start from:
> - [<repository>/docs/communication/README.md](../../communication/README.md)
> - [<repository>/docs/architecture/OVERVIEW.md](../../architecture/OVERVIEW.md)

**Last Updated**: February 27, 2026

## 📋 Table of Contents
- [Overview](#overview)
- [Connection](#connection)
- [Message Flow](#message-flow)
- [Request Types](#request-types)
- [Response Types](#response-types)
- [Error Handling](#error-handling)

---

## Overview

VsensAgent uses **WebSocket** for real-time bidirectional communication between the Unity client and Python backend. The protocol uses JSON for message serialization.

**Connection Details:**
- **Protocol**: WebSocket (ws://)
- **Host**: localhost
- **Port**: 8765
- **URL**: `ws://localhost:8765`
- **Format**: JSON

---

## Connection

### Unity Client (C#)

```csharp
using NativeWebSocket;

public class WsClient : MonoBehaviour
{
    private static WebSocket websocket;
    private const string serverUrl = "ws://localhost:8765";
    
    public static async void Connect()
    {
        websocket = new WebSocket(serverUrl);
        
        websocket.OnOpen += () =>
        {
            Debug.Log("[WsClient] Connected to server");
            OnConnected?.Invoke();
        };
        
        websocket.OnMessage += (bytes) =>
        {
            string message = System.Text.Encoding.UTF8.GetString(bytes);
            HandleMessage(message);
        };
        
        websocket.OnClose += (code) =>
        {
            Debug.Log($"[WsClient] Disconnected: {code}");
            OnDisconnected?.Invoke();
        };
        
        websocket.OnError += (error) =>
        {
            Debug.LogError($"[WsClient] Error: {error}");
        };
        
        await websocket.Connect();
    }
}
```

### Python Server

```python
import asyncio
import websockets
import json

class VsensWebSocketServer:
    async def handler(self, websocket):
        async for message in websocket:
            response = await self.process_message(message)
            await websocket.send(json.dumps(response))
    
    async def start(self):
        async with websockets.serve(self.handler, "localhost", 8765):
            await asyncio.Future()  # Run forever
```

---

## Message Flow

### 1. Voice Interaction Flow

```
Unity                                  Python
  │                                      │
  │──── TranscribeRequest ────────────▶ │
  │     {                                │
  │       type: "transcribe_and_reply"  │
  │       audio_path: "path/to.wav"     │
  │       scene_snapshot: "{...}"       │
  │     }                                │
  │                                      │
  │                                      ├─ Whisper STT
  │                                      ├─ GPT-4.1 Conversation
  │                                      └─ TTS Synthesis
  │                                      │
  │◀──── AgentReplyMessage ───────────┤
  │     {                                │
  │       type: "agent_ready"           │
  │       status: "success"             │
  │       transcription: "user said..." │
  │       reply: "agent response"       │
  │       audio_path: "/path/reply.mp3" │
  │       control: { actions: [...] }   │
  │     }                                │
  │                                      │
  └─ Play TTS Audio                      │
  └─ Execute Control Actions             │
```

### 2. Text Chat Flow

```
Unity                                  Python
  │                                      │
  │──── TextChatRequest ───────────────▶│
  │     {                                │
  │       type: "text_chat"             │
  │       message: "user typed..."      │
  │       scene_snapshot: "{...}"       │
  │       request_audio: false          │
  │     }                                │
  │                                      │
  │                                      └─ GPT-4.1 Conversation
  │                                      │
  │◀──── AgentReplyMessage ───────────┤
  │     {                                │
  │       type: "agent_ready"           │
  │       status: "success"             │
  │       transcription: null           │
  │       reply: "agent response"       │
  │       audio_path: null              │
  │       control: { actions: [...] }   │
  │     }                                │
  │                                      │
  └─ Display Text                        │
  └─ Execute Control Actions             │
```

### 3. Reset Flow

```
Unity                                  Python
  │                                      │
  │──── ResetRequest ──────────────────▶│
  │     {                                │
  │       type: "reset"                 │
  │     }                                │
  │                                      │
  │                                      └─ Clear conversation history
  │                                      │
  │◀──── ResetAck ─────────────────────┤
  │     {                                │
  │       type: "reset_ack"             │
  │       status: "conversation reset"  │
  │     }                                │
```

---

## Request Types

### 1. TranscribeRequest

**Purpose**: Send recorded audio for transcription and agent response

**C# Definition:**
```csharp
[Serializable]
public class TranscribeRequest
{
    public string type = "transcribe_and_reply";
    public string audio_path;
    public string scene_snapshot;
}
```

**JSON Example:**
```json
{
  "type": "transcribe_and_reply",
  "audio_path": "<local-path>",
  "scene_snapshot": "{\"Window_A\":{\"position\":[3.467,1.895,7.5],\"state\":\"closed\"}}"
}
```

**Fields:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | ✅ | Must be "transcribe_and_reply" |
| `audio_path` | string | ✅ | Absolute path to .wav file |
| `scene_snapshot` | string | ⚠️ | JSON string of scene state (can be empty) |

**Usage (Unity):**
```csharp
WsClient.SendTranscribeRequest(audioPath);
```

---

### 2. TextChatRequest

**Purpose**: Send text message for agent response (no voice)

**C# Definition:**
```csharp
[Serializable]
public class TextChatRequest
{
    public string type = "text_chat";
    public string message;
    public string scene_snapshot;
    public bool request_audio = false;
}
```

**JSON Example:**
```json
{
  "type": "text_chat",
  "message": "Where is the coffee maker?",
  "scene_snapshot": "{\"CoffeeMaker\":{\"position\":[2.5,1.2,4.0]}}",
  "request_audio": false
}
```

**Fields:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | ✅ | Must be "text_chat" |
| `message` | string | ✅ | User's text message |
| `scene_snapshot` | string | ⚠️ | JSON string of scene state |
| `request_audio` | bool | ❌ | Whether to generate TTS (default: false) |

**Usage (Unity):**
```csharp
WsClient.SendTextChatRequest(message, requestAudio: false);
```

---

### 3. ResetRequest

**Purpose**: Clear conversation history and start fresh

**C# Definition:**
```csharp
[Serializable]
public class ResetRequest
{
    public string type = "reset";
}
```

**JSON Example:**
```json
{
  "type": "reset"
}
```

**Fields:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | ✅ | Must be "reset" |

**Usage (Unity):**
```csharp
WsClient.SendResetRequest();
```

---

## Response Types

### 1. AgentReplyMessage

**Purpose**: Agent's response with text, audio, and control commands

**C# Definition:**
```csharp
[Serializable]
public class AgentReplyMessage
{
    public string type;           // "agent_ready"
    public string status;         // "success" or error status
    public string transcription;  // User's speech (from Whisper)
    public string reply;          // Agent's text response
    public string audio_path;     // Path to TTS audio file
    
    [JsonProperty("control")]
    public ControlActions control;
}

[Serializable]
public class ControlActions
{
    [JsonProperty("actions")]
    public ControlObject[] actions;
}
```

**JSON Example (Voice Interaction):**
```json
{
  "type": "agent_ready",
  "status": "success",
  "transcription": "Open the window",
  "reply": "Opening Window_A now.",
  "audio_path": "<local-path>",
  "control": {
    "actions": [
      {
        "target": "Window_A",
        "action": "set_state",
        "parameters": {
          "state": "open"
        }
      }
    ]
  }
}
```

**JSON Example (Text Interaction):**
```json
{
  "type": "agent_ready",
  "status": "success",
  "transcription": null,
  "reply": "The coffee maker is located at position (2.5, 1.2, 4.0).",
  "audio_path": null,
  "control": {
    "actions": [
      {
        "target": "CoffeeMaker",
        "action": "highlight",
        "parameters": {
          "color": "#FFD700"
        }
      }
    ]
  }
}
```

**Fields:**
| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| `type` | string | ❌ | "agent_ready" for success |
| `status` | string | ❌ | "success" or error description |
| `transcription` | string | ✅ | User's transcribed speech (null for text chat) |
| `reply` | string | ❌ | Agent's text response |
| `audio_path` | string | ✅ | Absolute path to TTS audio (null for text chat) |
| `control` | ControlActions | ✅ | Control commands (empty if no actions) |

---

### 2. Error Response

**Purpose**: Indicate processing errors

**JSON Example:**
```json
{
  "type": "error",
  "message": "Audio file not found: /path/to/file.wav",
  "details": "Traceback (most recent call last):\n  File ..."
}
```

**Fields:**
| Field | Type | Description |
|-------|------|-------------|
| `type` | string | "error" |
| `message` | string | Human-readable error message |
| `details` | string | Stack trace or detailed error info |

---

### 3. ResetAck

**Purpose**: Confirm conversation reset

**JSON Example:**
```json
{
  "type": "reset_ack",
  "status": "conversation reset"
}
```

---

## Error Handling

### Unity Side (C#)

```csharp
private void OnAgentReplyReceived(AgentReplyMessage response)
{
    if (response.status != "success")
    {
        AddSystemMessage($"❌ Agent reply failed: {response.status}");
        return;
    }
    
    // Process successful response
    if (!string.IsNullOrEmpty(response.reply))
    {
        AddAgentMessage(response.reply, response.audio_path);
    }
}
```

### Python Side

```python
async def process_message(self, raw_message: str) -> dict:
    try:
        msg = json.loads(raw_message)
    except json.JSONDecodeError:
        return {"error": "Invalid JSON message."}
    
    msg_type = msg.get("type")
    handler = self.handlers.get(msg_type)
    
    if handler:
        return await handler(msg)
    else:
        return {"error": f"Unsupported message type: {msg_type}"}
```

### Common Error Cases

| Error | Cause | Response |
|-------|-------|----------|
| Invalid JSON | Malformed message | `{"error": "Invalid JSON message."}` |
| Unknown type | Unsupported message type | `{"error": "Unsupported message type: X"}` |
| File not found | Audio file doesn't exist | `{"type": "error", "message": "Audio file not found"}` |
| API error | OpenAI API failure | `{"type": "error", "message": "API call failed", "details": "..."}` |

---

## Scene Snapshot Format

The `scene_snapshot` field contains a JSON string representing the current state of the virtual environment.

**Example Structure:**
```json
{
  "Window_A": {
    "position": [3.467, 1.895, 7.5],
    "size": [0.173, 1.184, 1.941],
    "rotation": [0, 180, 0],
    "properties": ["with_state"],
    "state": "closed",
    "availableStates": ["open", "closed"]
  },
  "CoffeeMaker": {
    "position": [2.609, 1.433, 4.233],
    "size": [1, 0.5, 0.8],
    "rotation": [0, 0, 0],
    "properties": ["movable"]
  },
  "OPTICAL-01": {
    "position": [2.609, 1.433, 4.233],
    "size": [1, 0.346, 1],
    "rotation": [0, 0, 0],
    "properties": ["sensor", "movable"],
    "attachTo": "CoffeeMaker",
    "sensor": {
      "sensorType": "OPTICAL",
      "showVisualization": false,
      "showDataGraph": false,
      "value": 0
    }
  },
  "DISTANCE-01": {
    "position": [2.609, 1.693, 4.069],
    "size": [1, 0.436, 0.643],
    "rotation": [0, 0, 0],
    "properties": ["sensor", "movable"],
    "attachTo": "CoffeeMaker",
    "sensor": {
      "sensorType": "DISTANCE",
      "showVisualization": false,
      "showDataGraph": false,
      "validDistance": 3,
      "value": 0.086,
      "lookRay": [0, 0, 1],
      "startPoint": [2.609, 1.683, 4.073]
    }
  }
}
```

**How Unity Generates It:**
```csharp
// Collect all scene objects
Dictionary<string, object> sceneData = new Dictionary<string, object>();

foreach (var obj in FindObjectsOfType<VirtualObject>())
{
    sceneData[obj.name] = obj.SerializeState();
}

string sceneSnapshot = JsonConvert.SerializeObject(sceneData);
```

---

## Performance Considerations

### Message Size
- Scene snapshots can be large (10KB - 100KB+)
- Consider compression for large scenes
- Limit snapshot frequency

### Latency
| Operation | Typical Latency |
|-----------|----------------|
| WebSocket send | <1ms |
| Network round-trip | 1-5ms (local) |
| Whisper transcription | 500-2000ms |
| GPT-4.1 response | 1000-5000ms |
| TTS synthesis | 500-2000ms |
| **Total (voice)** | **2-9 seconds** |
| **Total (text)** | **1-5 seconds** |

### Best Practices
1. **Minimize snapshot size** - Only include relevant objects
2. **Cache responses** - Don't re-send unchanged data
3. **Use async/await** - Don't block the main thread
4. **Handle timeouts** - Set reasonable timeout values
5. **Batch updates** - Group multiple control actions

---

## Related Documentation

- [Architecture Overview](../../architecture/OVERVIEW.md)
- [Python Agent System](../../architecture/PYTHON_AGENT.md)
- [Unity Namespaces](../../architecture/UNITY_NAMESPACES.md)
- [Data Structures](DATA_STRUCTURES.md)
