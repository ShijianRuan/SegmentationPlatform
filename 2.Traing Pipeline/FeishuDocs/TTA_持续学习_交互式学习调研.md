# TTA / 持续学习 / 交互式学习 技术调研

> 来源：https://uih.feishu.cn/wiki/Fumbwa62nidoSgkP3yQc9qCfnJc

TTA相关研究汇总：https://github.com/tim-learn/awesome-test-time-adaptation/tree/main

---

## 统计量自适应

分割网络中往往大量使用BN/IN这样的归一化操作，其中的统计量直接控制通道级的特征分布，对于对齐源域-目标域非常关键。对此，**一种简单的处理方法是在推理时用目标域当前batch/volume的统计量来更新BN中的running mean/var，从而快速对齐特征分布，即AdaBN**。也可以通过最小化熵来优化BN中的可学习参数，即**TENT方法**。另外，也有方法从专用网络的编码特征中获取目标域的特征信息来调整归一化层。

参考论文：Valanarasu J M J, Guo P, Vs V, et al. On-the-Fly Test-time Adaptation for Medical Image Segmentation[J]. 2022. DOI:10.48550/arXiv.2203.05574.

Code：https://github.com/jeya-maria-jose/On-The-Fly-Adaptation

1. **方法核心**：在大量数据上预训练一个自编码器，将其中的编码器（DPG）部分拿来用于提取输入图像的域编码（Domain Code，一维特征向量），提取其均值与标准差参与分割网络中BN/IN层的计算。

2. **实验效果**
   - 数据集：BraTS 2019数据集，包括FLAIR、T1、Tice、T2四种成像序列。3D脑肿瘤分割任务，验证模型在不同序列数据间的任务迁移效果。使用Kaggle MRI和IXI数据集预训练DPG。
   - 实验结果：**在T1/Tice间（风格较为相似）的域适应效果显著。但在T1/T2、T1/FLAIR这种差异明显的序列上失效**。

---

## 隐变量优化（Latent Refinement）

### 根据梯度更新隐变量

参考论文：Chen K, Luo X, Qin T, et al. Test-time Adaptation for Foundation Medical Segmentation Model without Parametric Updates[J]. 2025.（ICCV, 2025）

> ⚠️ Code：Not Available

1. **方法核心**：一套针对MedSAM等基础医学分割模型的TTA框架，不改变模型参数，仅优化图像的潜在表示。显著提升多中心/多prompt扰动条件下的分割性能，且计算开销远低于现有TTA方法。

### 隐变量特征检索与融合

参考论文：Wu J, Liu X, Wang G, Zhang S. SicTTA: Single image continual test time adaptation for medical image segmentation. *Med Image Anal*. 2026;108:103859. doi:10.1016/j.media.2025.103859

Code：https://github.com/HiLab-git/SicTTA

相关解读：https://mp.weixin.qq.com/s/5G-eoKZ8P1nzyjNx0Pqovg

1. **方法核心**：已有的优化归一化统计量的TTA方法通常依赖大batch size，在单张图像时表现不稳定。该研究针对单图像、持续性输入的医学图像分割场景提供了一个稳定有效的TTA框架。论文的核心出发点在于：在目标域的测试图像中，存在一部分**源友好目标图像（Source-Friendly Target，SFT）**。这些SFT图像的特征分布介于源域和主要目标域之间，更接近源域分布的边界情况。源模型在这些SFT图像上能产生相对可靠的预测结果。因此，SFT图像可以作为"桥梁"，帮助模型适应其他非SFT图像。

   1. **基于类紧凑密度的SFT图像过滤（CCD）**
      - 提出一种无监督的度量标准**类紧凑密度**，用于评估单张测试图像的分割质量（不确定性）。CCD通过计算预测结果中类间相似性矩阵的熵来实现：熵值越低，说明预测的类间区分度越高，分割质量越好，该图像越可能是SFT图像。
      - 维护一个固定大小的SFT图像池、特征池和CCD值池，采用**先进先出**策略进行更新，以适应持续变化的数据流。

   2. **源对齐批次增强（SABE）**
      - 对于当前的测试图像，根据特征相似性从SFT池中找出最相似的K张图像。
      - 将这K张SFT图像与当前测试图像组合成一个**增强批次**，并计算该批次的归一化统计量（均值和方差）。
      - 这样做避免了单图像统计量的不稳定性，提供了更鲁棒的归一化信息。

   3. **相似性驱动的特征融合（SFF）**
      - 将当前测试图像的特征与Top-K SFT图像的特征进行加权融合，权重由它们的余弦相似度决定。
      - 融合后的特征更贴近SFT图像的特征分布，从而与源模型的知识更好地对齐，提升分割精度。

