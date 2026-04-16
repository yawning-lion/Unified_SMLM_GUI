# SMLM调节步骤整理

说明：本文件根据 `SMLM操作指南.docx` 的正文和内嵌截图整理。软件路径优先采用当前电脑上实际存在的路径；GUI 名称采用截图中可见的窗口名、按钮名和字段名。

## 1. 软件、脚本、路径与 GUI 入口

| 项目 | 路径 | 窗口/入口 | 截图中可见的按钮或字段 |
| --- | --- | --- | --- |
| 激光/AOTF 控制软件 `TeledyneCam` | `C:\Users\SunLab319\Desktop\smlm_control\TeledyneCam.exe` | 桌面快捷方式 `TeledyneCam - Shortcut` | `Connect`, `Disconnect`, `Reset`, 通道 `405/488/560/642`, 每路 `Set`, `Laser modulation`, `Independent mode`, `one-chan FSK mode` |
| `Micro-Manager 2.0.0` | `C:\Program Files\Micro-Manager-2.0\ImageJ.exe` | 启动后会拉起 `Micro-Manager` 主窗口和 `ImageJ` 窗口 | `Snap`, `Live`, `Stop Live`, `Album`, `Multi-D Acq`, `ROI`, `Exposure [ms]`, `Binning`, `Shutter` |
| `Micro-Manager` 配置文件 | `C:\Program Files\Micro-Manager-2.0\GXD_sCMOS_XY_stage_250221.cfg` | `Micro-Manager Startup Configuration` | 启动时选择 `GXD_sCMOS_XY_stage_250221.cfg` |
| ROI 预设文件 | `C:\Users\SunLab319\Desktop\GXD_MM_ROI\0512-0512.roi` | 拖入 `ImageJ` 窗口 | `ROI` 方块按钮，`Stop Live` |
| `ImageJ` | 由 `C:\Program Files\Micro-Manager-2.0\ImageJ.exe` 启动 `Micro-Manager` 时自动打开 | `ImageJ` 窗口 | 工具栏、ROI 相关图标 |
| Focus lock 工程目录 | `D:\GXD\Python_control_gxd\Focus_lock_IX83_Prior` | `VSCode` 的 `Open Folder` | `Select Folder` |
| Focus lock 启动脚本 | `D:\GXD\Python_control_gxd\Focus_lock_IX83_Prior\IX83\focuslock_83.py` | `VSCode` 编辑器中直接运行 | 右上角运行按钮，`Run Python File` |
| Focus lock Conda 环境 | `C:\Users\SunLab319\anaconda3\envs\focuslock\python.exe` | `VSCode` 右下角解释器选择 | `3.10.16 ('focuslock')` |
| `IX83 Focus Lock` 窗口 | 由上面的 `focuslock_83.py` 启动 | 窗口标题 `IX83 Focus Lock` | `Off`, `Always On`, `Lock + Z Scan Calibration`, `Lock`, `Jump (+)`, `Jump (-)` |
| `IX83 Focus Lock` Z 扫描区 | 同上 | `Z Scan` 面板 | `Start (um)`, `End (um)`, `Step (um)`, `Frames per pos`, `Scan` |

## 2. 打开硬件

1. 打开 ODT 相机，确认电脑已经连接后，再打开 SMLM 相机。两台相机不要同时乱序上电，先连上一台再开下一台。
2. 打开锁焦激光器。先按左下按钮通电，再按右上按钮开激光，再用旋钮调节光强。
3. 打开 AOTF 所在插座的电源按钮。
4. 按激光器上的黑色电源按钮。等指示灯从黄灯变成绿灯后，再把钥匙向右拧开。
5. 打开震动马达，按插排按钮即可。

## 3. 软件操作与调节步骤

### 3.1 打开激光和采集软件

1. 双击桌面的 `TeledyneCam - Shortcut`，打开 `TeledyneCam`。
2. 打开 `Micro-Manager 2.0.0`，在 `Startup Configuration` 里选择 `GXD_sCMOS_XY_stage_250221.cfg`。启动后 `ImageJ` 会自动一起打开，不需要单独再开。
3. 在 `Micro-Manager` 主界面中，正常拍摄时把相机触发设置为 `Internal`。

