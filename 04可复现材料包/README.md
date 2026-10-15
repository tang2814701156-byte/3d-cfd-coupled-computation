# 可复现材料包

原型入口、离线镜像及 [部署与复跑手册](../02可运行的双向耦合原型/部署与复跑手册.md) 位于相邻的 02 目录。请完整复制 submission 并保持目录结构。

- `src/`、`scripts/`：源代码及分析、构建和运行脚本。
- `containers/`、`cases/`：求解器构建文件、全部算例输入和配置。
- `environment/`、`requirements.txt`：镜像标识、依赖清单和实际环境版本。
- `results/verification/`、`results/exploratory-study/`、`results/hardening-study/`：数值试验数据、统计、图表、误差分析和运行记录。
- `VERSION.json`、`.git`：提交版本与源码快照。
- `third_party/`、`THIRD_PARTY.md`：运行与构建依赖、版本、许可证及获取方式。
- `docs/`：设计说明与结果报告。
- `FILE_SHA256.json`：工程文件校验清单。

新运行输出使用独立目录。正式稳态配置为 `cases/submission-steady.json`。运行入口从当前交付目录解析路径。

从源码重新构建时，在本目录执行 `python scripts/build.py`，依赖及复现容差详见部署手册。

## 算例与试验运行

启动 Docker Desktop 的 Linux 容器引擎，在本 README 所在的 `04可复现材料包` 目录打开 PowerShell。运行依赖已包含在交付镜像中。

```powershell
# 算例一：稳态层流圆管，与 Poiseuille 解析解对照
powershell -NoProfile -ExecutionPolicy Bypass -File ".\run.ps1" -Case steady

# 算例二：无源项温度与相分数输运，与特征线解析解对照
powershell -NoProfile -ExecutionPolicy Bypass -File ".\run.ps1" -Case advection

# 阀门控制演示：毫秒级仿真时间控制与双向反馈
powershell -NoProfile -ExecutionPolicy Bypass -File ".\run.ps1" -Case valve

# 试验一：基础验证、细化与交换频率扫描
powershell -NoProfile -ExecutionPolicy Bypass -File ".\run.ps1" -Study validation

# 试验二：单因素细化、重复性与参数探索
powershell -NoProfile -ExecutionPolicy Bypass -File ".\run.ps1" -Study exploratory

# 试验三：综合性能、持续运行、故障注入与重新运行
powershell -NoProfile -ExecutionPolicy Bypass -File ".\run.ps1" -Study hardening

# 模型、控制逻辑与输入验证等自动化测试
powershell -NoProfile -ExecutionPolicy Bypass -File ".\run.ps1" -Tests
```

每次执行一条命令，结束后再执行下一条。批量试验包含多个工况，耗时明显长于单算例。Windows 入口会在同一终端显示求解日志和实时参数，无需提前定义变量或另外打开监控终端；输出目录自动生成，具体路径见终端输出。

监控字段包括仿真时间 t（s）、质量流量 mdot（kg/s）、背压 p（Pa）、温度 T（K）、相 A 体积分数 alpha、阀门开度 opening 和已接受窗口数 windows。稳态算例采用等温单相模型，T=300 K、alpha=1 为固定状态值；输运算例中温度和相分数随时间变化。

`hardening` 包含主动终止一维、三维参与者的故障注入，程序根据进程清理和数据保留情况判断是否符合预期；对应记录见本次输出下的 `execution_records.json`。运行完成并通过检查后，Windows 入口显示 `RUN AND CHECKS COMPLETED`。

新结果保存到本目录 `results/` 下的独立子目录；批量试验为各工况分别建立子目录。详细试验设计及结果分析见相邻交付文件 [一三维双向耦合算例验证报告](../03一三维双向耦合算例验证报告.docx)。
