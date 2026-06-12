import requests
import os
import zipfile

# 接口地址
url = "http://10.6.12.214:8888/file_parse"

# PDF 文件列表
pdf_files = [
    {
        "name": "小样本分割模型自适应",
        "path": r"e:\SegmentationPlatform\“小样本分割模型自适应”调研文献记录.pdf"
    },
    {
        "name": "小样本学习技术调研",
        "path": r"e:\SegmentationPlatform\小样本学习技术调研.pdf"
    },
    {
        "name": "少样本学习-技术调研报告",
        "path": r"e:\SegmentationPlatform\少样本学习-技术调研报告.pdf"
    },
    {
        "name": "算法预研：少样本下的分割模型自适应",
        "path": r"e:\SegmentationPlatform\算法预研：少样本下的分割模型自适应.pdf"
    }
]

# 输出目录
output_dir = r"e:\SegmentationPlatform\parsed_pdfs"
os.makedirs(output_dir, exist_ok=True)

for pdf in pdf_files:
    name = pdf["name"]
    pdf_path = pdf["path"]
    print(f"\n{'='*60}")
    print(f"🔄 正在处理：{name}")
    print(f"📄 文件：{pdf_path}")

    # 检查文件是否存在
    if not os.path.exists(pdf_path):
        print(f"❌ 文件不存在，跳过：{pdf_path}")
        continue

    # 参数
    payload = {
        "return_md": True,
        "return_images": True,
        "response_format_zip": True
    }

    # 上传文件
    files = [
        ('files', (
            'output.pdf',
            open(pdf_path, 'rb'),
            'application/pdf'
        ))
    ]

    try:
        # 发送请求
        response = requests.post(url, data=payload, files=files, timeout=120)
        response.raise_for_status()

        # 保存 ZIP
        zip_path = os.path.join(output_dir, f"{name}.zip")
        with open(zip_path, 'wb') as f:
            f.write(response.content)

        # 解压 ZIP
        extract_dir = os.path.join(output_dir, name)
        os.makedirs(extract_dir, exist_ok=True)

        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)

        print(f"✅ {name} 转换完成")
        print(f"   ZIP: {zip_path}")
        print(f"   解压到: {extract_dir}")

        # 列出解压后的文件
        for root, dirs, files_in_dir in os.walk(extract_dir):
            for f in files_in_dir:
                print(f"   📎 {os.path.join(root, f)}")

    except requests.exceptions.RequestException as e:
        print(f"❌ 请求失败：{e}")
    except zipfile.BadZipFile:
        print(f"❌ ZIP 解压失败（可能不是 ZIP 格式），尝试直接保存响应")
        # 如果不是 ZIP，直接保存返回内容
        txt_path = os.path.join(output_dir, f"{name}.response")
        with open(txt_path, 'wb') as f:
            f.write(response.content)
        print(f"   已保存原始响应到：{txt_path}")
    except Exception as e:
        print(f"❌ 未知错误：{e}")

print(f"\n{'='*60}")
print(f"🎉 全部处理完成！结果目录：{output_dir}")
