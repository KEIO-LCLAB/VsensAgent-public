# Sensor Recording UI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a monitor-panel recording control that starts/stops all virtual sensors, shows elapsed recording time, and exports recorded sensor CSV files.

**Architecture:** Keep recording orchestration and export in `VsensAgentSensorManager` so sensor lifecycle and persistence stay near sensor ownership. Keep the button/text UI binding in `MonitorManager`, which already owns the monitor panel. Use `SensorDataCenter` as the recording backend, with editor builds prompting for a folder and player builds exporting straight to the desktop.

**Tech Stack:** Unity C#, `SensorDataCenter`, `VirtualSensor`, `TMP_Text`, `Button`, editor-only `EditorUtility`

---

### Task 1: Add recording/export orchestration to the sensor manager

**Files:**
- Modify: `VsensAgent/Assets/VsensAgent/VirtualObject/Sensor/VsensAgentSensorManager.cs`

Implement:
- recording state
- start timestamp / elapsed time
- `StartSensorRecording()`
- `StopSensorRecordingAndExport()`
- editor folder prompt vs player desktop export
- per-sensor CSV export

### Task 2: Bind monitor UI to recording state

**Files:**
- Modify: `VsensAgent/Assets/VsensAgent/UI/Sensor/MonitorManager.cs`

Implement:
- serialized button/text refs
- button click toggles record/stop
- button image red while recording, white otherwise
- timer text visible only while recording
- timer text updates from manager elapsed time

### Task 3: Add focused tests

**Files:**
- Create: `VsensAgent/Assets/Tests/Editor/UI/SensorRecordingTests.cs`

Cover:
- manager starts/stops recording through `SensorDataCenter`
- button/timer UI reflects recording state
- export path resolution works for editor/player branches via overridable helpers