2. **实验效果**
   - 数据集：
     - 眼底图像分割：源域Drishti-GS (100张)和RIM-ONE (159张)；目标域REFUGE挑战赛训练集和验证集 (共400张)
     - 心室分割：源域Siemens心脏MRI；目标域Philips、GE、Canon心脏MRI
   - 参数设置：2D UNet，输入大小320×320，batch size设为1，SFT池大小为40，K为5，SFT入选阈值为10%
   - 实验结果：在单张图像上域适应效果显著，推理时间0.06s（2080Ti），占用显存4.95G（除去SFT图像和特征池，占2.63G）
   - **局限性**：
     1. 在测试的初始阶段，由于SFT池还没有构建完全，此时的域适应效果不佳，可以考虑通过热启动来改善。
     2. **TTA（包括该方法）主要用于相同模态下跨扫描设备、采集协议、种群的场景。对于更大程度的域偏移（比如跨模态），使用有监督的微调或域自适应更合适。**

---

## 能量模型（Energy Model）

参考论文：Zhang X, Hong B W, Park H, et al. Progressive Test Time Energy Adaptation for Medical Image Segmentation[J]. 2025. (ICCV, 2025)

Code：https://github.com/Voldemort108X/pttea_seg

1. **方法核心**：先在源域数据上训练一个区域级形状能量模型（shape energy model），用于区分局部分割形状的解剖合理性。部署时冻结分割模型的大部分参数和能量模型，每处理一批目标域数据，通过最小化能量损失来渐进式更新分割模型中的极少量参数（主要是归一化相关参数），让预测结果的形状往"低能量、合理解剖"的方向收敛，从而实现分布外数据的自适应。

   1. **区域形状能量模型（Shape Energy Model）**
      - 输入：来自分割模型fθ的预测概率图（one-hot编码+softmax）
      - 输出：一个K×K大小的能量图，每个元素对应原图上的一个h×w大小的patch。能量值越低，说明patch内的分割形状越像源域里见过的正常解剖
      - 模型结构：一个轻量的卷积网络，其作用可视为一个图像局部区域判别器
      - 训练方式：用源域分割模型fθ的预测结果和标签作为"合理形状"的样本；通过施加空间变换和扰动（FGSM方法）生成"错误形状"的样本
      - 优点：相较全局能量模型，patch级的能量模型对于局部偏差更敏感，且计算更高效

   2. **渐进式测试时能量自适应（Progressive Test-Time Energy Adaptation）**
      1. 对于目标域图像，首先使用固定参数的分割模型fθ给出初始预测结果
      2. 将初始预测结果输入能量模型获得patch级的能量图
      3. **将输出的能量图与能量模板（比如全为0）计算损失，对BN参数进行梯度更新**
      4. 基于上述过程进行迭代（论文中仅迭代10次）

2. **实验效果**
   - 数据集：8个2D医学图像分割数据集，包括心脏MRI、脊髓MRI和肺部XR图像
   - 实验设置：分割模型UNet、MedNeXt、SwinUNETR，输入大小256×256；能量模型4个卷积层，kernel_size=5，stride=2，patch size设为16，默认batch size为4，测试时参数迭代10次
   - 实验效果：基本优于其它TTA方法，且较原模型效果提升显著。能对初始分割结果做很好的修正，分割结果更贴近实际解剖
   - 若源域与目标域风格偏差太大（两腔心→四腔心），方法效果可能不佳

