# 小样本学习技术调研

> 来源：https://uih.feishu.cn/docx/ZdKBdhFSRoXc8TxyVB1cW7pqnSb

---

# 介绍

> 相关文档：[基于小样本学习的目标检测](https://uih.feishu.cn/docx/PY7EdAzEvofJ8pxjlm6cX1punEd)

## 小样本学习(Few-shot learning, FSL)

小样本学习(Few-shot learning, FSL) 是机器学习领域中一个重要的分支，其核心目标是通过较少的训练集实现模型的高效学习与泛化。这一技术的灵感源自人类的学习模式：人类能够在接触少量例子后迅速建立对新事物的认知，而传统机器学习通常需要大量的数据来保证模型的泛化能力。FSL旨在模仿人类的这种高效学习能力，从而在数据稀缺的场景下实现模型的有效训练和应用。

### 必要性和意义

- **降低模型训练的成本**：医学领域的数据获取和标注成本都非常高昂，FSL不依赖大规模的训练数据，能够显著减少数据采集和标注的开销，从而降低模型训练的总体成本。
- **提升模型动态适应力**：在面对新任务或数据稀缺的场景时，FSL能够在仅有少量样本的情况下快速适应新任务，从而提升了模型在实际应用中的适应性和灵活性，加速了模型的实际部署的进程。
- **推动人工智能的发展**：缩小人类和人工智能的距离，为实现通用AI提供了可能。

### 困难与挑战

- 少量监督样本会使学习算法的函数搜索空间大，易导致过拟合，因为样本形成的约束少，难以压缩函数的冗余空间，增加了泛化误差。

## 小样本学习的技术演进

### 非深度学习时期（2000年-2015年）

- 核心思想：通过**潜在变量**建模数据分布 P(X|Y)，结合贝叶斯决策进行分类。
- 代表方法：
  - **凝聚算法 (Congealing)** [2]：最早研究如何从极少样本中学习的方法
  - **变分贝叶斯框架 (VBF)** [3]：首次明确提出"单样本学习（one-shot learning）"这一术语的研究
  - **贝叶斯程序学习 (BPL)** [5]：突破传统生成模型限制，模拟人类认知的组合性与因果推理机制

### 深度学习时期（2015年-至今）

- 核心思想：随着深度神经网络表征学习能力的突破，小样本学习研究重心从生成式建模转向判别式模型设计。
- 代表方法：孪生卷积神经网络（Siamese CNN）的提出首次将深度学习融入到小样本学习问题的解决方案中。**Siamese CNN启发了度量学习与元学习两大主流技术路线**，为后续Prototypical Networks、Matching Networks等方法奠定基础。

## 类型

小样本学习的技术类型可以分为生成模型和判别模型。

## 小样本的数据集结构

小样本的深度学习通常将数据集分为三个部分：训练集(Training set), 支持集(Support set), 查询集(Query set)。

- **训练集**：用于预训练学习模型的源数据集
- **支持集**：用于选出具有优良任务性能模型的模板域训练数据集（包含少量标记信息）
- **查询集**：用于验证训练模型准确率的目标域测试数据集

---

# 小样本学习的关键技术

## 生成模型 (Generative model)

> 小样本学习方法通常面临数据与目标间概率关系不直观的问题，于是引入**中间潜在变量**来建立联系。几乎所有基于生成模型的小样本学习方法都遵循这一总体策略，即便它们在潜在变量的具体形式上有所不同。

以下方法从不同角度构建了潜在变量，除了神经统计学模型(2.1.7)之外的方法都诞生于非深度学习时期，并且大多数方法是根据特定的任务形式或数据形式量身定制的，缺乏对更一般情况的可扩展性。

### 基于变换的建模 (Transformation)

> 通过对数据进行特定形式的改变或转换操作，从而在数据和目标之间建立联系。

- [Learning from one example through shared densities on transforms](https://ieeexplore.ieee.org/abstract/document/855856) [2] (Congealing算法, 2004) — 首个尝试从单个样本学习的方法。仅适用于简单的数字或字母字符灰度图像。

### 参数化生成 (Parameters)

> 将潜在变量设定为**参数**，意味着把数据生成过程看作是由一组参数所掌控。

- [Learning Generative Visual Models from Few Training Examples](https://cs.nyu.edu/~fergus/papers/Fei-Fei_GMBV04.pdf) [3] (VBF算法, 2007) — 借助概率模型，对RGB图像中是否存在特定物体进行概率上的量化评估。

### 超类层次建模 (Superclass)

> 超类是一个比具体类别更宽泛且具概括性的类别概念，从更宏观的层面看待具体类别之间的关系，挖掘它们的共性特征。

- [One-shot learning with a hierarchical nonparametric Bayesian model](https://dl.acm.org/doi/10.5555/3045796.3045815) [4] (层次贝叶斯模型, 2011) — 通过超类关系构建，利用超类来整合同一超类下不同类别间的信息。

### 程序化生成 (Program)

> 将潜在变量视为程序，意味着把数据的生成过程看作是由一系列特定的步骤或指令组成的程序执行结果。

- [One shot learning of simple visual concepts](https://utstat.toronto.edu/~rsalakhu/papers/LakeEtAl2011CogSci.pdf) [5] (BPL算法) — 利用贝叶斯理论和方法，把字符对象从无到有的创建过程，以一种具有概率性质的程序形式来描述和理解。

### 划分集成方法 (Splits)

> 通过对辅助集的多样化划分和多预测器的综合运用，提升了模型在分类等任务中的性能和对数据的理解能力。

- [Pattern recognition from one example by chopping](https://proceedings.neurips.cc/paper/2005/file/d0bb8259d8fe3c7df4554dab9d7da3c9-Paper.pdf) [6] (Chopping模型, 2005) — 对辅助集进行多次随机划分，每次划分训练一个预测器，最终通过贝叶斯后验决策综合结果。

### 结构重构模型 (Reconstruction)

> 利用特定方式对测试样本进行重新构建的过程。

- [One Shot Learning via Compositions of Meaningful Patches](https://www.cs.jhu.edu/~ayuille/Pubs15/AlexWongOneShotCVPR2015.pdf) [7] — 提出组合补丁模型(CPM)，将训练集中每个类别的单个样本分割成一组组件，利用与或图来重构测试样本。

### 神经统计模型 (Statistics)

> 通过生成潜在空间中的统计量来深入理解数据的具体特征。

- [Towards a Neural Statistician](https://arxiv.org/pdf/1606.02185) [8] — 运用深度网络生成统计量，为每个训练集封装了一个生成模型。通过确定均值和方差，刻画潜在空间中数据点的分布情况。

---

## 判别模型 (Discriminative model)

> 基于判别模型的FSL方法尝试利用稀缺的训练集，直接为任务对后验概率进行建模，计算模型通常包含一个特征提取器和一个预测器。

### 数据增强（Data augmentation）

> 从辅助数据集中学习一个通用的数据增强函数，以增强训练集中的样本或样本特征。是一种直观的增加训练样本数量并提升数据多样性的方法。

⚠️ *数据增强和其他FSL方法并不冲突，作为即插即用的模块，经常和其他FSL算法一起使用。*

基础的数据增强包括旋转、翻转、裁剪、平移和添加噪声等基本的图像处理方式。在深度学习时期，人们提出了更多专门为FSL定制的更复杂的数据增强方案，**利用图像特征**进行数据增强。

#### 有监督数据增强

学习特征空间Ω_fe和辅助信息空间Ω_si的映射关系作为增强函数。

- [One-Shot Learning of Scene Locations via Feature Trajectory Transfer](https://openaccess.thecvf.com/content_cvpr_2016/papers/Kwitt_One-Shot_Learning_of_CVPR_2016_paper.pdf) (FFT, 2016) [9] — 利用场景图片上的连续属性来合成特征
- [AGA: Attribute Guided Augmentation](https://arxiv.org/pdf/1612.02559) (AGA, 2016) [10] — 构建编解码网络结构，将样本特征映射到不同属性强度的合成特征
- [Multi-level Semantic Feature Augmentation for One-shot Learning](https://arxiv.org/pdf/1804.05298) (Dual TriNet, 2018) [11] — 利用编码器将特征空间映射到语义空间中对数据增强
- [Attribute-Based Synthetic Network](https://www.sciencedirect.com/science/article/pii/S0031320318300876) (ABS-Net, 2018) [12] — 先在辅助数据集上学习属性并建立属性库
- [Attribute-Based Transfer Learning for Object Categorization](https://link.springer.com/content/pdf/10.1007/978-3-642-15555-0_10.pdf) (AT, 2010) [13] — 提出主题模型建模方案

#### 无监督数据增强

数据增强过程不依赖外部辅助信息。

- [Robust boosting for learning from few examples](https://ieeexplore.ieee.org/document/1467290) (GentleBoostKO, 2005) [14] — 通过剔除(knockout)过程来合成特征
- [Low-shot Visual Recognition by Shrinking and Hallucinating Features](https://openaccess.thecvf.com/content_ICCV_2017/papers/Hariharan_Low-Shot_Visual_Recognition_ICCV_2017_paper.pdf) (SH, 2017) [15] — 提出类内变异可以跨类进行泛化。开创了表征学习+小样本学习这一基准算法
- [Delta-encoder](https://arxiv.org/pdf/1806.04734) (Δ-编码器, 2018) [16] — 通过辅助集提取可迁移的类内变异（称Δ），并将这种变异应用于新的任务类别
- [Low-Shot Learning from Imaginary Data](https://arxiv.org/pdf/1801.05401) (幻觉生成器Hallucinator, 2018) [17] — 使用基于多层感知器的生成器为训练样本增强特征
- [Low-shot Learning via Covariance-Preserving Adversarial Augmentation Networks](https://arxiv.org/abs/1810.11730) (CP-ANN, 2018) [18] — 通过基于GAN的集对集转换实现特征增强
- [Data Augmentation Generative Adversarial Networks](https://arxiv.org/abs/1711.04340) (DAGAN, 2018) [19] — 将训练样本作为输入，通过条件GAN直接生成类内数据
- [Image Deformation Meta-Networks for One-Shot Learning](https://arxiv.org/abs/1905.11641) (IDeMe-Net, 2019) [20] — 为少量支持样本生成变形图像

### 度量学习（Metric learning）

> 利用辅助数据集构建相似性度量S(·, ·)，基于这个度量，相似的样本对能够获得更高的相似性得分，不相似的样本对则获得较低的相似性得分。

相似度的度量形式多样，简单的有欧氏距离等距离测量，复杂的有深度神经网络。

- [Object classification from a single example utilizing class relevance metrics](https://proceedings.neurips.cc/paper/2004/file/ef1e491a766ce3127556063d49bc2f98-Paper.pdf) (马氏距离, CRM, 2004) [21] — 非深度学习时期FSL领域具有开创性意义的工作
- [Learning a kernel function for classification with small training samples](https://dl.acm.org/doi/10.1145/1143844.1143895) (KernelBoost, 2006) [22] — 提出提升算法，将复杂核函数构建任务分解为多个简单弱核函数的组合
- [Siamese neural networks for one-shot image recognition](https://www.cs.cmu.edu/~rsalakhu/papers/oneshot1.pdf) (孪生网络, Siamese Nets, 2016) [23] — **首个将深度神经网络进入到FSL任务中方法**
- [Deep Triplet Ranking Networks for One-Shot Recognition](https://arxiv.org/abs/1804.07275) (Triplet Ranking Nets, 2018) [24] — 由孪生网络拓展而来，从处理样本对扩展为处理三元组样本

### 元学习（Meta learning）

> 一种跨任务学习策略，旨在从任务层面而非样本层面进行学习，学习与具体任务无关的通用学习系统，而非针对特定任务的模型。

元学习主张跨任务进行学习，通过学习多个任务去适应新任务。元学习方法分两个阶段：**元训练**和**元测试**。

- **元训练阶段**：会用到许多基于辅助数据集构建的相互独立的有监督任务，目的是学习如何去适应未来相关的任务。训练阶段使用的数据集被称为**支持集**。
- **元测试阶段**：模型会在一个新的任务上进行测试，这个新任务的标签空间与元训练阶段所见到的标签空间是不相交的。测试阶段使用的数据被称为**查询集**。
- **元学习目标**：找到模型参数θ，使所有任务上的期望损失L(·;θ)最小化

**也有文献将元学习的范式分为三类：**
- 基于度量（学习测量）：构建任务无关的特征空间
- 基于优化（学习微调）：优化模型初始点
- 基于模型（学习权重/调整/记忆）：用神经网络学习更新过程

#### 学习测量 (L2M)

学习测量方法本质上继承了度量学习的主要思想。L2M方法采用元学习策略来学习相似性度量，这种相似性度量期望能够在不同任务间进行迁移。

- **优势**：不会受到测试场景特定设置的限制
- **劣势**：跨域泛化差；复杂数据中类原型可能重叠导致边界模糊

| 方法 | 嵌入网络 | 相似度函数 | 优化目标 |
|------|----------|-----------|---------|
| 原型网络 Prototypical Nets | CNN | 欧几里得距离 | Cross-entropy |
| 匹配网络 Matching Nets | CNN+LSTM | 注意力加权余弦相似度 | Cross-entropy |
| 关系网络 Relation Nets | CNN | 可训练关系网络 | 均方误差MSE |

- [Prototypical Networks for Few-shot Learning](https://arxiv.org/pdf/1703.05175) (Prototypical Nets, 2017) [25] — 每个类别在嵌入空间中对应一个原型，分类通过计算查询样本与类原型的欧几里得距离实现
- [Matching Networks for One Shot Learning](https://arxiv.org/pdf/1606.04080) (Matching Nets, 2016) [26] — 首个基于深度学习的L2M方法
- [Learning to Compare: Relation Network for Few-Shot Learning](https://arxiv.org/pdf/1711.06025) (Relation Nets, 2017) [27] — 将支持样本和查询样本的特征进行拼接，使用CNN度量相似性

#### 学习微调 (L2F)

学习微调方法使用任务的少量支持样本对基础学习器进行微调，学习一个模型初始参数θ_meta，使得在新任务上经过少量的参数更新步骤就快速收敛。

- **优势**：适用于任意可以微调的模型架构；增量适应能力强
- **劣势**：二阶导数计算导致计算开销大；内循环步数少可能导致欠拟合

- [Model-Agnostic Meta-Learning for Fast Adaptation of Deep Networks](https://arxiv.org/pdf/1703.03400) (MAML, 2017) [28] — 通过跨任务训练策略为基础学习器的参数寻找一个良好的参数初始化。许多L2F方法都是MAML的变体
- [Optimization as a model for few-shot learning](https://openreview.net/pdf?id=rJY0-Kcll) (Meta-Learner LSTM, 2019) [29] — 通过基于LSTM的元学习器，将基础学习器的损失和梯度作为输入

#### 学习参数化 (L2P)

通过动态生成模型参数替代传统静态权重，使模型能够根据任务的支持集数据快速生成任务特定的参数。

- **优势**：高度灵活性，适配复杂模式；参数生成过程引入隐式正则化
- **劣势**：生成器和主网络联合优化的难度大；参数数量庞大计算代价高

- [Learning feed-forward one-shot learners](https://arxiv.org/pdf/1606.05233) (Siamese Learnet, 2016) [30] — 参数化中间特征层
- [LGM-Net: Learning to Generate Matching Networks for Few-Shot Learning](https://arxiv.org/pdf/1905.06331) (LGM-Net, 2019) [31] — 参数化中间特征层，开发MetaNet模块生成TargetNet权重
- [Learning to learn: Model regression networks for easy small sample learning](https://link.springer.com/content/pdf/10.1007/978-3-319-46466-4_37.pdf) (Regression Nets, 2017) [32] — 参数化整个基础学习器

#### 学习调整 (L2A)

针对特定样本，自适应地调整基础学习器中的计算流程或计算节点。核心在于引入轻量级调整模块（如注意力机制、特征变换器），根据支持集信息对基础网络的中间层进行细粒度调整。

- **优势**：计算开销小；兼容性强
- **劣势**：模块设计复杂；多任务共享调整模块可能导致干扰

- [Meta Networks](https://arxiv.org/pdf/1703.00837) (MetaNet, 2017) [33] — 基于动态权重调整的元学习方法
- [Rapid Adaptation with Conditionally Shifted Neurons](https://arxiv.org/pdf/1712.09926) (CSNs, 2017) [34] — 调整基础学习器中每个隐藏节点的神经元状态

#### 学习记忆 (L2R)

将一个FSL任务的支持集建模为一个序列，引入外部记忆模块存储关键样本或任务信息。

- **优势**：通过记忆回放增强持续学习能力
- **劣势**：固定大小记忆易导致信息溢出；大规模记忆搜索耗时

- [Meta-Learning with Memory-Augmented Neural Networks](https://proceedings.mlr.press/v48/santoro16.pdf) (MANN, 2016) [35] — 使用记忆增强型神经图灵机（NTM）
- [Attentive Recurrent Comparators](https://arxiv.org/pdf/1703.00767) (ARCs, 2017) [36] — 开发了基于注意力机制的RNN

### 迁移学习 (Transfer learning)

将源领域的知识迁移到目标领域，直接利用预训练模型的通用特征提升目标任务的性能。

⚠️ **迁移学习和学习微调方式的区别**：元任务之间可无关，模型学习跨任务的泛化能力；迁移学习依赖源任务和目标任务**领域相关**。

---

# 小样本学习的衍生

## 半监督小样本学习 (S-FSL)

训练集不仅包含带标签的支持样本，还包含一些未标注样本。

## 无监督小样本学习 (U-FSL)

训练集是完全未标注的，模型需要依靠自身能力从无标签数据中挖掘有价值的信息。

## 跨域小样本学习 (C-FSL)

当FSL任务来自一个全新的领域时，需使用在分布、特征等方面存在差异的域的数据集。

## 广义小样本学习 (G-FSL)

希望模型能够在更广泛的标签空间上进行推理和预测，而不仅仅局限于特定的小样本任务中的标签集合。

## 多模态小样本学习 (M-FSL)

涉及来自额外模态的信息或数据。包括跨模态匹配和多模态融合。

---

# 思考问题

## 多少算小样本？

在少样本学习领域，"少"并没有严格统一的标准：

- **常规分类任务**：每个类别的样本数通常是1到10个
  - 1-shot：每个类别仅1个样本
  - 5-shot：每个类别5个样本
  - 多数论文用5way-1shot和5way-5shot作为通用比较标准

- **目标检测任务**：每个新类仅需10到30个标注样本
  - MS-COCO数据集中一般是10/30-shot
  - PASCAL-VOS数据集中一般是1/2/3/4/10-shot

## 少样本性能的下限和上限

*下限要比同类算法尽可能高，上限要跟全监督的靠齐。*

---

# 参考文献

[1] [A Survey on Machine Learning from Few Samples](https://arxiv.org/pdf/2009.02653)

[2] [Learning from one example through shared densities on transforms](https://ieeexplore.ieee.org/abstract/document/855856)

[3] [Learning Generative Visual Models from Few Training Examples](https://cs.nyu.edu/~fergus/papers/Fei-Fei_GMBV04.pdf)

[4] [One-shot learning with a hierarchical nonparametric Bayesian model](https://dl.acm.org/doi/10.5555/3045796.3045815)

[5] [One shot learning of simple visual concepts](https://utstat.toronto.edu/~rsalakhu/papers/LakeEtAl2011CogSci.pdf)

[6] [Pattern recognition from one example by chopping](https://proceedings.neurips.cc/paper/2005/file/d0bb8259d8fe3c7df4554dab9d7da3c9-Paper.pdf)

[7] [One Shot Learning via Compositions of Meaningful Patches](https://www.cs.jhu.edu/~ayuille/Pubs15/AlexWongOneShotCVPR2015.pdf)

[8] [Towards a Neural Statistician](https://arxiv.org/pdf/1606.02185)

[9] [One-Shot Learning of Scene Locations via Feature Trajectory Transfer](https://openaccess.thecvf.com/content_cvpr_2016/papers/Kwitt_One-Shot_Learning_of_CVPR_2016_paper.pdf)

[10] [AGA: Attribute Guided Augmentation](https://arxiv.org/pdf/1612.02559)

[11] [Multi-level Semantic Feature Augmentation for One-shot Learning](https://arxiv.org/pdf/1804.05298)

[12] [Attribute-Based Synthetic Network (ABS-Net)](https://www.sciencedirect.com/science/article/pii/S0031320318300876)

[13] [Attribute-Based Transfer Learning for Object Categorization](https://link.springer.com/content/pdf/10.1007/978-3-642-15555-0_10.pdf)

[14] [Robust boosting for learning from few examples](https://ieeexplore.ieee.org/document/1467290)

[15] [Low-shot Visual Recognition by Shrinking and Hallucinating Features](https://openaccess.thecvf.com/content_ICCV_2017/papers/Hariharan_Low-Shot_Visual_Recognition_ICCV_2017_paper.pdf)

[16] [Delta-encoder: an effective sample synthesis method for few-shot object recognition](https://arxiv.org/pdf/1806.04734)

[17] [Low-Shot Learning from Imaginary Data](https://arxiv.org/pdf/1801.05401)

[18] [Low-shot Learning via Covariance-Preserving Adversarial Augmentation Networks](https://arxiv.org/abs/1810.11730)

[19] [Data Augmentation Generative Adversarial Networks](https://arxiv.org/abs/1711.04340)

[20] [Image Deformation Meta-Networks for One-Shot Learning](https://arxiv.org/abs/1905.11641)

[21] [Object classification from a single example utilizing class relevance metrics](https://proceedings.neurips.cc/paper/2004/file/ef1e491a766ce3127556063d49bc2f98-Paper.pdf)

[22] [Learning a kernel function for classification with small training samples](https://dl.acm.org/doi/10.1145/1143844.1143895)

[23] [Siamese neural networks for one-shot image recognition](https://www.cs.cmu.edu/~rsalakhu/papers/oneshot1.pdf)

[24] [Deep Triplet Ranking Networks for One-Shot Recognition](https://arxiv.org/abs/1804.07275)

[25] [Prototypical Networks for Few-shot Learning](https://arxiv.org/pdf/1703.05175)

[26] [Matching Networks for One Shot Learning](https://arxiv.org/pdf/1606.04080)

[27] [Learning to Compare: Relation Network for Few-Shot Learning](https://arxiv.org/pdf/1711.06025)

[28] [Model-Agnostic Meta-Learning for Fast Adaptation of Deep Networks](https://arxiv.org/pdf/1703.03400)

[29] [Optimization as a model for few-shot learning](https://openreview.net/pdf?id=rJY0-Kcll)

[30] [Learning feed-forward one-shot learners](https://arxiv.org/pdf/1606.05233)

[31] [LGM-Net: Learning to Generate Matching Networks for Few-Shot Learning](https://arxiv.org/pdf/1905.06331)

[32] [Learning to learn: Model regression networks for easy small sample learning](https://link.springer.com/content/pdf/10.1007/978-3-319-46466-4_37.pdf)

[33] [Meta Networks](https://arxiv.org/pdf/1703.00837)

[34] [Rapid Adaptation with Conditionally Shifted Neurons](https://arxiv.org/pdf/1712.09926)

[35] [Meta-Learning with Memory-Augmented Neural Networks](https://proceedings.mlr.press/v48/santoro16.pdf)

[36] [Attentive Recurrent Comparators](https://arxiv.org/pdf/1703.00767)
