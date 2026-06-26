# 医学图像少样本学习与少样本分割调研

> 核查日期：2026-06-14
> 阅读前提：具备基本深度学习和医学图像分割知识

内容覆盖少样本学习、原型学习、医学少样本分割、上下文学习和模型适配。TTA、持续学习和交互式学习只在概念边界中说明，不与少样本学习并列成主线。

文中的“代码公开”只表示能够找到作者或项目方发布的仓库，不自动代表代码易于复现、权重可商用或适合临床使用。开源许可、权重限制和仓库完整度分别记录。

## 0. 先建立整体认识

少样本学习不是一种单独的网络，也不等于“随便取几例数据训练”。它是一类问题设定：模型需要利用很少的新任务标注，完成对新类别、新解剖结构或新数据域的识别和分割。

医学图像少样本分割目前主要有四条可理解、可实验的路线：

1. **少量病例训练或微调现有分割模型**：例如用 1、3、5、10 个病例训练或微调 nnU-Net。这是工程上最重要的基线。
2. **基于 support/query 的原型或元学习分割**：support 图像和掩膜用于描述目标器官，模型通过特征匹配分割 query 图像。SSL-ALPNet、ADNet、RPT 属于这条发展线。
3. **少样本域适应**：已有源域模型和少量目标域标签，目标是适应新中心、扫描协议或解剖区域。PFMNet、DGST 一类工作回答的是这个问题。
4. **推理时上下文分割**：给预训练通用模型若干图像和掩膜示例，模型无需针对新任务重新训练。UniverSeg、Tyche、Neuroverse3D、Medverse 属于这条发展线。

四条路线并不互相替代：

- 第一条最接近常规医学分割训练，也是判断复杂方法是否真正有效的基准。
- 第二条适合研究“如何从少量标注中构造稳定的类别表示”。
- 第三条要求存在可迁移的源模型，主要解决域变化，不自动获得未见器官能力。
- 第四条追求一个模型适应多种未见任务，但需要大规模、多任务预训练，其训练成本并不“少样本”。

**基本实践原则**：先建立病例级 low-shot 监督基线，再根据目标选择预训练/PEFT、原型方法、域适应或 in-context 方法。不能因为某篇论文报告了 1-shot 结果，就跳过数据划分、重复采样、全数据基线和独立测试集。

---

## 第一部分：基本概念

### 1. 什么是少样本学习

#### 1.1 问题定义

普通监督学习假设训练阶段有足够多的带标签数据。少样本学习关注的是：面对一个新类别或新任务时，只有少量标注样本，模型如何仍然获得可接受的泛化能力。

经典 few-shot protocol 包含以下对象：

| 概念 | 含义 |
| --- | --- |
| Support set | 少量已标注样本，用于训练、微调、构造原型或作为推理上下文 |
| Query set | 当前 episode 中用于计算损失或评价的样本 |
| Test set | 最终独立评估集，不能参与支持样本选择和调参 |
| N-way | 一个 episode 中需要区分的类别数 |
| K-shot | 每个类别提供的支持样本数 |
| Episode | 一次 support/query 任务采样 |
| Base class | 训练阶段见过的类别 |
| Novel class | 评价时需要用少量样本适应的新类别 |

在分类任务中，5-way 1-shot 表示一次任务包含 5 个类别，每类提供 1 个支持样本。分割任务的输出是像素或体素标签，因此 support 不只是图像，还必须包含目标 mask。

#### 1.2 “少量数据训练”与标准 few-shot protocol 的区别

以下两种实验都常被称为少样本，但回答的问题不同：

**Low-shot supervised training**

- 从一个固定任务的数据集中只取 K 个病例训练。
- 模型仍然是普通监督模型。
- 重点是样本效率、预训练和过拟合控制。
- nnU-Net 1/3/5/10-shot 属于这一类。

**Episodic few-shot learning**

- 训练时反复构造 support/query episode。
- 目标是学到可迁移到 novel class 或 novel task 的适应机制。
- 原型网络、PANet、SSL-ALPNet、ADNet 属于这一类。

二者都值得做，但结果不能混在同一张表中直接比较。前者通常针对固定任务，后者通常强调类别泛化。

#### 1.3 医学分割里的 shot 到底是什么

医学图像中最容易犯的错误，是把切片数当成独立样本数。同一患者相邻切片高度相关，100 张切片不等于 100 个独立病例。

对 3D CT/MRI 分割，推荐将 shot 定义为：

```text
1 shot = 1 个患者级、一次检查级、具有目标器官可靠标签的 3D case
```

如果论文使用 2D slice 作为 support，需要明确：

- support slice 是否来自独立患者；
- support 是否覆盖目标器官完整范围；
- query 与 support 是否来自同一 volume；
- 评价结果是 slice-level 还是重建后的 volume-level。

医学体数据实验宜默认采用病例级 shot；复现采用 slice-level protocol 的论文时，应明确报告切片与患者之间的关系。

#### 1.4 医学分割中四种常被混称为 few-shot 的问题

| 问题设定 | 新任务时是否训练 | 少量标注怎样使用 | 主要回答的问题 | 常见维度 |
| --- | --- | --- | --- | --- |
| Low-shot supervised segmentation | 是 | 作为普通监督训练集 | 固定任务只有 K 个病例时能训练到什么程度 | 2D/3D |
| Episodic few-shot segmentation | 通常在元训练阶段训练；新任务可免训练 | support mask 构造原型或条件表示 | 能否适应元训练未见的类别 | 以 2D 为主，也有 3D |
| Few-shot domain adaptation | 是 | 微调源域模型或对齐源/目标特征 | 同一目标在新中心、新协议或新解剖区域能否快速适应 | 2D/3D |
| In-context segmentation | 新任务时不更新参数 | 作为推理上下文 | 一个通用模型能否按示例完成未见任务 | 2D 较成熟，3D 正在发展 |

这四种设定不能仅按“用了几例数据”区分。关键是先回答：

1. 新任务是否更新模型参数；
2. 新任务是新类别、新数据域，还是同一个固定任务；
3. support 是训练数据、元学习 episode，还是推理输入；
4. 模型是否提前在大量相关任务上学习过适应能力。

因此，“fully supervised”和“few-shot”并不矛盾。一个模型可以只使用 5 个病例，但这 5 个病例都提供完整像素级标签；它仍然是**全监督的 low-shot 训练**。反过来，UniverSeg 在新任务上可能只需要少量 support，但模型本身是在大规模分割任务集合上训练得到的。

#### 1.5 少样本协议中的任务、类别与域

后文真正需要区分的是三种变化：

| 变化 | 定义 | 医学分割例子 |
| --- | --- | --- |
| Novel class | 元训练时没有使用过该类别标签 | 训练 episode 使用肝、脾、肾，测试时用少量 support 分割胰腺 |
| Novel task | 输入、目标或输出规则发生变化 | 从器官分割转为肿瘤分割，或从单器官二分类转为多器官分割 |
| Target domain | 目标类别不变，但图像分布发生变化 | 同为肝脏分割，从 A 医院门静脉期 CT 迁移到 B 医院平扫 CT |

一个 **few-shot task** 通常写作：

```text
T = (support set S, query set Q, target definition)
```

- `S` 提供少量已标注示例，定义本次任务；
- `Q` 提供需要预测的样本，训练时可带标签计算损失，最终推理时没有可见标签；
- target definition 说明要分割哪个类别、采用何种标签语义和评价规则。

`base class`、`novel class` 是相对于元训练标签集合定义的，不是器官天然具有的属性。同一个胰腺，在一项实验中可以是 base class，在另一项实验中可以是 novel class。

同样是“一例 support”，任务难度也可能完全不同：

- 同中心、同模态、未见患者：主要考查病例泛化；
- 不同中心、同器官：同时包含域偏移；
- 未见器官：考查类别级适应；
- 不同模态、未见器官：同时包含类别和强域偏移。

### 2. 与相邻概念的边界

| 概念 | 核心问题 | 与少样本学习的关系 |
| --- | --- | --- |
| Transfer learning | 如何把预训练知识迁移到目标任务 | 是最常用的少样本实现手段 |
| Meta-learning | 如何学到快速适应新任务的机制 | 是经典少样本研究路线 |
| Semi-supervised learning | 少量标注加大量无标注数据如何训练 | 数据条件不同，不等同于 few-shot |
| Weakly supervised learning | 用点、框、图像级标签代替完整 mask | 降低标注粒度，不等同于 few-shot |
| Active learning | 应优先标注哪些样本 | 可帮助构建更有价值的 support set |
| Domain adaptation | 如何适应不同中心、设备或协议 | 目标是域变化，不一定有 novel class |
| Test-time adaptation | 推理时利用目标域数据调整模型 | 属于部署适应，不是少样本训练协议 |
| Continual learning | 连续学习新任务时如何减少遗忘 | 属于模型更新和治理问题 |
| In-context learning | 推理时用示例定义任务，不更新模型参数 | 是基础模型时代的少样本适应路线 |
| Promptable segmentation | 用点、框、文本等提示当前图像中的目标 | 提示通常提供实例位置，不等于类别级 support |

#### 2.1 少样本标注与 SAM 提示不是一回事

SAM 的点或框通常告诉模型“当前图像的目标在哪里”。切换到新图像后仍需要新的提示。few-shot support image + mask 则试图告诉模型“需要分割的概念是什么”，并把这一概念迁移到 query 图像。

二者可以组合。例如 ProtoSAM 先用支持图像构造目标原型，再自动生成点和框交给 SAM 精修。但 SAM 本身不会因为提供一个框就自动获得跨病例的器官概念。

#### 2.2 常见派生设定

| 设定 | 数据条件 | 医学场景 | 与基础 FSS 的差异 |
| --- | --- | --- | --- |
| Semi-supervised few-shot | 少量标注 support + 较多无标注数据 | 新中心只有少量标签，但有大量历史扫描 | 还需要伪标签、一致性或无监督损失 |
| Cross-domain few-shot | base 与 novel 来自不同域 | 不同中心、模态、场强或重建协议 | 类别泛化与域偏移同时存在 |
| Generalized few-shot | 推理时同时预测 base 与 novel class | 新增器官后仍需保留原有器官能力 | 必须处理 base/novel 偏置和类别冲突 |
| Transductive few-shot | 允许同时观察一批未标注 query | 批量离线适配某个新中心 | 可利用 query 分布，但不适合严格逐例在线推理 |
| Weakly supervised few-shot | support 只有点、框、涂鸦或粗 mask | 完整 3D 标注成本过高 | 同时减少样本数和单例标注精度 |
| Multimodal few-shot | support/query 含图像、文本或其他模态 | 图像加器官名称、报告或序列信息 | 需要处理模态对齐和缺失模态 |

这些设定会显著改变实验难度。比如 cross-domain 1-shot 失败，可能是 support 太少，也可能是域偏移过大；不能只归因于原型构造。实验设计应把“少标签”“未见类别”“未见域”作为不同变量。

#### 2.3 不要把四个独立维度混成一个方法名

一项医学分割研究通常同时具有四类属性：

| 维度 | 常见取值 | 回答的问题 |
| --- | --- | --- |
| 标注数量 | zero-shot、one-shot、few-shot、full-data | 有多少目标任务标注 |
| 监督信号 | supervised、self-supervised、semi-supervised、weakly supervised | 训练信号从哪里来 |
| 适应机制 | from scratch、fine-tuning、prototype matching、meta-learning、ICL | 模型怎样利用少量信息 |
| 变化类型 | 新病例、新类别、新任务、新域、新模态 | 模型究竟要适应什么 |

这些标签可以同时成立。例如：

```text
在大量无标签 CT 上做自监督预训练
    -> 在 5 个完整标注病例上全监督微调
    -> 从 A 医院迁移到 B 医院
```

这项实验同时属于：

- 自监督预训练；
- 全监督 fine-tuning；
- 5-shot/low-shot；
- few-shot domain adaptation。

这里保留这四个维度，是为了正确描述实验，而不是展开普通深度学习概念。尤其要避免把“用了 foundation model”“做了自监督预训练”直接等同于具备 few-shot 泛化能力；是否成立仍取决于目标任务上的 K-shot 协议。

---

## 第二部分：实验协议与方法基础

### 3. 少样本实验为什么难以比较

少样本结果对 support 选择极其敏感。某一例恰好形态标准、层厚合适，可能让 1-shot 结果明显偏高；另一例包含病变、术后改变或扫描范围不完整，则可能使结果显著下降。

