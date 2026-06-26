# 阶段 A 辅助脚本

这里保存文件包阶段已经可用的、与具体标注或训练工具无关的小型命令。

## 当前可用

| 脚本 | 作用 | 额外依赖 |
|---|---|---|
| `hash_package.py` | 为病例包生成或检查传输哈希 | 无 |
| `check_case_package.py` | 检查病例包 v0.5 的图像空间、初始标签、Mimics `.u8` 提交、配置和哈希 | 无 |
| `windows/setup_mimics_workstation.ps1` | 在 Windows 创建虚拟环境并生成工作站本地配置 | PowerShell、Python 3.10+ |
| `windows/invoke_mimics_case.ps1` | 统一执行 Doctor、探针、Prepare、Open、Finalize 和状态查询 | 已完成工作站初始化 |

这些脚本只负责文件包预检查，不代替数据登记、训练数据快照或工具适配器。

病例包规则见 [病例包交换契约](../docs/domains/labeling/case_package_contract.md)。

## 病例包校验

```bash
python3 scripts/check_case_package.py dataset_package/cases/case_001
python3 -m unittest discover -s tests -v
```

校验器只接受 v0.5 目录和字段；发现旧版扁平 `labels/` 时直接报错，不做隐式迁移。

## 已转入 `sp` 工程

多标签拆分、图像/标签几何检查、病例包生成、Mimics 桥接、提交登记和 Snapshot 创建已经实现于 `src/segplatform/`，统一通过 `sp` 命令调用，不再增加互相独立的顶层脚本。
