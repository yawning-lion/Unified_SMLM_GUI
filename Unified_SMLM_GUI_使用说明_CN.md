# Unified SMLM GUI 使用说明

## 1. 文档目的

本文档基于以下两部分内容整理：

- 实验流程说明：[SMLM调节步骤整理.md](./SMLM调节步骤整理.md)
- 当前统一控制项目：`unified_smlm`

本文档描述的是当前这套统一 GUI 的实际使用方式，而不是旧版分别打开 Micro-Manager、TeledyneCam 和 Focus Lock 三套界面的工作流。

当前 GUI 已整合：

- Micro-Manager 相机与采集控制
- 642/647 激光与 AOTF 控制
- Focus lock 运行时与 whole-cell Z scan
- 图像预览、事件日志、保存路径规划
- 默认参数配置、硬件常量配置和本地依赖资产管理

推荐启动入口仍然是桌面快捷方式 `Unified SMLM GUI.lnk`。

## 2. 当前 GUI 能做什么

当前统一 GUI 主要覆盖以下任务：

- 加载 `GXD_sCMOS_XY_stage_250221.cfg`
- 显示和刷新嵌入式 Micro-Manager 状态
- 开始/停止 Live、Snap、Acquire
- 自动加载并应用 ROI 预设文件
- 配置曝光、触发模式、保存格式、帧数
- 控制 642/647 激光输出、AOTF 输出和 modulation mode
- 初始化隐藏式 focus lock runtime，不再弹出旧版 focus lock 用户窗口
- 在当前 GUI 内执行 Lock / Unlock、Jump、whole-cell Z scan 参数配置
- 显示 XY/Z 位移台绝对坐标
- 在事件日志中显示 preset 使用说明、round plan、保存路径和运行状态

## 3. 启动方式

### 3.1 推荐方式

直接双击桌面快捷方式：

- `Unified SMLM GUI.lnk`

它会通过以下链路启动 GUI：

- `run_unified_gui_hidden.vbs`
- `run_unified_gui.bat`
- `python -m unified_smlm`

### 3.2 备用方式

如果桌面快捷方式暂时不可用，可以直接运行：

- `run_unified_gui.bat`

如果希望无控制台窗口启动，可以运行：

- `run_unified_gui_hidden.vbs`

### 3.3 如果项目目录被移动

如果整个项目目录位置变化，桌面快捷方式会失效。这时重新运行：

- `install_desktop_unified_gui_launcher.ps1`

它会重新创建桌面快捷方式。

## 4. 配置文件、资产文件与权限

### 4.1 中央配置文件

当前 GUI 的默认参数、preset 默认值和主要硬件常量统一保存在：

- [system_config.json](./unified_smlm/system_config.json)

该文件负责管理：

- GUI 默认采集参数
- Illumination 默认参数
- Focus lock 默认参数
- Bleach 默认参数
- Preset 一键切换时要写入的默认配置
- Teledyne 相关串口、AOTF 频率、DAQ 通道等硬件常量
- bundled 依赖文件的路径

修改此文件后，需要重启 GUI 才会生效。

### 4.2 管理员权限要求

`system_config.json` 当前已经被设置为：

- `Administrators` 可写
- `SYSTEM` 可写
- 普通 `Users` 只读

也就是说，修改默认配置需要管理员权限。

### 4.3 不建议手动修改的运行时文件

GUI 运行时会自动生成以下文件：

- `unified_smlm\runtime\teledyne\parameters.runtime.xml`
- `unified_smlm\runtime\focuslock\IX83_default.runtime.xml`

这些文件是由 `system_config.json` 和 bundled 资产自动派生出来的，不建议手动直接修改。应优先改：

- `unified_smlm\system_config.json`

### 4.4 本地 bundled 依赖资产

当前项目已经把最小自洽依赖收拢到：

- `unified_smlm\assets`

其中包括：

- `assets\micromanager\GXD_sCMOS_XY_stage_250221.cfg`
- `assets\roi\0512-0512.roi`
- `assets\teledyne\parameters.base.xml`
- `assets\teledyne\aotf_analog_calib.csv`
- `assets\teledyne\AotfLibrary.dll`
- `assets\teledyne\thorlabs_tsi_camera_sdk.dll`
- `assets\bin\PriorScientificSDK.dll`
- `assets\bin\uc480_64.dll`
- `assets\bin\uc480_tools_64.dll`