---

## 旁路参数调整

在主干网络之外插入极小的可学习模块（轻量卷积、Prompt token，Deformable Prompt等）。

参考论文：Kim H, Han G, Hwang D. Buffer layers for Test-Time Adaptation [EB/OL]. (2025-10-24). https://arxiv.org/abs/2510.21271, arXiv:2510.21271v2 [cs.LG]（NeurIPS, 2025）

Code：https://github.com/hyeongyu-kim/Buffer_TTA

1. **方法核心**：在网络的靠前的特征提取阶段插入一些轻量的可学习模块（1×1、3×3卷积），在测试阶段通过最小化熵或一致性正则等TTA常用的优化方法更新参数。这些Buffer layers也可以和BN中的参数同步更新，因此可以嵌入很多其它TTA方法中。

2. **实验效果**：
   - 验证方法：分类任务，在其它基于BN的TTA方法中嵌入Buffer layers，比较分类错误率
   - 效果：与其它基于BN的TTA方法相比，在小batch size下效果更好，增大batch size，效果进一步提升
   - 认识：
     1. 在小batch size的情况下，buffer layer嵌入网络的early stage效果更好。在大batch size的情况下，buffer layer嵌入网络的early和middle stage效果更好

---

## 基于原型库的TTA

参考论文：Wang W, Zhou J, Zhang C, Xing W, Fan S, Qu X. Prototype bank-driven test-time adaptation for medical ultrasound image segmentation. *Med Phys*. 2026;53(1):e70280. doi:10.1002/mp.70280 **（PBTTA）**

> ⚠️ Code：Not Available

1. **方法核心**：
   1. **动态统计融合模块（DSFM）**：依据源域模型中已有的BN统计量与目标域数据统计量动态调整测试阶段BN中的统计量
   2. **原型库引导的语义适应模块（PBSAM）**：
      - 原型库构建：为每个语义类别维护一个动态更新的原型库，容量固定，先进先出。原型是该类别高置信度像素（比如Sigmoid输出>0.95）的特征向量的均值，代表该类别的典型特征
      - 原型分类器：对于待分割的图像中的每个像素点，计算其特征向量与原型库中各类别原型的相似度。对top K个最相似的原型根据距离计算权重，通过加权形成一个基于原型的非参数分类器
   3. **双分类器融合**：最终的分割结果由模型的参数化分类器和上述原型分类器的输出加权融合得到

2. **实验效果**
   - 数据集：超声乳腺肿瘤分割（UDIAT, BUSI, BUSBRA, STU, SYSU）和超声甲状腺肿瘤分割（DDTI, TN3K, TNUS）
   - 参数设置：2D UNet，384×384大小输入，batch size设为1，λ_BN、λ_proto、λ_fusion均为0.8，原型库大小为20，K为8
   - **局限性**：超参数多，影响大；依赖原型库质量

---

## 域自适应（迁移学习）

https://uih.feishu.cn/minutes/obcn7me3qi4vy75sbzt7a2on（2024 MR冠脉研发对迁移学习的调研）

相关文件：迁移学习文献调研总结-DXY-LY(1).pptx

---

## 其它

### nnSAM：嵌入SAM先验的nnUNet框架

参考论文：Li Y, Jing B, Li Z, Wang J, Zhang Y. Plug-and-play segment anything model improves nnUNet performance. *Med Phys*. 2025;52(2):899-912. doi:10.1002/mp.17481

Code: https://github.com/Kent0n-Li/nnSAM

1. **核心工作**：**在nnUNet中嵌入SAM编码器，提升模型在小样本训练情况下的性能表现。**
   - SAM存在的问题：尽管SAM具备零样本分割能力，但其推理过程依赖于人机交互，使其仅为半自动化
   - nnUNet存在的问题：通常从零开始，需要大量领域特定训练数据才能获得良好的分割性能
   - 提出了nnSAM模型，结合了SAM强大的特征提取能力与nnUNet的数据中心自动配置能力。此外，还设计了一种基于水平集函数的曲率损失，使模型能够从有限标注数据中学习解剖形状先验

