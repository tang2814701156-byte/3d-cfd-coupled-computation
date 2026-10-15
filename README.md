# 一三维双向耦合交付说明

本项目基于 preCICE 3.4.1 框架二次开发，将一维管路模型与 OpenFOAM 三维圆管模型连接，完成流速、温度、相分数的正向传递及接口压力的反向反馈。同一对模型在共同交换窗口内协调时间推进，并支持毫秒级仿真时间上的阀门控制。

## 文件目录

| 名称 | 内容 |
| --- | --- |
| [01一三维耦合方案说明.docx](01一三维耦合方案说明.docx) | 模型与接口设计、总体执行流程、时间步长协调、控制同步及边界一致性 |
| [02可运行的双向耦合原型](02可运行的双向耦合原型/README.md) | Windows/Linux 启动脚本、离线容器镜像及部署与复跑手册 |
| [03一三维双向耦合算例验证报告.docx](03一三维双向耦合算例验证报告.docx) | 模型建立、两个解析算例、守恒验证、探索试验、云图及结果分析 |
| [04可复现材料包](04可复现材料包/README.md) | 工程源码、算例配置、依赖、原始结果、分析与制图脚本 |
| [05 演示视频.mp4](<05 演示视频.mp4>) | 耦合流程、算例与试验运行演示 |

建议先阅读方案说明与算例验证报告，再按部署手册运行算例。请完整复制本目录，并保持各子目录的相对位置，尤其是 02 与 04 两个目录相邻。

## 快速运行

推荐使用 x86-64 Windows 或 Linux。Windows 安装并启动 Docker Desktop，启用 Linux 容器；Linux 安装并启动 Docker Engine。运行所需的 OpenFOAM、preCICE 和 Python 已包含在离线镜像中。

在本 README 所在的 `submission` 目录打开终端，按需执行以下命令。

Windows PowerShell：

```powershell
# 算例一：稳态层流圆管，与 Poiseuille 解析解对照
powershell -NoProfile -ExecutionPolicy Bypass -File ".\02可运行的双向耦合原型\run.ps1" -Case steady

# 算例二：无源项温度与相分数输运，与特征线解析解对照
powershell -NoProfile -ExecutionPolicy Bypass -File ".\02可运行的双向耦合原型\run.ps1" -Case advection

# 阀门控制演示：毫秒级仿真时间控制与双向反馈
powershell -NoProfile -ExecutionPolicy Bypass -File ".\02可运行的双向耦合原型\run.ps1" -Case valve

# 试验一：基础验证、细化与交换频率扫描
powershell -NoProfile -ExecutionPolicy Bypass -File ".\02可运行的双向耦合原型\run.ps1" -Study validation

# 试验二：单因素细化、重复性与参数探索
powershell -NoProfile -ExecutionPolicy Bypass -File ".\02可运行的双向耦合原型\run.ps1" -Study exploratory

# 试验三：综合性能、持续运行、故障注入与重新运行
powershell -NoProfile -ExecutionPolicy Bypass -File ".\02可运行的双向耦合原型\run.ps1" -Study hardening

# 模型、控制逻辑与输入验证等自动化测试
powershell -NoProfile -ExecutionPolicy Bypass -File ".\02可运行的双向耦合原型\run.ps1" -Tests
```

每次执行一条命令，结束后再执行下一条。批量试验包含多个工况，耗时明显长于单算例。Windows 入口会在同一终端显示求解日志和实时参数，无需提前定义变量或另外打开监控终端；输出目录自动生成，具体路径见终端输出。

监控字段包括仿真时间 t（s）、质量流量 mdot（kg/s）、背压 p（Pa）、温度 T（K）、相 A 体积分数 alpha、阀门开度 opening 和已接受窗口数 windows。稳态算例采用等温单相模型，T=300 K、alpha=1 为固定状态值；输运算例中温度和相分数随时间变化。

`hardening` 包含主动终止一维、三维参与者的故障注入，程序根据进程清理和数据保留情况判断是否符合预期；对应记录见本次输出下的 `execution_records.json`。运行完成并通过检查后，Windows 入口显示 `RUN AND CHECKS COMPLETED`。

Linux 单算例入口（同样在 `submission` 目录执行）：

```bash
bash "./02可运行的双向耦合原型/run.sh" --case steady
bash "./02可运行的双向耦合原型/run.sh" --case advection
bash "./02可运行的双向耦合原型/run.sh" --case valve
```

首次启动会自动校验并导入离线镜像。新运行结果保存至 `04可复现材料包/results/` 下的独立目录，具体路径见终端输出。详细环境设置、参数与结果查看方式见 [部署与复跑手册](02可运行的双向耦合原型/部署与复跑手册.md)。

## 算例与试验内容

| 算例或试验 | 主要用途 |
| --- | --- |
| 稳态层流圆管 `steady` | 对照 Poiseuille 解析关系，验证流量、速度与接口背压 |
| 无源项输运 `advection` | 验证温度及相分数的边界传递、域内输运和接口收支 |
| 阀门控制 `valve` | 展示控制事件介入、流量变化及三维压力反馈 |
| 基础验证 `validation` | 稳态网格细化、制造解、输运细化，以及 0.0625、0.125、1、5、10 ms 五档交换窗口扫描 |
| 探索试验 `exploratory` | 时间与空间分别细化、交换周期重复、松弛参数、8 倍内部步长差、31.25 μs 窗口与多次阀门动作 |
| 综合试验 `hardening` | 松弛参数重复比较、2 s／20 次阀门动作、联合细化、两侧故障注入与完整重跑 |
| 自动化测试 `-Tests` | 检查模型计算、控制逻辑和输入验证等基础功能 |

报告中的云图涵盖速度、压力、温度、相分数及温度绝对误差，并与误差统计、守恒分析和时间历程结合阅读。控制时刻按仿真时间定义，计算耗时按实际墙钟时间评价。

## 数据与文件校验

原始试验结果位于材料包的 `results/verification/`、`results/exploratory-study/` 和 `results/hardening-study/`。报告图像位于 `results/document-figures/`，设计与报告文本位于 `docs/`，源码和复现脚本分别位于 `src/` 与 `scripts/`。

[SHA256SUMS.txt](SHA256SUMS.txt) 记录主要交付文件及工程校验清单的 SHA-256；[FILE_SHA256.json](04可复现材料包/FILE_SHA256.json) 记录材料包内的文件哈希。复制完成后可据此检查文件完整性。依赖版本和许可证信息见材料包中的 [THIRD_PARTY.md](04可复现材料包/THIRD_PARTY.md)。
