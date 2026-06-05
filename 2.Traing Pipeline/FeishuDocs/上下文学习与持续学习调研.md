# 上下文学习与持续学习技术调研

> 来源：https://uih.feishu.cn/docx/LsV0dXqIjoJs7KxnWONcyqhunjh
> 
> 特别提示：本文主要参考综述论文 Zhou T, Zhang F, Chang B, et al. Image Segmentation in Foundation Model Era: A Survey. arXiv 2024. arXiv preprint arXiv:2408.12957.

---

# 基于视觉语言模型+智能体构建的上下文学习

参考论文：Meng T, Tao Y, Yin W. Few-Shot Classification & Segmentation Using Large Language Models Agent[J]. arXiv preprint arXiv:2311.12065, 2023.

- 主要亮点：
  - 只是构建了一个分割智能体，**没有进行任何微调**
  - 基于支持图像+掩码，GPT4V对查询图像执行一个目标检测任务，生成目标检测框，用于作为SAM的视觉提示
  - Agent自我反思，对掩码进行迭代优化

- 整体结构和Agent运行流程：
  1. **Cognition**：输入是支持图像及其掩码和框、查询图像；调用GPT4V，基于支持图像+掩码+框，生成前景物体的文本描述
  2. **Questing**：继续调用GPT4V，基于支持图像文本描述、查询图像，生成查询框
  3. **Segmentation**：调用SAM，基于查询框，生成查询图像的掩码
  4. **Judgement(Self-Reflection)**：调用GPT4V，对整体输出结果进行自我反思，假设输出的查询图像掩码不合格，则反思改进建议，并循环运行、迭代改进

- 算法效果：从mIoU的数值来看，显著优于HSNet
- 模型参数规模：基座模型是GPT-4V和SAM-VIT-H，参数规模大

---

# 基于视觉语言模型实现"推理分割"

参考论文：Lai X, Tian Z, Chen Y, et al. Lisa: Reasoning segmentation via large language model[C]//Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition. 2024: 9579-9589.

- **Reasoning Segmentation（推理分割）**的含义：该任务要求根据涉及复杂推理的隐含查询文本生成二值分割掩码。查询文本不仅限于简单的引用（例如"橙子"），还包括更复杂的描述，这些描述涉及复杂的推理或世界知识（例如"富含维生素C的食物"）。

- 模型结构：
  - 从隐含查询文本中分析出分割目标：输入查询图像和查询问题，使用视觉语言模型对查询问题进行分析，生成分割目标及其文本描述
  - 提示分割：使用分割目标<SEG>作为提示（类似于文本提示），执行图像分割

---

# 基于纯视觉大模型的上下文学习：使用MAE策略进行训练

## Painter

参考论文：Wang X, Wang W, Cao Y, et al. Images speak in images: A generalist painter for in-context visual learning[C]//Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition. 2023: 6830-6839.

- 视觉任务的统一处理：全部统一为彩色图像生成任务
  - 将分割、点定位、深度估计等不同的视觉任务，统一转换为三通道RGB图像
- 训练：类似于MAE，输入图像与视觉任务输出图像转换为patch embedding，然后对输出图像进行掩码，再使用ViT对其进行重建、计算loss
- 推理：示例 + 查询图像 + 待预测掩码，ViT重建掩码区域内容

## SegGPT

参考论文：Wang X, Zhang X, Cao Y, et al. Seggpt: Segmenting everything in context[J]. arXiv preprint arXiv:2304.03284, 2023.

- 相较于Painter，专注于分割任务
- **效果表现非常好，达到SOTA，甚至比原型学习的效果更好**
- 模型参数规模：ViT-L，307M

---

# 基于纯视觉大模型的上下文学习：使用类GPT的训练策略

参考论文：Bai Y, Geng X, Mangalam K, et al. Sequential modeling enables scalable learning for large vision models[C]//Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition. 2024: 22861-22872.

- 数据集：无标签图像/视频数据集，有标签图像数据集/视频数据集
- 利用预训练的VQGAN，生成视觉token序列
- 训练自回归transformer模型：类似于GPT，前面所有token预测下一个token并与金标准计算交叉熵损失
- 应用场景：连续帧预测、分割/点定位/点追踪示例作为上下文prompt、图像补全、图像生成

- **技术挑战**：
  - **不同视觉任务输出具有一定的变异性**，使得纯视觉上下文学习存在一些挑战性
  - 通过上下文学习在**任意粒度级别**执行分割的能力仍是一个未探索的领域
  - 大模型容易出现**对象幻觉**的问题
  - 结合实际业务场景，需要实际评估大模型的**部署可行性及部署效率**

