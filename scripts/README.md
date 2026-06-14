# 阶段 A 辅助脚本

这里保存文件包阶段已经可用的、与具体标注或训练工具无关的小型命令。

## 当前可用

| 脚本 | 作用 | 额外依赖 |
|---|---|---|
| `hash_package.py` | 为病例包生成或检查传输哈希 | 无 |
| `check_case_package.py` | 检查病例包 v0.5 的 `image_sets`、`images/{image_id}`、`labels/{image_id}`、提交清单、目标输出、配置和哈希 | 无 |

这些脚本只负责文件包预检查，不代替数据登记、训练数据快照或工具适配器。

病例包规则见 [病例包交换契约](../docs/domains/labeling/case_package_contract.md)。

## 病例包校验

```bash
python3 scripts/check_case_package.py dataset_package/cases/case_001
python3 -m unittest discover -s tests -v
```

校验器只接受 v0.5 目录和字段；发现旧版扁平 `labels/` 时直接报错，不做隐式迁移。

## 尚未实现

以下命令只有在实际工作流需要时再添加：

| 计划脚本 | 作用 |
|---|---|
| `split_multilabel_to_masks.py` | 把多标签 NIfTI 拆成逐器官二值 Mask |
| `merge_masks_to_multilabel.py` | 把逐器官 Mask 合并为多标签 NIfTI |
| `check_geometry.py` | 比较图像与标签的 shape、spacing、方向和 affine |

README 中列出的计划脚本不应出现在“可执行命令”示例里，直到对应文件和测试真正存在。