一份可信的医学少样本实验至少要说明：

1. shot 的单位是病例、体数据还是切片；
2. train/support、validation/query、test 是否按患者隔离；
3. support 是否从固定 train pool 中采样；
4. 是否重复多个随机 support set；
5. support 数量是按器官计算还是按多器官病例计算；
6. 是否使用了目标测试集信息进行检索、归一化或调参；
7. 预处理、spacing、裁剪和强度归一化是否固定；
8. 标签是否完整，未标器官是否被错误当作背景；
9. 是否同时报告 full-data 和相同 K 值的普通监督基线。

#### 3.1 推荐的评价结构

| 评价维度 | 推荐内容 |
| --- | --- |
| 重复性 | 每个 K 值至少使用多个固定随机种子，报告 mean/std 和 worst repeat |
| 分割质量 | Dice、HD95 或 Surface Dice、体积误差 |
| 失败分析 | 按病例列出严重漏分、错分和空预测 |
| 分层分析 | 按器官、中心、扫描协议、层厚或病种分层 |
| 样本效率 | 1/3/5/10/20-shot 曲线，而不是只报一个 K |
| 基线 | 从零训练、预训练后微调、full-data 上界 |
| 资源 | GPU、训练时间、推理时间、支持集大小 |

#### 3.2 四种常见评价目标

**固定任务的数据效率**

目标是回答：“腹部 8 器官任务有多少病例时可以达到可用性能？”
适合使用 nnU-Net low-shot、预训练和 PEFT。

**未见类别泛化**

目标是回答：“训练时没有见过肝脏标签，给一例肝脏 support 后能否分割？”
适合原型网络和 episodic FSS。

**少样本域适应**

目标是回答：“已有源中心或源解剖区域模型，只有少量目标域标签时能否稳定迁移？”
适合 full fine-tuning、PEFT、DGST 和专门的 few-shot domain adaptation。

**未见任务的上下文适应**

目标是回答：“一个通用模型能否根据若干图像-mask 示例，在不训练的情况下完成新的分割任务？”
适合 UniverSeg、Tyche 和 3D ICL。

如果没有先写清评价目标，所谓“few-shot 效果更好”没有可解释含义。

#### 3.3 增加 support 不一定持续带来同等收益

一些方法的实验显示，support 数量增加后，性能提升会逐渐变小。但这个现象不能被写成固定的“饱和点”，更不能直接推导为所有医学任务在某个 K 值后都不再需要标注。

收益曲线会受到以下因素影响：

- support 是否覆盖典型和异常解剖；
- 目标是单器官还是多器官；
- 评价的是 2D 切片还是完整 3D 病例；
- support 与 query 的中心、模态和扫描协议差异；
- 模型如何使用 support；
- 标签质量和任务难度。

因此，实验不应只比较 1-shot 和一个较大的 K 值。更稳妥的做法是选择若干 K 值，例如 1、3、5、10，并为每个 K 固定多组 support 病例。这样才能看到平均收益、波动和最差情况。

#### 3.4 医学 FSS 中容易被忽略的标签可见性

多器官 CT 中，即使某个器官被定义为 novel class，它仍然可能真实出现在元训练图像里，只是没有作为前景标签使用。此时模型可能通过背景区域间接见过其外观。

文献中的具体 setting 命名并不完全统一，但应至少区分：

| 情况 | 元训练时 novel organ 是否出现在图像中 | 是否提供 novel 标签 | 难度与风险 |
| --- | --- | --- | --- |
| Label-unseen but image-visible | 可能出现，并通常并入背景 | 否 | 模型可能间接学习其外观；背景监督还可能把它推离前景 |
| Image-excluded novel class | 尽量排除含 novel organ 的训练图像或区域 | 否 | 更接近严格未见类别，但医学全身图像中很难做到 |
| Cross-domain novel class | novel organ 还来自不同中心或模态 | 否 | 同时存在类别和域偏移，最难 |

因此，“训练时没用该器官标签”不自动等于“模型从未见过该器官”。实验必须说明 novel 区域在 base-training 图像中如何处理：

- 当作背景参与 loss；
- 使用 ignore mask 排除；
- 裁剪或筛除包含 novel class 的图像；
- 保留图像但不使用对应区域监督。

这四种处理会改变问题难度，也会改变背景 prototype 的含义。

#### 3.5 2D 医学 FSS 的 support slice 对齐

完整 3D 器官在不同轴向位置的外观差异很大。用 support 中器官最大面积切片去分割 query 的所有切片，通常无法覆盖器官头尾部形态。常见策略包括：

| 策略 | 做法 | 隐含信息 |
| --- | --- | --- |
| Fixed support slice | 固定一张或少数 support 切片 | 最简单，但对形态变化最脆弱 |
| Relative-position matching | 按器官或 volume 的归一化 z 位置匹配 support/query | 使用了空间位置先验 |
| Partition-based support | 将器官范围分段，每段选择 support 切片 | 增加覆盖，但实际 support 数可能超过表面上的 1-shot |
| Feature retrieval | 按图像或特征相似度检索 support slice | 使用 query 信息，属于检索式适配 |
| 3D support | 整个 support volume 参与匹配 | 信息完整，但计算和实现成本高 |

论文写“1-shot”时，可能指一个 support volume，而推理过程中从该 volume 使用多张切片；也可能只指一张 support slice。两者标注成本、可用信息和复现难度不同，必须分开记录。

如果 support-query 对齐使用了 query 的真实器官范围、真实 mask 或由真值计算的相对位置，就构成测试信息泄漏。可接受的位置匹配必须只依赖图像元数据、自动定位结果或预先定义的无标签规则。

### 4. 经典少样本学习方法谱系

#### 4.1 数据增强和生成

增强不是少样本学习特有的方法，只是 low-shot 训练的重要控制变量。少样本实验需要额外注意三点：

1. 不同方法必须尽量使用相同增强预算，否则增益可能来自训练策略而不是 few-shot 机制；
2. support 与 query 的增强关系要明确：二者独立增强可提高鲁棒性，共享几何增强则可能泄漏对应关系；
3. 3D 病例不能把相邻切片经过互不一致的随机几何变换后仍称为完整体数据。

生成式增强、feature hallucination 或合成病灶只有在独立消融中证明有效时，才应计入少样本方法收益；生成样本不能被计作新的真实 shot。

#### 4.2 度量学习和原型学习

**度量学习**的目标，是学习一个适合比较样本的特征空间和相似度规则。模型不直接记住“肝脏的固定外观”，而是学习把语义相同的区域映射到较近的位置，把不同区域映射得更远。

这里的“度量”可以是：

- 余弦相似度；
- 欧氏距离；
- 由小型神经网络学习的 relation score；
- attention 或相关性矩阵产生的匹配分数。

因此，度量学习不只是“选一个距离公式”。真正重要的是 encoder 是否学到了可迁移的特征表示。

**原型学习**是度量学习的一类。prototype 是一个类别在特征空间中的代表向量或代表集合。它不是器官的平均形状、模板 mask，也不是标签编号。

Prototypical Networks 的基本思想是用每个类别支持样本的平均特征作为 prototype：

```text
support image + support mask
        |
        v
提取前景/背景特征并聚合
        |
        v
foreground prototype / background prototype
        |
        v
与 query 每个像素或体素特征计算相似度
        |
        v
query segmentation
```

以一例肝脏 support 为例：

1. encoder 把 support CT 转成 feature map；
2. support mask 指出哪些位置属于肝脏；
3. 取这些位置的特征并求平均，得到 liver prototype；
4. 对 query CT 的每个位置提取特征；
5. 计算每个 query 特征与 liver prototype 的相似度；
6. 高相似位置更可能被预测为肝脏。

第 3 步常称为 **masked average pooling**：mask 内的特征参与聚合，mask 外特征不参与。若同时构造背景 prototype，则会对前景和背景分别聚合。

一个简化表达是：

```text
prototype_c = support 中类别 c 的特征平均值
score_c(x) = query 位置 x 的特征与 prototype_c 的相似度
prediction(x) = 得分最高的类别
```

更形式化地，设第 `k` 个 support 图像的特征为 `F_s^k`，类别 `c` 的二值 mask 为 `M_s^{k,c}`，最基本的 K-shot prototype 为：

```text
p_c =
  sum_k sum_x [M_s^{k,c}(x) * F_s^k(x)]
  ------------------------------------------------
  sum_k sum_x M_s^{k,c}(x)
```

其中 `x` 是像素或体素位置。这个公式直接把所有 support 的目标区域合并后求均值，但实际实现有三种常见 K-shot 聚合：

| 聚合方式 | 做法 | 优点 | 风险 |
| --- | --- | --- | --- |
| Pixel-pooled | 汇总所有 support 前景位置后统一求均值 | 简单，目标体积大的 support 贡献更多 | 大器官病例可能支配 prototype |
| Shot-averaged | 每个 support 先生成 prototype，再对 K 个 prototype 等权平均 | 每例权重相同 | 小而不完整的 support 也获得同等权重 |
| Learned aggregation | attention 或小型网络学习各 support/区域的权重 | 可降低低质量 support 影响 | 增加参数，少样本下更易过拟合 |

对 query 特征 `F_q(x)`，常用余弦相似度：

```text
s_c(x) = cosine(F_q(x), p_c) / tau
P(y(x)=c) = softmax_c(s_c(x))
```

`tau` 是温度参数，用于控制 softmax 分布的尖锐程度。训练损失通常是 query mask 上的交叉熵、Dice loss，或二者组合。也就是说，support 标签用于产生 prototype，真正反向传播的监督通常来自 query 标签。

**1-way 与 N-way 分割**

- `1-way`：一个 episode 只定义一个目标器官，输出前景/背景二分类；
- `N-way`：同一 episode 同时定义 N 个目标类别，每类有自己的 support 和 prototype；
- `K-shot`：每个类别有 K 个 support，不一定等于总共有 K 个病例；
- 多器官完整标注病例可能同时为多个 way 提供 support，但要明确每类是否都具有完整标签。

医学 FSS 论文大量采用 1-way 1-shot，因为它把问题简化为逐器官二分类。将多个这样的模型用于全身多器官时，还要解决类别竞争和重叠，不能把 N 个独立二分类结果直接视为一个 N-way 模型。

实际医学方法通常不会只保留一个平均向量。prototype 可以是：

- 一个全局前景向量；
- 多个局部原型；
- 按区域、尺度或边界构造的原型集合；
- 根据 query 进一步校正的动态原型。

**前景原型与背景原型**

前景通常是一个相对明确的器官，背景则包含其他器官、骨骼、脂肪、病灶和扫描外区域。用一个背景均值描述这些结构，往往比构造前景原型更困难。这也是 ADNet 选择只稳定建模前景、把偏离前景的区域视为异常的原因。

**原型是怎样学会可迁移的**

prototype 本身通常由当前 support 即时计算，真正通过训练长期保存的是 encoder 的参数。episodic training 会不断更换 support/query 和目标类别，迫使 encoder 学到一种表示，使新类别也能通过少量 support 被描述和匹配。

一个标准训练 episode 的计算过程是：

1. 从 base classes 采样本次 episode 的 N 个类别；
2. 每类采样 K 个 support，并另采样 query；
3. 对 support/query 做一致的空间和强度预处理；
4. 从 support mask 聚合前景、背景或局部 prototype；
5. 计算 query 每个位置与 prototype 的相似度；
6. 使用 query 真值计算分割损失并更新特征提取网络；
7. 可选地加入 prototype alignment、对比损失、边界损失或一致性损失。

元测试时通常不再更新主网络参数，只用 novel class support 重新计算 prototype，再分割 query。若方法还要在 support 上梯度微调，就应明确归为带适应步骤的方法，而不是纯 prototype inference。

**Prototype alignment**

PANet 的核心不是简单再算一次 prototype，而是加入双向约束：

1. 用 support prototype 分割 query；
2. 从 query 预测中重新聚合 query prototype；
3. 用 query prototype 回头分割 support；
4. 用 support 真值约束回分割结果。

这样做要求 support 与 query 的类别表示具有可逆一致性，减少 prototype 只适合单向匹配的情况。但 query prototype 来源于预测 mask，早期错误也可能被反向放大。

**局部原型为什么有用**

全局平均会把器官内部的不同区域压成一个向量。例如肝脏内部血管附近、边缘和实质区的特征并不完全一致。局部原型常按以下方式构造：