- 模型参数规模：**纯视觉大模型的研究尚处前沿**，它使用的**模型规模与GPT-3等大语言模型相比要小得多**，这可能是限制它性能的关键因素

---

# 医学图像领域的纯视觉大模型-上下文学习

参考论文：Ren S, Huang X, Li X, et al. Medical Vision Generalist: Unifying Medical Imaging Tasks in Context[J]. arXiv preprint arXiv:2406.05565, 2024. **(2025 ICLR)**

本文算法参考了自然图像领域的纯视觉大模型**Painter和SegGPT**(参数量<1B)

### 数据集构建

- 规模与多样性：13个公开数据集；**250万2D图像**（共计28173 volumes，每个volume平均贡献约88个片层）；覆盖CT/MRI/X射线/微超声4种模态；涉及腹部/骨盆/脑部/胸部4大解剖区域
- 任务覆盖：分割（9个数据集）；跨模态合成；脑部修复；低剂量去噪；病灶检测
- 预处理规范：CT图像统一窗位[-100,200]HU；图像尺寸标准化为512×512→随机裁剪448×448

### 基座模型

Medical MIM：通过MAE方法，在医学图像数据集上预训练的ViT。

### 训练过程

- 任务统一：将分割/跨模态合成/修复/去噪等任务统一为图像生成问题，输入输出均标准化为单通道灰度图像格式
- 混合训练策略：
  - 分割任务：100%采用自回归训练（保留全局上下文）
  - 其他任务：90%掩码图像建模（MAE）+10%自回归训练
- 损失函数：采用平滑L1损失，优化器使用AdamW（学习率1e-3，余弦退火策略）

### 算法效果

- 整体测试效果完全领先其他视觉大模型
- 分割任务上，可取得80左右的mIOU值(1 shot)；相较于全监督nnUNet，mIOU数值相差0.05~0.15左右
- 训练集越大、效果越好，表现出scaling law；医学图像预训练带来的增益非常明显

---

# 基于多模态大模型的上下文学习

参考论文：Sheng D, Chen D, Tan Z, et al. Towards More Unified In-context Visual Understanding[J]. IEEE, 2023. DOI:10.1109/CVPR52733.2024.01269.

- 多模态embedding构建：
  1. 视觉量化：使用预训练好的VQGAN生成视觉embedding
  2. 文本量化：使用GPT-2
  3. 统一嵌入：通过全连接层，将多模态embeddings对齐到相同语义空间中
- 模型结构：类GPT的decoder-only结构；增加了MOE层
- 上下文视觉理解任务上表现良好，上下文分割任务上不如SegGPT
- 模型参数规模：309M

---

# 基于多模态大模型的上下文学习SegICL（2D）：应用于医学图像

参考论文：Shen L, Shang F, Yang Y, et al. SegICL: A Universal In-context Learning Framework for Enhanced Segmentation in Medical Imaging[J]. arXiv preprint arXiv:2403.16578, 2024.

- 目标：实现医学图像分割和医学图像描述，特别是在处理超出分布（OOD）任务时
- 背景/与其他方法的对比：
  - **少样本学习(小模型)的通用性/域适应性还是相对较弱**
  - 多模态ICL在分割等细粒度较高任务上的尝试还尚处前沿

- 本文构建了一个多模态大模型，支持输入图像和文本，并将其映射和编码到相同的隐空间。**图像解码器使用Stable Diffusion模型**

- 数据集构建和微调训练流程：
  - 构建文本引导分割的指令微调数据集
  - 构建少样本-上下文学习的指令微调数据集
  - 微调训练的基座模型：
    - 多模态编码器：视觉语言模型Qwen-7B
    - 图像解码器：扩散模型SD 1.5B

- 算法效果：在MRI少样本学习测试集上，Dice可达到85.13 (3 shot)
- 模型参数规模：多模态编码器基于Qwen-7B微调；图像解码器SD 1.5B

---

# 基于Diffusion model的上下文学习

参考论文：Wang Z, Jiang Y, Lu Y, et al. In-context learning unlocked for diffusion models[J]. Advances in Neural Information Processing Systems, 2023, 36: 8542-8562.

- 视觉+语言上下文的格式：文本提示，图像示例，查询图像
- 具体模型结构设计：使用ControlNet模型结构
  - 文本上下文通过文本编码器+交叉注意力引入到diffusion model中
  - 示例图像对通过concat+堆叠卷积处理后输入到ControlNet中
  - 查询图像通过另一组堆叠卷积处理后输入到ControlNet中
- 模型训练：构建6个任务，对ControlNet进行微调

---

