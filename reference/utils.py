# coding=utf-8
# 这里临时放一些比较杂的辅助函数
# from wanjun
# edit zou
# 20210318

import mimics

import numpy as np
import SimpleITK as sitk
from threading import Thread
import threading
import ctypes
import os
import re
import time
from typing import Union, Optional, Sequence
import datetime
import shutil

bin_dir = r"D:\MCSF\BRANCH\ZHENGHE_69_SP4\UIH\bin"
# os.chdir(bin_dir)

def close_mimics(save: bool = True):
    """
    关闭当前mcs
    :param save: 是否要保存
    :return:
    """

    if mimics.file.is_project_loaded():
        if save and mimics.file.is_project_modified():
            mimics.file.save_project()
        mimics.file.close_project()

def show_mask(mask_names):
    for a_mask_name in mask_names:
        a_mask = mimics.data.masks.find(a_mask_name, regex=False)
        a_mask.visible = True
        a_mask.selected = True
        
    mimics.view.enable_mask_3d_preview()

def close_mask_show(masks):
    for a_mask in masks:
        a_mask.visible = False
        a_mask.selected = False

def close_all_show():
    # 关闭所有显示
    mimics.view.disable_mask_3d_preview()
    # 去除所有obj的可视化
    for a_obj in mimics.data.objects:
        a_obj.visible = False
    for a_mask in mimics.data.masks:
        a_mask.visible = False

def hypophysial_fossa_point_detection(image_mhd_path):
    """
    给定一个头部的图像 得到垂体窝定位的位置
    调用C的接口 需要依赖自己添加的dll和UIH包
    :param image_mhd_path:
    :return: 垂体窝的像素位置图像的物理位置
    """
    # 被加载的模块
    lib = ctypes.cdll.LoadLibrary(os.path.join(bin_dir, "Algo.dll"))

    image = sitk.ReadImage(image_mhd_path)
    image = sitk.Cast(image, sitk.sitkInt16)
    imageArray = sitk.GetArrayFromImage(image)

    imagedataptr = imageArray.ctypes.data_as(ctypes.POINTER(ctypes.c_short))  # ctypes.c_char_p

    Dims = image.GetSize()

    cDims = (ctypes.c_int * 3)(*Dims)

    spacing = image.GetSpacing()

    cSpacing = (ctypes.c_float * 3)(*spacing)

    location = (ctypes.c_int * 3)(0)
    value = lib.HypophysialFossaPointLocalization(imagedataptr, cDims, cSpacing, location)
    if value == 1:
        return [a_location * a_spacing for a_location, a_spacing in zip(location, spacing)]
    else:
        return None


def create_mask(mask_name: str, *mask_names: str, operate: str = "AND"):
    """
    在当前的mimics工程中 对给定的mask或者mask列表 进行逻辑操作 并返回np类型的mask处理结果
    :param mask_name: mimics工程中的mask的名字 也支持正则表达式输入
    :param mask_names: 可以输入多个mask进行逻辑操作
    :param operate: 目前仅支持 AND OR NOT 其中NOT是对所有mask做OR后再做的NOT
    :return: res_mask
    """

    assert operate in ["AND", "OR", "NOT"], "只支持 \"AND\", \"OR\", \"NOT\" 这几种逻辑操作!"

    mask_name_list = [mask_name, *mask_names]
    mask_list = []
    # print(mask_name_list)

    for a_name in mask_name_list:
        a_mcs_mask = mimics.data.masks.find(a_name, regex=True)
        assert a_mcs_mask is not None, "当前mimics工程中没有指定mask! mask = {}".format(a_name)
        # 提取出numpy类型的mask
        buffer = a_mcs_mask.get_voxel_buffer()
        a_np_mask = np.frombuffer(buffer.tobytes(), dtype=bool).reshape(buffer.shape)
        # mimics和ITK中的数据内存排布 不太一样 所以要转一下
        a_np_mask = a_np_mask.transpose()

        mask_list.append(a_np_mask)

    # 进行处理逻辑操作 如果是NOT 则要先进行AND 然后对结果做 NOT
    merge_mask = None
    if operate == "NOT":
        for a_mask in mask_list:
            merge_mask = np.logical_and(merge_mask, a_mask) if merge_mask is not None else a_mask

        merge_mask = np.logical_not(merge_mask)
    else:
        operater = np.logical_and if operate == "AND" else np.logical_or
        merge_mask = None
        for a_mask in mask_list:
            merge_mask = operater(merge_mask, a_mask) if merge_mask is not None else a_mask

    return merge_mask.astype(np.uint8)