- 把 support feature map 划分为规则网格；
- 按超像素或超体素聚合；
- 只在 mask 覆盖充分的局部窗口中生成 prototype；
- 使用聚类得到多个代表中心；
- 在多尺度特征层分别构造 prototype。

预测时，可以让每个 query 位置与所有局部 prototype 比较，取最大相似度、加权和或 attention 聚合。局部原型提高表达能力，也带来 prototype 数量、窗口大小、聚类数和匹配复杂度等超参数。

**Query-guided prototype refinement**

support 单独产生的 prototype 可能无法覆盖 query 的成像差异。一些方法先得到粗 query mask，再利用高置信 query 区域修正 prototype：

```text
support prototype
    -> query 粗预测
    -> 选择高置信 query 特征
    -> 与 support prototype 融合
    -> refined prototype
    -> query 精预测
```

这属于 transductive 或 query-aware 适配。优势是利用目标图像自身分布，风险是粗预测错误会形成确认偏差，因此通常需要置信度筛选、双向一致性或迭代次数限制。

**原型方法中的常见损失**

| 损失 | 作用 |
| --- | --- |
| Query segmentation loss | 直接监督 query mask，是基本训练目标 |
| Prototype alignment loss | 约束 support/query 双向类别表示一致 |
| Contrastive loss | 拉近同类特征或 prototype，推远不同类别 |
| Boundary loss | 让边界区域拥有更可区分的表示 |
| Consistency loss | 约束不同增强、尺度或迭代预测保持一致 |
| Prototype diversity loss | 避免多个局部 prototype 坍缩为相同表示 |

增加辅助损失必须说明其监督信息来自哪里。若使用 query 真值构造 refined prototype，却在测试时无法获得 query 真值，训练和推理会产生信息不对称。

原型方法易于解释，但有四个核心困难：

1. 一个平均向量难以覆盖器官内部的多样形态；
2. 背景包含大量异质结构，单一背景原型通常不可靠；
3. support 与 query 的位置、尺度和成像域差异会破坏特征对应；
4. 2D support slice 可能根本没有覆盖器官在头尾方向的完整形态。

PANet 的 prototype alignment、SSL-ALPNet 的自适应局部原型、ADNet 的前景异常检测、RPT 的区域原型校正，都是围绕这些困难展开。

后续方法大致沿六个方向发展：

| 方向 | 核心思想 | 代表方法 | 更适合的场景 |
| --- | --- | --- | --- |
| 局部/区域原型 | 避免用单个均值描述整个器官 | SSL-ALPNet、RPT | 器官内部异质、形态变化明显 |
| 多代表描述符 | 保留多个前景模式，减少均值坍缩 | GMRD | support 中包含多个外观或部位模式 |
| 细节自精炼原型 | 聚类前景的多模态结构，并补充通道级背景结构 | DSPNet | 前景细节和复杂背景都难以由均值表示 |
| 图推理 | 在原型或区域间建立关系图 | PGRNet | 需要表达空间或语义关系 |
| 向量量化 | 通过离散码本保留中间特征结构 | VQ 路线 | 单一 masked average 丢失信息时 |
| 前景异常检测 | 只稳定建模前景，弱化背景原型 | ADNet | 背景极复杂且不稳定 |

这些方法多数以 2D slice 和 one-way binary segmentation 为主。若目标是完整 3D 多器官分割，需要额外解决切片选择、跨切片一致性、多器官冲突和体素级空间恢复，不能仅凭论文中单器官 2D Dice 判断可用性。

**从 2D 扩展到 3D 时真正发生了什么**

| 方案 | 技术做法 | 优点 | 局限 |
| --- | --- | --- | --- |
| Slice-wise 2D | support/query 都按切片处理 | 复现最容易，显存低 | 不使用跨切片信息，support slice 对齐敏感 |
| 2.5D | 输入相邻切片，但预测中心切片 | 增加有限上下文 | 仍不是完整 3D，边缘切片处理复杂 |
| 3D patch prototype | 在 3D patch/feature block 内聚合体素原型 | 利用局部体空间 | support/query patch 对应和器官覆盖困难 |
| Full-volume 3D | 整个重采样 volume 形成上下文 | 语义完整 | 显存高，分辨率和器官尺度差异大 |

3D prototype 不能只把公式里的像素换成体素。器官体积差异会影响 pooled prototype，patch 采样会决定 support 是否覆盖目标，重采样也会改变小结构。因而 3D 实验必须同时记录 spacing、patch 策略、前景采样比例和 support 覆盖范围。

#### 4.3 元学习

**元学习（meta-learning）**不是一种具体网络，而是“从许多任务中学习如何快速适应新任务”的训练思想，也常被概括为 learning to learn。

普通监督训练学习的是一个固定映射：

```text
图像 -> 固定标签空间中的预测
```

元学习希望学习的是一种适应过程：

```text
少量 support 描述当前任务
        +
query 图像
        ->
当前任务的 query 预测
```

因此，元学习的数据组织单位通常不是单张图像，而是**任务或 episode**。一个 episode 模拟一次未来适应：

```text
任务：分割肝脏
support：少量 CT + 肝脏 mask
query：另一批 CT + 肝脏 mask
目标：利用 support 正确分割 query
```

下一个 episode 可以改为脾脏、心脏或其他任务。模型跨大量 episode 更新，学习哪些特征、初始化或更新规则更有利于快速适应。

**元训练、元验证与元测试**

| 阶段 | 作用 | 类别或任务要求 |
| --- | --- | --- |
| Meta-training | 通过大量 episode 学习适应机制 | 使用 base classes/tasks |
| Meta-validation | 选择超参数和 checkpoint | 应与最终测试隔离 |
| Meta-testing | 给少量 support，评价 novel task/class | novel class 不应出现在元训练标签中 |

如果所谓 novel organ 已经作为元训练标签出现，实验评价的是新病例或新域适应，而不是严格的未见类别 few-shot 泛化。

常见路线包括：

- **学习度量**：Matching Networks、Prototypical Networks、Relation Networks；
- **学习初始化**：MAML，使模型用少量梯度步骤适应新任务；
- **学习优化器或更新规则**：用另一个模型控制参数更新；
- **学习动态参数或记忆**：根据 support 生成部分权重、条件参数或任务表示。

这些路线学习的对象不同：

| 路线 | 元训练真正学到什么 | 新任务如何适应 | 典型成本 |
| --- | --- | --- | --- |
| Matching Networks | support-query attention 与特征空间 | 对 query 与全部 support 做加权匹配 | K 增大时匹配成本上升 |
| Prototypical Networks | 适合类中心表示的特征空间 | 每类聚合 prototype 后做距离分类 | 简单稳定，但均值可能丢失结构 |
| Relation Networks | 一个可学习的相似度函数 | 对 support/query 特征对计算 relation score | 参数更多，域外泛化未必稳定 |
| MAML | 易于少量梯度更新的初始化 | support 上做若干步 fine-tuning | 内外循环成本高 |
| Learned optimizer | 参数更新规则本身 | 由另一个网络产生更新 | 实现复杂，对任务分布依赖强 |
| Hypernetwork/dynamic weights | 从 support 生成任务条件参数 | 一次前向生成部分模型参数 | 参数生成稳定性和规模受限 |

原型网络通常属于**基于度量的元学习**：新任务时不一定更新模型参数，而是根据 support 计算 prototype。MAML 属于**基于优化的元学习**：它学习一个容易被少量梯度步骤调整的初始化。二者都可以使用 episode，但适应机制不同。

**MAML 的内外循环**

MAML 类方法包含两层优化：

1. **内循环**：在当前 episode 的 support 上做少量梯度更新，得到任务适配参数；
2. **外循环**：用适配后的参数在 query 上计算损失，再更新共享初始化；
3. 反复更换任务，使共享初始化适合快速适应。

```text
共享初始化 θ
    -> support 上更新几步
    -> 得到任务参数 θ'
    -> query 上评价 θ'
    -> 用 query 损失改进 θ
```

外循环关心的不是模型在 support 上记得多好，而是“经过少量 support 更新后，能否在未见 query 上表现好”。这正是元学习与普通小数据训练的核心区别。

设共享初始化为 `theta`，任务 `T_i` 的 support loss 为 `L_Si`，query loss 为 `L_Qi`，单步 MAML 可写为：

```text
theta_i' = theta - alpha * grad_theta L_Si(theta)

theta <- theta - beta * grad_theta
         sum_i L_Qi(theta_i')
```

- `alpha` 是内循环学习率；
- `beta` 是外循环学习率；
- `theta_i'` 只服务于当前任务；
- 更新共享 `theta` 时，需要考虑 `theta_i'` 是怎样由 `theta` 得到的。

标准 MAML 因而涉及二阶梯度。First-Order MAML 忽略部分二阶项以降低计算和显存；Reptile 则通过让初始化靠近各任务适配后的参数来近似学习可快速适应的初始化。这些简化降低成本，但并不自动解决医学分割中的任务不足和域偏移问题。

**分割中的内循环怎样定义**

在医学分割里，MAML 的 support loss 不是分类样本上的简单交叉熵，通常需要选择：

- Dice、cross-entropy 或复合分割损失；
- support 是完整 volume、2D slice 还是 patch；
- 每次内循环更新全模型、decoder、normalization 还是部分参数；
- 内循环步数和学习率；
- query loss 是否使用同一器官、同一患者或同一域。

1-shot 3D 情况下，如果把一个 volume 切成大量 patch 做内循环，统计上仍然只有一个独立患者。patch 数量不能被当成额外 shot。

**Episode 分布必须模拟最终使用方式**

元学习优化的是从训练任务分布 `p(T)` 到测试任务的迁移。如果元训练 episode 与最终场景不匹配，算法即使收敛也可能学错适应方式。

| 最终目标 | 元训练 episode 应怎样构造 |
| --- | --- |
| 未见器官适应 | 以器官类别划分 base/novel，episode 在不同器官间切换 |
| 跨中心同器官适应 | task 应包含中心或协议变化，而不只是随机患者切片 |
| 3D 病例级适应 | support/query 必须按患者隔离，不能从同一 volume 抽相邻切片 |
| 多器官适应 | episode 需要明确 N-way 竞争和缺失标签处理 |
| 病灶分割 | episode 应覆盖大小、数量、边界和阴性病例差异 |

这解释了为什么“在单一数据集里随机切 support/query”不一定是真正有价值的 meta-learning：模型可能只学会同分布图像匹配，而没有学习跨任务适应。

**元学习、episodic training 和原型学习的关系**

| 概念 | 是什么 | 三者关系 |
| --- | --- | --- |
| Meta-learning | 学习快速适应机制的总体思想 | 上位概念 |
| Episodic training | 用 support/query 任务模拟未来适应的训练组织方式 | 常用于元学习，但不是唯一方式 |
| Prototype learning | 用类别代表特征进行匹配的方法 | 常通过 episodic training 训练，是度量型元学习的一类 |

三者不能作为互斥算法并列。更准确的表述是：“该方法采用 episodic training，学习一个基于 prototype matching 的适应机制。”

训练时通常反复采样 episode：

```text
选择任务或类别
    -> 采样 support image + mask
    -> 采样 query image + mask
    -> 由 support 产生适应结果
    -> 在 query 上计算损失
    -> 跨 episode 更新模型
```

一个可复现的 episodic sampler 至少要冻结：

- base/validation/novel 类别列表；
- patient-level 数据池；
- N-way、K-shot 和每个 episode 的 query 数；
- 是否允许同一患者出现在 support 与 query；
- 前景为空的切片如何处理；
- 类别和器官是否均匀采样；
- support/query 的增强是否独立；
- episode seed 和总 episode 数。

医学数据类别不平衡明显。若按病例均匀采样，大器官和常见器官会主导训练；若按类别均匀采样，则稀有类别可能被反复使用并过拟合。采样策略本身是方法的一部分，不能只报告网络结构。

医学分割使用元学习时，需要定义足够多、差异足够大的训练任务。只有一个器官、一个中心和很少病例时，复杂 meta-learning 往往没有足够的任务多样性，未必优于普通迁移学习。

MAML 一类基于梯度的元学习还会带来二阶梯度、内外循环和显存开销；prototype-based episodic training 的实现通常更直接，因此在医学 FSS 中更常见。无论采用哪种形式，都要说明 novel class 是否真的没有在元训练标签中出现，否则实验可能只是同类数据上的低样本训练。

**元学习何时值得使用**

更有利的条件：