# Diffusion model用于实现支持图像示例扩增

参考论文：Tan W, Chen S, Yan B. Diffss: Diffusion model for few-shot semantic segmentation[J]. arXiv preprint arXiv:2307.00773, 2023.

- ControlNet预训练：预训练一个ControlNet模型，以单幅支持图像及其对应的掩码作为条件，生成多个辅助支持图像
- 这些生成的支持图像与原始支持图像共享相同的语义掩码，但在内容、背景和外观上存在显著变化
- 用于增强FSS(Few-Shot Segmentation)的效果：将原始支持图像与新生成的辅助支持图像一起作为输入，传递给FSS模型

---

# Few Shot Learning Leaderboard

## 结论

- **SOTA in the few shot learning leaderboard**
  - few shot segmentation leaderboard：**SegGPT**，一种基于纯视觉大模型的上下文学习范式，以元学习策略进行训练，可取得SOTA性能
  - few shot object detection leaderboard：**FM-FSOD**，一种基于视觉语言模型的上下文学习范式，以元学习+迁移学习策略进行训练，可取得SOTA性能

- 在具体模型/少样本学习范式上，基于大模型的上下文学习，可取得SOTA性能
- 与元学习相比，迁移学习也是一种常用的少样本学习范式（FSOD中的NIFF；FSS中的nnSAM）
  - 但是，对于迁移学习，需要用少样本进行微调，由于新类和基类数据样本极不平衡，新类样本极其有限，因此微调后的模型依然会偏向基类，在新类上的效果会显著下降
  - 迁移学习的方法（如少样本目标检测中的NIFF），可以在G-FSOD（广义少样本目标检测）中取得SOTA效果
- 元学习训练策略，可以显著提升模型在新类上的泛化性能；将二者（迁移学习和元学习）结合使用，能够获得新类别/基类别上的SOTA性能

## Few Shot Segmentation Leaderboard

- https://paperswithcode.com/sota/few-shot-semantic-segmentation-on-pascal-5i-1
- https://paperswithcode.com/task/few-shot-image-segmentation
- **SegGPT（视觉基础模型）达到SOTA性能**

## Few Shot Object Detection Leaderboard

参考综述：Chudasama V, Sarkar H, Wasnik P, et al. Beyond few-shot object detection: A detailed survey[J]. arXiv preprint arXiv:2408.14249, 2024.

根据综述内容可知，**FM-FSOD（多模态大模型）是目前少样本目标检测领域的SOTA算法**。

### FM-FSOD

参考论文：Han G, Lim S N. Few-shot object detection with foundation models[C]//Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition. 2024: 28608-28618.

**模型结构**：
- 视觉编码器：查询图像编码到embedding隐空间；支持图像(前景区域)构建隐空间内的visual prototype
- DETR提示框生成器：通过交叉注意力机制，参考视觉原型模板，对查询图像的潜在提示框进行预测
- LLM：基于目标检测示例的上下文，对查询图像上的提示框进行类别预测

**基座模型及参数规模**：
- DINOv2 ViT-S/B/L：20M / 90M / 300M
- Deformable DETR：50M左右
- Vicuna-7B：一个7B的视觉语言模型(LLAMA2微调获得)

**训练过程：一种迁移学习+元学习的训练策略**：
1. **第一阶段预训练**：基于基类训练数据，对Deformable DETR进行传统有监督训练
2. **第二阶段元训练**：基于基类训练数据，构建查询集-支持集，对D-DETR、LLM进行元学习策略的训练（60 way 30-shot）
3. **第三阶段少样本微调**：通过新类数据+基类数据，对模型进行混合微调

**算法结果**：在PASCAL-VOC和MSCOCO数据集上，相较于NIFF，FM-FSOD在基类和**新类**上的表现显著更强

---

# 3D少样本学习调研

## 基于多模态大模型的上下文学习M3D（3D）：应用于医学图像

参考论文：Bai F, Du Y, Huang T, et al. M3d: Advancing 3d medical image analysis with multi-modal large language models[J]. arXiv preprint arXiv:2404.00578, 2024.

### 数据集构建

- 图像+文本→文本指令微调数据集
- 图像+mask/Box+文本指令微调数据集
- 该数据集总规模达到**780K多模态数据**，是目前最大的3D医学多模态数据集，覆盖8类任务（包括3D上下文/参考分割）

### 训练流程

1. 3D医学视觉编码器预训练
2. 3D空间池化(多模态对齐模块)的指令微调
3. 视觉编码器、3D感知器、LLM和分割模块指令微调

### 算法效果

