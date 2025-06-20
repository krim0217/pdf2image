from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

import fitz  # PyMuPDF
import os
from typing import List
import requests
import io
from typing import Optional # 在 Python 3.10+ 中，可以直接用 | None

def download_dify_file_content(
    dify_file_obj: object, 
    dify_host_url: str, 
) -> bytes | None:
    """
    从Dify文件对象中下载文件内容到内存。

    Args:
        dify_file_obj (object): Dify文件对象，应包含 'filename' 和 'url' 属性。
        dify_host_url (str): Dify实例的主机URL (例如 "http://127.0.0.1")。
        http_session (requests.Session): 用于执行HTTP请求的requests会话对象。

    Returns:
        bytes | None: 成功则返回文件的二进制内容(blob)，否则返回None。
    """
    try:
        file_name_full = dify_file_obj.filename
        relative_url = dify_file_obj.url
    except AttributeError:
        print(f"错误: Dify文件对象结构不正确，缺少 'filename' 或 'url' 属性。对象: {dify_file_obj}")
        return None

    cleaned_host_url = dify_host_url.rstrip('/')
    
    # 构建完整URL
    full_url = relative_url
    if not relative_url.startswith(('http://', 'https://')):
        if relative_url.startswith('/'):
            full_url = f"{cleaned_host_url}{relative_url}"
        else:
            full_url = f"{cleaned_host_url}/{relative_url}"

    print(f"  [Downloader] 准备从URL下载: {full_url}")
    try:
        response = requests.get(full_url, timeout=60)
        response.raise_for_status()  # 检查HTTP错误 (如 404, 500)
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

    :param pdf_bytes: PDF文件的字节内容。
    :param dpi: 图像的分辨率 (dots per inch)，值越高越清晰。
    :param image_format: 输出图片的格式，如 "png", "jpeg" 等。
    :return: 一个列表，其中每个元素都是一页PDF转换后的图片字节数据。
    """
    # 用于存储每页图片字节数据的列表
    image_blobs = []

    try:
        # 1. 从内存中打开PDF文件
        # 使用 fitz.open(stream=...) 来处理字节流数据
        pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")

        # 2. 遍历PDF的每一页
        for page_number in range(len(pdf_document)):
            page = pdf_document.load_page(page_number)
            
            # 3. 将页面渲染为像素图 (Pixmap)
            pix = page.get_pixmap(dpi=dpi)
            
            # 4. 将像素图转换为指定格式的图片字节流 (blob)
            # pix.tobytes() 是获取图片blob的核心方法
            img_data = pix.tobytes(output=image_format)
            
            # 5. 将图片字节流添加到列表中
            image_blobs.append(img_data)
            
            print(f"成功处理页面 {page_number + 1}/{len(pdf_document)}")

        # 关闭PDF文档
        pdf_document.close()

    except Exception as e:
        print(f"处理PDF时发生错误: {e}")
        # 如果出错，返回一个空列表
        return []

    return image_blobs

class Pdf2imageTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:

        dify_file_obj = tool_parameters.get('pdf_file')
        dify_host_url = tool_parameters.get('host_url')

        pdf_blob = download_dify_file_content(dify_file_obj, dify_host_url)
        image_blobs = convert_pdf_to_image_blobs(pdf_blob)
        
        for i, image_blob in enumerate(image_blobs):
            yield self.create_blob_message(blob=image_blob, meta={
                "file_name": f"{dify_file_obj.filename}_page{i+1}.png",
                "mime_type": "image/png"
            })