- 可获得多个训练器官、任务或中心，能够形成真实任务分布；
- 未来会反复遇到新任务，而不是只做一次固定器官训练；
- 新任务标注极少，且需要快速、标准化适应；
- 有严格的 base/novel 隔离和重复 episode 评价。

不利条件：

- 只有一个固定器官和一个小数据集；
- 目标是把现有 nnU-Net 在该任务上做到最好；
- 任务间标签定义、模态和空间预处理差异过大；
- 无法构造患者级无泄漏 episode；
- 计算资源不足以支持嵌套优化或大规模 episodic training。

元学习也不等于 in-context learning。二者都可以在新任务中使用 support，但：

- 经典元学习强调训练阶段显式学习“如何适应”，新任务时可能计算 prototype 或执行梯度更新；
- ICL 强调预训练模型在推理时把 context 直接作为输入，通常不更新模型参数；
- 一些 ICL 模型本身也采用 episodic/meta-training，因此两者在训练方式上可能重叠，区别主要落在新任务时的接口和参数更新行为。

#### 4.4 迁移学习、预训练和参数高效微调

工程上最常见的少样本路线是：

1. 在大规模相近数据上预训练；
2. 用少量目标病例微调；
3. 通过冻结部分层、较小学习率或正则化减少过拟合。

可训练参数的范围可以分为：

| 方式 | 可训练部分 | 特点 |
| --- | --- | --- |
| Linear/head tuning | 仅输出头 | 成本低，但表达能力受限 |
| Decoder tuning | 解码器或末端层 | 适合迁移相近的编码特征 |
| Full fine-tuning | 全模型 | 灵活，但低样本时更易过拟合 |
| Adapter/LoRA/SSF | 新增小模块或缩放平移参数 | 适合大模型或多任务适配 |

**少样本迁移究竟在优化什么**

设预训练参数为 `theta_0`，目标域只有 K 个标注病例。最普通的 fine-tuning 是：

```text
theta* = argmin_theta L_target(theta; D_target^K)
```

少样本下的问题是 `D_target^K` 太小，直接优化容易让 `theta` 偏离已有知识并记住 K 个病例。常见约束方式包括：

| 策略 | 技术含义 | 主要假设 |
| --- | --- | --- |
| 冻结部分参数 | 只更新输出端、decoder 或 normalization | 预训练特征已经足够通用 |
| 小学习率/早停 | 限制参数离开 `theta_0` 的速度 | 目标任务与预训练任务相近 |
| Weight regularization | 显式惩罚 `theta` 偏离 `theta_0` | 原参数是有价值的先验 |
| PEFT | 仅学习低维更新或附加模块 | 目标适应可由少量自由度表达 |
| Gradient selection | 每步只更新最敏感的参数 | 重要参数随任务和迭代变化 |
| Feature alignment | 缩小 source/target 表示差异 | 域差异可在特征空间对齐 |

如果 source 和 target 只是中心不同，常以同一标签空间微调；如果目标器官或类别数变化，则输出层通常必须重建，能否迁移主要取决于编码表示和空间特征是否相关。

**少样本域适应与普通 fine-tuning 的区别**

few-shot domain adaptation 明确存在 source domain 和 target domain。除目标监督损失外，方法还可能使用：

```text
L = L_target_supervised
  + lambda_align * L_domain_alignment
  + lambda_reg * L_parameter_or_feature_regularization
```

- `L_target_supervised` 使用少量目标域标注；
- `L_domain_alignment` 对齐 source/target 的全局、区域或 prototype 分布；
- 正则项用于防止小样本微调过拟合或遗忘源域能力。

是否还能访问 source 数据是重要设定：

- **Source-present adaptation**：适配时可联合使用源数据，较容易做特征对齐和重放；
- **Source-free adaptation**：只能使用源模型和少量目标数据，隐私和存储更友好，但约束更强；
- **Cross-domain FSS**：不仅域变化，还要求用 support 适应 novel class，难度高于同类别域适应。

预训练来源可以分为：

- **任务相关监督预训练**：例如先在相同模态、相近器官或大规模多器官标签上训练；
- **自监督预训练**：例如 MAE、对比学习或位置感知预训练，不依赖目标分割标签；
- **通用视觉编码器**：例如 SAM/DINOv2 的图像编码器，但自然图像先验不保证直接适合 3D 医学数据；
- **医学基础模型**：在大量 CT/MRI 或多任务数据上训练，再迁移到目标任务。

预训练是否有效，首先取决于模态、空间维度、解剖区域和预处理是否匹配。一个在 2D 自然图像上预训练的编码器，与一个在大规模 3D CT 上预训练的 nnU-Net 编码器，不应笼统写成同一种“预训练模型”。

LoRA（Low-Rank Adaptation）在原权重旁增加低秩更新，合并权重后可不增加推理路径。SSF 只学习逐层缩放和平移参数。Adapter 在网络层之间插入小型 bottleneck 模块。对 CNN，LoRA 需要明确作用于卷积核、注意力层还是其他线性映射，不能直接照搬 Transformer 的 Q/K/V 配置。

LoRA 对一个二维权重矩阵的典型更新为：

```text
W' = W + scale * B * A
```

其中原权重 `W` 冻结，只训练低秩矩阵 `A`、`B`。对 3D 卷积核，必须选择展平、分解或卷积专用 LoRA 形式；不同实现的参数量和表达能力并不等价。

Adapter 通常把输入特征经过降维、非线性变换和升维后，以残差形式加回：

```text
h' = h + W_up * activation(W_down * h)
```

它适合为不同任务保存独立小模块，但会改变模型结构和 checkpoint 管理。SSF 只学习通道级 scale/shift，参数最少，但当目标域需要较大空间或语义变化时可能不足。

DGST 则不是新增固定 adapter，而是在每次迭代中按梯度选择少量重要参数更新。已公开的淋巴结工作以 nnU-Net v2 为基础，在头颈部预训练后对新淋巴结数据集做少样本微调。它说明“少更新参数”不只等于 LoRA，但其证据目前集中在特定 CT 淋巴结迁移任务，不能直接泛化到所有器官。

PEFT 并不保证优于全量微调。是否有效取决于预训练任务和目标任务的接近程度、样本量、模型结构和正则化。合理的比较顺序是先建立 low-shot 全监督基线和预训练 full fine-tuning，再评价 PEFT。可直接复现的 3D 医学分割实现见第 7 章。

#### 4.5 nnU-Net 在少标注研究中的定位

nnU-Net 是训练和评估基线，不是专门的 few-shot 算法。涉及 nnU-Net 的少标注实验可按初始化和参数更新方式分为：

| 名称 | 怎样训练 | 是否改变 nnU-Net 架构 | 本质 |
| --- | --- | --- | --- |
| K-case nnU-Net from scratch | 只用 K 个完整标注病例运行普通 nnU-Net 训练 | 否 | 全监督 low-shot 基线 |
| Pretrained nnU-Net full fine-tuning | 载入兼容预训练权重，再更新全部参数 | 通常否 | 少样本迁移学习 |
| nnU-Net partial fine-tuning | 冻结 encoder 或大部分参数，只训练 decoder、输出头、bias/norm | 否 | 简单参数高效适配 |
| nnU-Net + LoRA/Adapter/DGST | 训练低秩模块、Adapter 或动态选中的参数 | 是或需要自定义 Trainer | PEFT 研究路线 |
| nnSAM | 加入冻结的 SAM/MobileSAM 编码特征和曲率辅助目标 | 是 | 架构增强的目标任务监督训练 |

这四者都不同于经典 episodic FSS。它们通常不会在推理时接收一个新的 support set，也不会因为给出一例新器官 mask 就自动分割该器官；每个目标任务仍需训练或微调一个模型。

**K-case nnU-Net from scratch 的实际做法**

1. 先在患者级固定 train/validation/test；
2. 从 train pool 选择 K 个病例，形成一个冻结的 K-shot subset；
3. 使用与 full-data 基线一致的标签定义、预处理和评价；
4. 对每个 K 使用多个固定 subset 和随机种子；
5. 分别训练 2D、3D full-resolution 或其他已选 nnU-Net configuration；
6. 在同一个独立 test set 上报告均值、标准差、最差重复和空预测率。

这里的“fully supervised”只说明 K 个病例提供完整像素/体素标签，并不说明病例很多。“K-case 全监督 nnU-Net 基线”是准确表述，但它不应被列为一个新的少样本模型。

实际组织时，推荐每个 `(K, subset_id)` 对应一个不可变的数据快照，并导出稳定的 `splits_final.json`。可以把 K 个训练病例物化为独立 nnU-Net dataset，也可以复用预处理结果并通过自定义 split 限定训练病例；无论采用哪种方式，都必须证明 trainer 没有读取 subset 外的标签。

还要单独计算验证集的标注预算。若论文写“5-shot”，但使用另外 20 个完整标注病例调参和选择 checkpoint，那么它不是总计只使用 5 个标签病例。建议同时报告：

```text
train shots = 5
validation labeled cases = N
test labeled cases = M
pretraining labeled cases = P
```

test 标签只用于最终评价，不算训练预算，但不能用于选 support、调阈值或挑 checkpoint。

**nnU-Net 自动规划带来的比较问题**

nnU-Net 根据 dataset fingerprint 生成计划，包括目标 spacing、patch size、batch size、网络拓扑和配置。若每个 K-shot subset 都重新 fingerprint 和 re-plan，K 变化可能同时改变训练数据和系统配置。两种实验设计都可以，但含义不同：

- **固定计划**：从共同数据定义生成一套计划，各 K 复用。更适合比较算法和样本量；
- **每个 K 独立规划**：评价 nnU-Net 作为完整自动化系统在该 subset 上的表现，但必须记录 plan 差异。

为了比较不同 K 值，宜固定标签空间、预处理规范和主要 configuration；如果允许重新规划，要把 plans 文件随实验保存，不能只记录 K 值。

**预训练 nnU-Net 与普通 K-shot nnU-Net 的区别**

普通 K-shot nnU-Net 从随机初始化开始，只能从 K 个病例学习图像表征和分割映射。预训练版本先从更大数据中获得结构或成像先验，再在相同 K 个目标病例上适配。公平比较必须保持 K 病例、test set、训练预算和评价方式一致，并单独说明预训练数据是否包含目标病例、相同患者或目标测试数据。

**nnSAM 与普通 K-shot nnU-Net 的区别**

nnSAM 论文中的核心结构是并行的 nnU-Net 编码器和冻结的 SAM/MobileSAM 编码器；两路特征融合后送入 nnU-Net 解码器，并通过分割头与基于水平集曲率的回归辅助目标共同训练。它不是 prompt-based SAM，也不是推理时 few-shot。其论文实验使用有限标注的 2D 医学数据；仓库虽然沿用 nnU-Net 命令接口，但论文未建立原生 3D nnSAM 的证据。因此：

- 可以把它作为“2D 目标任务、有限标签下引入 SAM 特征先验”的研究对照；
- 不能把它直接称为已验证的 3D few-shot nnU-Net；
- 必须与相同 K、相同 2D configuration 的普通 nnU-Net 比较，才能判断增益来自 SAM 特征、曲率辅助目标还是其他训练差异。

**复现难度判断**

| 方案 | 2D/3D | 复现难度 | 主要额外工作 |
| --- | --- | --- | --- |
| K-case nnU-Net from scratch | 2D/3D | 低 | 冻结 subset、重复实验、保存 plans |
| 预训练 nnU-Net fine-tuning | 取决于 checkpoint | 中 | 权重兼容、迁移层映射、预训练泄漏检查 |
| Decoder/head tuning | 2D/3D | 低到中 | 冻结策略和学习率设置 |
| LoRA/Adapter/SSF nnU-Net | 2D/3D，依实现而定 | 中到高 | 官方 nnU-Net 没有通用开关；需修改网络、checkpoint 格式和训练器 |
| DGST | 已有 3D CT 实例 | 高 | 自定义 trainer、动态参数选择、任务外验证 |
| nnSAM | 论文证据以 2D 为主 | 中到高 | SAM 权重、双编码器特征融合、旧版 nnU-Net 兼容 |

#### 4.6 In-context learning

In-context segmentation 在推理时接收一组支持样本：

```text
context = {(image_1, mask_1), ..., (image_K, mask_K)}
target = query image
output = query mask
```

模型参数在新任务上不更新，任务由 context 定义。它的优势是一个模型可以处理多种任务；代价是模型必须在训练阶段见过大量、足够多样的分割任务。