2. **方法**：
   - nnSAM由两个并行编码器组成：nnUNet编码器和SAM编码器。SAM编码器是一个在广泛的SA-1B分割数据集上预训练的视觉变换器（ViT）。来自两个编码器的嵌入被连接在一起，然后输入到nnUNet的解码器中
   - 解码器有两个输出层，一个是分割头，另一个是基于水平集的回归头
   - SAM编码器作为即插即用插件，在训练过程中其参数保持冻结。**考虑到推理效率问题，实际使用Mobile-SAM（参数量为原始SAM的1/60）**

3. **效果**：在小样本下（≤20）性能明显优于nnUNet、SwinUNet等其它经典模型

4. **局限性**：
   1. 基于水平集的曲率损失（形状监督）机制仅对形状规则、结构相对固定的器官/组织有效，**对于形状多变、边界不规则的分割目标（如肿瘤）可能不适用**
   2. 在3D场景下，需先将图像逐切片输入SAM编码器，再融合成3D特征

---

# 持续学习（Continual/Lifelong/Incremental Learning）

持续学习（或终身学习、增量学习），是指在模型部署后，可以**在任务或数据流不断变化的情况下学习新知识，同时尽量不忘记旧知识**。相关方法大体可分为三类：

- **Replay-based**：在训练新任务时，保留部分历史数据或特征（记忆库），使用新旧数据混合训练，以减轻灾难性遗忘
- **Regularization**：在loss中加入参数约束项，防止模型在新任务上训练时大幅改变对旧任务重要的参数。代表方法EWC、LWF
- **Dynamic Model**：模型动态扩展与参数隔离。为每个新任务分配一部分独立参数（Adapter、LoRA等），通过门控选择机制在推理时选择合适的子网络

依据文献中的实验结果，**Replay-based类方法的效果通常更优**。但其可能存在数据隐私与存储资源方面的风险问题。

相关综述：
- [1] Qazi M A, Hashmi A U R, Sanjeev S, et al. Continual Learning in Medical Imaging: A Survey and Practical Analysis[J]. 2025. ACM Comput. Surv. https://doi.org/10.1145/3785663
- [2] Bruno P, Quarta A, Calimeri F. Continual Learning in Medicine: A Systematic Literature Review[J]. Neural Processing Letters, 2025, 57(1). DOI:10.1007/s11063-024-11709-7

---

## Lifelong nnU-Net

参考论文：González, C., Ranem, A., Pinto Dos Santos, D., Othman, A., & Mukhopadhyay, A. (2023). Lifelong nnU-Net: a framework for standardized medical continual learning. Scientific reports, 13(1), 9381. https://doi.org/10.1038/s41598-023-34484-2

Code：https://github.com/MECLabTUDA/Lifelong-nnUNet

1. **核心工作**：专门针对分割问题，基于nnUNet搭建了一个标准化医学影像持续学习训练和评估框架。
   - 底层结构：标准nnUNet，包括负责特征提取的UNet主体（编码-解码），以及任务头（输出头）
   - 支持多头架构：多任务时，模型主体共享，每个任务独有一个输出头；处理新任务时，会复制一个新输出头
   - 集成多种持续学习方法：
     1. 顺序学习（Sequential Training）
     2. 重放训练（Rehearsal）
     3. Elastic Weight Consolidation（EWC）
     4. Learning Without Forgetting（LWF）
     5. Modeling the Background（MiB）
     6. Pseudo-labeling and LOcal Pod（PLOP）
   - 持续学习效果自动评估：自动对每个任务的数据集做训练/验证/测试；在任务序列中记录每次训练后，在所有旧任务上的性能，计算BWT/FWT等持续学习指标

