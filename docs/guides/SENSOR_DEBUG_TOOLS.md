# Sensor Debug Tools 使用指南

> Current guide. This document is still relevant because it maps to the active Unity Editor debug tool.

## 概述

**Sensor Debug Tools** 是一个Unity Editor调试工具，用于在场景中快速添加和测试VirtualSensor，方便开发者测试SensorDataCenter和SensorMonitorPanel的功能。

## 打开工具

在Unity编辑器菜单栏中选择：
```
VsensAgent → Debug Tools → Sensor Debug Tools
```

## 功能说明

### 1. 传感器类型选择

支持三种传感器类型：
- **IMU Sensor** - 惯性测量单元传感器（加速度、方向、位置）
- **Light Sensor** - 光照传感器（照度测量）
- **Distance Sensor** - 距离传感器（距离测量）

可选：为每种传感器类型指定预制体（Prefab），如果不指定则动态创建组件。

### 2. 基本选项

- **生成位置** - 传感器在场景中的初始位置（Vector3）
- **自动注册到SensorDataCenter** - 创建后自动注册到SensorDataCenter进行数据采集
- **激活传感器** - 创建后传感器是否处于激活状态

### 3. 高级选项

- **批量创建数量** - 一次性创建多个传感器（1-20个）
- **间距** - 批量创建时传感器之间的间距（沿X轴）

### 4. 操作按钮

#### 🆕 创建新传感器GameObject
- 在场景中创建新的GameObject并添加选定类型的传感器组件
- 支持批量创建

#### ➕ 在选中对象上添加传感器组件
- 在当前选中的GameObject上添加传感器组件
- 适用于在已有对象上添加传感器功能

#### 📦 从预制体实例化
- 使用指定的预制体实例化传感器
- 需要先在对应的预制体字段中指定预制体

### 5. 快速测试功能

#### 🚀 创建测试场景
- 一键创建包含3种传感器（IMU、Light、Distance）各1个的测试场景
- 传感器沿X轴排列，间距1.5米

#### 🔍 查找场景中所有传感器
- 查找并在控制台列出场景中所有的VirtualSensor
- 显示传感器类型、名称、激活状态和位置
- 统计各类型传感器数量

#### 🗑️ 删除场景中所有传感器
- 删除场景中所有的VirtualSensor GameObject
- 会弹出确认对话框

### 6. 场景信息

显示当前场景的传感器相关信息：
- SensorDataCenter是否存在及其采样率
- 场景中传感器总数量

## 使用场景

### 场景1：快速测试SensorMonitorPanel

1. 打开 **Sensor Debug Tools**
2. 点击 **"🚀 创建测试场景"** 按钮
3. 场景中会自动创建3种传感器各1个
4. 打开SensorMonitorPanel查看传感器显示是否正常

### 场景2：测试特定类型传感器

1. 选择要测试的传感器类型（如IMU）
2. 设置生成位置和数量
3. 点击 **"🆕 创建新传感器GameObject"**
4. 观察传感器行为

### 场景3：批量创建传感器测试性能

1. 选择传感器类型
2. 在高级选项中设置批量创建数量（如10个）
3. 设置间距（如0.5米）
4. 点击 **"🆕 创建新传感器GameObject"**
5. 测试SensorDataCenter处理多个传感器的性能

### 场景4：在特定对象上添加传感器

1. 在场景中选择一个GameObject（如角色身体部位）
2. 选择要添加的传感器类型
3. 点击 **"➕ 在选中对象上添加传感器组件"**
4. 传感器会跟随该对象移动

### 场景5：使用预制体创建传感器

1. 准备好传感器预制体
2. 在对应的预制体字段中拖入预制体
3. 点击 **"📦 从预制体实例化"**
4. 创建的传感器会保留预制体的所有配置

## 调试技巧

### 查看传感器状态

使用 **"🔍 查找场景中所有传感器"** 功能，在控制台查看：
```
=== 场景中共找到 5 个传感器 ===
  - VirtualIMUSensor: TestSensor_IMU (Active: True, Position: (0.0, 0.0, 0.0))
  - VirtualLightSensor: TestSensor_Light (Active: True, Position: (1.5, 0.0, 0.0))
  - VirtualDistanceSensor: TestSensor_Distance (Active: True, Position: (3.0, 0.0, 0.0))
  ...
统计: IMU=2, Light=2, Distance=1
```

### 清理测试场景

测试完成后，使用 **"🗑️ 删除场景中所有传感器"** 一键清理所有测试传感器。

### 验证SensorDataCenter

工具会自动检测场景中是否存在SensorDataCenter：
- ✅ 绿色提示：SensorDataCenter已找到并显示采样率
- ⚠️ 黄色警告：未找到SensorDataCenter

## 注意事项

1. **自动注册** - 如果勾选了"自动注册到SensorDataCenter"，传感器会在Start时自动注册。但如果是运行时创建，需要手动调用注册方法。

2. **预制体** - 使用预制体实例化时，请确保预制体已经正确配置了所有必要的组件和可视化对象。

3. **批量创建** - 批量创建大量传感器时，注意性能影响。建议先小批量测试。

4. **Undo支持** - 所有创建和删除操作都支持Undo（Ctrl+Z），可以安全地撤销操作。

## 与其他工具的配合

- **SensorMonitorPanel** - 创建传感器后，可在SensorMonitorPanel中实时查看传感器数据
- **SensorDataCenter** - 自动注册功能可直接将传感器加入数据采集系统
- **VirtualSensorEditor** - 创建后可在Inspector中使用VirtualSensorEditor进行详细配置

## 开发者信息

- **文件位置**: `VsensAgent/Assets/VsensAgent/Editor/SensorDebugTools.cs`
- **命名空间**: `VsensAgent.Editor`
- **依赖**: Sensor命名空间（VirtualSensor及其子类）

## 更新日志

### v1.0 (2026-02-27)
- 初始版本
- 支持3种传感器类型的创建
- 批量创建功能
- 快速测试场景创建
- 传感器查找和管理功能