**Context 如何进入模型**

医学 in-context segmentation 常见三类机制：

| 机制 | 技术做法 | 代表性特点 |
| --- | --- | --- |
| Feature interaction | 分别编码 context image、context mask 和 target，再跨样本交互 | 适合显式 support-target 匹配 |
| Task representation | 将多个 context 聚合为 task token、task embedding 或条件参数 | context 数变化时更容易复用 |
| Joint sequence/modeling | 把 context 与 target 组织为统一序列或空间输入 | 表达能力强，但显存和输入长度敏感 |

以 feature interaction 为例，模型可能在每一层执行：

```text
context image feature + context mask feature
        -> task-conditioned context representation
        -> 与 target feature 做 cross-attention/cross-convolution
        -> target mask
```

它与简单 prototype 的区别是，context 信息不一定先压缩成一个类别均值，而可以在多个尺度和网络层与 target 交互。

**Context set 的置换与数量问题**

理论上，context 是一个集合，交换 support 顺序不应改变结果。实现中需要使用置换不变聚合，例如求和、平均、集合注意力，或者通过训练降低顺序敏感性。若模型把 context 直接拼接成序列，则必须实测顺序是否影响预测。

context 数量增加还会带来：

- 显存和计算随 support 数增长；
- 低质量或域外 support 可能稀释有效信息；
- 不同器官或任务的 context 可能互相冲突；
- 训练时最大 context 数限制测试时可用数量；
- 3D context 的空间尺寸、spacing 和方向必须兼容。

因此，ICL 实验不仅比较 K，还应比较 support 质量、顺序、检索策略和上下文冲突。

**ICL 的训练并不是零成本**

训练阶段通常仍需从大量数据集采样 task episode：

1. 选择一个分割任务或标签语义；
2. 从该任务采样若干 context image-mask pairs；
3. 采样独立 target image；
4. 让模型依据 context 预测 target mask；
5. 用 target 真值更新模型；
6. 跨数据集、模态、器官和任务重复。

只有训练任务足够多样，模型才可能在新任务上把 context 当作“任务说明”，而不是记忆固定器官。所谓新任务免微调，不等于训练阶段只用了少量数据。

需要特别区分：

- **零微调推理**：只改变 context，不改变模型参数；
- **上下文检索**：从标签库选择与 query 相似的 support；
- **上下文优化**：优化任务 token 或隐变量，但不一定更新模型；
- **few-shot fine-tuning**：直接用支持样本更新模型参数。

这些方式的计算、审计和复现要求不同，不能都笼统写成 ICL。

---

## 第三部分：医学图像少样本分割的发展

### 5. 医学图像为什么更困难

医学 few-shot 的困难不仅是样本少，还包括：

#### 5.1 病例不是独立同分布的普通图像

同一患者的多期检查、同一 volume 的相邻切片、同一中心的固定协议都具有强相关性。切片级随机划分会造成泄漏。

#### 5.2 标签昂贵且不一定完整

数据集常只标注一个器官或一个病灶。未标注不能自动解释为不存在。少样本实验如果把缺失标签写成背景，会产生错误监督。

#### 5.3 3D 空间关系重要

2D 方法可能在单切片上得到合理 mask，但跨切片不连续。对体积、手术规划或后续定量分析，3D 一致性是必要要求。

#### 5.4 域偏移强

设备、重建核、增强期、视野、层厚和患者群体都会改变图像分布。少量 support 很难同时覆盖所有变化。

#### 5.5 背景远比自然图像复杂

目标器官通常相对一致，背景却包含多个器官、骨骼、脂肪、病灶和扫描外区域。传统前景/背景双原型容易让背景表示失真。

#### 5.6 小目标和异常解剖更脆弱

肾上腺、血管、淋巴结、术后结构和小病灶在 few-shot 下更容易出现空预测或严重边界误差。平均 Dice 会掩盖这些失败。

### 6. 发展脉络

#### 6.1 通用 FSS 奠定 support-query 原型框架

Prototypical Networks 建立了类别原型思想。PANet 在 few-shot semantic segmentation 中加入 prototype alignment，使 support 到 query 和 query 到 support 的预测相互约束。医学方法随后大量沿用这一框架。

PANet 的训练目标可概括为：

```text
L_total = L_support_to_query + lambda * L_query_to_support
```

- `L_support_to_query`：由 support prototype 分割 query；
- `L_query_to_support`：从 query 预测构造 prototype，再回分割 support；
- 第二项迫使 support/query 的类中心在同一特征空间中保持一致。

推理时只保留 support 到 query 的方向，不需要 query 真值。其核心贡献是把“prototype 能否双向复用”变成训练约束，而不是增加一个更复杂的分割 decoder。

PANet 不是医学专用方法，但理解它有助于理解后续方法为什么反复讨论 prototype、alignment 和 foreground/background。

#### 6.2 SSL-ALPNet：减少元训练对人工标签的依赖

SSL-ALPNet 在 ECCV 2020 提出用超像素伪标签构造自监督 episode，不要求元训练阶段拥有大量人工语义标签。其 Adaptive Local Prototype Pooling 用多个局部原型缓解前景和背景不平衡。

它的训练链路是：

```text
未标注医学图像
  -> 超像素分割
  -> 随机选择一个超像素区域作为伪前景
  -> 构造 support/query 自监督 episode
  -> support 伪 mask 生成局部/全局 prototype
  -> 分割 query 中的对应区域
```

这里的“自监督”不是生成真实器官伪标签，而是把局部相干的超像素当成临时类别，训练模型在构造出的 support/query 伪任务中学习区域匹配。元测试时，超像素任务被真实器官 support mask 替换。

Adaptive Local Prototype Pooling 的关键是：不把整个前景或背景压成单一均值，而是在局部窗口中聚合 prototype。局部窗口只有在 mask 覆盖足够时才产生有效类别表示，并与全局 prototype 一起参与 query 匹配。这样可以：

- 为小前景保留局部细节；
- 将异质背景拆成多个局部模式；
- 减少大面积背景在平均池化中支配类别表示。

超像素数量、窗口尺度和 mask 覆盖阈值会直接改变 prototype 数量和质量，因此它们不是无关紧要的预处理参数。

它的重要贡献不是“解决了所有医学 few-shot”，而是证明了：

- 3D 医学图像自身的空间结构可以产生自监督任务；
- 少样本分割模型可以在没有目标器官人工元训练标签的情况下学习匹配机制；
- 局部原型比单一全局原型更适合异质结构。

官方仓库包含腹部 CT、腹部 MRI 和心脏 MRI 的预处理与训练脚本。据其 README 和 requirements 记录，依赖栈较旧（PyTorch 1.3 等），实际复现前应确认是否能在现代 CUDA/PyTorch 环境中重建。

#### 6.3 ADNet：不再显式建模复杂背景

ADNet 在 Medical Image Analysis 2022 提出 anomaly detection-inspired FSS。它只建模相对同质的前景原型，把偏离前景原型的 query 像素视为异常，并学习阈值完成分割，从而避免用有限 support 去概括高度异质的背景。

其基本评分过程是：

```text
support foreground mask
  -> 单一 foreground prototype p_fg

query feature f_q(x)
  -> 与 p_fg 的相似度或距离
  -> anomaly score a(x)
  -> 与学习阈值比较
  -> foreground/background
```

这里“anomaly”的参照物是前景 prototype：与前景表示足够接近的位置判为目标，偏离的位置归入背景。它没有尝试学习一个能覆盖所有背景组织的 `p_bg`。

阈值是方法的重要组成部分。如果阈值固定，不同器官、模态和域的特征尺度变化会导致预测面积不稳定；ADNet 因而学习分割阈值，并通过 episode 训练使前景距离与阈值共同适配。该设计更适合单一、相对同质的前景，不自然支持多个前景类别同时竞争。

它同时使用 3D supervoxel 形成自监督任务。官方仓库包含 2D 和 3D 的腹部、心脏训练与推理脚本，并提供 Dockerfile。

supervoxel 相比逐切片 superpixel 利用体数据连续性生成伪任务，但最终是否为原生 3D 网络仍要看具体训练配置；“用 3D supervoxel 生成标签”与“全流程使用 3D 特征匹配”是两件事。

ADNet 的方法价值在于重新审视“背景原型是否必要”。其局限是阈值和前景表征仍可能受域偏移、边界模糊和多类别任务影响。

#### 6.4 原型细化：从单一均值走向区域、局部和多代表表示

后续工作主要沿以下方向改进：

- 将前景拆为多个区域原型；
- 通过 cross-attention 对齐 support/query；
- 用 query 信息修正 support prototype；
- 显式建模边界和局部结构；
- 用多个描述符表达类内多样性。

代表方法可按“prototype 中保留了多少结构”理解：

| 方法 | 关键机制 | 医学任务与维度 | 开源与复现判断 |
| --- | --- | --- | --- |
| RPT | 将 support 前景细分为区域 prototype；BaT block 自选择并迭代抑制干扰，最终校正全局 prototype | 2D episodic FSS | 官方代码、预处理数据和权重公开；环境和路径配置较旧 |
| VQ 路线 | 将 support 特征量化为 codebook，避免 masked average 丢失细节 | 2D 医学 FSS | 论文公开；截至本次核查未确认可直接复现的官方实现 |
| DSPNet | 前景空间聚合保留多模态结构，背景通道调节补充细节，形成高保真 prototype | 2D 医学 FSS | 官方仓库公开，但 README 较简略，需自行重建数据协议 |
| GMRD | 为每类生成多个 representative descriptors；MAMP 融合多张 affinity map，并用双路径平衡前景/背景 | 2D 医学 FSS | 官方代码公开，依赖 PyTorch 1.10.1/CUDA 10.2，仓库未声明标准许可 |
| PGRNet | prototype-guided graph reasoning，建模区域或原型间关系 | 2D 医学 FSS | 官方代码公开，需下载特征编码器权重，仓库未声明标准许可 |
| PFMNet | 学习 prototype feature mapping，将少量目标域 prototype 映射到源域表示空间后分割 | 2D 医学域适应 | 论文公开；未确认官方代码，不适合作为首批复现对象 |

RPT、GMRD、DSPNet 和 PGRNet 等工作的共同目标，是减少“一个平均前景向量”造成的信息损失。它们在机制上有研究价值，但公开实现多使用各自的数据预处理、fold 划分、2D 切片规则和旧依赖，复现难度高于 low-shot nnU-Net。

VQ 方法进一步指出，masked average 可能不是原型学习唯一合理的聚合方式；通过离散码本保留局部模式，可以把“类别表示”从单一向量扩展为可组合的视觉词。但这条路线仍需验证码本是否跨中心、模态和器官稳定。

这些方法可以映射回原型流水线的不同改动点：

| 改动点 | 方法示例 | 要解决的问题 |
| --- | --- | --- |
| support 特征怎样聚合 | ALPNet、DSPNet、GMRD、VQ | 单一均值丢失局部或多模态结构 |
| support/query 怎样交互 | RPT、query-guided refinement | 固定 support prototype 不适应当前 query |
| affinity map 怎样融合 | GMRD/MAMP | 多 descriptor 会产生多张相似度图 |
| 背景怎样表示 | ALPNet、ADNet、GMRD 双路径 | 背景高度异质 |
| 区域关系怎样建模 | PGRNet | 独立 prototype 缺少结构关系 |
| 域偏移怎样处理 | PFMNet | 目标域 prototype 与源域特征空间不对齐 |

原型越复杂，复现时对 backbone、support 切片选择、超像素、特征尺度和预处理的依赖也越强。比较这些方法时，应尽量使用一致的数据划分、support 采样和预处理，避免把实验配置差异误认为原型设计带来的收益。

#### 6.5 目标任务少样本训练：从零训练、预训练和受限微调

这条路线不追求“给一个新 support 就分割新器官”，而是提高固定目标任务在少量病例下的训练效率。

**从零训练**

K-case nnU-Net from scratch 是必要下界。它不需要新算法，但必须严格冻结患者级 subset、plans 和 test set。若复杂方法不能在同一 K 下稳定优于该基线，其工程价值有限。

**3D nnU-Net 自监督预训练**

Spark3D 对 3D nnU-Net 使用 MAE 式预训练，并系统比较固定与动态数据预处理。官方 `nnssl` 仓库提供预训练、微调、评估代码和预训练权重。该工作最重要的工程启示不是某个固定增益，而是：