### 3.2 设置相机 ROI 和基础采集参数

1. 点击 `Live` 预览。
2. 把 `C:\Users\SunLab319\Desktop\GXD_MM_ROI\0512-0512.roi` 拖进 `ImageJ` 窗口。
3. 回到 `Micro-Manager` 主界面，点击 `ROI` 区域对应的小方块按钮，把 ROI 应用到相机。
4. 点击 `Stop Live` 停止预览。
5. 点击 `Multi-D Acq` 打开 `Multi-Dimensional Acquisition`。
6. 在 `Time Points` 中设置：
   - `Interval` 为 `0`
   - `Count` 为拍摄总帧数，STORM 常用 `20000`
7. 在 `Save Images` 中设置：
   - `Directory root` 为保存根目录
   - `Name prefix` 为样品名
   - STORM 采集时 `Saving format` 选 `separate image files`
   - 如果先拍一组宽场预览，可选 `image stack file`，例如先拍 `50` 帧
8. `Exposure [ms]` 一般设为 `25 ms`。

### 3.3 打开并调节 focus lock

1. 用 `VSCode` 打开 `D:\GXD\Python_control_gxd\Focus_lock_IX83_Prior`。
2. 解释器切换到 `C:\Users\SunLab319\anaconda3\envs\focuslock\python.exe`。
3. 打开并运行 `D:\GXD\Python_control_gxd\Focus_lock_IX83_Prior\IX83\focuslock_83.py`。
4. 出现 `IX83 Focus Lock` 窗口后，先把焦点调到比正常成像焦面高约 `200 um`。
5. 锁焦激光器强度先保持默认值。
6. 在 `IX83 Focus Lock` 中选择 `Always On`，确认 live 画面里已经能看到锁焦图案和亮点。
7. 亮点稳定后点击 `Lock`。

### 3.4 打开激光并切换调制模式

1. 在 `TeledyneCam` 顶部通道区找到 `642` 这一行。先在 `642` 行右侧输入目标激光输出值，再点击这一行的 `Set`，把 642 激光先打开。
2. 打开后确认 `642` 左侧状态灯已经亮起，再继续调 AOTF；找样品时这里先用较低激光功率。
3. 在下方 `Laser modulation` 区域，先把模式保持在 `Independent mode`，这表示激光输出和相机触发无关。
4. 在 `Laser modulation` 的 `642` 行打开通道，把红色滑条或右侧数值框调到需要的 AOTF 透过率。找样品时 AOTF 先调到 several mW，文档截图给出的经验值是 AOTF 读数约 `4.4`。
5. 正式联动采集前，再把 `Laser modulation` 从 `Independent mode` 改成 `one-chan FSK mode`，这表示相机 trigger 已与 AOTF 联动。

### 3.5 拍图顺序

1. 先拍单分子，再拍 ODT。
2. 为避免 ODT 激光干扰单分子成像，找单分子时可用小卡片先把 ODT 光路挡掉。
3. 对焦优先靠单分子完成，不要依赖 ODT 那个反射镜。
4. 切换到 ODT 前，先把锁焦改成 `Unlock` 或取消锁定；否则 ODT 反射镜挡光后，位移台可能乱飘。

### 3.6 单分子打灭和正式采集

1. 为让荧光进入暗态，先把激光输出调到 `1000`，同时把 AOTF 透过率调到 `100`。
2. 用高功率打光使单分子点变稀疏。文档经验值：
   - 线粒体样品通常打 `3~5 min`
   - 稀疏标准是 XY 上尽量不要重叠
3. 正式采集时，把激光设置回 `400`。

### 3.7 Z 轴 whole-cell 扫描

1. Z 扫描前需要设置 focus lock 里的 `Jump Control` 偏移量 `Offset (um)`。
2. 文档建议设置 `10` 个深度，每个深度 `100` 帧，并执行交错扫描，以尽量公平分配光子衰减。
3. 如果使用 `Lock + Z Scan Calibration` / `Z Scan` 模式：
   - 填写 `Start (um)`
   - 填写 `End (um)`
   - 填写 `Step (um)`
   - 填写 `Frames per pos`
   - 点击 `Scan`