当前仍然保留的外部依赖主要只有：

- 系统中实际安装的 Micro-Manager 主程序目录
- NI-DAQ、串口驱动及真实硬件设备

## 5. 启动前的硬件准备

仍然建议遵循实验室原始 SOP 的硬件上电顺序。根据当前流程，推荐顺序如下：

1. 打开 ODT 相机，再打开 SMLM 相机。
2. 打开锁焦激光器。
3. 打开 AOTF 所在插座电源。
4. 打开主激光器并等待其进入正常 ready 状态。
5. 打开振动马达。

如果实验室已有更新版硬件 SOP，以实验室 SOP 为准。

## 6. 启动后的界面结构

### 6.1 左侧：Preset / Acquisition / Illumination

左侧主要负责“拍什么”和“怎么保存”：

- `Preset Modes`
- `Acquisition`
- `Illumination (642 / AOTF)`

### 6.2 中间：预览与日志

中间区域主要负责：

- 实时预览
- Snap / Live / Acquire
- Event Log

### 6.3 右侧：Micro-Manager / Focus Lock / Z Planner

右侧主要负责：

- `Embedded Micro-Manager`
- `Focus Lock and Z Scan`
- `Advanced Focus Lock Parameters`
- `Z Scan Planner`

## 7. 每次开机后的推荐操作顺序

建议按以下顺序操作：

1. 启动统一 GUI。
2. 在 `Embedded Micro-Manager` 中确认 config 路径正确。
3. 点击 `Load Config`。
4. 确认状态栏显示 config 已加载，位移台坐标开始刷新。
5. 确认 ROI 已自动应用；如需更换 ROI，使用 `ROI Preset` + `Apply ROI`。
6. 在 `Focus Lock and Z Scan` 中点击 `Initialize`。
7. 先找焦，再决定是否手动 `Lock`。
8. 选择合适的 preset。
9. 需要点亮激光时，在 `Illumination` 区设置参数并点击 `Apply To Hardware`。
10. 使用 `Acquire` 开始采集。

## 8. 当前 GUI 与旧流程的关键区别

### 8.1 不再需要分别打开旧版三套窗口

旧流程需要分别打开：

- `TeledyneCam`
- `Micro-Manager`
- `focuslock_83.py`

当前统一 GUI 已把这些核心能力整合到一个窗口里。正常使用时，不需要再单独打开旧界面。

### 8.2 Focus lock 原始窗口默认隐藏

当前 GUI 使用的是集成后的 focus lock runtime。原始 `IX83 Focus Lock` 窗口不再作为用户界面弹出。

### 8.3 Search / Focus 与 ROI Preview 合并使用

当前 GUI 不再保留独立的全视野 Search / Focus 预览模式。统一使用 `ROI Preview` 作为当前的找焦和预览入口。

### 8.4 Preset 不会自动帮你锁焦

切换 preset 时，GUI 不会自动把 focus lock 设成 locked。

必须先：

1. `Initialize`
2. 手动找焦
3. 手动点击 `Lock`

之后才允许进入：

- `STORM 2D`
- `Whole-Cell Z Scan`

如果还没手动 lock，GUI 会阻止切换并提示。

## 9. 各个 Preset 的推荐用途

### 9.1 ROI Preview

用途：

- 找焦
- 检查 ROI 是否正确
- 检查亮度和信号稳定性

当前默认特性：

- Trigger: `Internal`
- Saving Format: `Image Stack File`
- Illumination modulation: `Independent mode`
- 这是当前唯一推荐的预览 preset

推荐流程：

1. `Load Config`
2. 确认 ROI 已加载
3. `Start Live`
4. 找到样品和焦面
5. 如果后面要做 STORM 或 whole-cell，再手动点击 `Lock`

### 9.2 Widefield Test

用途：

- 用短栈快速检查亮度、对焦和保存路径

当前默认特性：

