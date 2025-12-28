import os
import sys
import glob
import re
from notion_client import Client

# VibeVibe 的 GitHub 仓库原始文件地址
GITHUB_RAW_URL = "https://raw.githubusercontent.com/datawhalechina/vibe-vibe/main"

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
ROOT_PAGE_ID = os.environ.get("NOTION_PAGE_ID")
DOCS_DIR = "docs"

if not NOTION_TOKEN or not ROOT_PAGE_ID:
    print("Error: 缺少配置")
    sys.exit(1)

client = Client(auth=NOTION_TOKEN)

# 缓存文件夹对应的 Page ID，避免重复查找创建
# 格式: { "docs/Basic": "page_id_123", "docs/Basic/01-Chapter": "page_id_456" }
folder_cache = {}

def parse_rich_text(text):
    """
    [高级解析] 将文本中的 Markdown 符号 (**粗体**, `代码`) 转换为 Notion Rich Text 对象
    """
    rich_text = []
    # 正则匹配：**粗体**, `代码`, 或者普通文本
    # 这一步比较简单，只处理了最常见的粗体和行内代码，防止过于复杂出错
    pattern = re.compile(r'(\*\*.*?\*\*|`[^`]+`)')
    parts = pattern.split(text)
    
    for part in parts:
        if not part: continue
        
        if part.startswith("**") and part.endswith("**"):
            # 粗体
            content = part[2:-2]
            rich_text.append({
                "type": "text",
                "text": {"content": content},
                "annotations": {"bold": True}
            })
        elif part.startswith("`") and part.endswith("`"):
            # 行内代码
            content = part[1:-1]
            rich_text.append({
                "type": "text",
                "text": {"content": content},
                "annotations": {"code": True}
            })
        else:
            # 普通文本
            rich_text.append({
                "type": "text",
                "text": {"content": part}
            })
    return rich_text

def get_parent_page_id(file_path):
    """
    根据文件路径，递归创建/查找 Notion 中的父文件夹页面
    例如: docs/Basic/01.md -> 会先确保 'Basic' 页面存在，并返回它的 ID
    """
    # 获取文件所在的目录路径 (例如 docs/Basic/02-mindset)
    dir_path = os.path.dirname(file_path)
    
    # 如果就在 docs 根目录下，直接返回根页面 ID
    if dir_path == DOCS_DIR:
        return ROOT_PAGE_ID
        
    # 如果已经缓存过，直接返回
    if dir_path in folder_cache:
        return folder_cache[dir_path]
    
    # 递归查找上一级目录
    parent_dir = os.path.dirname(dir_path)
    if parent_dir == DOCS_DIR or parent_dir == "":
        parent_id = ROOT_PAGE_ID
    else:
        # 递归调用
        parent_id = get_parent_page_id(os.path.join(parent_dir, "placeholder.md"))

    # 当前文件夹的名字 (作为页面标题)
    folder_name = os.path.basename(dir_path)
    
    # 在父页面下查找是否已存在该文件夹页面
    found_id = None
    try:
        response = client.blocks.children.list(block_id=parent_id)
        for block in response.get("results", []):
            if block["type"] == "child_page" and block["child_page"]["title"] == folder_name:
                found_id = block["id"]
                break
    except:
        pass
        
    if not found_id:
        print(f"📁 创建目录页面: {folder_name}")
        new_page = client.pages.create(
            parent={"page_id": parent_id},
            properties={"title": [{"text": {"content": folder_name}}]},
            icon={"emoji": "📂"} # 给文件夹加个图标
        )
        found_id = new_page["id"]
    
    # 存入缓存
    folder_cache[dir_path] = found_id
    return found_id