4. 文档提示在 Z 扫描模式下，采集信号可能由采集卡统一发出，此时相机触发模式可能要从 `Internal` 改为 `External`。

## 4. 关软件顺序

1. 先 `Unlock` 锁焦，再点窗口右上角 `X` 关闭 `IX83 Focus Lock`。
2. `Micro-Manager` 可以直接关闭。
3. 在 `TeledyneCam` 里先把激光输出降到最小，文档建议先降到 `100`，再把前面的圆形使能点关掉。
4. AOTF 软件不需要单独做复杂操作，直接关闭即可。

## 5. 关硬件顺序

1. 先关震动马达。
2. 关激光器：先把钥匙拧回，再关电源开关。
3. 关锁焦激光器：先关右上，再关左下。
4. 关闭 AOTF 插座电源按钮。
5. 关闭相机电源。

## 6. GUI 按钮速查

### 6.1 `Micro-Manager`

- 主界面常用按钮：`Snap`, `Live`, `Stop Live`, `Album`, `Multi-D Acq`, `Refresh`, `Close All`
- 采集参数字段：`Exposure [ms]`, `Binning`, `Shutter`
- 触发相关：`Internal`, `External`
- ROI 相关：`ROI` 小方块按钮

### 6.2 `Multi-Dimensional Acquisition`

- `Count`
- `Interval`
- `Directory root`
- `Name prefix`
- `Saving format`
- `separate image files`
- `image stack file`

### 6.3 `IX83 Focus Lock`

- 模式：`Off`, `Always On`, `Lock + Z Scan Calibration`
- 锁焦：`Lock`
- 跳焦：`Offset (um)`, `Jump (+)`, `Jump (-)`
- Z 扫描：`Start (um)`, `End (um)`, `Step (um)`, `Frames per pos`, `Scan`

### 6.4 `TeledyneCam`

- 通道：`405`, `488`, `560`, `642`
- 顶部每路都有状态灯、数值输入框和 `Set`
- 先在顶部 `642` 行设定激光输出并点 `Set`
- 下方 `Laser modulation` 区域再打开 `642` 的 AOTF 通道并调滑条/数值
- 调制模式：`Independent mode`, `one-chan FSK mode`
- 连接相关：`Connect`, `Disconnect`, `Reset`

## 7. 一句话版顺序

先开相机、锁焦激光器、AOTF、激光器和马达；然后打开 `TeledyneCam`、`Micro-Manager`、`focuslock_83.py`；在 `Micro-Manager` 里设好 `Internal`、ROI、`Multi-D Acq`、曝光 `25 ms`；在 `IX83 Focus Lock` 里 `Always On` 后 `Lock`；找样品时用低功率和 `Independent mode`，正式采集切到 `one-chan FSK mode`，打灭后按需要拍 STORM 或做 Z 扫描；结束时先解锁、关软件，再按马达、激光器、锁焦激光器、AOTF、相机的顺序断电。

## 8. 当前软件功能模块总结

### 8.1 总体分工

当前这套 SMLM 软件不是单一程序，而是由 3 个主软件加 1 个辅助窗口协同完成：

- `TeledyneCam`：负责激光和 AOTF 输出控制。
- `Micro-Manager 2.0.0`：负责 sCMOS 相机采集、ROI、曝光、触发和数据保存。
- `ImageJ`：作为 `Micro-Manager` 联动打开的图像显示窗口，主要用于 ROI 文件拖入和预览。
- `IX83 Focus Lock`：负责锁焦、Z 偏移和 whole-cell Z 扫描。

### 8.2 `TeledyneCam` 功能模块

- 设备连接模块：`Connect`, `Disconnect`, `Reset`
- 激光通道模块：`405`, `488`, `560`, `642` 四路激光，每路都有数值输入和 `Set`
- AOTF/调制模块：位于 `Laser modulation` 区域，可单独对各通道做透过率控制
- 模式切换模块：
  - `Independent mode`：激光/AOTF 不跟相机触发联动，适合找样品、找焦
  - `one-chan FSK mode`：相机 trigger 和 AOTF 联动，适合正式采集

