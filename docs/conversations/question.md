# 

### 阶段 2：创建病例包

当源数据不是 DICOM（或被用在 nifti/metaimage 场景）时，当前 scan 步骤不适用的原因是：

1\.分组依据不存在（NIfTI 没有 PatientID/StudyUID/SeriesUID）

2\.无法自动聚类成"患者→检查→序列"三层

3\.扫描报告里 format 被硬编码成 "dicom\_series"，没法改成别的

如果数据源不是 DICOM，不是像读 DICOM 头一样自动分组。目前的 scan 没有实现分组，如果要支持非 DICOM，这是一个需要加的功能缺口。



当前代码完全没有考虑初始标签可能和图像混在一起，或者放在独立路径时如何自动发现:

两个核心问题没有解决：

问题 A：没有"标签发现"机制

当前没有任何代码做"扫某几个路径找可能的 mask 文件并匹配到对应的 image"。如果标签和图像在同一目录但按不同命名规则存放（比如 image\_001\.nii\.gz 和 image\_001\_mask\_liver\.nii\.gz），scan 阶段不认得这种约定。



问题 B：没有数据集级的 label mapping 配置

每次数据集可能都不一样：

数据集 A：每个器官一个独立 NIfTI，文件名前缀相同，只有后缀标识器官

数据集 B：一个多标签 NIfTI，voxel value 1=liver，2=spleen

数据集 C：一个多标签 NIfTI，但 1=spleen，2=liver

数据集 D：标签和图像完全分开放，靠一个 CSV 记录了配对关系

怎么解决上述情况



所有"数据集特有"的知识必须在 package create之前被消化完, 当前文档和代码给人一种"scan 能搞定一切"的错觉:

拿一个典型的外部数据集来拆解：

|**要做的事**|**TotalSegmentator**|**MSD Liver**|**某医院 DICOM 数据**|
|---|---|---|---|
|\(1\) 发现图像文件|NIfTI 在目录里|NIfTI 在目录里|DICOM，靠头分组|
|\(2\) 检查图像几何|nibabel 读，校验|nibabel 读，校验|pydicom 读，校验|
|\(3\) 分组到 case/study/image|一个文件 = 一个 image|一个文件 = 一个 image|DICOM 头自动分组|
|\(4\) 找到标签文件|同一个目录，同名加后缀|分开的目录，文件名无规律|可能没有初标|
|\(5\) 标签→器官映射|文件名前缀约定|一个多标签文件 \+ 配置|—|
|\(6\) 填充 initial\_labels|organ: 从文件名提取|label\_map: 从配置读|\[\]|
|\(7\) 构造请求 YAML|同一套结构|同一套结构|同一套结构|

现在对于这些等多种情况都能覆盖吗，需要思考如何更好地重新设计面对复杂的数据集状况



现在"比如NIfTI/MHD/MHA：按文件发现，同一父目录默认归为一个 Case；顶层文件各自成为独立 Case；RAW：没有明确 sidecar 时只报告为不可直接导入；复杂数据集：自动生成的请求只是草稿，仍需要人工或数据集描述文件补充“哪些文件是标签、标签值对应哪个器官、哪些序列应进入标注"，这种边界的设计实在有点过于简单了



"病例包可以登记 NIfTI/MHD，但 Mimics 21 主路径的首次打开仍以 DICOM 或已有 `.mcs` 为准。若标注工具选择 Mimics，非 DICOM 图像需要先转换成 Mimics 可接受的 DICOM/`.mcs` 工作区，或改用能原生打开该格式的标注工具"的内容也不符合要求，Mimics 21必须可以打开NIfTI/MHD，转换成DICOM/`.mcs` 是必要的吗，既然有python api以及mimics本身支持python。是否可以三方库读取然后导入到mimics中呢，我需要一个最佳实践



### 阶段 3：为 Mimics 准备任务队列

