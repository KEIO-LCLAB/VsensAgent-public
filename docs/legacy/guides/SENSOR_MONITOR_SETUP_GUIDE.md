# Sensor Monitor UI 创建步骤指南

> Historical guide. This is a manual UI setup walkthrough from an earlier stage of the project and should not be treated as the main architecture or UI reference.

## 📋 准备工作
已创建的脚本：
- ✅ `SensorMonitorManager.cs` - 传感器监控管理器
- ✅ `SensorUIItem.cs` - 传感器UI项组件

## 🎨 Unity Editor 操作步骤

### 第一步：创建主Panel（右侧布局）

1. **打开场景**
   - 打开 `Assets/Scenes/VsensAgent/Room Test.unity`

2. **在Hierarchy中找到MainCanvas**
   - 展开 `MainCanvas`（应该已经有 ChatWindow 和 ControlButtonGroup）

3. **创建SensorMonitorPanel**
   - 右键点击 `MainCanvas` → UI → Panel
   - 重命名为 `SensorMonitorPanel`

4. **设置SensorMonitorPanel的RectTransform**
   - 选中 `SensorMonitorPanel`
   - 在Inspector中设置：
     ```
     Anchor Presets: 点击右上角的锚点图标
     - 按住 Alt+Shift，点击右侧中间的锚点预设
     
     或者手动设置：
     Anchor Min: X=0.6, Y=0.1
     Anchor Max: X=0.98, Y=0.9
     
     Pivot: X=0.5, Y=0.5
     
     Anchored Position: X=0, Y=0
     Left: 0, Right: 0, Top: 0, Bottom: 0
     ```

5. **设置Panel的背景**
   - 在 `SensorMonitorPanel` 的 Image 组件中：
     - Color: 设置为半透明黑色 (R:0, G:0, B:0, A:180)
     - 或者你喜欢的颜色

---

### 第二步：创建Header（标题栏）

1. **创建Header**
   - 右键点击 `SensorMonitorPanel` → UI → Panel
   - 重命名为 `Header`

2. **设置Header的RectTransform**
   ```
   Anchor Min: X=0, Y=1
   Anchor Max: X=1, Y=1
   Pivot: X=0.5, Y=1
   
   Anchored Position: X=0, Y=0
   Size Delta: X=0, Y=50
   ```

3. **设置Header背景颜色**
   - Color: 深蓝色 (R:30, G:60, B:100, A:255)

4. **创建标题文字**
   - 右键点击 `Header` → UI → Text - TextMeshPro
   - 重命名为 `TitleText`
   - 设置RectTransform：
     ```
     Anchor: Stretch (左右拉伸)
     Left: 10, Right: 10, Top: 5, Bottom: 5
     ```
   - 设置TextMeshPro属性：
     - Text: "Sensor Monitor"
     - Font Size: 20
     - Alignment: Center & Middle
     - Color: White
     - Font Style: Bold

---

### 第三步：创建Sensor List区域（滚动列表）

1. **创建ScrollView**
   - 右键点击 `SensorMonitorPanel` → UI → Scroll View
   - 重命名为 `SensorListScrollView`

2. **设置ScrollView的RectTransform**
   ```
   Anchor Min: X=0, Y=0
   Anchor Max: X=1, Y=1
   Pivot: X=0.5, Y=0.5
   
   Left: 10, Right: 10, Top: 60, Bottom: 10
   ```

3. **配置ScrollView组件**
   - Scroll Rect (Script) 组件：
     - ✅ Vertical (勾选)
     - ❌ Horizontal (取消勾选)
     - Movement Type: Elastic
     - Scrollbar Visibility: Auto Hide

4. **删除Horizontal Scrollbar**
   - 在Hierarchy中，展开 `SensorListScrollView`
   - 删除 `Scrollbar Horizontal` 对象