- 下游 nnU-Net plan 必须与预训练 patch/spacing 兼容；
- 预训练权重迁移需要明确 encoder、decoder 和 head 的映射；
- low-data 评估应在多个数据集和多个 K 上进行，不能只挑一个有利任务。

**大规模 3D CT 预训练**

VoCo v2/VoComni 使用大规模 3D CT 数据进行自监督、半监督和全监督组合预训练。官方仓库提供多种规模 checkpoint，并包含 nnU-Net 相关下游配置。它适合研究“全身 CT 预训练是否能改善新器官少样本微调”，但模型规模、预处理契约、权重许可和目标数据重叠需要逐项核查。

SuPreM 使用大规模腹部 CT 及器官/病灶标注进行监督预训练，并发布 U-Net 与 Swin UNETR 权重。它更适合腹部 CT 迁移，而不是默认视为跨模态、跨全身区域的通用初始化。

**少样本参数选择**

DGST 以一个大规模淋巴结 nnU-Net v2 模型为基础，在少量下游 CT 上按梯度动态选择参数更新。官方仓库提供预训练权重、数据准备和 nnUNetv2 trainer 使用方式。它适合研究“相关源任务到相关目标任务”的少样本迁移，不等同于从零开始的通用 few-shot segmentation。

**如何选择预训练模型**

优先级通常是：

1. 同模态、同空间维度；
2. 相近解剖区域或相近目标；
3. 预处理与当前 nnU-Net plans 可兼容；
4. 训练数据来源和许可可追踪；
5. 有公开微调代码，而不只是 checkpoint。

预训练数据规模大，不代表对目标任务一定有效。跨模态、跨区域或标签语义差异较大时，冻结过多参数反而会限制适应。

#### 6.6 少样本域适应：从特征映射到参数高效更新

少样本域适应的前提是已经存在源域模型，并获得少量目标域标注。目标通常不是学习一个完全未知的器官概念，而是保持目标定义不变，同时适应中心、设备、扫描协议、人群或解剖区域差异。

PFMNet 从 prototype feature mapping 出发，把少量目标域 prototype 映射到源域表示空间。它代表的是特征对齐路线：尽量保持源模型表示，只学习源域和目标域之间的映射。论文公开，但截至核查日期未确认官方实现，复现通常需要自行实现关键模块。

DGST 从参数更新角度处理少样本适配。它基于 nnUNetv2 淋巴结模型，在训练过程中按梯度动态选择少量重要参数更新。官方仓库提供 trainer 和权重，但证据集中在特定 3D CT 淋巴结迁移场景。

FSEFT、ARENA 和 Med-Tuning 的主要贡献是参数高效适配，但也可放入域适应协议中评价：

- FSEFT 可比较 full fine-tuning、LoRA、AdaptFormer、bias/normalization tuning 和 black-box 3D Adapter；
- ARENA 在 LoRA 基础上自动调整有效秩，减少对手工 rank 搜索的依赖；
- Med-Tuning 使用 Med-Adapter 把自然图像预训练 backbone 迁移到 CT/MRI 体积分割。

域适应结果必须与实验约束一起解释：

- 适配时是否仍可访问源数据；
- 目标类别是否与源任务相同；
- 目标域变化来自中心、模态、协议还是解剖区域；
- 预训练数据是否包含目标测试患者或高度重叠的数据来源。

#### 6.7 UniverSeg：从单数据集 FSS 走向通用医学 ICL

UniverSeg 在 ICCV 2023 提出一个轻量级 2D 通用医学分割模型。用户在推理时提供 context images 和 context labels，模型无需针对新任务微调。

官方实现的明确输入契约是：

- 单通道 2D 图像；
- target shape 为 `(B, 1, H, W)`；
- support shape 为 `(B, S, 1, H, W)`；
- 输入 min-max 归一化到 `[0, 1]`；
- 空间尺寸固定为 `128 x 128`。

仓库提供 pip 安装、Colab、模型权重和示例。代码采用 Apache-2.0；模型权重使用 OpenRAIL++-M，仓库明确标注仅限研究用途。

UniverSeg 是适合理解医学 ICL 的公开实现之一，但它不是原生全分辨率 3D 全身分割方案。将 3D volume 切片后直接推理会丢失跨切片一致性，需要单独评价。

#### 6.8 Tyche：把标注不确定性加入上下文分割

Tyche 在 CVPR 2024 研究两个问题：

1. 如何用 context set 适应未见分割任务；
2. 如何输出多个合理但不同的候选 mask，表达标注者之间的差异和任务不确定性。

Tyche 提供 train-time stochasticity 和 in-context test-time augmentation 两种方式。官方仓库采用 Apache-2.0，发布了 CVPR 权重，但文档更偏模型代码而不是完整数据处理教程，因此复现门槛高于 UniverSeg。

Tyche 的多候选输出不能被理解为“自动选出正确标签”。它适合表达歧义、支持人工复核或不确定性研究；实验必须说明如何评价和选择多个候选输出。

#### 6.9 3D ICL：从固定 2D 输入走向体数据

Neuroverse3D（ICCV 2025）和 Medverse（AAAI 2026）将 context-based adaptation 扩展到 3D 医学图像。

**Neuroverse3D**

- 提供官方训练代码、推理脚本、预训练权重和演示数据；
- 输入采用 nnU-Net 风格 NIfTI 目录；
- 提供 3D context image、context label 和 target image 接口；
- 仓库采用 MIT 许可；
- 研究重点是神经影像和内存可控的 3D context 处理。

**Medverse**

- 面向全分辨率 3D 分割、变换和增强；
- 官方仓库提供权重加载和 autoregressive inference 示例；
- context 和 target 的空间尺寸必须匹配；
- 截至核查日期，仓库未声明明确软件许可，也没有像 Neuroverse3D 一样清晰展示完整训练流程。

3D ICL 直接处理体数据，但仍是高成本研究方向。尝试前必须验证 GPU 显存、输入重采样、完整器官覆盖、输出 affine、模型/权重许可和跨中心表现。

#### 6.10 Foundation model + prototype/prompt 的桥接路线

ProtoSAM 用 DINOv2 特征和局部原型生成粗 mask，再自动生成点和框交给 SAM 精修。官方仓库采用 GPL-3.0，并提供 CT、MRI 和息肉数据的运行说明。

这类方法的意义是：

- 利用 foundation model 的视觉特征；
- 保留 support-query 的类别定义；
- 用 promptable model 做边界修正。

其风险是系统由多个模型和预处理步骤组成，误差可能在“原型粗分割 → 自动提示 → SAM 输出”之间累积。它适合作为研究对照，不应因使用 SAM 就默认优于专用医学分割模型。

---

## 第四部分：开源可尝试性

### 7. 面向目标的方法与模型选型

#### 7.1 四条路线与方法归属

| 路线 | 核心问题 | 主要方法 |
| --- | --- | --- |
| 路线一：固定任务的 low-shot 训练与适配 | 目标器官和标签空间固定，只有少量完整标注病例 | K-case nnU-Net、nnssl/Spark3D、VoCo、SuPreM、FSEFT、ARENA、Med-Tuning、nnSAM、MA-SAM |
| 路线二：support/query 原型或元学习分割 | 用少量 support image/mask 描述训练阶段未固定的新类别 | PANet、SSL-ALPNet、ADNet、RPT、VQ、DSPNet、GMRD、PGRNet、ProtoSAM |
| 路线三：少样本域适应 | 已有源模型，用少量目标域标签适应新中心、新协议或新解剖区域 | PFMNet、DGST；FSEFT、ARENA、Med-Tuning 也可用于域偏移场景 |
| 路线四：推理时上下文分割 | 新任务时不更新参数，由若干图像-mask示例定义任务 | UniverSeg、Tyche、Neuroverse3D、Medverse |

方法归属按其主要研究问题划分，并不表示方法只能用于一条路线。例如，FSEFT 的核心是少样本参数高效微调，既能用于固定任务适配，也能在源域和目标域存在差异时用于少样本域适应。

#### 7.2 路线一：固定任务的 low-shot 训练、预训练与 PEFT

nnU-Net 本身不是少样本算法，也不是默认意义上的微调方法。普通 nnU-Net 通常从随机初始化开始，使用目标数据做全监督训练。

“全监督”和“全量微调”描述的是两件不同的事：

- **全监督**描述标签：训练病例提供完整的像素或体素标签；
- **全量微调**描述参数：从预训练模型开始，更新模型的全部参数。

因此，使用 5 个完整标注病例训练 nnU-Net 可以是“少病例、全监督、从零训练”，但不一定是微调。只有先加载预训练权重再继续训练，才属于 fine-tuning。