- `Widefield Frames` 默认 `10`
- `Image Stack File`
- `Internal` 触发

推荐用途：

- 正式拍单分子前先做一次短测试

### 9.3 STORM 2D

用途：

- 标准二维单分子采集

进入条件：

- focus lock 已初始化
- 当前已经手动 lock

当前默认特性：

- Trigger: `Internal`
- Saving Format: `Separate Image Files`
- Modulation: `one-chan FSK mode`

推荐流程：

1. 在 `ROI Preview` 中找到正确焦面
2. 手动点击 `Lock`
3. 切换到 `STORM 2D`
4. 检查 642 与 AOTF 参数
5. 确认 modulation mode 为 `one-chan FSK mode`
6. 点击 `Apply To Hardware`
7. 点击 `Acquire`

### 9.4 Whole-Cell Z Scan

用途：

- 通过 focus lock 的 DAQ 路径实现整细胞 Z 扫描采集

进入条件：

- focus lock 已初始化
- 当前已经手动 lock

当前默认特性：

- Trigger: `External`
- Saving Format: `Separate Image Files`
- Modulation: `one-chan FSK mode`
- 默认 Z 范围为 `-4.5 um` 到 `+4.5 um`
- 当前 preset 默认 `Depth Count = 16`
- 默认 `Frames / Depth / Round = 100`

推荐流程：

1. `Load Config`
2. `Initialize` focus lock
3. 找焦
4. 手动点击 `Lock`
5. 切换到 `Whole-Cell Z Scan`
6. 设置 `Z Start` / `Z End` / `Depth Count` 或 `Z Step`
7. 检查 `Frames / Depth / Round`
8. 确认 illumination 为 `one-chan FSK mode`
9. 点击 `Apply To Hardware`
10. 点击 `Acquire`

不要把真实数据采集写成：

- 先点 `Run Z Scan`
- 再点 `Acquire`

当前真实采集推荐方式是：

- 直接点 `Acquire`

因为当前 whole-cell 的真实联动流程是：

1. 先让相机进入 external-trigger 等待状态
2. 再由集成后的 focus lock DAQ 发出 Z 扫描和触发脉冲

## 10. Focus Lock 参数应如何理解

### 10.1 Lock / Unlock

- `Lock`：进入闭环锁焦
- `Unlock`：退出闭环锁焦

切换到 ODT 或离开单分子流程前，仍建议先解锁。

### 10.2 Jump Offset

`Jump Offset` 就是每次点击 `Jump +` 或 `Jump -` 的实际位移量。

当前默认值：

- `10 um`

### 10.3 Z Start / Z End

`Whole-Cell Z Scan` 中的 `Z Start` 和 `Z End` 不是绝对坐标。

它们表示：

- 相对于开始 whole-cell 扫描那一刻当前位置的相对偏移

如果是在锁定状态下开始扫描，这个参考位置通常就是当前锁定平面。

默认：

- `Z Start = -4.5 um`
- `Z End = +4.5 um`

含义是：

- 以当前焦面为中心，向下 4.5 um 到向上 4.5 um 做对称扫描

### 10.4 Frames / Depth / Round 与 STORM Total Frames 的关系

这是 whole-cell 模式中最容易搞错的地方。

在 whole-cell 模式下：

- `STORM Total Frames` 表示每个深度最终目标总帧数
- `Frames / Depth / Round` 表示每一轮扫描中每个深度采多少帧

例如：

- `STORM Total Frames = 200`
- `Frames / Depth / Round = 100`

系统会自动规划为：

- `2 rounds`

如果 `Depth Count = 16`，总图像数就是：

- `16 depths x 200 frames/depth = 3200 images`

如果保留：

- `STORM Total Frames = 20000`
- `Frames / Depth / Round = 100`

那么意味着：

- 每个深度目标是 `20000` 帧
- 系统将规划 `200 rounds`

因此在 whole-cell 模式下，采集前一定要确认：

- `STORM Total Frames`
- `Frames / Depth / Round`
- `Depth Count`

## 11. 保存路径与命名规则

### 11.1 总体规则

当前保存路径不再使用 `trial`。

