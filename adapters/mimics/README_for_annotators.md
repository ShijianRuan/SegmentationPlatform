# Mimics 标注员说明

> 状态：阶段 A 脚本已实现；正式使用前必须由管理员完成 Mimics Research 21.0 工作站验收

标注者只负责核对图像并修正器官边界，不负责路径、格式、标签编号、生命周期状态和训练规则。

## 第一次使用

工作站只需要安装 Mimics Research 21。平台交付的工作包已经包含脚本和病例，也可能包含预生成 `.mcs`；不需要安装平台 Python、配置 Registry、填写本机 JSON 或修改病例路径。

平台会提前完成数据整理、病例包创建、空间映射和 Mimics 运行数据准备。若未预生成 `.mcs`，首次打开会由 Mimics 自动导入工作包中的 DICOM。提交后的 QC、标签版本登记和返修工作包由平台处理。

## 打开和切换任务

1. 打开 Mimics。
2. 建议把工作包根目录设为 Scripting Library；也可以从 `Script -> Run Script` 直接选择脚本。
3. 按需要运行：
   - `Labeling_Open_Next_Case.py`：直接打开下一例；
   - `Labeling_Case_Navigation.py`：继续上次病例、选择任意病例或暂时跳过当前病例。
4. 在 Mimics 显示的任务摘要中核对病例、图像序列和目标器官。
5. 若病例、序列、方向或初始 Mask 明显不符，运行 `Labeling_Submit_or_Report_Issue.py` 并选择 Report Problem。

不要直接双击历史 `.mcs`。通过对应的 `Labeling_*.py` 入口打开，脚本会检查任务版本和路径。

## 标注和保存

- 使用 Mimics 正常工具编辑平台创建的 Mask。
- 可以随时保存 `.mcs` 并关闭软件。
- 保存只保留进度，不会提交，也不会创建 verified 标签。
- 忘记当前病例、序列或目标器官时，运行 `Labeling_View_Task_List.py`；它会分页显示任务目标和当前 Mask 状态。
- 长时间工作或完成一个阶段后，运行 `Labeling_Save_Recovery_Backup.py`，额外保存全部 Mask 的恢复快照。
- 当前病例暂时不想处理时，运行 `Labeling_Case_Navigation.py` 并选择 Skip Case。
- 临时观察或试画可以自建 Mask，但它只是草稿参考，不会被平台提交或验证。若这个 Mask 需要成为正式标签，先联系平台管理员创建追加任务，再把内容转入平台创建的正式 Mask。
- 不自行改变平台 Mask 的器官名称或删除其任务 metadata。
- 不手工复制 header、重采样、改标签编号或导出 NIfTI。

## 提交

完成本次工作时：

1. 已完成时运行 `Labeling_Submit_Complete.py`。
2. 医学判断不确定或遇到数据/工具问题时运行 `Labeling_Submit_or_Report_Issue.py`，再选择 Needs Review 或 Report Problem。
4. 如果本病例包含多个目标组，再选择本次要提交的目标组。

| 选择 | 何时使用 |
| --- | --- |
| Complete | 本次目标已经达到标注要求 |
| Needs Review | 已经检查，但医学判断仍不确定 |
| Report Problem | 数据、方向、Mask 绑定或工具错误导致无法继续 |
| Cancel | 取消当前脚本，不生成提交 |

不要用 Report Problem 表示“今天先不标”。这种情况使用 `Labeling_Case_Navigation.py` 中的 Skip Case。

脚本只导出本次任务管理的 Mask，并提示“已导出，仍需平台检查”。如果项目里存在自建或非平台管理的 Mask，提交前会提示这些 Mask 不会被导出。平台随后独立运行格式转换和空间 QC；只有检查通过的“提交完成”才会生成新的人工确认标签版本。

最常见路径是单目标组、无空 Mask时直接运行 `Labeling_Submit_Complete.py`：不会先出现功能总菜单或提交类型菜单，只等待导出完成提示。

提交前脚本会聚合检查 Mask 是否齐全、是否绑定正确图像、基础标签版本和 shape。多个空 Mask 会先显示数量和前若干项，完整清单写入报告文件；可以统一选择“全部确认不存在”“全部待复查”，也可以逐项判断。

任务清单表示“本次希望处理哪些器官”，不表示平台已经提前知道哪些器官存在或不存在。不要因为图像看起来是局部扫描就自行删除目标 Mask；如果无法确认，提交复查或报告阻塞。

一个目标组需要复查或检查失败，不应阻塞同一病例其他已经完成的目标组。

## 继续和返修

- 未提交任务：运行 `Labeling_Case_Navigation.py`。
- 已提交任务：仍可通过 Case Navigation 的 Choose Case 重新打开、修正并重新提交。
- 提交前检查失败：弹窗列出主要问题，完整内容见 `reports/mimics_submit_precheck.json`。
- 平台 QC 失败：弹窗会列出主要问题和下一步动作。能修的 Mask 问题回到任务里修；提示版本、序列、几何或 hash 问题时不要手工改文件，联系平台管理员。完整技术报告见 `reports/review_report.json`。
- `.mcs` 损坏：不要删除病例包。管理员保留旧文件并从最近的 recovery backup 重建工作区。
- 已验证标签再修改：平台创建新的 `review_id`，旧标签作为基础版本；新结果形成新版本，不覆盖旧版本。
- 多位标注者：每个人使用独立任务和 `.mcs`，不要多人共享写同一项目文件。

## 出现异常时

以下情况不要自行绕过：

- 图像方向、spacing 或 origin 无法确认；
- Mask 与图像错位；
- Mask 绑定到错误序列；
- 应有的目标 Mask 缺失；
- 项目打开后病例或任务摘要不一致；
- 提交脚本报错或导出失败。

运行 `Labeling_Submit_or_Report_Issue.py` 并选择 Report Problem，保留 `.mcs` 和错误提示。

## AI 辅助标注（如果工作包包含 nnInteractive）

打开任一病例后，从 `Script -> Scripting Library -> nnInteractive` 启动 AI 工具：

- 在 Project Tree 中选中要修正的 Mask，或让工具创建新的结果 Mask。
- 通过 Point、Scribble、Box、Lasso 四种方式给 AI 提示。
- 每次提示后 AI 立即更新 Mask 结果。
- Undo 撤销最后一个提示，Reset 回到初始状态。
- Finish 结束，结果保留在 Mimics 中，可继续用标注工具手工修改后提交。

AI 工具第一次运行会加载模型（较慢），后续提示复用已加载的模型。
