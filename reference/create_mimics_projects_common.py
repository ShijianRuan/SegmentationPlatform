# 补全必要导入（Python 3.5 必备 + 代码依赖）
from file import file_filter
import os
import numpy as np  # 代码中使用了np但原代码未导入，必须补
from utils import *  # 假设read_mhd等函数在utils中
from typing import List, Optional, Callable  # 3.5 需显式导入这些类型
from generate_mimics import *

# 修复1：给mask_rule_fun添加Callable类型注解（3.5 兼容）
class McsLabelNameAndMaskRule:
    def __init__(self, mcs_label_name: str, mask_rule_fun: Callable):
        """
        :param mcs_label_name: 标签名
        :param mask_rule_fun: 掩码规则函数（lambda/Callable），接收np.ndarray返回布尔数组
        """
        self.mcs_label_name = mcs_label_name
        self.mask_rule_fun = mask_rule_fun

# 修复2：保持List注解（3.5 支持typing.List）
class MaskLabelMap:
    def __init__(self, mask_filename: str, mask_label_name_and_rule: McsLabelNameAndMaskRule):
        """
        :param mask_filename: 掩码文件名
        :param mask_label_name_and_rule: McsLabelNameAndMaskRule实例
        """
        self.mask_filename = mask_filename
        self.mask_label_name_and_rule = mask_label_name_and_rule

def get_mask_buffer(arr: np.ndarray, mask_rule: Callable) -> np.ndarray:
    """
    生成与输入数组形状相同的掩码数组：
    - 初始全为0
    - 满足mask_rule条件的位置设为1
    :param arr: 输入NumPy数组（用于判断条件）
    :param mask_rule: lambda表达式，接收数组arr，返回布尔掩码（True表示需要设为1）
    :return: 布尔掩码数组（True=满足条件，False=不满足）
    """
    # 1. 创建与arr形状、数据类型完全相同的全0数组（掩码初始值）
    mask = np.zeros_like(arr, dtype=np.uint8)  # dtype建议用uint8，节省内存
    
    # 2. 调用传入的规则生成布尔掩码
    condition_mask = mask_rule(arr)
    
    # 3. 将满足条件的位置设为1
    mask[condition_mask] = 1
    
    return mask == 1

# 修复3：将 List[MaskLabelMap] | None 改为 Optional[List[MaskLabelMap]]（3.5 兼容）
def generate_mcs_fun(image_path: str, mcs_filename: str, cache_dir: str, 
                     mask_label_map_list: Optional[List[MaskLabelMap]] = None):
    if not os.path.exists(image_path):
        return
    
    if not os.path.exists(cache_dir):
        print("缓存路径不存在，请创建")
        return
    
    dir_path = os.path.dirname(image_path)
    # 修复4：解决mcs_filename为None时mcs_path未定义的bug（原代码逻辑漏洞）
    if mcs_filename is not None:
        mcs_path = os.path.join(dir_path, mcs_filename)
    else:
        # 从image_path推导mcs路径（替换mhd后缀为mcs）
        mcs_path = os.path.splitext(image_path)[0] + ".mcs"
    
    createMcsProject(image_path, mcs_path, modality="MR", cache_dir=cache_dir)
    
    if mask_label_map_list is not None:
        for a_mask_label_map in mask_label_map_list:
            a_mask_filename = a_mask_label_map.mask_filename
            a_mask_path = os.path.join(dir_path, a_mask_filename)
            if not os.path.exists(a_mask_path):
                continue
            
            a_mask_array, _, _ = read_mhd(a_mask_path, out_type=np.uint8)
            a_mask_array = a_mask_array.transpose((2, 1, 0))

            name_and_rule = a_mask_label_map.mask_label_name_and_rule
            a_mcs_name = name_and_rule.mcs_label_name
            a_mask_rule = name_and_rule.mask_rule_fun
            a_mask_buffer = get_mask_buffer(a_mask_array, a_mask_rule)
            a_mcs_mask = mimics.segment.create_mask(a_mask_buffer)
            a_mcs_mask.name = a_mcs_name

if __name__ == "__main__":
    path = r"G:\1_TempDel\test\image\YHMR00134284_20230330_701_t1_gre_fsp_3d_sag_ACS+C"
    mcs_filename = r"brain_tissue.mcs"
    img_filename = "YHMR00134284_20230330_701_t1_gre_fsp_3d_sag_ACS+C\.mhd$"
    cache_dir = r"G:\1_TempDel\tmp"

    # 保持原有lambda逻辑（3.5 完全支持lambda）
    mask_label_map_list = [
        MaskLabelMap("mask.mhd", McsLabelNameAndMaskRule("brain", lambda x : x != 0)),
        # MaskLabelMap("coronary_tree_auxmask_nn42.mhd", McsLabelNameAndMaskRule("coronary_tree_auxmask_nn42", lambda x : x != 0)),
        # MaskLabelMap("Mask_resample.mhd", McsLabelNameAndMaskRule("coronary_net", lambda x : x == 7)),
        # MaskLabelMap("Mask_resample.mhd", McsLabelNameAndMaskRule("heart_net", lambda x : (x != 0) & (x != 7))),
        # MaskLabelMap("coronary_tree_gold_mask.mhd", McsLabelNameAndMaskRule("coronary_tree_auxmask_v1", lambda x : x != 0)),
    ]
    all_image_path = file_filter(path, img_filename)
    
    for a_image_path in all_image_path:
        print(a_image_path)
        generate_mcs_fun(a_image_path, mcs_filename, cache_dir, mask_label_map_list)