**`known_absent`** 的设计非常鸡肋，声明"这个病人已知没有这些器官"是并不会提前知道的，不打开病例前我不知道是什么部位数据是否没有哪些器官，腹部的数据是不可能标注头部的器官的，虽然头部器官在标注范围内，但是我是不会提前知道这套数据属于哪个部位。初始标签的器官 → Open 时自动创建 Mask，无初始器官的需要提醒标注者但是不希望打扰或者阻塞标注者，而是一个类似于标注者可以随时查看需要标注哪些器官的说明或设计，比如：利用 Mimics 的 Project Tree 下的 Custom 对象，Mimics 界面的左侧 Project Tree 中，除了 Images、Masks 等之外，还有一个 Custom 分区，可以放置测量点、注释等。脚本可以在这里创建一个"注释"条目，内容就是目标器官清单。这个注释会一直留存在 \.mcs 中，标注者随时可以在左侧看到。不过这种方式需要确认 Mimics Python 3\.5\.2 API 是否暴露了 Custom 注释的写入接口——当前代码中没有用过这个 API，诸如此类的方式都可以



### 阶段 4：标注者工作

SP Review Console、 Open Next Review等mimics使用的这些名称并不方便标注者理解，从标注者角度是否有可以优化的设计，或者做成图标啥的？不能做成图标是否可以改成易于理解的名字。核对：病例是否正确、有哪些序列、每个序列要标哪些器官。要核对的信息那么多，如果有一百多个器官，弹窗足够容纳吗，标注者理解成本高吗，所有弹窗设计都应该注意这些点。Ctrl\+S 保存 `.mcs`可以保存只保留进度，Save Checkpoint也可以保留进度，这是冗余的设计吗，是否真的必要，如有必要checkpoint 不自动清理——长期标注产生大量 checkpoint buffer



### 阶段 5：提交

和阶段4类似，设计或者名称都要保证易用性、易于理解性，尽可能较少交互和等待，保证标注更多的时间和精力在标注本身。



### 阶段 6：平台收尾

这一阶段是否支持批处理的，如果不同标注者分别标注了不同的数据，这一步是必须统一处理吗还是可以分别处理然后合并到一起



Snapshot 请求要求每个 case 显式指定 label\_id？对几十个病例来说可以手动写，但对几千个病例不可行



**在分配多标注者任务时是否有以下的卡点需要解决**：

卡点 1：病例包怎么分发到标注者的机器

数据量：一个病例几十到几百 MB。如果是多个病例给多个标注者，每个标注者只需要拿到自己分到的那些病例的目录，不需要整个 `dataset_package/`。



卡点 2：标注者机器上没有 Registry

标注者打开 Console → Open Next Review → 脚本调用 `sp review next --registry D:\platform_registry` → 如果 Registry 不在本机上，这个调用就失败。



卡点 3：提交后怎么把标签收回到中央机

标注者提交后，产出在 cases/case\_001/submissions/\{review\_id\}/：需要把这些提交文件拷回中央机，让中央机运行 sp mimics finalize。当前没有"收集提交"的命令——需要手动复制或写 shell 脚本？



卡点4：标注环境怎么准备可以直接迁移到不同标注者的机器上

每个标注者需要在本地准备标注环境，如何提前准备好以方便标注者傻瓜式迁移和使用





真实的标注场景中可能随时在变的，比如数据集在标注中可能在增加，标注任务可能在标注中需要增加器官，已经标注完的数据就需要重新进行标注，分配的数据可能不是都要标完的，考虑全面这些可能存在的真实场景，思考在现在的流程中是否支持，即使支持会不会引起大规模的从头再来或者已完成工作的丢弃和浪费

场景 1：数据集在标注中增加

这个场景当前支持，不需要放弃已有工作。已有的 50 个 case 的病例包、已提交的标签、已完成的 review 全部不受影响。scan\_source\(\) 是纯扫描，不修改任何已有记录。package create\-many（只创建新病例的包）但是这部分怎么加入到现有标注者的本地标注队列里



场景 2：标注任务中需要增加器官

假设你批量为 50 个病例创建了目标 \[liver, spleen\]。2 周后决定加 kidney。