从使用逻辑上看，`TeledyneCam` 分成上下两层：

- 上层是“激光源开关和基础输出功率”
- 下层是“AOTF 调制和与相机触发的联动模式”

也就是说，通常要先在上层打开 `642` 激光，再在下层打开 `642` 的 AOTF 输出。

### 8.3 `Micro-Manager` 功能模块

- 启动配置模块：在 `Startup Configuration` 里加载 `GXD_sCMOS_XY_stage_250221.cfg`
- 相机控制模块：`Snap`, `Live`, `Stop Live`
- 成像参数模块：`Exposure [ms]`, `Binning`, `Shutter`
- ROI 模块：通过 `ImageJ` 导入 `.roi` 文件，再在主界面点击 `ROI` 方块应用
- 多维采集模块：`Multi-D Acq`
- 保存模块：
  - `Directory root`
  - `Name prefix`
  - `Saving format`
  - `separate image files`
  - `image stack file`
- 触发模块：
  - `Internal`
  - `External`

其中 `Micro-Manager` 是整套流程中的“主采集软件”，负责把相机配置和文件输出固定下来。

### 8.4 `IX83 Focus Lock` 功能模块

从代码目录和 GUI 来看，`IX83 Focus Lock` 至少包含以下几层：

- 启动入口：
  - `focuslock_83.py`
- GUI 层：
  - `focusLockZ.py`
  - `lockDisplay.py`
  - `lockDisplayWidgets.py`
- 控制层：
  - `lockControl.py`
  - `lockModes.py`
- 硬件执行层：
  - `IX83FocusLock.py`
  - `stageOffsetControl_bx.py`
- 质量评估层：
  - `focusQuality.py`
- 硬件接口层：
  - `priorZController` 负责 Z 位移台
  - `uc480Camera` 负责锁焦相机

它的 GUI 上对应的核心功能模块是：

- 锁焦模式模块：`Off`, `Always On`, `Lock + Z Scan Calibration`
- 锁焦执行模块：`Lock`
- Z 补偿模块：`Offset (um)`, `Jump (+)`, `Jump (-)`
- Z 扫描模块：`Start (um)`, `End (um)`, `Step (um)`, `Frames per pos`, `Scan`

从控制逻辑上看，`IX83 Focus Lock` 的核心链路是：

锁焦相机读出偏差信号 -> PID/控制线程计算修正量 -> Prior Z 台移动 -> 继续读偏差 -> 形成闭环。

## 9. SMLM 拍图中涉及到的拍图模式

### 9.1 找样品/找焦模式

用途：先找到样品、对焦、确认锁焦工作正常。

典型设置：

- `Micro-Manager`：`Live`
- 相机触发：`Internal`
- `TeledyneCam`：低功率 `642`
- AOTF 模式：`Independent mode`
- `IX83 Focus Lock`：`Always On`

这一模式的核心特点是“连续预览优先、联动要求低、功率先保守”。

### 9.2 ROI 预览模式

用途：把视场裁剪到采集区域，减少数据量，提高帧率和后续处理效率。

典型设置：

- 在 `ImageJ` 中导入 `0512-0512.roi`
- 在 `Micro-Manager` 中点击 `ROI`
- 用 `Live` 或短时预览确认 ROI 是否正确

这一模式本质上还是预览模式，但已经进入正式采集前的“参数收敛阶段”。

### 9.3 宽场测试模式

用途：在正式 STORM 前先拍一小段宽场数据，检查亮度、焦平面和保存目录是否正确。

典型设置：

- `Multi-D Acq`
- `Count` 设较小值，例如 `50`
- `Saving format` 选 `image stack file`
- 相机触发：`Internal`

这一模式的特点是“拍得少、看得快、用于检查，不用于最终重建”。

### 9.4 STORM 正式采集模式

用途：获取单分子定位所需的大帧数序列。

典型设置：

