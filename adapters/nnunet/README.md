# nnUNet Adapter

> 日期：2026-06-07  
> 状态：概念已明确；当前实现仍主要复用 `pipelines/nnunet/`。

这个目录保留给“平台数据如何导出成 nnUNet 可消费格式”的适配层。

当前真实情况是：

- 训练核心代码在 `pipelines/nnunet/`
- `ModelMap.toml` 和 `Config_*.toml` 仍是现有任务入口
- 平台级的 `Dataset Snapshot -> nnUNet_raw` 导出逻辑还没有独立抽出来

因此，这个目录目前先作为明确落点，避免“蓝图里有 nnUNet Adapter，但仓库里没有位置”的虚实差距。