|状态|数量|问题|
|---|---|---|
|已标完已提交 \(completed\)|30|只有 liver\+spleen 的标签，缺少 kidney|
|正在标注 \(in\_progress\)|15|标注者已经标了 liver\+spleen，现在要多标 kidney|
|尚未开始 \(ready\)|5|直接更新目标即可，怎么更新|

当前唯一的选择是 overwrite=True 重建——这会删除所有提交记录。这不是我想要的。 已完成的 30 个病例的 liver\+spleen 标注是有效的，不应该因为加一个 kidney 就丢弃。



场景 3：已标注完的数据需要重新标注

这个场景当前部分支持但手工操作多。文档明确写了：已验证标签要修改：新建 review\_id，旧标签作为 base label，不覆盖旧版本。



这个路径在最终 QC 和 Registry 层面是通的——新标签有 parent\_label\_id 指向旧标签，旧标签永久保留。但病例包层面没有增量更新机制：

1\.无法在已有病例包上追加一个 target

2\.没有"复用旧标签作为 base label 并增量标注"的便捷命令

3\.需要手写新的请求 YAML，指定 initial\_labels 指向已有的 verified label

4\.已经完成的工作（liver\+spleen）不会丢，但要用比较绕的方式才能把它们带进第二轮而不造成标注者的困惑



场景 4：分配的数据不是都要标完的

当前 next\_review\(\) 按时间取最早的未开始 review。如果一批 50 个病例里只需要标 30 个，当前唯一的方式是：

标完 30 个后，剩下的 20 个在队列里一直挂着；或者手动把这 20 个的 review 状态改成 blocked 或删除

没有"取 N 个然后跳过剩余"的机制。 SP Review Console 里也没有"跳过这个"的按钮——只有 Submit（完成/复查/阻塞）和 Checkpoint。没有一个既不标记完成也不标记阻塞的"先放一边"选项。



当前方式会导致的浪费

如果要走 `overwrite=True` 重建：

**旧 case 包被删除：**

`images/` ✅ 可以重新复制

`labels/` ✅ 可以重新从 `verified_label` 拆回初标

`submissions/` ❌ 已提交的 buffer 被删除

`reports/` ❌ 报告被删除

`manifest.json` ❌ 重新生成



标注者需要：

对 30 个已完成的 case，需要重新打开 review，补标 kidney

看到 liver\+spleen 的 Mask 已经存在（因为有 base label），只补 kidney

重新提交

第 2 轮 finalize 创建新版本的 Label Artifact



标注者的工作不是完全浪费——liver 和 spleen 的 Mask 已经存在，标注者只需要补 kidney。但提交记录、finalize 记录、review 的历史 event 全部丢失了（因为 case 包被 rm \-rf 了）。



更合理的方式是

不需要动已有的病例包。

新创建一个 case package，请求中：

图像指向同一份数据（或复用）

targets = \[kidney\]（只新增的器官）

initial\_labels 引用已有的 verified\_label（liver\+spleen）作为 base



标注者打开这个新 review 时看到：

liver 和 spleen 的 Mask 已经有内容（base label 注入）

kidney 的 Mask 是空的（新增，需要标）

他只标 kidney，提交

finalize 后得到一个新的 Label Artifact，包含 liver\+spleen\+kidney

parent\_label\_id 指向旧标签



标注者的已有工作完全保留，不需要重标 liver\+spleen。

但当前系统要做到这件事需要手动完成很多步：写 YAML、手动设置 base\_label\_id、手动确保图像路径复用。没有一条命令做“给已有病例追加器官”。



**已提到的场景**



- ✅ 数据集在标注中增加

- ✅ 标注中追加器官

- ✅ 已标完的需要重标

- ✅ 分配的数据不一定全标

    

**你未提及但真实存在的场景**

**场景 1：病例包创建到一半失败了**  

发生在 `create_case_package()` 中——没有 `try/finally` 清理：

case\_root\.mkdir\(parents=True\)                          \# 创建目录

\_copy\_image\(\.\.\.\)                                       \# 复制图像，已写入文件

\_write\_initial\_labels\(\.\.\.\)                             \# 写入标签 → 如果这里报错

write\_json\(manifest\)                                   \# 从未到达