每次启动 GUI 时，系统会生成一个固定的本次会话时间戳前缀；在本次 GUI 不关闭之前，这个时间戳保持不变。

会话文件夹命名规则为：

- `[optional prefix]_[launch timestamp]_[optional sample]`

其中：

- `Save Prefix` 可留空
- `Sample Name` 可留空

### 11.2 例子

假设：

- `Save Root = D:\Research_RSC`
- GUI 启动时间戳 = `20260416_021734`
- `Save Prefix = test`
- `Sample Name = HeLa`

则 session 文件夹为：

- `D:\Research_RSC\test_20260416_021734_HeLa`

如果前缀和样品名都留空，则可能为：

- `D:\Research_RSC\20260416_021734`

### 11.3 各模式子目录

不同 preset 会写入不同子目录：

- `ROI Preview` -> `roi_preview`
- `Widefield Test` -> `widefield`
- `STORM 2D` -> `sr_smlm`
- `Whole-Cell Z Scan` -> `whole_cell_z`

### 11.4 文件名前缀

默认文件名前缀：

- `roi`
- `wf`
- `sr`
- `zscan`

例如：

- `wf_20260416_153000.tif`
- `sr_20260416_153000`
- `zscan_20260416_153000`

## 12. 两种保存格式的真实行为

### 12.1 Separate Image Files

当前实现会直接逐帧流式写单帧 TIFF。

输出是一个目录，例如：

