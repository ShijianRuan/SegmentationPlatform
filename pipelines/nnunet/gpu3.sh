#!/bin/bash
# gpu3.sh —— 自动生成的 GPU 3 训练和预测脚本
# 生成时间: 2026-05-11 01:47:43
# 配置来源: Config_MR_v500.toml

set -e

# ── 训练 ──────────────────────────────────────────────────
echo "[GPU 3] Training Start: Dataset207_MR7_AbdomenBone (ID=207)"
CUDA_VISIBLE_DEVICES=3 nnUNetv2_train 207 3d_fullres 0 -tr nnUNetTrainerNoMirroring -p nnUNetPlans
echo "[GPU 3] Training End: Dataset207_MR7_AbdomenBone"

echo "[GPU 3] Training Start: Dataset208_MR8_Muscle (ID=208)"
CUDA_VISIBLE_DEVICES=3 nnUNetv2_train 208 3d_fullres 0 -tr nnUNetTrainerNoMirroring -p nnUNetPlans
echo "[GPU 3] Training End: Dataset208_MR8_Muscle"

# ── 预测 ──────────────────────────────────────────────────
echo "[GPU 3] Predicting Start: Dataset207_MR7_AbdomenBone (ID=207)"
cd /data1/segmentationForTrain/traindata/MIv500_RAI_MR/nnUNet_raw/Dataset207_MR7_AbdomenBone
CUDA_VISIBLE_DEVICES=3 nnUNetv2_predict -i imagesTs -o labelsTs_predicted -d 207 -c 3d_fullres -tr nnUNetTrainerNoMirroring -p nnUNetPlans -f 0 --disable_tta
echo "[GPU 3] Predicting End: Dataset207_MR7_AbdomenBone"

echo "[GPU 3] Predicting Start: Dataset208_MR8_Muscle (ID=208)"
cd /data1/segmentationForTrain/traindata/MIv500_RAI_MR/nnUNet_raw/Dataset208_MR8_Muscle
CUDA_VISIBLE_DEVICES=3 nnUNetv2_predict -i imagesTs -o labelsTs_predicted -d 208 -c 3d_fullres -tr nnUNetTrainerNoMirroring -p nnUNetPlans -f 0 --disable_tta
echo "[GPU 3] Predicting End: Dataset208_MR8_Muscle"

echo "[GPU 3] 所有任务完成！"
