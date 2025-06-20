from collections.abc import Generator
from typing import Any, List, Optional
import io
import os

import fitz  # PyMuPDF
import requests
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

# --- download_dify_file_content 函数保持不变 ---
def download_dify_file_content(
    dify_file_obj: object, 
    dify_host_url: str, 
) -> bytes | None:
    """
    从Dify文件对象中下载文件内容到内存。
    """
    try:
        file_name_full = dify_file_obj.filename
        relative_url = dify_file_obj.url
    except AttributeError:
        print(f"错误: Dify文件对象结构不正确，缺少 'filename' 或 'url' 属性。对象: {dify_file_obj}")
        return None

    cleaned_host_url = dify_host_url.rstrip('/')
    
    full_url = relative_url
    if not relative_url.startswith(('http://', 'https://')):
        if relative_url.startswith('/'):
            full_url = f"{cleaned_host_url}{relative_url}"
        else:
            full_url = f"{cleaned_host_url}/{relative_url}"

    print(f"  [Downloader] 准备从URL下载: {full_url}")
    try:
        response = requests.get(full_url, timeout=60)
        response.raise_for_status()
        blob_content = response.content
        print(f"  [Downloader] 成功下载 {len(blob_content)} bytes for file '{file_name_full}'.")
        return blob_content
    except requests.exceptions.RequestException as e:
        print(f"  [Downloader] 错误: 下载文件 '{file_name_full}' 从URL '{full_url}' 失败: {e}")
        return None

def convert_pdf_to_image_blobs(
    pdf_bytes: bytes, 
    dpi: int = 200, 
    image_format: str = "png"
) -> List[bytes]:
    """
    将内存中的PDF文件内容转换为图片字节流（blobs）。
    如果任何一页转换失败，此函数将引发一个异常，而不是返回部分结果。

    :param pdf_bytes: PDF文件的字节内容。
    :param dpi: 图像的分辨率 (dots per inch)。
    :param image_format: 输出图片的格式。
    :return: 一个包含所有页面图片字节数据的列表。
    :raises ValueError: 如果PDF的任何一页转换失败。
    """
    image_blobs = []
    pdf_document = None  # 先声明，以便在finally块中可用

    try:
        # 1. 从内存中打开PDF文件
        pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")

        # 2. 遍历PDF的每一页
        for page_number in range(len(pdf_document)):
            try:
                page = pdf_document.load_page(page_number)
                pix = page.get_pixmap(dpi=dpi)
                img_data = pix.tobytes(output=image_format)
                image_blobs.append(img_data)
                print(f"成功处理页面 {page_number + 1}/{len(pdf_document)}")
            except Exception as e:
                # [核心改动] 如果单页转换失败，立即构造错误信息并抛出异常
                # 这会中断整个循环，并让上层调用者（_invoke方法）捕获到错误
                error_message = f"处理PDF第 {page_number + 1} 页时失败: {e}"
                print(error_message) # 在服务器日志中也打印出来
                raise ValueError(error_message)

    except fitz.errors.FitzError as e:
        # 捕获PyMuPDF特有的打开文件等错误
        raise ValueError(f"打开或解析PDF文件时出错: {e}")
    finally:
        # 3. 确保无论成功还是失败，都关闭PDF文档以释放资源
        if pdf_document:
            pdf_document.close()

    # 只有当for循环完全成功执行后，才会到达这里
    return image_blobs

class Pdf2imageTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        
        pdf_file_list = tool_parameters.get('pdf_files') 
        dify_host_url = tool_parameters.get('host_url')

        try:
            yield self.create_text_message("▶️ 开始验证所有文件格式...")
            for dify_file_obj in pdf_file_list:
                if dify_file_obj.mime_type != "application/pdf":
                    yield self.create_json_message({
                        "result": f"Unsupported file type: {dify_file_obj.mime_type}"
                    })
                    raise ValueError(f"输入错误: 文件 '{dify_file_obj.filename}' 不是PDF格式。此工具仅支持处理PDF文件。")
            
            yield self.create_text_message("✅ 所有文件格式验证通过。开始处理...")

            for dify_file_obj in pdf_file_list:
                yield self.create_text_message(f"⚙️ 正在处理文件: {dify_file_obj.filename}...")
                
                # 步骤 1: 下载
                pdf_blob = download_dify_file_content(dify_file_obj, dify_host_url)
                if not pdf_blob:
                    raise IOError(f"下载文件 '{dify_file_obj.filename}' 失败，请检查URL或网络连接。") # 使用IOError更语义化

                # 步骤 2: 转换
                # 此函数如果失败会抛出 ValueError
                image_blobs = convert_pdf_to_image_blobs(pdf_blob)
                
                yield self.create_text_message(f"✔️ 文件 '{dify_file_obj.filename}' 成功转换为 {len(image_blobs)} 张图片。")

                # 步骤 3: 输出结果
                for i, image_blob in enumerate(image_blobs):
                    yield self.create_blob_message(
                        blob=image_blob, 
                        meta={
                            "file_name": f"{dify_file_obj.filename}_page{i+1}.png",
                            "mime_type": "image/png"
                        }
                    )
            
            yield self.create_text_message("🎉 所有文件处理完成！")

        except Exception as e:
            # 任何错误（格式、下载、转换）都会在这里被捕获，并终止执行
            error_msg = f"操作已中止，发生错误: {e}"
            print(f"[ERROR] {error_msg}")
            yield self.create_json_message({
                "result": error_msg
            })
            return