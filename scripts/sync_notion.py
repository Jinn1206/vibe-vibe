import os
import sys
import glob
import re
from io import StringIO
from notion_client import Client
from md2notion.upload import upload

# 获取环境变量
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
ROOT_PAGE_ID = os.environ.get("NOTION_PAGE_ID")
DOCS_DIR = "docs"

if not NOTION_TOKEN or not ROOT_PAGE_ID:
    print("Error: 缺少配置")
    sys.exit(1)

client = Client(auth=NOTION_TOKEN)

def parse_file_content(file_path):
    """
    智能读取文件：
    1. 提取真正的标题 (第一行 # 后的内容)
    2. 去除开头的元数据 (Frontmatter)
    """
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    title = os.path.basename(file_path) # 默认用文件名兜底
    start_idx = 0
    
    # 1. 处理 Frontmatter (去除开头的 --- ... ---)
    if lines and lines[0].strip() == '---':
        try:
            # 找第二个 ---
            for i in range(1, len(lines)):
                if lines[i].strip() == '---':
                    start_idx = i + 1
                    break
        except Exception:
            pass
            
    # 提取正文内容
    content_lines = lines[start_idx:]
    full_content = "".join(content_lines)
    
    # 2. 尝试从正文里找真正的标题 (比如 "# 1.1 觉醒")
    for line in content_lines:
        if line.strip().startswith("# "):
            title = line.strip().replace("# ", "").strip()
            break
            
    return title, full_content

def sync_file(file_path, parent_id):
    real_title, cleaned_content = parse_file_content(file_path)
    print(f"正在处理: {real_title}...")
    
    # 简单查重逻辑（通过标题查找）
    # 注意：如果标题变了，可能会重复创建，建议首次使用空页面运行
    exists = False
    try:
        response = client.blocks.children.list(block_id=parent_id)
        for block in response.get("results", []):
            if block["type"] == "child_page" and block["child_page"]["title"] == real_title:
                exists = True
                print(f"  - 跳过 (已存在): {real_title}")
                break
    except Exception as e:
        print(f"  - 查重失败: {e}")

    if not exists:
        try:
            # 创建新页面
            new_page = client.pages.create(
                parent={"page_id": parent_id},
                properties={"title": [{"text": {"content": real_title}}]},
                children=[]
            )
            
            # 使用 io.StringIO 把清洗后的字符串伪装成文件对象上传
            f_obj = StringIO(cleaned_content)
            upload(f_obj, client.pages.retrieve(new_page["id"]), client)
            print(f"  - ✅ 成功上传内容")
        except Exception as e:
            print(f"  - ❌ 上传失败: {e}")

def main():
    print("🚀 开始 V2.0 智能同步...")
    
    # 1. 获取所有 .md 文件
    files = glob.glob(f"{DOCS_DIR}/**/*.md", recursive=True)
    
    # 2. 关键修复：按文件名排序 (解决乱序问题)
    files.sort() 
    
    print(f"共发现 {len(files)} 篇文章")
    
    for file_path in files:
        # 过滤掉非文章文件（比如 README 或 索引文件）
        if "README" in file_path or "index" in file_path:
            continue
            
        sync_file(file_path, ROOT_PAGE_ID)

if __name__ == "__main__":
    main()
