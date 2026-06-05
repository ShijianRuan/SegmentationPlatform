#!/bin/bash
# gpu1.sh —— 自动生成的 GPU 1 训练和预测脚本
# 生成时间: 2026-05-14 08:19:25
# 配置来源: Config_CoarseSeg_CT.toml

set -e

# ── 训练 ──────────────────────────────────────────────────
echo "[GPU 1] Training Start: Dataset505_CT_FixPatch (ID=505)"
CUDA_VISIBLE_DEVICES=1 nnUNetv2_train 505 3d_fullres 0 -tr nnUNetTrainerNoMirroring -p nnUNetPlans
echo "[GPU 1] Training End: Dataset505_CT_FixPatch"

# ── 预测 ──────────────────────────────────────────────────
echo "[GPU 1] Predicting Start: Dataset505_CT_FixPatch (ID=505)"
cd /data1/segmentationForTrain/traindata/AllCoarse_RAI/nnUNet_raw/Dataset505_CT_FixPatch
CUDA_VISIBLE_DEVICES=1 nnUNetv2_predict -i imagesTs -o labelsTs_predicted -d 505 -c 3d_fullres -tr nnUNetTrainerNoMirroring -p nnUNetPlans -f 0 --disable_tta
echo "[GPU 1] Predicting End: Dataset505_CT_FixPatch"

echo "[GPU 1] 所有任务完成！"
