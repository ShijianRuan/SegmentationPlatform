# -*- coding: utf-8 -*-
# 通用的向已有mimics工程中导入mask的功能
# 参考 create_mimics_projects_common.py 的写法
# 支持批量遍历mcs工程、从mhd文件导入mask、自定义label映射规则

import mimics
import numpy as np
import os
from typing import List, Optional, Callable
from utils import read_mhd, close_mimics
from file import file_filter


def get_mask_buffer(arr, mask_rule):
    """
    根据mask_rule从array中提取布尔掩码
    :param arr: 输入NumPy数组（mimics排布，xyz）
    :param mask_rule: lambda/Callable，接收数组arr，返回布尔掩码
    :return: 布尔掩码数组
    """
    mask = np.zeros_like(arr, dtype=np.uint8)
    condition_mask = mask_rule(arr)
    mask[condition_mask] = 1
    return mask == 1


class McsLabelNameAndMaskRule:
    """
    描述mask在mimics中的名称和提取规则：
    - mcs_label_name: 导入到mimics后的mask名称
    - mask_rule_fun: 掩码规则函数（lambda/Callable），接收np.ndarray返回布尔数组
    """
    def __init__(self, mcs_label_name, mask_rule_fun):
        """
        :param mcs_label_name: 导入mimics后mask的命名
        :param mask_rule_fun: lambda/Callable，如 lambda x: x != 0
        """
        self.mcs_label_name = mcs_label_name
        self.mask_rule_fun = mask_rule_fun


class ImportMaskConfig:
    """
    描述一个待导入的mask文件配置：
    - mask_filename: mhd文件名（相对于mcs所在目录）
    - label_rules: 该文件中要导入的label规则列表
    - skip_if_mask_exists: 如果mimics中已存在同名mask，是否跳过
    """
    def __init__(self, mask_filename, label_rules, skip_if_mask_exists=True):
        """
        :param mask_filename: mask的mhd文件名（在mcs文件同目录下查找）
        :param label_rules: List[McsLabelNameAndMaskRule]，要从该文件中提取的mask列表
        :param skip_if_mask_exists: 如果mimics工程中已有同名mask则跳过该mask
        """
        self.mask_filename = mask_filename
        self.label_rules = label_rules  # type: List[McsLabelNameAndMaskRule]
        self.skip_if_mask_exists = skip_if_mask_exists


def import_masks_into_current_project(import_configs, mcs_dir_path):
    """
    在当前已打开的mimics工程中，根据import_configs从mhd文件导入mask
    :param import_configs: List[ImportMaskConfig]
    :param mcs_dir_path: mcs文件所在目录路径，用于拼接mask文件路径
    """
    for a_config in import_configs:
        mask_path = os.path.join(mcs_dir_path, a_config.mask_filename)

        if not os.path.exists(mask_path):
            print("[warn] mask文件不存在，跳过: {}".format(mask_path))
            continue

        # 读取mhd文件，得到C排布(zyx)的数组
        mask_array, _, _ = read_mhd(mask_path, out_type=np.uint8)
        # 转为mimics排布(xyz)
        mask_array = mask_array.transpose((2, 1, 0))

        for a_rule in a_config.label_rules:
            a_mcs_name = a_rule.mcs_label_name

            # 检查是否已存在同名mask
            if a_config.skip_if_mask_exists:
                existing_mask = mimics.data.masks.find(a_mcs_name, regex=False)
                if existing_mask is not None:
                    print("[skip] mimics中已存在mask: {}".format(a_mcs_name))
                    continue

            # 根据规则提取布尔掩码
            a_mask_buffer = get_mask_buffer(mask_array, a_rule.mask_rule_fun)

            # 检查掩码是否有效（非全零）
            if not np.any(a_mask_buffer):
                print("[warn] mask为空，跳过: {} -> {}".format(a_config.mask_filename, a_mcs_name))
                continue

            # 在mimics中创建mask并命名
            a_mcs_mask = mimics.segment.create_mask(a_mask_buffer)
            a_mcs_mask.name = a_mcs_name
            print("[done] 导入mask: {} -> {}".format(a_config.mask_filename, a_mcs_name))

    print("[done] 当前工程mask导入完成")


