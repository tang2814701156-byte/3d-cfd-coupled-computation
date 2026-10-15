# 可运行的双向耦合原型

本目录提供 Windows/Linux 启动入口、离线容器镜像及 [部署与复跑手册](部署与复跑手册.md)。源码和算例输入位于相邻的 [04可复现材料包](../04可复现材料包/README.md)。请完整复制 submission 并保持两个目录相邻。

安装并启动 Docker Linux 引擎，在本目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 -Case steady
powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 -Case advection
```

Linux 使用 `bash run.sh --case valve`、`bash run.sh --case steady` 或 `bash run.sh --case advection`。首次启动自动校验并导入 images 中的镜像。推荐 x86-64 Windows/Linux 主机；无需主机 Python、OpenFOAM 或 preCICE。

结果保存在相邻材料包的 results 目录。默认 valve 展示阀门控制及双向响应，steady 和 advection 为两类正式解析算例。