2. **实验效果**
   - 数据集：前列腺分割（ISBI, I2CVB, UCL, DecathProst）、海马体分割（Harp, Dryad, DecathHip）、心脏腔室分割（多中心、多厂商）
   - 持续学习中的评价指标：
     - **Backward Transfer（BWT）**：反映在学完新任务后，旧任务性能的变化。>0表示学新任务能帮助旧任务，<0表示遗忘
     - **Forward Transfer（FWT）**：反映在学新任务时，之前经验是否加速新任务学习。>0表示有正向迁移
   - **关键结论**：
     1. **没有任何方法在这些设置下实现正向BWT（BWT>0）**，也就是在3D医学图像分割中还做不到越学越会
     2. **Rehearsal方法的表现最好。遗忘最小，代价是需要保存历史样本，涉及到数据隐私和存储资源的问题**
     3. EWC/MiB都能较好地降低部分旧任务遗忘，但对新任务的学习能力（可塑性）下降明显
     4. LwF/RW在分割任务中表现不佳。对旧任务保护有限，且新任务性能也受损
     5. 多个输出头和单个输出头效果差距不大

---

## CLMS（无监督域自适应+持续学习）

参考论文：Li W, Zhang Y, Zhou H, et al. CLMS: Bridging domain gaps in medical imaging segmentation with source-free continual learning for robust knowledge transfer and adaptation[J]. Medical image analysis, 2025:100. DOI:10.1016/j.media.2024.103404.

Code：https://github.com/xie-lab/CLMS

1. **核心工作**：在无源域数据和目标域标签的情况下实现模型跨域自适应，训练过程略复杂。（场景属于**Source-free domain adaption**，但用到了Replay-based持续学习方法来减轻模型遗忘）
   1. 多尺度图像重建：将目标域图像patch或整图转换为一种隐式的规范形式（**Canonical Form**）
   2. 持续学习模块：避免灾难性遗忘
   3. 风格特征对齐模块：将规范形式的风格与源域对齐

2. **实验效果**
   - 数据集：前列腺MRI分割（NCI-ISBI13 + I2CVB → PROMISE12）、结肠息肉分割（CVC-ClinicDB → ETIS-Larib）、眼底图像分割（私有多中心眼底数据集）

---

## CLMU-Net（Replay-based）

参考论文：Sadegheih Y, Merhof D, Kumari P. Towards Modality-Agnostic Continual Domain-Incremental Brain Lesion Segmentation [EB/OL]. (2026-01-20). https://arxiv.org/abs/2601.13927v1, arXiv:2601.13927v1 [eess.IV].

Code：https://github.com/xmindflow/CLMU-Net

1. **核心工作**：增量学习+多模态3D脑病灶分割，不依赖数据集中特定的模态组合
   1. **模态无关的输入层设计**：
      - 通道膨胀：输入层的卷积通道数与此前参与训练的通道数对应，若有新的模态，则增加一个通道，对应卷积参数随机初始化
      - 随机模态丢弃：训练时对当前样本可用模态数据随机置零，模拟模态组合变化的情况
   2. **域条件文本引导（DCTG）**：
      - 为每个病例构造一段简短的文本描述，并通过BioBERT编码
      - 将文本编码投影到域视觉特征匹配的维度
      - 把UNet瓶颈层输出在空间维度展平并叠加相应的位置编码
      - 将文本编码与特征编码进行多头注意力，将输出与原瓶颈层特征融合再传给解码器
   3. **病变感知回放缓冲（Lesion-aware Replay Buffer）**：在很小的Buffer预算下尽量减少遗忘

2. **实验效果**
   - 数据集：5个3D脑MRI数据集，模态与病种异质
     - BRATS-Decathlon：脑肿瘤（T1, T1c, T2, FLAIR）
     - ATLAS：卒中（多为T1）
     - MSSEG：多发性硬化（T1, FLAIR, T2, PD, T1c）
     - ISLES：急性卒中（DWI）
     - WMH：白质高信号（FLAIR, T1）
   - 参数设置：128×128×128大小输入，batch size为2，每个任务缓存10个case。Nvidia H100，训练41h
   - 结果：与当前Replay-based和非Replay-based方法比较，基本能达到最优效果。增大缓存大小可进一步提升性能

---

## CL-LoRA（Dynamic Model）