def batch_import_masks(mcs_path_list, import_configs,
                       disable_3d_preview=True, save_after_import=True):
    """
    批量遍历mcs工程文件列表，对每个工程从mhd文件导入mask
    :param mcs_path_list: mcs文件路径列表
    :param import_configs: List[ImportMaskConfig]，导入配置列表
    :param disable_3d_preview: 是否在打开工程后禁用3D预览（加速）
    :param save_after_import: 导入mask后是否保存工程
    """
    total = len(mcs_path_list)
    for idx, a_mcs_path in enumerate(mcs_path_list):
        print("[{}/{}] 处理: {}".format(idx + 1, total, a_mcs_path))

        # 关闭当前工程
        close_mimics(save=True)

        a_dir_path = os.path.dirname(a_mcs_path)

        if not os.path.exists(a_mcs_path):
            print("[warn] mcs文件不存在，跳过: {}".format(a_mcs_path))
            continue

        try:
            mimics.file.open_project(a_mcs_path)
            if disable_3d_preview:
                mimics.view.disable_mask_3d_preview()

            import_masks_into_current_project(import_configs, a_dir_path)

            if save_after_import:
                mimics.file.save_project()
        except Exception as e:
            print("[error] 处理失败: {} -> {}".format(a_mcs_path, str(e)))
            continue

    # 处理完最后一个，关闭工程
    close_mimics(save=True)
    print("[all done] 批量导入完成，共处理 {} 个工程".format(total))


def collect_mcs_paths(path_list, pattern=".*mcs"):
    """
    从多个目录中收集所有符合条件的mcs文件路径
    :param path_list: 目录路径列表
    :param pattern: 文件名匹配的正则表达式，默认匹配mcs文件
    :return: mcs文件路径列表
    """
    all_mcs_path = []
    for a_path in path_list:
        all_mcs_path.extend(file_filter(a_path, pattern=pattern))
    return all_mcs_path


def collect_mcs_paths_from_txt(txt_path):
    """
    从txt文件中读取mcs文件路径（每行一个路径）
    - 支持空行和注释行（以#开头）
    - 自动过滤不存在的路径
    :param txt_path: txt文件路径
    :return: mcs文件路径列表
    """
    all_mcs_path = []
    if not os.path.exists(txt_path):
        print("[warn] 路径文件不存在: {}".format(txt_path))
        return all_mcs_path

    with open(txt_path, "r", encoding="utf-8") as f:
        for line in f:
            a_path = line.strip().strip('"').strip("'")
            if a_path == "" or a_path.startswith("#"):
                continue
            if not os.path.exists(a_path):
                print("[warn] mcs路径不存在，已跳过: {}".format(a_path))
                continue
            all_mcs_path.append(a_path)

    return all_mcs_path


