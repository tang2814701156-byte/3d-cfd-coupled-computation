# 下载完整交付材料

本仓库根目录对应原 submission 目录。镜像和演示视频使用 Git LFS 保存，请安装 Git LFS 后执行：

```bash
git lfs install
git clone https://github.com/tang2814701156-byte/3d-cfd-coupled-computation.git
cd 3d-cfd-coupled-computation
git lfs pull
git lfs fsck
```

请优先使用上述方式获取完整文件。下载 ZIP 后，应确认镜像与视频不是只有几行内容的 LFS 指针文件。运行入口见 README.md。

原交付文件内容保持不变，包括全部试验原始数据及校验清单。工程目录内原有 .git 历史通过 `04可复现材料包/SOURCE_HISTORY.bundle` 保存；当前交付源码直接保存在工程目录，包含基线提交之后的工作区更新。恢复历史时请克隆到另一个目录：

```bash
git clone "04可复现材料包/SOURCE_HISTORY.bundle" source-history
```

历史包用于查看基线历史，复跑应使用本仓库的当前工程文件。`SHA256SUMS.txt` 和工程内 `FILE_SHA256.json` 对应原交付文件；新增 GitHub 下载说明、LFS 配置和历史包不在原清单内。