def mask_vr(image_or_path: Union[str, np.ndarray],
            mask_or_path: Union[str, np.ndarray],
            spacing=(1, 1, 1),
            origin=(0, 0, 0),
            tmp_dir: str = r"d:\\"):
    """
    给定一个图像或路径 一个mask或路径 然后VR显示
    :param image_or_path:
    :param mask_or_path: 目前外面的dll认为mask==2的是前景 会被显示
    :param spacing: 如果是path 那么这个参数无效
    :param origin: 如果是path 那么这个参数无效
    :param tmp_dir: 存放临时文件的地方
    :return:
    """
    # 如果当前图像不是文件形式 那么转存到临时文件中
    if isinstance(image_or_path, np.ndarray):
        image_path = os.path.join(tmp_dir, "image.mhd")
        write_mhd(image_path, image_or_path, spacing, origin)
    else:
        image_path = image_or_path

    if isinstance(mask_or_path, np.ndarray):
        mask_path = os.path.join(tmp_dir, "mask.mhd")
        write_mhd(mask_path, mask_or_path, spacing, origin)
    else:
        mask_path = mask_or_path

    # # 调用外部dll 显示vr
    # # renderToimage  renderToscreen
    # exe_path = r"D:\MCSF\BRANCH\ZHENGHE_69_SP4\UIH\bin\VolumeRenderingWidget.exe"
    # out_dir = tmp_dir  # 目前用不到这个 先随便给一个路径
    # command = '%s "renderToscreen" "%s" "%s" "%s"' % (exe_path, out_dir, image_path, mask_path)
    # os.system(command)

    vrt=r'D:\MCSF\BRANCH\ZHENGHE_69_SP4\UIH\appdata\user_settings\default\config\viewer3d\LUT\CT\HEAD_NECK\CT_Clr_Carotid_2_HEAD_NECK.xml'
    vrt = r"D:\MCSF\BRANCH\ZHENGHE_69_SP4\UIH\appdata\user_settings\default\config\viewer3d\LUT\CT\CTA\CT_Vessel_Carotid_default.xml"
    th0=VRrender(image_path,mask_path,None,[1],vrt,is_smooth=False)


def execCmd(cmd):
    try:
        print("命令%s开始运行%s" % (cmd,datetime.datetime.now()))
        os.system(cmd)
        print("命令%s结束运行%s" % (cmd,datetime.datetime.now()))
    except Exception as e:
        print('%s\t 运行失败,失败原因\r\n%s' % (cmd,e))


def VRrender(image_path: str, mask_path: Optional[str], savePath: Optional[str], visibleList: Optional[Sequence],
             vrtconfig: Optional[str], is_smooth: bool, renderingModel: str = 'VR', mip_ww=650, mip_wl=300, is_async: bool = False):
    exe_path = r"D:\MCSF\BRANCH\ZHENGHE_69_SP4\UIH\bin\VolumeRenderingWidget.exe"
    spaceSeparator = ' '

    if mask_path != None:
        mask_path = '-m %s' % (mask_path)
    else:
        mask_path = ''

    if savePath != None:
        savePath = '%s -s %s' % ("--force-offscreen-rendering", savePath)
    else:
        savePath = '--force-onscreen-rendering'

    visible = ''
    if visibleList != None:
        visibleStrList = [str(label) for label in visibleList]
        # visible='-l'.join(spaceSeparator.join(visibleStrList))
        visible = '-l ' + (spaceSeparator.join(visibleStrList))

    vrt = ''
    if vrtconfig != None:
        vrt = '--vrt-configture-path ' + vrtconfig

    smooth = ''
    if is_smooth:
        smooth = '--smooth-rendering'
    command = '%s -v %s %s %s %s %s %s --rendering-model %s --mip-ww %d --mip-wl %d' % (
    exe_path, image_path, mask_path, savePath, visible, vrt, smooth, renderingModel, mip_ww, mip_wl)
    th = threading.Thread(target=execCmd, args=(command,))
    th.start()
    if is_async:
        return th
    else:
        th.join()


