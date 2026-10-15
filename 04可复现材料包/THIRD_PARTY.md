# 第三方版本与获取方式

| 组件 | 版本与来源 |
| --- | --- |
| Ubuntu | 24.04；基础镜像摘要见 `containers/Dockerfile` |
| OpenFOAM | 2512；https://dl.openfoam.com/repos/deb ，镜像内使用 openfoam2512-dev |
| preCICE | 3.4.1；https://github.com/precice/precice/releases/tag/v3.4.1 ，校验与下载逻辑见 `scripts/prepare.py` |
| preCICE Python 绑定 | pyprecice 3.4.0；https://pypi.org/project/pyprecice/3.4.0/ |
| OpenFOAM adapter | 固定提交源码 ZIP：`third_party/openfoam-adapter-0801887b958f.zip`，完整提交信息及哈希见 `third_party/manifest.json` |
| preCICE tutorials | 提交 e31881130d79a160fde1ad9f4da3324f8d310b63；随附 `tutorials-e31881130d79.zip` |
| Python / GCC / Python 库 / 系统库 | 实际版本清单见 `environment/solver-environment.json`；直接依赖见 `requirements.txt` |

上游归属和许可证保留在各源码 ZIP、软件包和镜像中。OpenFOAM 开发源码位于镜像 `/usr/lib/openfoam/openfoam2512/src` 和 `applications`，本项目修改后的适配器源码位于 `/opt/cfd/openfoam-adapter`。扩展求解器的构建及改动见交付工程 `containers/`。preCICE 对应源代码可从 https://github.com/precice/precice/tree/v3.4.1 获取。

本项目使用 OpenFOAM 和 preCICE 的上游许可证条款；交付快照保留作者和许可文件，不改变第三方软件的归属。镜像中的 `/usr/share/doc/` 保留系统包的版权声明。