参考论文：He J, Duan Z, Zhu F. CL-LoRA: Continual Low-Rank Adaptation for Rehearsal-Free Class-Incremental Learning[C]//2025. DOI:10.1109/CVPR52734.2025.02843. **(CVPR 2025)**

Code：https://github.com/JiangpengHe/CL-LoRA

1. **核心工作**：**现有PEFT-CIL通常为每个新任务/阶段创建一套全新的适配器。随着任务数量增加，这导致参数冗余。由于任务间适配器是相互独立的，这些方法未能有效利用和学习任务间的共享知识，限制了模型的性能和泛化能力**。为了克服上述局限，该研究针对类别增量任务提出了CL-LoRA（ContinuaL Low-Rank Adaptation）。其核心动机是通过引入一种双适配器（Dual-Adapter）架构，明确分离并处理跨任务的共享知识和任务独有的特定特征，同时通过特殊机制来防止知识遗忘和参数冗余。

   1. **双适配器**：
      - 任务共享LoRA：学习跨任务的共性知识。随机初始化一个固定的正交矩阵B，以及可学习的矩阵A。作用于ViT网络的前l个block
      - 任务特定LoRA：学习每个任务的特有差异。即常规的LoRA模块，作用于ViT网络的后N-l个block

   2. **早退出知识蒸馏（Early-Exit KD）**：在不保存旧样本的情况下让共享LoRA记住旧任务分布。文中通过在共享段末端（第l个block）做蒸馏

   3. **梯度重分配**：对共享LoRA中的矩阵A的蒸馏损失梯度做重要性加权，权重取决于矩阵A中各行向量的范数

   4. **Block级权重与正交约束**：给任务特定LoRA模块添加可学习的缩放矩阵U，通过损失函数保持不同任务特定LoRA模块对应的缩放矩阵U之间的正交性

   5. **原型分类器**：训练阶段用各任务训练集样本的[CLS] token最终特征取均值得到每个类别的类原型；推理阶段对测试样本计算每个任务特定LoRA的[CLS] token最终特征与相应类原型的余弦相似度

2. **实验效果**
   - 数据集：CIFAR-100、ImageNet-R、ImageNet-A、VTAB
   - 参数设置：ViT-B/16，含12个transformer block，前6个block插入共享LoRA，后6个block插入任务特定LoRA；LoRA的秩设为10
   - 结果：在ImageNet-R, ImageNet-A, VTAB这些难度较高、分布偏移明显的数据集上CL-LoRA能取得最优效果

---

## Foundation model + LoRA（Dynamic Model）

参考论文：Few-Shot Continual Learning for 3D Brain MRI with Frozen Foundation Models

> ⚠️ Code: Not Available

冻结预训练骨干 + 为每个异质任务单独训练专属LoRA适配器 + 任务头，推理时按需加载对应插件，即可实现零遗忘。

> 💡 **实验观察到，对于分割任务，将LoRA同时作用到编码器和解码器上微调效果会更好。**

---

## UNEG（Dynamic Model）