def read_mhd(mhd_path: str, out_type=None):
    """
    读取mhd/nii文件
    :param mhd_path: 文件路径
    :param out_type: 转换数据类型 None为默认类型
    :return: tuple(array_image, spacing, origin) or None
    !!读取进来的数据array_image遵循C的数据排布规则，三个维度为zyx
    !!spacing 和 origin是列表 对应的顺序为xyz
    !!使用时一定注意！！
    """

    # if not os.path.exists(os.path.abspath(mhd_path)):
    #     print("read mhd file err! path is :{}".format(mhd_path))
    #     return None
    assert os.path.exists(os.path.abspath(mhd_path))

    sitk_image = sitk.ReadImage(mhd_path)
    array_image = sitk.GetArrayFromImage(sitk_image)
    if out_type is not None:
        array_image = array_image.astype(out_type)
    spacing = sitk_image.GetSpacing()
    origin = sitk_image.GetOrigin()
    return array_image, spacing, origin


def write_mhd(mhd_path: str,
              array_image: np.ndarray,
              spacing=(1.0, 1.0, 1.0),
              origin=(0.0, 0.0, 0.0),
              out_type=None,
              compression: bool = False):
    """
    写一个数据为mhd，如果路径不存在则创建
    :param mhd_path:写的 路径+文件名
    :param array_image:图像矩阵，也确定了数据类型
    :param spacing:spacing
    :param origin:origin
    :param out_type: 转换数据类型 None为输入数据的类型
    :param compression: 是否压缩数据
    :return:
    !!写入的时候array_image遵循C的数据排布规则，三个维度为zyx
    !!spacing 和 origin是列表 对应的顺序为xyz
    !!使用时一定注意！！
    """

    if out_type is not None:
        array_image = array_image.astype(out_type)

    sitk_image = sitk.GetImageFromArray(array_image)
    sitk_image.SetSpacing([float(x) for x in spacing])
    sitk_image.SetOrigin([float(x) for x in origin])

    root, name = os.path.split(mhd_path)
    if not os.path.exists(root):
        os.makedirs(root)

    # 其他的都默认就行
    sitk.WriteImage(sitk_image, mhd_path, useCompression=compression)