def get_title_and_body(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    title = os.path.basename(file_path)
    body_lines = lines
    
    if lines and lines[0].strip() == '---':
        try:
            for i in range(1, len(lines)):
                if lines[i].strip() == '---':
                    body_lines = lines[i+1:]
                    break
        except: pass
            
    final_body = []
    found_title = False
    for line in body_lines:
        if not found_title and line.strip().startswith("# "):
            title = line.strip().replace("# ", "").strip()
            found_title = True
            continue 
        final_body.append(line)
    return title, final_body

def markdown_to_blocks(lines):
    blocks = []
    code_mode = False
    code_content = []
    code_language = "plain text"
    
    for line in lines:
        stripped = line.strip()
        
        # --- 处理代码块 (含 Mermaid 修复) ---
        if stripped.startswith("```"):
            if not code_mode:
                code_mode = True
                lang = stripped.replace("```", "").strip().lower()
                # 修复: 明确标记 mermaid，否则 Notion 无法渲染图表
                code_language = lang if lang else "plain text"
                continue
            else:
                code_mode = False
                blocks.append({
                    "object": "block",
                    "type": "code",
                    "code": {
                        "rich_text": [{"type": "text", "text": {"content": "".join(code_content)[:2000]}}],
                        "language": code_language.split()[0]  # Notion 只接受一个单词
                    }
                })
                code_content = []
                continue
        
        if code_mode:
            code_content.append(line)
            continue
            
        if not stripped: continue

        # --- 图片处理 ---
        img_match = re.match(r'!\[(.*?)\]\((.*?)\)', stripped)
        if img_match:
            img_url = img_match.group(2)
            if not img_url.startswith("http"):
                clean_url = img_url.lstrip("/")
                base_path = "docs/public" if "public" not in clean_url else "docs"
                if "/images/" in clean_url and "public" not in clean_url:
                     clean_url = clean_url.replace("images/", "public/images/")
                     if clean_url.startswith("docs/"): clean_url = clean_url[5:]
                img_url = f"{GITHUB_RAW_URL}/docs/{clean_url}".replace("/docs/docs/", "/docs/")

            blocks.append({
                "object": "block",
                "type": "image",
                "image": {"type": "external", "external": {"url": img_url}}
            })
            continue

        # --- 标题与文本 (接入 Rich Text 解析) ---
        if stripped.startswith("## "):
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": parse_rich_text(stripped[3:])}
            })
        elif stripped.startswith("### "):
            blocks.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": {"rich_text": parse_rich_text(stripped[4:])}
            })
        elif stripped.startswith("- ") or stripped.startswith("* "):
            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": parse_rich_text(stripped[2:])}
            })
        else:
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": parse_rich_text(stripped[:2000])}
            })
            
    return blocks

def sync_file(file_path, root_id):
    # 1. 智能获取父页面 (解决目录结构问题)
    # 脚本会自动去 Notion 创建 "Basic", "Chapter-1" 等文件夹页面
    parent_id = get_parent_page_id(file_path)
    
    real_title, body_lines = get_title_and_body(file_path)
    print(f"处理: {real_title} (父页面: {parent_id})")
    
    try:
        # 查重
        exists = False
        response = client.blocks.children.list(block_id=parent_id)
        for block in response.get("results", []):
            if block["type"] == "child_page" and block["child_page"]["title"] == real_title:
                print("  - 跳过")
                return 

        # 创建页面
        new_page = client.pages.create(
            parent={"page_id": parent_id},
            properties={"title": [{"text": {"content": real_title}}]},
            children=[]
        )
        
        # 上传内容
        blocks = markdown_to_blocks(body_lines)
        batch_size = 90
        for i in range(0, len(blocks), batch_size):
            client.blocks.children.append(block_id=new_page["id"], children=blocks[i:i+batch_size])
        print("  - ✅ 成功")
            
    except Exception as e:
        print(f"  - ❌ 失败: {e}")

def main():
    print("🚀 开始 V5.0 终极同步...")
    files = glob.glob(f"{DOCS_DIR}/**/*.md", recursive=True)
    files.sort()
    
    for file_path in files:
        if "README" in file_path or "index" in file_path: continue
        sync_file(file_path, ROOT_PAGE_ID)

if __name__ == "__main__":
    main()