registry\.put\("cases", \.\.\.\)                             \# 从未到达

case\_root\.mkdir\(parents=True\)                          \# 创建目录

\_copy\_image\(\.\.\.\)                                       \# 复制图像，已写入文件

\_write\_initial\_labels\(\.\.\.\)                             \# 写入标签 → 如果这里报错

write\_json\(manifest\)                                   \# 从未到达

registry\.put\("cases", \.\.\.\)                             \# 从未到达

结果：`cases/case_001/` 目录残留着部分图像和标签文件，Registry 中没有任何记录。下次重跑时因为 `case_root.exists()` 抛 `ValidationError`，必须手动删除目录或设 `overwrite=True`。没有自动清理。



**场景 2：Mimics 崩溃导致提交只导出了一半**  

用户点 Submit → 导出第 2/4 个器官的 buffer 时 Mimics 崩溃：

submissions/review\_001/

buffers/img\_venous/target\_abdomen/liver\.u8      ✅ 已导出

buffers/img\_venous/target\_abdomen/spleen\.u8     ✅ 已导出

buffers/img\_venous/target\_abdomen/kidney\_left\.u8 ❌ 正在导出时崩溃

export\_manifest\.json                             ❌ 还没写

结果：两个孤立的 `.u8` 文件占着磁盘，但 `finalize.py` 因为找不到 `export_manifest.json` 永远不会处理它们。标注者不知道这是"部分提交"还是"没提交过"。



**场景 3：旧标签永远不"退休"**  

每次 finalize 创建新标签时：

label\_record = \{

"label\_id": "label\_xxx\_v2",

"artifact\_lifecycle": "active",    \# ← 新的 active

"parent\_label\_id": "label\_xxx\_v1", \# ← 指向旧的

\}

旧标签的 artifact\_lifecycle 仍然是 "active"

`label_xxx_v1` 和 `label_xxx_v2` 同时 active。标签索引中两者并列。`find_labels()` 返回 2 个结果。Snapshot 必须手动指定 `label_id`，否则报错。短期内可以接受——但迭代 10 轮后，一个器官有 10 个 "active" 标签，索引查询和管理完全混乱。缺少 "superseded" 生命周期状态来标记旧版本。



**场景 4：没有"跳过"语义**  

标注者打开一个 review，发现：

- 图像质量太差，不想标

- 今天累了，想先标别的

- 这个病例不是他的专长

当前 Console 里只有：Submit（完成/复查/阻塞）和 Save Checkpoint。没有 "Skip / 先放一边" 按钮。如果选 "Report Blocked"，review 状态变成 blocked，但这意味着"无法完成"，不是"先跳过"。平台操作者需要手动介入才能把 blocked 的 review 重新分配。



**场景 5：Checkpoint 越积越多，磁盘撑爆**  

标注者每天 Save Checkpoint 几次。一个月后：

working/checkpoints/review\_001/

20260601T100000/   \# \~200 MB

20260601T160000/   \# \~200 MB

20260602T090000/   \# \~200 MB

\.\.\.

20260630T170000/   \# \~200 MB

latest\.json

没有自动清理策略。也没有命令说"保留最近 5 个，删掉更早的"。一个活跃的标注工作站一个月可能积累几十 GB 的 checkpoint 数据。



**场景 6：同一 DICOM 序列被多次复制到不同病例包**  

如果一个 DICOM 序列出现在两个不同的标注批次中：

dataset\_package\_batch1/cases/case\_001/images/img\_venous/dicom/  → 200 个文件，\~100 MB

dataset\_package\_batch2/cases/case\_099/images/img\_venous/dicom/  → 同一批文件，再占 100 MB

没有共享存储或去重机制。对大规模标注来说磁盘浪费很可观。



**场景 7：自动 finalize 时标注者不知道失败原因**  

`sp_review_console.local.json` 中设了 `auto_finalize: true`。标注者点 Submit → 后台 finalize 失败 → 显示 "Platform QC finished: failed"。标注者不知道具体为什么失败（是哈希不匹配？几何不一致？空 Mask？），需要去翻 `reports/review_report.json`。