5. **配置Content**
   - 选中 `SensorListScrollView` → `Viewport` → `Content`
   - 添加 `Vertical Layout Group` 组件：
     - Padding: Left=5, Right=5, Top=5, Bottom=5
     - Spacing: 5
     - Child Alignment: Upper Center
     - ✅ Child Control Width
     - ✅ Child Control Height
     - Child Force Expand Width: ✅
     - Child Force Expand Height: ❌
   
   - 添加 `Content Size Fitter` 组件：
     - Horizontal Fit: Unconstrained
     - Vertical Fit: Preferred Size

6. **调整Scrollbar样式（可选）**
   - 选中 `Scrollbar Vertical`
   - 可以调整宽度和颜色使其更美观

---

### 第四步：添加SensorMonitorManager脚本

1. **添加脚本组件**
   - 选中 `SensorMonitorPanel`
   - 在Inspector中点击 `Add Component`
   - 搜索并添加 `SensorMonitorManager`

2. **配置SensorMonitorManager引用**
   - 将以下对象拖拽到对应字段：
     ```
     Sensor Monitor Panel: 拖拽 SensorMonitorPanel 自己
     Sensor List Scroll Rect: 拖拽 SensorListScrollView
     Sensor Item Container: 拖拽 Content (在SensorListScrollView/Viewport下)
     ```

3. **配置设置**
   ```
   Update Interval: 0.5
   Auto Refresh List: ✅ (勾选)
   List Refresh Interval: 2
   Show Debug Info: ✅ (勾选，调试时使用)
   ```

---

### 第五步：测试基础功能

1. **保存场景**
   - Ctrl+S 保存场景

2. **运行测试**
   - 点击 Play 按钮
   - 应该看到右侧出现Sensor Monitor面板
   - 由于使用了自动创建UI的功能，如果场景中有传感器，应该会自动显示

3. **检查Console**
   - 查看是否有错误信息
   - 应该看到类似这样的日志：
     ```
     [SensorMonitorManager] ✅ Sensor Monitor initialized
     [SensorMonitorManager] 🔍 Found X sensors in scene
     ```

---

## 🎯 下一步优化（可选）

### 创建SensorItem预制件（更美观的显示）

如果你想要更精致的传感器Item显示，可以创建一个预制件：

1. **创建SensorItem预制件**
   - 在Project窗口，创建文件夹 `Assets/VsensAgent/Prefabs/UI`
   - 在Content下右键 → UI → Panel，命名为 `SensorItem`
   
2. **配置SensorItem布局**
   - 添加 `Horizontal Layout Group`
   - 添加 `Layout Element`：Preferred Height = 60

3. **添加子元素**
   - Status Indicator (Image) - 10x10，圆形状态指示灯
   - Name (TextMeshPro) - 传感器名称
   - Type (TextMeshPro) - 传感器类型
   - Data (TextMeshPro) - 传感器数据

4. **添加SensorUIItem脚本**
   - 将引用连接好

5. **保存为预制件**
   - 拖拽到Project窗口创建Prefab
   - 删除Hierarchy中的临时对象

6. **设置预制件引用**
   - 选中 `SensorMonitorPanel`
   - 将刚创建的预制件拖拽到 `Sensor Item Prefab` 字段

---

## 🔧 快捷键提示

- **对齐锚点**: 选中对象后，在RectTransform组件的锚点预设图标处，按住 Alt+Shift 点击可以同时设置锚点和位置
- **快速创建UI**: Ctrl+Shift+N 打开GameObject创建菜单
- **复制组件**: 右键组件标题 → Copy Component / Paste Component Values

---

## ❓ 遇到问题？

### 传感器不显示
- 检查场景中是否有 `VsensAgentSensorManager` 对象
- 检查是否有 VirtualSensor 对象在场景中
- 查看Console的日志信息

### UI布局不对
- 检查锚点设置是否正确
- 确保Content有Vertical Layout Group和Content Size Fitter

### 脚本报错
- 确保TextMeshPro已导入项目
- 检查命名空间是否正确

---

## 📸 预期效果

完成后，你应该看到：
- 右侧有一个占据屏幕约40%宽度的半透明面板
- 顶部有"Sensor Monitor"标题
- 中间是可滚动的传感器列表
- 每个传感器显示：名称、类型、当前数据
- 自动更新传感器数据（每0.5秒）
