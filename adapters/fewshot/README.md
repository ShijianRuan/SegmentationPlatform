# FewShot Adapter

> 日期：2026-06-08  
> 状态：架构位置已确认；实现后置。

FewShot Adapter 属于 `training` 域，和 `nnUNet Adapter` 平行。

它不是第一阶段必须实现的模块。当前只确认它的架构位置：

```text
Dataset Snapshot
  -> nnUNet Adapter
  -> FewShot Adapter
  -> future MONAI / Transformer Adapter
```

FewShot Adapter 只有在下面条件满足后才适合进入实现：

1. Data Registry 和 Dataset Snapshot 能冻结病例级数据。
2. 训练/验证/测试拆分能按患者级别固定。
3. 已有 nnUNet 同数据量基线。
4. 已定义 N-shot 实验协议，例如 N=1、3、5、10、20。
5. 评估集和准入标准已固定。

当前建议先把它当作实验层，不要直接做成平台核心能力。