参考论文：Camila Gonzalez, Nick Lemke, Amin Ranem, et al., 2025. What is Wrong with Continual Learning in Medical Image Segmentation? In Proceedings of the International Workshop on Personalized Incremental Learning in Medicine (PILM '25). Association for Computing Machinery, New York, NY, USA, 25–34. https://doi.org/10.1145/3746259.3760435

> ⚠️ Code: Not Available（基于Lifelong-nnUNet实现的）

针对域增量学习的持续学习策略：
- 对每个数据域单独训练一个nnUNet模型用于分割目标
- 对每个数据域单独训练一个自编码器（相同nnUNet结构）
- 当处理新数据时，先输入各个自编码器比较重建结果，以进行数据域的识别，而后选择相应域的分割模型

---

## EWC-LoRA

参考论文：Zheng Y, Zhang Y, Joost V D W, et al. Revisiting Weight Regularization for Low-Rank Continual Learning[J]. 2026. https://arxiv.org/abs/2602.17559（ICLR, 2026）

Code：https://github.com/yaoyz96/low-rank-cl

---

# 交互式学习

适合细粒度的个性化适配。即接受用户的反馈（修改、偏好选择）来调整后续的输出，实现"越用越好用"的目标。但现阶段研究**均需要使用多标注者数据训练模型**，除去公开数据集，要获取这样的数据标注资源比较困难。**但也许可以通过数据增强来模拟多标注者？在Tyche中通过对查询图像以及上下文施加多次扰动，从而使模型输出多种不同风格的分割结果，感觉这样的思想可以嵌入进来。**

---

## SPA（交互式分割对齐用户偏好）

参考论文：Zhu J, Wu J, Ouyang C, et al. SPA: Efficient User-Preference Alignment against Uncertainty in Medical Image Segmentation[J]. 2024.（ICCV, 2025）

Code：https://github.com/ImprintLab/SPA

1. **核心工作**：**把"用户对不确定区域的偏好"显式建模成一个可学习的潜在分布，在测试时通过极少量交互快速对齐**，并能在后续病例上继续使用，从而实现真正意义上的用户偏好对齐 + 交互式持续适应。

   1. **用户偏好建模**：把用户偏好抽象为一个潜在随机变量z，假设其服从高斯混合分布
   2. **偏好感知分割**：在当前偏好分布pθ(z)下生成一组反映不确定性的分割结果，给予用户挑选
      - 通过SAM的图像编码器和prompt编码器分别得到输入图像x的特征ex与用户交互结果的特征eu
      - 从当前偏好分布pθ(z)中采样N个潜在向量zn，将其与图像特征ex融合，得到偏好感知特征exn
      - 使用SAM的mask解码器对每一个exn+eu输出一个分割预测yn
      - 对所有预测结果做聚类，得到k个差异明显的候选分割给用户选择
   3. **基于反馈的偏好适配**：根据用户选择更新偏好分布
   4. **训练过程**：
      - 训练数据构建：**每张图像有多个医生标注**，每次迭代从多个标注中通过随机采样和加权组合来形成GT
      - Training Loop：双层循环。外层是模型参数迭代更新循环，内层是模拟用户交互的循环

2. **实验效果**
   - 数据集：REFUGE2（眼底图像视杯分割，7位眼科医生标注）、LIDC-IDRI（肺结节CT分割）、QUBIQ系列任务
   - 参数设置：混合高斯模型包含16个高斯分量，每轮从偏好分布中采样48个点，最终提供4个候选分割，最多交互6轮
   - 实验效果：在7个不同任务上，**3次迭代后的平均Dice达到约89.68%**，显著优于其它分割模型/交互式分割方法

---

## VerSe

参考论文：Guo B, Ye M, Gao Y, et al. VerSe: Integrating Multiple Queries as Prompts for Versatile Cardiac MRI Segmentation[J]. 2024.

Code：https://github.com/bangwayne/Verse（含CMR分割的模型权重）

相比于一般交互式分割方法来说，它能支持以下三种分割模式：

1. **全自动分割**：可提供完全自动的分割结果，无需交互。分割效果能逼近全监督专家模型
2. **半自动分割**：在需要用户修正结果的情况下，用更少的交互次数即能达到目标效果
3. **纯交互式分割**：在无初始自动分割结果的情况下，仅依赖用户点击实现分割。该功能在分布外数据上依然有效

---

## 其它待整理论文

- Wu Y, Luo X, Xu Z, et al. Diversified and Personalized Multi-rater Medical Image Segmentation[J]. IEEE, 2024. DOI:10.1109/CVPR52733.2024.01090. **(CVPR, 2024)** — Code: https://github.com/ycwu1997/D-Persona
- Liu K, Gao S, Fu Y, et al. Probabilistic Modeling of Multi-rater Medical Image Segmentation for Diversity and Personalization[J]. 2025. https://arxiv.org/abs/2512.00748 — Code: https://github.com/AI4MOL/ProSeg
- Elgebaly A, Delopoulos N, Hrner-Rieber J, et al. ProSona: Prompt-Guided Personalization for Multi-Expert Medical Image Segmentation[J]. 2025. https://arxiv.org/abs/2511.08046 — Code: https://github.com/albarqounilab/ProSona
- Zhang Y. Beyond Manual Annotation: A Human-AI Collaborative Framework for Medical Image Segmentation Using Only "Better or Worse" Expert Feedback[J]. 2025. — ⚠️ Code: Not Available
- Xu W, Liang Z, Anthony H, et al. You Point, I Learn: Online Adaptation of Interactive Segmentation Models for Handling Distribution Shifts in Medical Imaging[J]. 2025. — ⚠️ Code: Not Available

---

# 分布外检测（Out-of-distribution Detection）

OOD检测是机器学习中识别与训练数据分布显著不同的输入样本任务，核心是让模型能判断"我是否见过/能可靠处理这个输入"，避免对未知数据给出错误且过度自信的预测。

---

# 附录

## TT-SVD

TT-SVD 是**张量列车分解（Tensor-Train Decomposition, TTD）** 的一种高效实现方式，专门用于高维张量的低秩近似分解。其核心目标是将一个d维高秩张量（如CNN卷积层的4维权重张量W∈R^{Cout×Cin×k×k}）分解为一系列低维3D"核心模块（Core）"的乘积形式，且分解后通过核心模块的"模式收缩（Mode Contraction）"可近似重构原始张量。

- 对于d维张量W∈R^{n1×n2×⋯×nd}，TT-SVD分解后得到d个3D核心模块{G(1), G(2), ..., G(d)}，每个核心模块的维度为G(k)∈R^{rk-1×nk×rk}
- rk为"TT秩（Tensor-Train Rank）"，是控制分解精度与参数规模的关键超参数（满足r0=rd=1）

TT-SVD通过"逐次奇异值分解（SVD）+ 秩截断"实现高维张量的分解，避免直接对高维张量操作带来的计算爆炸。

---

## 其它参考材料

Gemini的建议：
- 面向小样本与个性化需求的医学影像分割自适应范式研究报告：从参数高效微调到用户偏好对齐
- 医疗影像分割中基于LoRA的微调策略：样本筛选、边界不确定性量化与个性化适应的深度研究报告
- 面向用户特定边界偏好的分割模型高效适配与演进：一种避免灾难性遗忘的混合策略研究报告

---

# 讨论会记录

## 2026.3.6同步会议程

1. 近期调研进展、各类技术方向总览
2. 调研报告框架（草稿）
3. Fenix 2.0后处理立项 模型自更新相关问题

下周计划：完善调研报告数据：

两套方案：
1. 小样本不训练
2. 医院自己的云，可以训练，可能有什么问题？（与目标一的场景相关了，只是在公司内部跟在医院云上训练会面临不同的问题）

提供大体算法架构，输入输出（需要什么，能提供什么）

过程中不确定的问题，哪些需要找其它角色聊的

用户标注样本入库准则？是算法层面判断，还是交给用户

## 2026.1.27同步会议程

1. 上下文学习方法澄清：
   1. 适配医学图像的非Transformer类方法
   2. 3D方案，以及效果、性能、资源要求
   3. 可扩展性（不同的目标类别数等）
2. 目标、计划、工作收敛性

理想的方案应该有什么样的能力？

举例：训练了一个通用的3D分割模型，满足：
1. 在大部分应用场景中，基于少量样本示例就能获得满意的预测结果
2. 某些情况下效果达不到要求，增加再多示例样本也无用（效果饱和），此时可以通过某种低成本的方式微调模型，但应避免模型遗忘

其它调研方向：**在线持续学习**、领域自适应（24年MR冠脉研发阶段做过尝试，未奏效）等

要考虑的点：
- 🟡 **梳理什么样的场景适用什么样的方法**
- 上下文入库质控、交互，库构建
- 小样本难例阳性数据，上下文学习效果问题

专利相关：奇康专利：少样本学习交互工作流、模型自更新（持续学习）

项目相关Timeline: 2.0后处理立项 6月份（越用越好用是重要feature）
