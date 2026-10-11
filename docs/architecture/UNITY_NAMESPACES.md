# Unity Namespace Architecture

**Last Updated**: February 27, 2026

## 📋 Table of Contents
- [Overview](#overview)
- [Namespace Hierarchy](#namespace-hierarchy)
- [Core Namespaces](#core-namespaces)
- [Component Details](#component-details)
- [Service Locator Pattern](#service-locator-pattern)

---

## Overview

The Unity codebase is organized into several namespaces that separate concerns and provide clear boundaries between different system components. This document describes the structure and purpose of each namespace.

---

## Namespace Hierarchy

```
VsensAgent/
├── VsensAgent                    # Root namespace
│   ├── Audio                     # Audio recording and playback
│   ├── Network                   # WebSocket client and protocol
│   │   └── Protocol              # Message/request data structures
│   ├── Core                      # Core systems and utilities
│   ├── UI                        # User interface components
│   ├── Data                      # Data models and structures
│   ├── Agent                     # Agent controllers
│   └── Editor                    # Unity editor tools
```

---

## Core Namespaces

### 1. `VsensAgent` (Root)
**Purpose**: Root namespace for standalone components

**Key Classes:**
```csharp
namespace VsensAgent
{
    class UserMainCameraControl     // Camera control for user
    class InputController            // Input management
    class DoorObject                 // State-based objects
    class SensorDebugTest            // Debug utilities
}
```

**Responsibilities:**
- Camera control and movement
- Input system management
- Virtual object behaviors
- Debug and testing utilities

---

### 2. `VsensAgent.Audio`
**Purpose**: Audio recording and playback systems

**Key Classes:**
```csharp
namespace VsensAgent.Audio
{
    class AudioRecorder
    {
        // Recording configuration
        string micDevice
        int maxDuration = 10
        int sampleRate = 16000
        
        // Recording control
        void StartRecording()
        void StopRecording()
        void SaveWAV(string filepath)
        
        // Input state management
        void EnableInput()
        void DisableInput()
    }
}
```

**Features:**
- Microphone recording
- WAV file export
- Input enable/disable (prevents conflicts with chat UI)
- Visual feedback integration

**Service Registration:**
```csharp
void Awake()
{
    ServiceLocator.Register<AudioRecorder>(this);
}
```

---

### 3. `VsensAgent.Network`
**Purpose**: WebSocket communication with Python backend

**Key Classes:**
```csharp
namespace VsensAgent.Network
{
    class WsClient
    {
        // Connection management
        static async void Connect()
        static async void Disconnect()
        
        // Message sending
        static void SendTranscribeRequest(string audioPath)
        static void SendTextChatRequest(string message, bool requestAudio)
        static void SendResetRequest()
        
        // Events
        static event Action<AgentReplyMessage> OnAgentReply
        static event Action OnConnected
        static event Action OnDisconnected
    }
}
```

**Features:**
- WebSocket client (ws://localhost:8765)
- Async message sending
- Event-driven message receiving
- Automatic reconnection handling
- Scene snapshot serialization

---

### 4. `VsensAgent.Network.Protocol`
**Purpose**: Data structures for network communication

**Message Types:**
```csharp
namespace VsensAgent.Network.Protocol
{
    // Incoming messages from Python
    class AgentReplyMessage
    {
        string type
        string status
        string transcription          // User's transcribed speech
        string reply                  // Agent's text response
        string audio_path             // Path to TTS audio file
        ControlActions control        // Structured control commands
    }
    
    class ControlActions
    {
        ControlObject[] actions
    }
}
```

**Request Types:**
```csharp
namespace VsensAgent.Network.Protocol
{
    // Outgoing requests to Python
    class TranscribeRequest
    {
        string type = "transcribe_and_reply"
        string audio_path
        string scene_snapshot
    }
    
    class TextChatRequest
    {
        string type = "text_chat"
        string message
        string scene_snapshot
        bool request_audio = false
    }
    
    class ResetRequest
    {
        string type = "reset"
    }
}
```

**Control Structures:**
```csharp
namespace VsensAgent.Network.Protocol
{
    class ControlObject
    {
        string target                 // Object name
        string action                 // Action type
        Dictionary<string, object> parameters
    }
    
    class AgentBehavior
    {
        string behaviorType           // "move_to", "look_at", etc.
        Dictionary<string, object> parameters
    }
}
```

---

### 5. `VsensAgent.Core`
**Purpose**: Core systems and utilities

**Key Classes:**
```csharp
namespace VsensAgent.Core
{
    class ServiceLocator
    {
        static void Register<T>(T service)
        static T Get<T>()
        static bool TryGet<T>(out T service)
        static void Clear()
    }
    
    class Constants
    {
        static class Audio
        {
            const int MAX_RECORDING_DURATION = 10
            const int DEFAULT_SAMPLE_RATE = 16000
        }
        
        static class Network
        {
            const string WS_SERVER_URL = "ws://localhost:8765"
        }
        
        static class UI
        {
            const int MAX_CHAT_HISTORY = 100
        }
        
        static class InputKeys
        {
            const KeyCode VOICE_RECORD = KeyCode.R
            const KeyCode UNFOCUS = KeyCode.Escape
        }
    }
}
```

**Service Locator Pattern:**
- Centralized dependency management
- Type-safe service registration/retrieval
- Reduces hard dependencies between components

**Usage Example:**
```csharp
// Registration
ServiceLocator.Register<AudioRecorder>(this);

// Retrieval
var audioRecorder = ServiceLocator.Get<AudioRecorder>();

// Safe retrieval
if (ServiceLocator.TryGet<ChatUIManager>(out var chatUI))
{
    chatUI.AddMessage("Hello");
}
```

---

### 6. `VsensAgent.Agent`
**Purpose**: Agent behavior and voice control

**Key Classes:**
```csharp
namespace VsensAgent.Agent
{
    class AgentVoiceController
    {
        AudioSource audioSource
        
        // Voice playback
        void PlayTTSFromPath(string path)
        IEnumerator LoadAndPlay(string path)
        
        // Event handling
        void OnAgentReplyReceived(AgentReplyMessage reply)
    }
    
    class AgentBehaviorController
    {
        // Control execution
        void ExecuteControl(ControlActions control)
        void ExecuteAction(ControlObject action)
        
        // Action handlers
        void SetObjectState(string target, parameters)
        void SetObjectTransform(string target, parameters)
        void HighlightObject(string target, parameters)
        void SetSensor(string target, parameters)
    }
}
```

**Features:**
- TTS audio playback via UnityWebRequest
- Control command parsing and execution
- Object state management
- Sensor placement and configuration

---

### 7. `VsensAgent.UI`
**Purpose**: User interface components

**Key Classes:**
```csharp
namespace VsensAgent.UI
{
    class ChatUIManager
    {
        // UI components
        GameObject chatWindow
        ScrollRect messageScrollRect
        TMP_InputField textInputField
        Button sendButton
        GameObject voiceInputIndicator
        
        // Message management
        void AddUserMessage(string content)
        void AddAgentMessage(string content, string audioPath)
        void AddSystemMessage(string content)
        
        // Voice recording UI
        void ShowVoiceRecording(bool show)
        
        // Input focus management
        void FocusInput()
        void UnfocusInput()
        
        // Events
        static event Action<string> OnUserMessageSent
        static event Action<ChatMessage> OnMessageAdded
        static event Action<bool> OnInputFocusChanged
    }
    
    class SensorMonitorManager
    {
        // Sensor UI management
        void RegisterSensor(SensorController sensor)
        void UnregisterSensor(SensorController sensor)
        void UpdateSensorUI(string sensorId, sensorData)
    }
    
    class SensorUIItem
    {
        // Individual sensor display
        TextMeshProUGUI sensorNameText
        TextMeshProUGUI sensorValueText
        Toggle visualizationToggle
        Toggle graphToggle
    }
}
```

**Features:**
- Chat message display and scrolling
- Voice recording indicator
- Sensor monitoring dashboard
- Input focus management (prevents camera movement while typing)

---

### 8. `VsensAgent.Data`
**Purpose**: Data models and structures

**Key Classes:**
```csharp
namespace VsensAgent.Data
{
    class ChatMessage
    {
        enum MessageType { User, Agent, System }
        
        string id
        string content
        MessageType type
        string audioPath              // For agent messages with TTS
        DateTime timestamp
        
        bool HasAudio()
    }
}
```

---

### 9. `VsensAgent.Editor`
**Purpose**: Unity editor extensions and tools

**Key Classes:**
```csharp
namespace VsensAgent.Editor
{
    class SensorDebugTools
    {
        // Editor window for sensor debugging
        [MenuItem("VsensAgent/Sensor Debug Tools")]
        static void ShowWindow()
        
        void OnGUI()                  // Editor UI
    }
    
    class UIGenerator
    {
        // Generate UI prefabs from templates
        [MenuItem("VsensAgent/Generate UI")]
        static void GenerateUI()
    }
}
```

---

## Service Locator Pattern

### Architecture

The Service Locator pattern is used for dependency injection:

```csharp
// Registration (in Awake or Start)
public class AudioRecorder : MonoBehaviour
{
    void Awake()
    {
        ServiceLocator.Register<AudioRecorder>(this);
    }
}

// Consumption (in OnEnable or when needed)
public class ChatUIManager : MonoBehaviour
{
    void OnEnable()
    {
        audioRecorder = ServiceLocator.Get<AudioRecorder>();
    }
}
```

### Benefits
1. **Decoupling** - Components don't need direct references
2. **Testability** - Easy to mock services for testing
3. **Flexibility** - Services can be swapped at runtime
4. **Centralized** - Single source of truth for dependencies

### Execution Order

Unity execution order matters for service registration:

```
Awake()     → Register services here
OnEnable()  → Consume services here
Start()     → Services already available
```

**Example:**
```csharp
// AudioRecorder.cs
void Awake()
{
    ServiceLocator.Register<AudioRecorder>(this);  // ✅ Early registration
}

// ChatUIManager.cs
void OnEnable()
{
    var recorder = ServiceLocator.Get<AudioRecorder>();  // ✅ Will find it
}
```

---

## Component Dependencies

### Dependency Graph

```
ChatUIManager
    ├─ depends on → AudioRecorder (for voice input)
    ├─ depends on → WsClient (for sending messages)
    └─ depends on → InputController (for focus management)

AudioRecorder
    └─ depends on → ChatUIManager (for visual feedback)

AgentVoiceController
    └─ depends on → WsClient (for receiving audio paths)

AgentBehaviorController
    └─ depends on → WsClient (for receiving control commands)

WsClient
    └─ depends on → nothing (standalone)
```

---

## Event System

### Event Declaration (Static Events)
```csharp
public static event Action<AgentReplyMessage> OnAgentReply;
public static event Action<string> OnUserMessageSent;
public static event Action<bool> OnInputFocusChanged;
```

### Event Subscription
```csharp
void OnEnable()
{
    WsClient.OnAgentReply += OnAgentReplyReceived;
}

void OnDisable()
{
    WsClient.OnAgentReply -= OnAgentReplyReceived;
}
```

### Event Invocation
```csharp
OnAgentReply?.Invoke(reply);
```

---

## Best Practices

### 1. Namespace Organization
✅ **DO:**
- Use namespaces for all classes
- Group related classes in the same namespace
- Use nested namespaces for sub-systems

❌ **DON'T:**
- Leave classes without namespaces
- Mix unrelated classes in the same namespace

### 2. Service Registration
✅ **DO:**
- Register in `Awake()`
- Retrieve in `OnEnable()` or later
- Use `TryGet()` for optional services

❌ **DON'T:**
- Register in `Start()` (too late)
- Retrieve in `Awake()` (might not exist yet)

### 3. Event Handling
✅ **DO:**
- Subscribe in `OnEnable()`
- Unsubscribe in `OnDisable()`
- Use null-conditional operator (`?.`)

❌ **DON'T:**
- Forget to unsubscribe (memory leaks)
- Subscribe multiple times

---

## Related Documentation

- [Architecture Overview](OVERVIEW.md)
- [Python Agent System](PYTHON_AGENT.md)
- [Communication Overview](../communication/README.md)
- [Legacy Archive](../legacy/README.md)