- `...\sr_smlm\sr_20260416_153000\`

目录中是大量单帧 TIFF 文件。

这条路径不会额外保留 `_mda` 数据集目录。

推荐用于：

- `STORM 2D`
- `Whole-Cell Z Scan`

### 12.2 Image Stack File

当前实现仍然使用 MDA 流程生成 stack 输出。

主输出为：

- 一个 `.tif`

在默认情况下，某些 `Image Stack File` 流程仍可能保留 `_mda` 数据集目录。

但例外是：

- `Widefield Test` 当前不会在最终保存目录中保留 `_mda`

推荐用于：

- `ROI Preview`
- 小数据量检查型采集

## 13. Event Log 中会显示什么

当前 Event Log 会显示很多关键提示，包括：

- 当前 preset 的使用说明
- 当前参数配置摘要
- 计划保存路径
- MDA 或 streaming TIFF 的输出信息
- whole-cell 的 round plan
- 总帧数/总图像数
- 采集完成或中断信息
- illumination apply / safe shutdown 信息

如果是 whole-cell，日志里会明确显示：

- round 数
- 每轮 `frames/depth`
- `frames/depth total`
- `depths x frames/depth = total images`

## 14. 绝对位移台位置显示

当前 GUI 会实时显示绝对位移台坐标：

- XY stage 绝对位置
- Focus stage 绝对 Z 位置

显示位置在：

- `Embedded Micro-Manager` 面板中的 `Stage`

在 focus lock 工作时，Z 读数会优先显示 focus lock runtime 返回的位置。

## 15. Illumination 面板如何使用

当前 Illumination 面板主要暴露：

- 642/647 激光开关
- 激光功率
- AOTF 开关
- AOTF 数值
- modulation mode

常见模式：

- `Independent mode`
  - 用于找样品、找焦、宽场检查
- `one-chan FSK mode`
  - 用于 STORM 和 whole-cell，使相机时序与 AOTF 联动

推荐流程：

1. 修改参数
2. 点击 `Apply To Hardware`
3. 查看 Event Log 中的应用结果

## 16. Safe Shutdown 与关闭 GUI

### 16.1 Illumination 的 Safe Shutdown 按钮

点击 `Safe Shutdown` 会执行当前软件层的安全关闭路径：

1. 将 647 激光目标功率拉回 safe shutdown setpoint
2. 关闭 AOTF 输出
3. 拉低 NI-DAQ 输出
4. 重置 AOTF DDS 状态
5. 关闭激光输出

### 16.2 直接关闭整个 GUI

如果直接关闭 GUI：

- 系统也会尝试自动执行 illumination safe shutdown

如果当时正处于 external-trigger whole-cell 采集中，当前退出顺序为：

1. 停止采集等待态
2. 请求 focus lock 停止 DAQ 扫描
3. 对激光 / AOTF 执行 safe shutdown
4. 再释放 Micro-Manager、focus lock 和 Teledyne runtime

## 17. 推荐的软件关闭顺序

建议：

1. 如果正在锁焦，先 `Unlock`
2. 如果正在采集，先 `Stop Acquisition`
3. 如有需要，点击 `Safe Shutdown`
4. 关闭 GUI

## 18. 推荐的硬件断电顺序

仍建议遵循原始实验流程中的顺序：

1. 先关振动马达
2. 关主激光器
3. 关锁焦激光器
4. 关 AOTF 电源
5. 最后关相机电源

## 19. 常见问题排查

### 19.1 快捷方式无法启动

检查：

- 项目目录是否被移动
- `run_unified_gui_hidden.vbs` 是否仍在项目根目录

如项目位置变化，重新运行：

- `install_desktop_unified_gui_launcher.ps1`

### 19.2 Load Config 失败，提示串口或设备占用

通常说明：

- 旧 GUI 还没彻底退出
- 其他程序占用了相机、位移台或串口

先关闭：

- 其他可能连接 Micro-Manager 的程序
- 旧版 focus lock
- 旧版 TeledyneCam

然后再重试。

### 19.3 无法切换到 STORM 2D 或 Whole-Cell Z Scan

这是当前设计，不是 bug。

必须先：

1. 初始化 focus lock runtime
2. 找焦
3. 手动点击 `Lock`

之后才可进入这两个 preset。

### 19.4 whole-cell 的 round 数不对

优先检查：

- `STORM Total Frames`
- `Frames / Depth / Round`
- `Depth Count`

记住：

- `STORM Total Frames` 在 whole-cell 模式下表示每个深度的目标总帧数

### 19.5 没有光或亮度不对

依次检查：

1. 激光器硬件是否真的上电
2. AOTF 硬件是否上电
3. `642 Laser` 是否启用
4. `AOTF 642` 是否启用
5. 是否点击了 `Apply To Hardware`
6. modulation mode 是否正确
7. 当前实验是否需要 `one-chan FSK mode`
8. Event Log 是否报告 runtime apply 失败

### 19.6 保存失败或目录已存在

`Separate Image Files` 模式要求目标输出目录不存在或为空。

如果手动重复使用同一路径，可能触发冲突。最简单的解决方式是：

- 改一下 `Save Prefix`
- 改一下 `Sample Name`
- 或关闭并重新打开 GUI，让 session 时间戳变化

### 19.7 想改默认参数但 GUI 内改完下次又恢复

这是因为 GUI 内改动主要是本次会话级别。

如果希望修改下次启动时的默认值，应以管理员权限编辑：

- `unified_smlm\system_config.json`

改完后重启 GUI。

## 20. 当前 GUI 对原始流程的推荐映射

如果把旧流程压缩成当前 GUI 的推荐用法，可理解为：

1. 用桌面快捷方式启动统一 GUI
2. `Load Config`
3. 在 `ROI Preview` 中找焦
4. 手动 `Lock`
5. 根据需要切换到 `Widefield Test`、`STORM 2D` 或 `Whole-Cell Z Scan`
6. 在 `Illumination` 区应用对应激光和 AOTF 设置
7. 点击 `Acquire`
8. 查看 Event Log 和保存路径预览
9. 结束后 `Unlock`，再关闭 GUI

## 21. 相关文件

当前行为对应的关键文件包括：

- `SMLM调节步骤整理.md`
- `run_unified_gui.bat`
- `run_unified_gui_hidden.vbs`
- `install_desktop_unified_gui_launcher.ps1`
- `unified_smlm\system_config.json`
- `unified_smlm\config_store.py`
- `unified_smlm\main_window.py`
- `unified_smlm\presets.py`
- `unified_smlm\mm_backend.py`
- `unified_smlm\focuslock_integration.py`
- `unified_smlm\teledyne_integration.py`
- `unified_smlm\save_paths.py`
- `unified_smlm\assets\`
- `unified_smlm\runtime\`

如果后续 GUI 功能继续调整，建议同步更新本文件和对应英文说明。