def read_mhd_attr(mhd_path: str, key: str, dtype: str):
    """
    给定一个mhd文件的路径 提取出key对应的内容
    :param mhd_path: 文件路径
    :param key: key 固定的一些key
    :param dtype: 说明这个key是什么类型的数据，方便进行转换 如"str" "int" "float"
    :return: str or array or None
    """

    # if not os.path.exists(mhd_path):
    #     print("read mhd file err! path is :{}".format(mhd_path))
    #     return None
    assert os.path.exists(mhd_path)

    with open(mhd_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    # 正则表达式匹配到目标 并 得到对应的元素
    regex = re.compile(r"^\s*" + key + r"\s*=\s*(.*)\s*$")
    attr = None
    for a_line in lines:
        match_obj = re.match(regex, a_line)
        if match_obj is not None:
            attr = match_obj.group(1)
            break

    # 说明没找到对应的项 返回了
    if attr is None:
        return None

    attr = attr.strip()

    if dtype == "str":
        return attr
    elif dtype == "bool":
        assert attr == "True" or attr == "False"
        return attr == "True"
    else:
        return np.array(attr.split(), dtype)


def mimics_project_split():
    """
    获取当前mimics工程所在目录 和 工程文件名字
    :return: dir, name
    """
    p = mimics.file.get_project_information()
    path = p.project_path
    name, _ = os.path.splitext(os.path.basename(path))
    dir = os.path.dirname(path)

    return dir, name


def multi_mask_morphology_operations(*masks, **kwargs):
    """
    封装下mimics里面的形态学操作 让多个mask都同时进行这个形态学操作
    :param masks: 其他的mimics mask 如果是None 返回的也是None
    :param kwargs: mimics.segment.morphology_operations 函数的控制参数
    :return: 根据输入的mask返回对应的mask 或mask列表
    """

    #
    dilate_mask_list = []
    for a_mask in masks:
        if a_mask:
            a_dilate_mask = mimics.segment.morphology_operations(a_mask, **kwargs)
            a_dilate_mask.visible = False
        else:
            a_dilate_mask = None

        dilate_mask_list.append(a_dilate_mask)

    # 如果有多个输入 那么返回列表
    if masks:
        return dilate_mask_list
    else:
        return dilate_mask_list[0]


def multi_mask_boolean_operations(a_mask, *b_masks, **kwargs):
    """
    对a_mask 和 b_mask列表中的每个mask顺序进行bool操作
    :param a_mask: 1个mask
    :param b_masks: 多个mask列表
    :param kwargs: mimics.segment.boolean_operations函数的控制参数
    :return: 一个结果mask
    """
    assert b_masks, "b_masks不能为空！"

    # 临时变量列表 用后删除
    res_mask = mimics.data.masks.duplicate(a_mask)
    for b_mask in b_masks:
        # 最后一个是结果mask
        if b_mask is not None:
            new_res_mask = mimics.segment.boolean_operations(res_mask, b_mask, **kwargs)
            # 删除原来的res_mask 并更新
            mimics.data.masks.delete(res_mask)
            res_mask = new_res_mask

    res_mask.visible = False
    return res_mask


# 将三维体素保存成slice形式的dicom
# https://github.com/zivy/SimpleITK/blob/8e94451e4c0e90bcc6a1ffdd7bc3d56c81f58d80/Examples/DicomSeriesReadModifyWrite/DicomSeriesReadModifySeriesWrite.py
def mhd2dicom(input_mhd: str, output_dir: str):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    image = sitk.ReadImage(input_mhd)

    writer = sitk.ImageFileWriter()
    writer.KeepOriginalImageUIDOn()
    modification_time = time.strftime("%H%M%S")
    modification_date = time.strftime("%Y%m%d")

    # Copy some of the tags and add the relevant tags indicating the change.
    # For the series instance UID (0020|000e), each of the components is a number, cannot start
    # with zero, and separated by a '.' We create a unique series ID using the date and time.
    # tags of interest:
    direction = image.GetDirection()
    series_tag_values = [("0008|0031", modification_time),  # Series Time
                         ("0008|0021", modification_date),  # Series Date
                         ("0008|0008", "DERIVED\\SECONDARY"),  # Image Type
                         ("0020|000e", "1.2.826.0.1.3680043.2.1125." + modification_date + ".1" + modification_time),
                         # Series Instance UID
                         ("0020|0037",
                          '\\'.join(map(str, (direction[0], direction[3], direction[6],  # Image Orientation (Patient)
                                              direction[1], direction[4], direction[7])))),
                         ("0008|103e", "Created-SimpleITK"),  # Series Description
                         ("0020|000D", "1.2.826.0.1.3680043.2.1125." + modification_date),  # Study Instance UID
                         ("0028|1052", "-1024"),  # Rescale Intercept
                         ("0028|1053", "1"),  # Rescale Slope
                         ("0008|0060", "CT"),  # Rescale Slope
                         ("0010|0020", "33997"),  # Rescale Slope

                         # ("0028|1054","US")#, #Rescale Type
                         # ("0028|0103","0") #Pixel Representation
                         ]

    for i in range(image.GetDepth()):
        image_slice = image[:, :, i]
        # Tags shared by the series.
        for tag, value in series_tag_values:
            image_slice.SetMetaData(tag, value)
        # Slice specific tags.
        image_slice.SetMetaData("0008|0012", time.strftime("%Y%m%d"))  # Instance Creation Date
        image_slice.SetMetaData("0008|0013", time.strftime("%H%M%S"))  # Instance Creation Time
        # Setting the type to CT preserves the slice location.
        image_slice.SetMetaData("0008|0060", "CT")  # set the type to CT so the thickness is carried over

        # (0020, 0032) image position patient determines the 3D spacing between slices.
        image_slice.SetMetaData("0020|0032", '\\'.join(
            map(str, image.TransformIndexToPhysicalPoint((0, 0, i)))))  # Image Position (Patient)
        image_slice.SetMetaData("0020,0013", str(i))  # Instance Number

        # Write to the output directory and add the extension dcm, to force writing in DICOM format.
        writer.SetFileName(os.path.join(output_dir, str(i) + '.dcm'))
        writer.Execute(image_slice)


def get_dir_list(a_dir):
    """
    获取当前文件夹下的子文件夹路径
    :param a_dir:给定的文件夹
    :return:dir_path_list
    """
    for root, dirs, _ in os.walk(a_dir):
        return [os.path.join(root, x) for x in dirs]
    return []


def get_file_list(a_dir):
    """
    获取当前文件夹下的所有非文件夹文件的路径
    :param a_dir:给定的文件夹
    :return:file_path_list
    """
    for root, _, files in os.walk(a_dir):
        return [os.path.join(root, x) for x in files]
    return []


def create_files_list(a_dir, mode="", ext=""):
    """
    查找指定文件夹下的 所有指定后缀的文件 返回一个文件路径list
    a_dir:
    mode = 'r'代表递归遍历  其他字符串表示只遍历当前文件夹
    ext = 文件扩展名 .txt

    return files_list
    """
    files_list = []
    for root, dirs, files in os.walk(os.path.abspath(a_dir)):
        for a_file in files:
            a_file_dir = os.path.join(root, a_file)
            _, a_ext = os.path.splitext(a_file_dir)
            if a_ext == ext:
                files_list.append(a_file_dir)
        if mode != "r" and mode != "R":
            break

    return files_list


def file_read_lines(file_path):
    """
    读训文件 不跳过空行(方便定位问题行) 得到每一行内容
    """
    if not os.path.exists(os.path.abspath(file_path)):
        print("Err!! FUN : file_read_lines MSG : file_path not exist : {}".format(file_path))
        return None

    # 读源文件
    lines = []
    with open(os.path.abspath(file_path), "r", encoding="utf-8") as f:
        lines = f.readlines()

    return lines


# 将一个工程中的东西转到另一个工程中
def import_mask_from_a_to_b(a_mcs_path: str, b_mcs_path: str, mask_name: str):
    """
    从a_mcs工程 把指定mask 导入到 b_mcs工程中
    用于合并标记数据
    :param a_mcs_path:
    :param b_mcs_path:
    :param mask_name: 支持正则表达式
    :return:
    """
    assert os.path.exists(a_mcs_path) and os.path.exists(b_mcs_path)

    if mimics.file.is_project_loaded():
        if mimics.file.is_project_modified():
            mimics.file.save_project()
        mimics.file.close_project()

    # 打开a 获取目标mask
    mimics.file.open_project(a_mcs_path)

    mask = mimics.data.masks.find(mask_name, regex=True)
    assert mask is not None

    name = mask.name
    buffer = mask.get_voxel_buffer()

    mimics.file.close_project()

    # 打开b 如果存在 那么覆盖 如果不存在 那么创建mask
    mimics.file.open_project(b_mcs_path)
    mask = mimics.data.masks.find(mask_name, regex=True)
    if mask is None:
        mask = mimics.segment.create_mask(buffer)
        mask.name = name
    else:
        mask.set_voxel_buffer(buffer)

    mimics.file.save_project()
    mimics.file.close_project()


def mhd2dicom(input, outDir):
    image = sitk.ReadImage(input)
    writer = sitk.ImageFileWriter()
    writer.KeepOriginalImageUIDOn()
    modification_time = time.strftime("%H%M%S")
    modification_date = time.strftime("%Y%m%d")

    # Copy some of the tags and add the relevant tags indicating the change.
    # For the series instance UID (0020|000e), each of the components is a number, cannot start
    # with zero, and separated by a '.' We create a unique series ID using the date and time.
    # tags of interest:
    direction = image.GetDirection()
    series_tag_values = [("0008|0031", modification_time),  # Series Time
                         ("0008|0021", modification_date),  # Series Date
                         ("0008|0008", "DERIVED\\SECONDARY"),  # Image Type
                         ("0020|000e", "1.2.826.0.1.3680043.2.1125." + modification_date + ".1" + modification_time),
                         # Series Instance UID
                         ("0020|0037",
                          '\\'.join(map(str, (direction[0], direction[3], direction[6],  # Image Orientation (Patient)
                                              direction[1], direction[4], direction[7])))),
                         ("0008|103e", "Created-SimpleITK"),  # Series Description
                         ("0020|000D", "1.2.826.0.1.3680043.2.1125." + modification_date),  # Study Instance UID
                         ("0028|1052", "-1024"),  # Rescale Intercept
                         ("0028|1053", "1"),  # Rescale Slope
                         # ("0028|1054","US")#, #Rescale Type
                         # ("0028|0103","0") #Pixel Representation
                         ]

    for i in range(image.GetDepth()):
        image_slice = image[:, :, i]
        # Tags shared by the series.
        for tag, value in series_tag_values:
            image_slice.SetMetaData(tag, value)
        # Slice specific tags.
        image_slice.SetMetaData("0008|0012", time.strftime("%Y%m%d"))  # Instance Creation Date
        image_slice.SetMetaData("0008|0013", time.strftime("%H%M%S"))  # Instance Creation Time
        # Setting the type to CT preserves the slice location.
        image_slice.SetMetaData("0008|0060", "CT")  # set the type to CT so the thickness is carried over

        # (0020, 0032) image position patient determines the 3D spacing between slices.
        image_slice.SetMetaData("0020|0032", '\\'.join(
            map(str, image.TransformIndexToPhysicalPoint((0, 0, i)))))  # Image Position (Patient)
        image_slice.SetMetaData("0020,0013", str(i))  # Instance Number

        # Write to the output directory and add the extension dcm, to force writing in DICOM format.
        writer.SetFileName(os.path.join(outDir, str(i) + '.dcm'))
        writer.Execute(image_slice)


def createMcsProject(mhd_path, project_path, modality="CT", cache_dir=r"F:\temp_del\dicom"):
    if mimics.file.is_project_loaded():
        if mimics.file.is_project_modified():
            mimics.file.save_project()
        mimics.file.close_project()

    if os.path.exists(cache_dir):
        shutil.rmtree(cache_dir)
    os.makedirs(cache_dir)

    mhd2dicom(mhd_path, cache_dir)

    input_dir = cache_dir

    input_path = []
    for root, _, files in os.walk(input_dir):
        input_path.extend(os.path.join(root, f) for f in files)

    image_objs = mimics.file.test_images(filenames=input_path, force_raw_import=False)
    print(len(image_objs))

    conf_images = mimics.file.configure_dicom_images(imagefiles=image_objs)
    print(len(conf_images))

    studies = mimics.file.split_images_into_studies(configured_imagefiles=conf_images,
                                                    patient_name_grouping=True,
                                                    series_description_grouping=True,
                                                    study_description_grouping=True)
    if (len(studies) != 1):
        print(len(studies))
        print("!!!error!!!" + mhd_path)
        return

    if modality == "CT":
        image_data = mimics.file.load_series_into_memory(studies=[studies[0]])
    elif modality == "MR":
        # 之前MR图像 加载进来的数据 和 mhd的维度差了一点 不知道为什么 改成下面的就好了
        image_data = mimics.file.load_series_into_memory(studies=[studies[0]], pixel_processing="RESIZE_MAX")
    else:
        assert False, "模态错误"
    mimics.file.open_images_as_project(imagedata=image_data)
    mimics.file.save_project(filename=project_path)
    # mimics.file.close_project()
    



if __name__ == "__main__":
    mhd2dicom("d:/mask.mhd", "d:/tmptestdicom")

    path = r'D:\VesselDatabaseAnnotationvesselrawdatahead_neck\000mcs_spacing=111\GAOLIANGRONG\GAOLIANGRONG.mhd'

    # location = hypophysial_fossa_point_detection(path)
    # print(location)

    # create_mask("skull__wj")
    merge_mask = create_mask("skull__.*", "cervical_vertebra__.*", operate='OR')
    # 确认前景 标签
    merge_mask *= 2

    p = mimics.file.get_project_information()
    path = p.project_path
    dir = os.path.dirname(path)
    name = os.path.basename(path).split(".", 1)[0]
    image_path = os.path.join(dir, name + ".mhd")

    mask_vr(image_path, merge_mask)

    outImg = sitk.GetImageFromArray(merge_mask.astype(np.ubyte))
    sitk.WriteImage(outImg, r"d:\test_mask.mhd")