- 对于开放度较高的回答，效果都不佳
- 视觉定位(生成结构化文本)的效果稍好一些，但IOU依然不足以到及格线
- 对于分割测试结果，Dice值60-80左右
- **没有专门评测上下文学习的效果**

### 参数规模

7-10B；基座模型是LLAMA-2-7B

### 2D ViT和3D ViT运算量对比

Transformer自注意力的计算复杂度为O(N²d)；N表示patch嵌入数量，d为嵌入维度；因此，**3D ViT的计算复杂度是2D ViT的100倍**。在本文中，用3D空间池化层对初始3D patch嵌入数量进行压缩。

---

## 基于3D UNet的3D视觉上下文学习MedVerse（3D）：应用于医学图像

### 一、与SegGPT的关系

- **与SegGPT的本质关联**：核心范式一致，均基于"上下文示例+查询图像"的in-context learning，通过多任务训练实现通用任务适配
- **核心差异**：
  1. 适配场景：针对3D医学图像（而非2D自然图像）
  2. 模型架构：引入三分支3D U-Net+自回归机制，支持全分辨率输出
  3. 上下文处理：支持动态上下文长度（1-8个示例），而非固定长度为1

### 二、推理流程（下-上尺度自回归迭代）

整体遵循"粗尺度全局推理→多轮细尺度滑窗优化"的next-scale autoregressive逻辑：

#### 预处理与初始设置

- 输入：查询图像（3D体数据）、上下文示例集（多组3D图像-标签对）
- 模型固定输入块大小：128×128×128
- 自回归步数计算：根据原始图像分辨率与128的比值确定，每步分辨率翻倍

#### 第一轮推理（低尺度全局上下文学习）

- 尺度调整：将查询图像、所有上下文示例集统一缩放到最小尺度（如128×128×128）
- 双分支并行推理：
  - 上下文分支：多个示例集在batch维度并行输入3D U-Net
  - 查询分支：查询图像输入相同结构的3D U-Net
- 跨分支特征融合：
  - Encoder阶段：查询图像特征作为Key和Value，上下文示例特征作为Query
  - Decoder阶段：反向操作——上下文示例特征作为Key和Value，查询特征作为Query
- 输出：得到低尺度下的全局预测结果

#### 第二轮及后续推理（高尺度滑窗+自回归上下文融合）

- 尺度升级：将查询图像、上下文示例集、上一轮预测结果统一上采样翻倍
- 滑窗拆分：上采样后的图像超过128×128×128，拆分为多个块
- 三分支协同推理：新增"自回归上下文分支"
- 块结果聚合：所有块推理完成后，拼接得到当前尺度的完整预测结果

#### 终止条件

重复上述步骤，直至预测结果分辨率与原始查询图像一致。

### 三、训练过程

- **多任务训练**：覆盖分割、去噪、偏置场校正、模态转换、颅骨剥离等任务
- **动态上下文长度**：训练时随机采样上下文示例集长度（1-8个）
- **训练策略**：采用教师强制（teacher forcing），自回归上下文用下采样2-4倍的真实标签替代
- **数据增强**：包括图像层面和任务层面

---

# 持续学习与模型微调技术

## MONAI LABEL：一种医学图像分割模型的典型主动学习方法

参考论文：MONAI Label: A framework for AI-assisted Interactive Labeling of 3D Medical Images

- 对输出结果进行不确定性评估，将不确定性高的case分配给用户进行人工标注
- 自动数据处理
- 自动模型训练

## Prompt-Based Tuning of Transformer Models for Multi-Center Medical Image Segmentation of Head and Neck Cancer

- 以上实验都是在100左右的数据量条件下完成
- 相较于不做微调，做了微调肯定会提高分割效果；参数高效微调VPT与全量微调效果差不多

## DVPT: Dynamic Visual Prompt Tuning of Large Pre-trained Models for Medical Image Analysis

- 数据量比较有限的情况下(参考Synapse/ACDC数据集测试效果)，VIT微调后的效果不算太好，显著弱于UNet全监督训练的效果
- 数据量比较多的情况下(参考Skin、Polyp)，VIT微调后的效果达到相对最佳

## Exploring Visual Prompt Tuning for Demographic Adaptation in Foundation Models for Medical Imaging

- X光片数据量共计600758；Asian人群数据量为34228，约占总数据集5.7%
- Asian人群这个数据规模情况下，参数高效微调VPT与全量微调效果相当；弱于所有数据集-全量微调的效果

---

## Adapter-Enhanced Semantic Prompting for Continual Learning

参考论文：Yin B, Zhao J, Jiang H, et al. Adapter-Enhanced Semantic Prompting for Continual Learning[J]. arXiv preprint arXiv:2412.11074, 2024.

