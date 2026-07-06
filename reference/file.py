# -*- coding: utf-8 -*-
# 文件操作 读写
# zou 20181009


import os
import re


def file_filter(a_dir: str, pattern=".*", recursion: bool = True, file: bool = True, dir: bool = False):
    """
    文件/文件夹过滤器 过滤出目标文件/文件夹路径
    :param a_dir: 根目录
    :param pattern: 正则表达式字符串 用于匹配文件
    :param recursion: 是否递归遍历文件夹
    :param file: 文件是否陪匹配
    :param dir: 文件夹是否被匹配
    :return: path_list
    """
    regex = re.compile(pattern)

    path_list = []
    for root, dirs, files in os.walk(os.path.abspath(a_dir)):
        # 如果需要匹配文件夹 那么验证这个文件夹是否符合要求
        if dir:
            path_list.extend([os.path.join(root, a_dir) for a_dir in dirs if re.match(regex, a_dir) is not None])
        # 如果需要匹配文件 那么验证这个文件夹是否符合要求
        if file:
            path_list.extend([os.path.join(root, a_file) for a_file in files if regex.match(a_file) is not None])

        if not recursion:
            break

    return path_list


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