# ============================================================
# 使用示例
# ============================================================
if __name__ == "__main__":
    # 1. 配置搜索路径（包含mcs文件的目录）
    path_list = [
        r"V:\0_Projects\20260121_CTAHeartCoronary\18_segment_segmentation_of_coronary_artery\AllTrainDataSet\2_Marked_Vessel",
    ]

    LABELER_NAME = "_zhanghui"
    # 可选：从txt文件读取mcs路径（每行一个mcs绝对路径）
    # 若文件存在则优先使用txt中的路径；否则使用path_list扫描
    mcs_path_txt = r""

    # 2. 配置导入规则
    #    每个ImportMaskConfig对应一个mhd文件，可以从中提取多个mask
    import_configs = [
        # 示例1: 从coronary_18part_auxpost_mask_crop.mhd导入非零区域为一个mask
        ImportMaskConfig(
            mask_filename="coronary_18part_auxpost_mask_crop.mhd",
            label_rules=[
                McsLabelNameAndMaskRule("coronary_01_pRCA{}".format(LABELER_NAME), lambda x: x == 1),
                McsLabelNameAndMaskRule("coronary_02_mRCA{}".format(LABELER_NAME), lambda x: x == 2),
                McsLabelNameAndMaskRule("coronary_03_dRCA{}".format(LABELER_NAME), lambda x: x == 3),
                McsLabelNameAndMaskRule("coronary_04_R_PDA{}".format(LABELER_NAME), lambda x: x == 4),
                McsLabelNameAndMaskRule("coronary_05_LM{}".format(LABELER_NAME), lambda x: x == 5),
                McsLabelNameAndMaskRule("coronary_06_pLAD{}".format(LABELER_NAME), lambda x: x == 6),
                McsLabelNameAndMaskRule("coronary_07_mLAD{}".format(LABELER_NAME), lambda x: x == 7),
                McsLabelNameAndMaskRule("coronary_08_dLAD{}".format(LABELER_NAME), lambda x: x == 8),
                McsLabelNameAndMaskRule("coronary_09_D1{}".format(LABELER_NAME), lambda x: x == 9),
                McsLabelNameAndMaskRule("coronary_10_D2{}".format(LABELER_NAME), lambda x: x == 10),
                McsLabelNameAndMaskRule("coronary_11_pCx{}".format(LABELER_NAME), lambda x: x == 11),
                McsLabelNameAndMaskRule("coronary_12_OM1{}".format(LABELER_NAME), lambda x: x == 12),
                McsLabelNameAndMaskRule("coronary_13_LCx{}".format(LABELER_NAME), lambda x: x == 13),
                McsLabelNameAndMaskRule("coronary_14_OM2{}".format(LABELER_NAME), lambda x: x == 14),
                McsLabelNameAndMaskRule("coronary_15_L_PDA{}".format(LABELER_NAME), lambda x: x == 15),
                McsLabelNameAndMaskRule("coronary_16_R_PLB{}".format(LABELER_NAME), lambda x: x == 16),
                McsLabelNameAndMaskRule("coronary_17_RI{}".format(LABELER_NAME), lambda x: x == 17),
                McsLabelNameAndMaskRule("coronary_18_L_PLB{}".format(LABELER_NAME), lambda x: x == 18),
                McsLabelNameAndMaskRule("Others_100{}".format(LABELER_NAME), lambda x: x == 100),
            ],
            skip_if_mask_exists=True,
        ),
        # # 示例2: 从coronary_tree_auxmask_nn42.mhd导入
        # ImportMaskConfig(
        #     mask_filename="coronary_tree_auxmask_nn42.mhd",
        #     label_rules=[
        #         McsLabelNameAndMaskRule("coronary_tree_auxmask_nn42", lambda x: x != 0),
        #     ],
        #     skip_if_mask_exists=True,
        # ),
        # # 示例3: 从同一个Mask_resample.mhd中按不同label提取多个mask
        # ImportMaskConfig(
        #     mask_filename="Mask_resample.mhd",
        #     label_rules=[
        #         McsLabelNameAndMaskRule("coronary_net", lambda x: x == 7),
        #         McsLabelNameAndMaskRule("heart_net", lambda x: (x != 0) & (x != 7)),
        #     ],
        #     skip_if_mask_exists=True,
        # ),
        # # 示例4: 从coronary_tree_gold_mask.mhd导入
        # ImportMaskConfig(
        #     mask_filename="coronary_tree_gold_mask.mhd",
        #     label_rules=[
        #         McsLabelNameAndMaskRule("coronary_tree_auxmask_v1", lambda x: x != 0),
        #     ],
        #     skip_if_mask_exists=True,
        # ),
    ]

    # 3. 收集mcs文件路径
    if mcs_path_txt != "" and os.path.exists(mcs_path_txt):
        all_mcs_path = collect_mcs_paths_from_txt(mcs_path_txt)
    else:
        all_mcs_path = collect_mcs_paths(path_list)

    # 4. 批量导入mask到已有的mcs工程中
    batch_import_masks(all_mcs_path, import_configs)