- 持续学习（CL）的概念：首先，有一个基座模型，这个模型是在大量数据上做过预训练；对于不断积累的新任务数据，CL方法允许模型逐渐学习新的知识，但同时避免发生对已有知识的灾难性遗忘
- CL相关研究简介：
  - 正则化方法
  - 知识蒸馏
  - 参数隔离策略
  - 重放方法(Rehearsal methods)
  - 参数高效微调方法(PEFT)：提示微调、适配器微调、LoRA

- **原理**：
  - 对于每一个新任务/新场景，构建一系列特有微调参数，包括：一把"钥匙"key(隐空间向量)，文本提示，视觉提示，adapter参数，分类头
  - 推理流程：输入图像→预训练ViT编码→与提示库中每个key计算余弦相似度→匹配最相似的key→加载对应的文本/视觉提示向量、adapter参数→执行推理
  - 训练流程：冻结大模型的所有参数；新增一组微调参数[key、文本提示、视觉提示、adapter、分类头]；基于新任务数据，仅对上述新增参数进行微调

---

## Dual-Modality Guided Prompt for Continual Learning of Large Multimodal Models

参考论文：Zeng F, Zhu F, Guo H, et al. Dual-Modality Guided Prompt for Continual Learning of Large Multimodal Models[J].（2025 ICLR）

- 多模态大模型的参数高效微调方法主要包括：适配器学习、提示学习和LoRA
  - 它们分别通过块内并行连接、输入嵌入的前缀和低秩分解更新模型。主流方法采用LoRA以降低大模型训练成本
- 持续学习CL的主要方法：
  - 正则化方法
  - 重放方法（数据安全和隐私问题）
  - 参数高效微调
    - LLM领域的持续学习研究工作：Progressive Prompts，Pop等
    - 多模态大模型LMM领域的持续学习研究：CoIN
      - CoIN提出了多模态持续学习基准并应用MoELoRA，实验结果中，发现在新任务上性能显著下降，表明LoRA可能并非多模态持续学习的最佳解决方案

- **算法原理**：
  - 对于每一个新任务/新场景，构建一个特有视觉提示Prompt
  - 推理过程：对于输入的图像和文本，先使用CLIP编码→计算与每一个视觉提示prompt之间的余弦相似度→筛选出k个相似度最高的prompt→与视觉embedding、文本embedding连在一起输入LLM
  - 训练流程：基于新任务的多模态指令数据集，对模型进行指令微调

- 实验结果：相较于全量微调、MoELoRA，结果表现显著提升；遗忘率显著降低

---

## 100%自动定位-持续学习的思考问题

1. **持续收集用户使用过程中的数据，那么所需收集的数据量上限是多少？**
   - 按照基于CNN的EasyScan算法开发经验，100例左右能够获得比较稳定的自动定位结果
   - 在一些大模型微调研究中，使用100例左右的数据进行模型微调，在专一任务上的表现可取得显著提升
   - 初步认为，可将数据收集分为两个阶段：第一阶段收集所有数据直到达到100例左右；第二阶段继续收集异常数据及用户修正过的数据

2. **如何对大模型持续在线/持续学习的过程进行监控？**
   - 监控持续学习是否提升任务表现效果？
   - 监控持续学习是否达到最佳水平、即可以停止持续学习？

3. **如何设置数据筛选机制，避免将"有歧义"的数据纳入到示例数据库中？**
   - 歧义数据的定义：1）对于存在结构异常或病变的定位像数据，导致定位方式显著改变；2）对于其他用户的定位数据，可能与当前数据库中的定位习惯差异较大
   - 对于歧义数据的情况1，考虑通过图像相似度匹配，对结构异常或病变的定位像数据进行筛选。比如使用原型学习技术，用示例数据库中的图像构建原型向量，与输入图像进行相似度匹配，筛选出相似度较低的异常数据
   - 如何筛选出定位方式与数据库不一致的数据？

---

# 大模型-长上下文的处理方式调研

（待补充）

---

# 下一步计划

- **下一步可以持续调研一些医学图像领域的基座大模型、少样本学习技术**
  - 推荐参考综述论文：Pachetti E, Colantonio S. A systematic review of few-shot learning in medical imaging[J]. Artificial intelligence in medicine, 2024: 102949.
- https://scholar.google.com.hk/scholar?cites=6584157451068012904&as_sdt=2005&sciodt=0,5&hl=zh-CN
- https://scholar.google.com.hk/scholar?cites=2672283459296608720&as_sdt=2005&sciodt=0,5&hl=zh-CN