- `Multi-D Acq`
- `Count` 常用 `20000`
- `Saving format` 选 `separate image files`
- `Exposure [ms]` 常用 `25`
- 激光先打灭，再把正式采集功率调回合适值，例如文档中的 `400`
- `TeledyneCam` 模式切到 `one-chan FSK mode`

这一模式的本质是“单分子稀疏化之后的大批量连续采集”。

### 9.5 ODT 切换模式

用途：在单分子拍完后切换到 ODT 相关观察或采集。

关键逻辑：

- 先拍单分子，再拍 ODT
- 切到 ODT 前先 `Unlock`
- 否则 ODT 反射镜挡光，可能导致锁焦误判并使位移台漂移

这不是独立的软件模式，而是一个“跨光路切换模式”。

### 9.6 Whole-cell Z 扫描模式

用途：在整个细胞厚度范围内按深度逐层采集。

典型设置：

- `IX83 Focus Lock` 中设置 `Offset (um)`
- 使用 `Z Scan` 或 `Lock + Z Scan Calibration`
- 设置 `Start (um)`, `End (um)`, `Step (um)`, `Frames per pos`
- 文档建议：`10` 个深度，每层 `100` 帧
- 该模式下相机触发可能要改为 `External`

这一模式的核心是“锁焦软件负责 Z 轴组织，相机按外部节奏取帧”。

## 10. 相关逻辑结构

### 10.1 软件之间的层级关系

整套系统可以理解成 3 层：

1. 光源层：`TeledyneCam`
   负责激光开关、激光功率、AOTF 透过率、与相机 trigger 的联动方式。
2. 成像层：`Micro-Manager`
   负责相机参数、ROI、触发、采集和文件保存。
3. 稳焦/位移层：`IX83 Focus Lock`
   负责 Z 轴锁焦、焦点补偿和 Z 扫描。

`ImageJ` 更像是 `Micro-Manager` 的图像交互前端，而不是独立控制层。

### 10.2 正常 SMLM 拍图逻辑链

正常单分子拍图的逻辑链如下：

1. 硬件上电。
2. `TeledyneCam` 打开激光基础输出。
3. `Micro-Manager` 打开相机、设置 `Internal`、设置 ROI、设置采集参数。
4. `IX83 Focus Lock` 启动并锁定焦面。
5. `TeledyneCam` 调低功率找样品，AOTF 保持 `Independent mode`。
6. 找到样品后提高功率打灭，建立单分子稀疏状态。
7. 正式采集时把 `TeledyneCam` 切到 `one-chan FSK mode`。
8. `Micro-Manager` 执行大帧数采集并保存。

### 10.3 触发逻辑

当前流程里至少有两类触发逻辑：

- `Internal` 触发：
  - 主要用于正常预览、宽场测试和大多数常规采集
  - 相机自己按设定曝光时间连续采集
- `External` 触发：
  - 主要出现在 whole-cell Z 扫描等需要统一时序的模式
  - 相机由外部信号或采集卡统一驱动

因此，是否切到 `External`，本质上取决于“当前采集节奏由谁主导”：

- 如果由相机自己主导，用 `Internal`
- 如果由采集卡/外部同步主导，用 `External`

### 10.4 光路控制逻辑

光路控制也分两层：

- 激光器本体输出
- AOTF 实际透过和调制

所以在 GUI 上会看到一个常见顺序：

1. 在 `TeledyneCam` 顶部打开 `642` 激光源
2. 在 `Laser modulation` 里打开 `642` 的 AOTF 输出
3. 根据阶段选择 `Independent mode` 或 `one-chan FSK mode`

这也是为什么“开 642”和“开 AOTF”在软件里是两个动作，而不是一个动作。

### 10.5 锁焦逻辑

锁焦逻辑不是简单开关，而是闭环控制：

1. 锁焦相机看到反射斑或亮点
2. 软件计算 `Offset`
3. 控制线程根据偏差输出修正量
4. Z 位移台移动
5. 再次读取偏差并更新状态

所以：

- `Always On` 更像“持续监测/准备工作状态”
- `Lock` 才是“进入闭环补偿状态”
- `Unlock` 是退出闭环，防止切换 ODT 时误补偿