| 方法 | 公开资产与许可 | 维度 | 可进行的实验 | 复现难度与限制 |
| --- | --- | --- | --- | --- |
| [nnU-Net](https://github.com/MIC-DKFZ/nnUNet) | 完整官方代码，Apache-2.0 | 2D/3D | K-case from-scratch、full-data 上界；有兼容权重时可做 full/partial fine-tuning | 低；它是低样本全监督基线，不提供通用 LoRA/Adapter 开关 |
| [nnssl / Spark3D](https://github.com/MIC-DKFZ/nnssl) | 官方预训练、微调和评估代码，CC-BY-SA-4.0 | 3D | 使用医学自监督 checkpoint 微调；也可重新进行 MAE 式预训练 | 使用公开权重为中等；从零预训练需要大量数据和算力 |
| [VoCo / VoComni](https://github.com/Luffy03/Large-Scale-Medical) | 官方代码和多种 checkpoint，Apache-2.0 | 3D | 评估大规模 CT 预训练对少标注器官分割的帮助 | 中等；需核对 checkpoint 架构、预处理、训练数据和权重条款 |
| [SuPreM](https://github.com/MrGiovanni/SuPreM) | 代码和 U-Net/Swin UNETR 权重；仓库未声明标准许可证 | 3D CT | 监督预训练模型在腹部器官任务上的 full/partial fine-tuning | 中等；正式使用前需确认代码与权重许可 |
| [FSEFT](https://github.com/jusiro/fewshot-finetuning) | 官方框架、预训练权重和实验入口；仓库未声明标准许可证 | 3D CT | Linear probing、black-box 3D Adapter、LoRA、AdaptFormer、bias/normalization tuning、full fine-tuning | 中等；基于 MONAI/Swin-UNETR，不是 nnU-Net 插件 |
| [ARENA](https://github.com/ghassenbaklouti/ARENA) | MICCAI 2025 官方代码；仓库未声明标准许可证 | 3D CT | 比较 LoRA、AdaLoRA、BitFit、Affine-LN、full fine-tuning，并用正则化自动调整有效秩 | 中到高；建立在 FSEFT 类预训练模型和 PEFT 流程上 |
| [Med-Tuning](https://github.com/jessie-chen99/Med-Tuning-Official) | MIDL 2024 官方代码，Apache-2.0 | 体积分割，采用 2D backbone 与体积交互 | 评估 Med-Adapter 在 CT/MRI 少量标注下的参数高效适配 | 中到高；架构和数据流程独立于 nnU-Net |
| [nnSAM](https://github.com/Kent0n-Li/nnSAM) | 官方代码，Apache-2.0 | 论文证据主要为 2D | 在有限标签条件下评估冻结 SAM 特征与 nnU-Net 特征融合 | 中到高；不是 prompt-based few-shot，原生 3D 有效性尚未建立 |
| [MA-SAM](https://github.com/cchen-cc/MA-SAM) | 官方代码与部分权重，Apache-2.0 | 3D CT/MRI 和医学视频 | 评估 SAM 经参数适配后的体积分割能力 | 高；官方完整训练配置使用 8 张 A100 80GB，资源成本显著 |

PEFT 的前提是存在一个有价值的预训练模型。若模型仍是随机初始化，冻结大部分参数通常只会限制学习能力。

| PEFT 做法 | 更新哪些参数 | 实现难度 | 适用说明 |
| --- | --- | --- | --- |
| 输出头微调 | 最后的分类或分割头 | 低 | 最弱的适配基线，适合标签空间变化但特征可复用的情况 |
| Decoder 微调 | Decoder 和输出头 | 低 | 适合编码特征与目标任务接近的情况 |
| Bias/normalization tuning | Bias 与 normalization 仿射参数 | 低到中 | 参数量小，适合测试较轻的域偏移 |
| Linear probing | 冻结 backbone，在固定特征上训练线性预测器 | 低到中 | 能检验预训练特征本身是否已经可分 |
| Black-box 3D Adapter | 冻结主模型，在输出特征上训练轻量空间模块 | 中 | FSEFT 提供实现，不需要改动预训练主干 |
| LoRA | 冻结原权重，训练低秩更新 | 中 | 更适合 Swin、ViT、SAM 等含线性注意力层的模型 |
| AdaptFormer / bottleneck Adapter | 在 Transformer block 或特征层加入小模块 | 中 | 可为不同任务保存独立的适配参数 |
| ARENA | 在 LoRA 基础上通过正则化调整有效秩 | 中到高 | 用于减少人工选择 LoRA rank 的依赖 |
| DGST | 每次迭代按梯度选择少量参数更新 | 高 | 已有 nnUNetv2 专项实现，但任务耦合较强 |

在 nnU-Net 上，输出头、decoder、bias/norm 冻结策略可通过自定义 Trainer 实现；卷积 LoRA、Adapter 或动态参数选择还需要修改网络、优化器和 checkpoint 管理。

#### 7.3 路线二：support/query 原型与元学习分割

| 方法 | 公开资产与许可 | 维度 | 主要技术与适用场景 | 复现难度与限制 |
| --- | --- | --- | --- | --- |
| [PANet](https://github.com/kaixin96/PANet) | 官方代码公开 | 2D | 原型对齐；适合理解通用 FSS 的 support-query 基础 | 中等；不是医学专用方法，需要自行构造医学数据 episode |
| [SSL-ALPNet](https://github.com/cheng-01037/Self-supervised-Fewshot-Medical-Image-Segmentation) | 官方代码，MIT | 2D | 超像素自监督 episode 与局部原型；腹部 CT/MRI 经典基线 | 中等；依赖栈较旧，需要重建预处理和环境 |
| [ADNet](https://github.com/sha168/ADNet) | 官方代码，MIT，并提供 Dockerfile | 2D/3D 实验路径 | 以异常检测方式主要建模前景，减轻复杂背景原型问题 | 中等；应按官方协议分别核查 2D 与 3D 实验 |
| [RPT](https://github.com/YazhouZhu19/RPT) | 官方代码和部分预处理资产；未声明标准许可证 | 2D | 区域增强原型和 Transformer 交互 | 中到高；环境、路径和数据准备较旧 |
| VQ few-shot medical segmentation | 论文公开；未确认完整官方实现 | 2D | 用离散码本保留多个局部视觉模式 | 高；需自行实现或寻找非官方复现 |
| [DSPNet](https://github.com/tntek/DSPNet) | 官方代码，MIT | 2D | 双重语义、高保真原型与细节自精炼 | 中到高；README 较简略，需自行核对数据协议 |
| [GMRD](https://github.com/zmcheng9/GMRD) | 官方代码；未声明标准许可证 | 2D | 为类别生成多个代表描述符，减少单原型信息损失 | 高；旧版 PyTorch/CUDA，需处理环境迁移 |
| [PGRNet](https://github.com/Fhujinwu/PGRNet) | 官方代码；未声明标准许可证 | 2D | 原型引导图推理，显式建模区域关系 | 高；需要额外 encoder 权重和较多环境适配 |
| [ProtoSAM](https://github.com/levayz/ProtoSAM) | 官方代码，GPL-3.0 | 2D | 用支持集原型自动生成 SAM 提示 | 中到高；依赖 DINOv2/SAM，多模型链路且许可传播需注意 |

这条路线的主要比较变量包括 prototype 构造、support-query 对齐、背景处理和 episode 采样。二维方法用于三维病例时，还需单独评价跨切片连续性。

#### 7.4 路线三：少样本域适应

| 方法 | 公开资产与许可 | 维度 | 主要技术与适用场景 | 复现难度与限制 |
| --- | --- | --- | --- | --- |
| PFMNet | 正式论文公开；未确认官方代码 | 2D | Prototype-based feature mapping，用少量目标域标注对齐源域与目标域 | 高；缺少已确认的官方实现 |
| [DGST / LN-Seg-FM](https://github.com/HiLab-git/LN-Seg-FM) | 官方 nnUNetv2 trainer 和权重；未声明标准许可证 | 3D CT | 动态梯度稀疏化，在少量目标域病例上选择重要参数更新 | 高；证据集中在淋巴结和特定 CT 迁移场景 |
| [FSEFT](https://github.com/jusiro/fewshot-finetuning) | 官方框架和权重；未声明标准许可证 | 3D CT | 当目标数据与预训练分布存在中心或数据集差异时，可比较 full fine-tuning、PEFT 和 black-box adapter | 中等；需要明确源模型、目标域和可访问的源数据 |
| [ARENA](https://github.com/ghassenbaklouti/ARENA) | 官方代码；未声明标准许可证 | 3D CT | 在 TotalSegmentator、FLARE 等存在分布差异的任务上进行少样本 LoRA 适配 | 中到高；需要先建立普通 LoRA 和 full fine-tuning 对照 |
| [Med-Tuning](https://github.com/jessie-chen99/Med-Tuning-Official) | 官方代码，Apache-2.0 | CT/MRI 体积分割 | 使用 Med-Adapter 将自然图像预训练 backbone 适配到医学体数据 | 中到高；同时包含模态与结构差异，不能只按普通同域微调解释 |

域适应实验必须说明源数据在适配阶段是否可见。Source-present、source-free 和 cross-domain novel-class 的约束不同，结果不能直接混合比较。

#### 7.5 路线四：推理时上下文分割

| 方法 | 公开资产与许可 | 维度 | 主要技术与适用场景 | 复现难度与限制 |
| --- | --- | --- | --- | --- |
| [UniverSeg](https://github.com/JJGO/UniverSeg) | 官方代码 Apache-2.0；公开权重为 OpenRAIL++-M 且限研究使用 | 2D | 用多个 context image/mask 在不更新参数时定义新任务 | 低到中；官方示例完整，但固定输入尺寸且不是原生 3D |
| [Tyche](https://github.com/mariannerakic/Tyche) | 官方代码与权重，Apache-2.0 | 2D | 随机上下文分割，输出多个合理候选以表达歧义 | 中等；数据流程说明少于 UniverSeg，需定义多候选评价方式 |
| [Neuroverse3D](https://github.com/jiesihu/Neuroverse3D) | 官方训练、推理、权重和演示，MIT | 3D | 面向神经影像的原生 3D in-context segmentation | 中到高；方法较新，需要评估显存、输入尺寸和跨任务泛化 |
| [Medverse](https://github.com/jiesihu/Medverse) | 官方推理代码和权重；未声明标准许可证 | 3D | 全分辨率 3D 医学 ICL，并扩展到转换和增强任务 | 高；训练流程和许可信息不完整 |

#### 7.6 判断“开源可尝试”的最低条件

以下状态核查于 2026-06-14。仓库、权重链接和许可可能变化，实际使用前应再次核对。

开始复现前至少检查：

- 仓库是否有明确 license；
- 模型权重是否有独立许可或仅限研究；
- 是否提供训练代码、推理代码、预处理和权重；
- 论文实验是否真的覆盖目标维度；命令行出现 `3d_fullres` 不等于论文验证了 3D 方法；
- 依赖是否能在当前 CUDA/PyTorch 环境中重建；
- 输入是 2D slice、3D patch 还是全 volume；
- 输出是否保留原始 affine、spacing 和 orientation；
- 是否只能二分类逐器官推理；
- support selection 是否需要访问测试标签；
- 是否能在独立患者测试集上复现。

### 8. 如何开始实验

#### 8.1 路线一：固定任务的 low-shot 训练与适配

可按以下顺序建立逐级对照：

1. full-data nnU-Net；
2. 1/3/5/10/20-case nnU-Net from scratch，作为全监督低样本基线；
3. 在同一 K subset 上选择一个来源清楚的 3D 预训练模型，做 full fine-tuning；
4. 使用相同 checkpoint 比较 decoder-only、bias/norm tuning；
5. 使用 FSEFT 比较 LoRA、AdaptFormer、linear probing 和 3D Adapter；
6. 普通 LoRA 有稳定收益后再尝试 ARENA；
7. 根据模型结构和资源条件，再评价 Med-Tuning、nnSAM 或 MA-SAM。

一个可执行的实验目录至少要冻结：

```text
experiment/
  protocol.yaml          # K、subset ids、seed、test ids、评价指标
  plans/                 # nnU-Net plans 与 configuration
  splits_final.json      # 患者级划分
  checkpoints/           # from-scratch 或 pretrained 初始化来源
  runs/                  # 每个 K/subset/seed 的输出
  evaluation/            # 病例级和器官级指标
```

对每个 K，建议至少保存：

- K 个病例的稳定 ID，而不是只保存随机种子；
- 初始化方式和预训练 checkpoint hash；
- 冻结/可训练参数清单；
- nnU-Net plans 和 trainer；
- 最佳 checkpoint 的选择规则；
- 失败病例和空预测统计。

#### 8.2 路线二：support/query 原型与元学习

可先复现基础机制，再逐步增加原型复杂度：

1. SSL-ALPNet，理解自监督 episode 和局部原型；
2. ADNet，理解复杂背景问题；
3. RPT，理解区域原型和迭代校正；
4. DSPNet，研究高保真原型和细节自精炼；
5. GMRD，研究多代表描述符；
6. PGRNet，研究原型引导图推理；
7. VQ 方法，研究离散码本表示；由于缺少已确认的完整官方实现，开发量较大；
8. ProtoSAM，研究原型信息如何转换为 SAM 提示。

不能直接搬运不同论文表格中的 Dice 排名，因为数据划分、setting、backbone 和 support 采样可能不同。

#### 8.3 路线三：少样本域适应

域适应实验至少需要一组源模型、一个明确的目标域和少量目标域标注。可比较：

1. 不适配的源模型；
2. 使用 K 个目标域病例做 full fine-tuning；
3. Decoder、bias/norm 等简单 partial fine-tuning；
4. FSEFT 的 LoRA、AdaptFormer 或 black-box 3D Adapter；
5. ARENA 的自适应低秩更新；
6. DGST 的动态梯度稀疏化；
7. PFMNet 的 prototype-based feature mapping；由于未确认官方代码，通常需要自行实现。

必须固定目标域测试集，并说明适配时能否访问源数据。若目标器官也属于未见类别，则实验同时包含域适应和 novel-class few-shot，难度与普通同类别域适应不同。

#### 8.4 路线四：推理时上下文分割

二维实验可使用 UniverSeg 和 Tyche：

1. 固定 support selection；
2. 比较不同 support 数量；
3. 同时报告 slice-level 和重建 volume-level 指标；
4. 对 Tyche 说明多候选输出的评价与选择规则。

UniverSeg 的固定 `128 x 128` 输入和研究用途权重应写入实验限制。

原生三维实验可使用 Neuroverse3D 和 Medverse：

- Neuroverse3D 的训练和推理契约更完整，许可更清楚；
- Medverse 面向全分辨率 3D 任务，但许可和训练完整度需要进一步确认；
- 两者均不能跳过与 low-shot nnU-Net 的公平对比。

---

## 第五部分：面向医学分割的实验设计

### 9. 推荐的基准矩阵

| 路线 | 组别 | 目的 |
| --- | --- | --- |
| 路线一 | Full-data nnU-Net | 任务上界和数据充分时的参考 |
| 路线一 | K-shot nnU-Net from scratch | 普通监督低样本下界 |
| 路线一 | K-shot pretrained full fine-tuning | 衡量预训练和迁移学习收益 |
| 路线一 | K-shot decoder/head/bias tuning | 判断简单 partial fine-tuning 是否足够 |
| 路线一 | FSEFT/ARENA/Med-Tuning | 比较 LoRA、Adapter 等参数高效微调 |
| 路线一 | nnSAM（适用 2D 协议）/MA-SAM | 评价 SAM 特征和医学适配结构 |
| 路线二 | SSL-ALPNet/ADNet/RPT/DSPNet/GMRD/PGRNet | 评价不同原型构造与 support-query 交互 |
| 路线三 | Source model、full fine-tuning、PFMNet/DGST/PEFT | 评价少量目标域标签下的迁移能力 |
| 路线四 | UniverSeg/Tyche | 评价 2D 零微调上下文分割 |
| 路线四 | Neuroverse3D/Medverse | 评价 3D 上下文分割 |

所有方法应尽量共享：

- 同一患者级 test set；
- 同一目标器官定义；
- 同一空间预处理或可逆映射；
- 同一 K-shot support case 列表；
- 同一标签质量要求；
- 同一病例级评价脚本。

对于 nnU-Net 系列比较，还应共享或明确记录：

- 是否固定同一 plans/configuration；
- 训练 epoch、patch 采样和数据增强是否相同；
- checkpoint 初始化来源；
- 哪些参数被冻结；
- 是否重新搜索学习率或其他超参数。

若方法必须使用不同输入尺寸、不同预训练数据或 2D 切片，应明确记录，不强行伪装成完全相同的训练条件。公平比较的目标是让差异可解释，而不是让所有方法形式上完全一致。

### 10. Support set 的选择

随机选择是必要基线，但实际应用还可以研究：

- 按扫描中心或协议平衡；
- 覆盖典型和异常解剖；
- 按目标器官体积或形态分层；
- 使用图像特征检索相似 support；
- 使用多样性采样避免支持集重复。

检索 support 时要防止泄漏。允许使用 query 图像特征进行无标签检索，但不能使用 query 的真实 mask、测试指标或人工结果选择最有利的 support。

### 11. 多器官任务的额外问题

经典 FSS 经常按一个 episode 分割一个前景类别。全身多器官任务需要额外回答：

- 一个模型一次输出一个器官还是多个器官；
- K-shot 是每器官 K 例，还是 K 个多器官完整标注病例；
- 不同器官的 support 是否来自同一患者；
- 多个二值结果如何处理空间冲突；
- 某个器官缺失标签时，是否排除该病例的对应监督；
- 多器官合并是在模型内部完成，还是由独立后处理完成。

因此，论文中的 one-way one-shot 不能直接等价为“一个病例即可训练全身器官模型”。

### 12. 常见失败模式

| 失败模式 | 原因 | 检查方式 |
| --- | --- | --- |
| 结果对 support 极敏感 | 支持病例不具代表性 | 多随机种子和 worst repeat |
| 小器官空预测 | 前景过小、下采样或类别不平衡 | 按器官统计空预测率 |
| 2D 结果跨切片跳变 | 无 3D 上下文 | volume 重建后检查连通性 |
| 背景错分严重 | 背景原型过于粗糙 | 背景区域和邻近器官错误分析 |
| 域外中心性能骤降 | support 未覆盖协议差异 | 按中心/设备分层 |
| Dice 尚可但边界不可用 | 大器官平均指标掩盖表面误差 | HD95、Surface Dice、可视化 |
| 结果无法复现 | support 和随机种子未保存 | 冻结 protocol 和运行记录 |
| 伪标签自我强化 | 模型生成标签又用于同源评估 | 标签 lineage 和独立 verified test |

---

## 第六部分：结论与研究边界

### 13. 当前可以形成的判断

1. **少样本首先是实验协议问题**。没有病例级 split、固定 support、重复采样和独立 test，算法比较没有意义。
2. **普通 low-shot 训练必须作为基线**。复杂 few-shot 方法至少应提高分割性能、稳定性或参数效率，才能证明新增复杂度有价值。
3. **医学 FSS 的核心技术演化围绕原型质量展开**：局部原型、背景处理、区域原型、support-query 对齐和不确定性。
4. **ICL 把适应从训练时移到推理时，但训练通用模型本身需要大量多任务数据**。它不是“整个项目只需几例数据”。
5. **2D 开源方法目前更成熟，3D ICL 能直接处理体数据，但复现和资源成本更高**。
6. **开源代码、权重和许可必须分开判断**。UniverSeg 是典型例子：代码许可宽松，但官方权重明确限制研究用途。
7. **K-case nnU-Net 是固定任务 low-shot 训练的基础对照，不是专门的少样本模型**。
8. **涉及 nnU-Net 的实验必须说明初始化和参数更新方式**：from scratch、pretrained full fine-tuning、partial fine-tuning 或自定义 PEFT。
9. **论文命令或仓库支持某个 configuration，不等于论文已经验证该维度**。nnSAM 的公开论文证据以 2D 为主，不能仅凭 nnU-Net 命令接口推断其 3D 有效性。
10. **FSEFT 提供了较完整的 3D PEFT 比较入口**，包含 linear probing、3D Adapter、LoRA 和 AdaptFormer；ARENA进一步研究低秩的自动调整。

### 14. 仍需通过实验回答的问题

- 对不同器官和模态，多少病例属于有效的“少样本”区间，性能拐点在哪里；
- 预训练 nnU-Net 是否比从零训练稳定；
- 固定 plans 与按 K 重新规划会产生多大差异；
- 哪类预训练对目标模态和解剖区域真正有效；
- decoder tuning、full fine-tuning、DGST/LoRA 哪一种在相同 K 下更稳定；
- 逐器官二值 few-shot 是否比多器官 low-shot 更可靠；
- 2D ICL 重建为 3D 后的连续性是否可接受；
- support 检索能否稳定提升，而不是只对个别病例有效；
- 3D ICL 的显存、推理时间和输出空间一致性是否满足批量处理；
- 模型权重许可是否允许目标使用场景；
- few-shot 输出在什么质量条件下适合直接使用，什么情况下需要人工修正。

---

## 参考文献与官方实现

### A. 基础少样本学习

- Koch et al. [Siamese Neural Networks for One-shot Image Recognition](https://www.cs.cmu.edu/~rsalakhu/papers/oneshot1.pdf)
- Vinyals et al. [Matching Networks for One Shot Learning](https://arxiv.org/abs/1606.04080)
- Snell et al. [Prototypical Networks for Few-shot Learning](https://arxiv.org/abs/1703.05175)
- Sung et al. [Learning to Compare: Relation Network for Few-Shot Learning](https://arxiv.org/abs/1711.06025)
- Finn et al. [Model-Agnostic Meta-Learning for Fast Adaptation of Deep Networks](https://arxiv.org/abs/1703.03400)
- Wang et al. [PANet: Few-Shot Image Semantic Segmentation with Prototype Alignment](https://arxiv.org/abs/1908.06391), [official code](https://github.com/kaixin96/PANet)

### B. 医学图像少样本综述

- Pachetti and Colantonio. [A Systematic Review of Few-Shot Learning in Medical Imaging](https://arxiv.org/abs/2309.11433), [PubMed](https://pubmed.ncbi.nlm.nih.gov/39178621/)

### C. 路线二：医学原型与 episodic FSS

- Ouyang et al. [Self-Supervision with Superpixels: Training Few-Shot Medical Image Segmentation without Annotation](https://arxiv.org/abs/2007.09886), [official code](https://github.com/cheng-01037/Self-supervised-Fewshot-Medical-Image-Segmentation)
- Hansen et al. [Anomaly Detection-Inspired Few-Shot Medical Image Segmentation Through Self-Supervision With Supervoxels](https://www.sciencedirect.com/science/article/pii/S1361841522000378), [official code](https://github.com/sha168/ADNet)
- Zhu et al. [Few-Shot Medical Image Segmentation via a Region-Enhanced Prototypical Transformer](https://conferences.miccai.org/2023/papers/272-Paper1190.html), [official code](https://github.com/YazhouZhu19/RPT)
- Huang et al. [Rethinking Few-Shot Medical Segmentation: A Vector Quantization View](https://openaccess.thecvf.com/content/CVPR2023/html/Huang_Rethinking_Few-Shot_Medical_Segmentation_A_Vector_Quantization_View_CVPR_2023_paper.html)
- Tang et al. [Few-Shot Medical Image Segmentation with High-Fidelity Prototypes](https://arxiv.org/abs/2406.18074), [official code](https://github.com/tntek/DSPNet)
- Cheng et al. [Few-Shot Medical Image Segmentation via Generating Multiple Representative Descriptors](https://doi.org/10.1109/TMI.2024.3358295), [official code](https://github.com/zmcheng9/GMRD)
- Huang et al. [Prototype-Guided Graph Reasoning Network for Few-Shot Medical Image Segmentation](https://doi.org/10.1109/TMI.2024.3459943), [official code](https://github.com/Fhujinwu/PGRNet)
- Ayzenberg et al. [ProtoSAM: One-Shot Medical Image Segmentation With Foundational Models](https://arxiv.org/abs/2407.07042), [official code](https://github.com/levayz/ProtoSAM)

### D. 路线三：少样本域适应

- Wang et al. [Prototype-based Feature Mapping for Few-shot Domain Adaptation](https://pubmed.ncbi.nlm.nih.gov/38824715/)
- Luo et al. [Dynamic Gradient Sparsification Training for Few-Shot Fine-Tuning of CT Lymph Node Segmentation Foundation Model](https://arxiv.org/abs/2503.00748), [official code](https://github.com/HiLab-git/LN-Seg-FM)

### E. 路线四：医学 in-context segmentation

- Butoi et al. [UniverSeg: Universal Medical Image Segmentation](https://arxiv.org/abs/2304.06131), [official code](https://github.com/JJGO/UniverSeg), [project page](https://universeg.csail.mit.edu/)
- Rakic et al. [Tyche: Stochastic In-Context Learning for Medical Image Segmentation](https://arxiv.org/abs/2401.13650), [CVPR paper](https://openaccess.thecvf.com/content/CVPR2024/papers/Rakic_Tyche_Stochastic_In-Context_Learning_for_Medical_Image_Segmentation_CVPR_2024_paper.pdf), [official code](https://github.com/mariannerakic/Tyche)
- Hu et al. [Neuroverse3D: Developing In-Context Learning Universal Model for Neuroimaging in 3D](https://openaccess.thecvf.com/content/ICCV2025/papers/Hu_Neuroverse3D_Developing_In-Context_Learning_Universal_Model_for_Neuroimaging_in_3D_ICCV_2025_paper.pdf), [official code](https://github.com/jiesihu/Neuroverse3D)
- Hu et al. [Medverse: A Universal Model for Full-Resolution 3D Medical Image Segmentation, Transformation and Enhancement](https://ojs.aaai.org/index.php/AAAI/article/view/42490), [official code](https://github.com/jiesihu/Medverse)

### F. 路线一：少样本训练、预训练与参数适配

- Silva-Rodríguez et al. [Towards Foundation Models and Few-Shot Parameter-Efficient Fine-Tuning for Volumetric Organ Segmentation](https://www.sciencedirect.com/science/article/pii/S1361841525001434), [official FSEFT code](https://github.com/jusiro/fewshot-finetuning)
- Baklouti et al. [Regularized Low-Rank Adaptation for Few-Shot Organ Segmentation](https://papers.miccai.org/miccai-2025/0768-Paper4888.html), [official ARENA code](https://github.com/ghassenbaklouti/ARENA)
- Shen et al. [Med-Tuning: A New Parameter-Efficient Tuning Framework for Medical Volumetric Segmentation](https://proceedings.mlr.press/v250/shen24a.html), [official code](https://github.com/jessie-chen99/Med-Tuning-Official)
- Chen et al. [MA-SAM: Modality-Agnostic SAM Adaptation for 3D Medical Image Segmentation](https://pubmed.ncbi.nlm.nih.gov/39182302/), [official code](https://github.com/cchen-cc/MA-SAM)
- Li et al. [nnSAM: Plug-and-Play Segment Anything Model Improves nnU-Net Performance](https://arxiv.org/abs/2309.16967), [official code](https://github.com/Kent0n-Li/nnSAM)
- Wald et al. [Revisiting MAE Pre-training for 3D Medical Image Segmentation](https://arxiv.org/abs/2410.23132), [official nnssl code](https://github.com/MIC-DKFZ/nnssl)
- Wu et al. [VoCo: A Simple-yet-Effective Volume Contrastive Learning Framework for 3D Medical Image Analysis](https://openaccess.thecvf.com/content/CVPR2024/html/Wu_VoCo_A_Simple-yet-Effective_Volume_Contrastive_Learning_Framework_for_3D_Medical_CVPR_2024_paper.html), [VoCo v2/VoComni code and weights](https://github.com/Luffy03/Large-Scale-Medical)
- Li et al. [How Well Do Supervised 3D Models Transfer to Medical Imaging Tasks?](https://www.cs.jhu.edu/~zongwei/publication/li2023suprem.pdf), [SuPreM code and weights](https://github.com/MrGiovanni/SuPreM)

### G. 工程基线

- Isensee et al. [nnU-Net: a self-configuring method for deep learning-based biomedical image segmentation](https://pubmed.ncbi.nlm.nih.gov/33288961/), [official code](https://github.com/MIC-DKFZ/nnUNet)
