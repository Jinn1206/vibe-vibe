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

folder_cache = {}

def get_folder_display_name(folder_path):
    """读取文件夹下的 index.md 获取中文标题"""
    default_name = os.path.basename(folder_path)
    for index_file in ["index.md", "README.md", "readme.md"]:
        path = os.path.join(folder_path, index_file)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                match = re.search(r'^title:\s*["\']?(.*?)["\']?$', content, re.MULTILINE)
                if match: return match.group(1).strip()
                match = re.search(r'^#\s+(.*?)$', content, re.MULTILINE)
                if match: return match.group(1).strip()
            except: pass
    return default_name

def parse_rich_text(text):
    """简单的 Markdown 样式解析"""
    rich_text = []
    pattern = re.compile(r'(\*\*.*?\*\*|`[^`]+`)')
    parts = pattern.split(text)
    for part in parts:
        if not part: continue
        if part.startswith("**") and part.endswith("**"):
            rich_text.append({"type": "text", "text": {"content": part[2:-2]}, "annotations": {"bold": True}})
        elif part.startswith("`") and part.endswith("`"):
            rich_text.append({"type": "text", "text": {"content": part[1:-1]}, "annotations": {"code": True}})
        else:
            rich_text.append({"type": "text", "text": {"content": part}})
    return rich_text

def get_parent_page_id(file_path):
    dir_path = os.path.dirname(file_path)
    if dir_path == DOCS_DIR: return ROOT_PAGE_ID
    if dir_path in folder_cache: return folder_cache[dir_path]
    
    parent_dir = os.path.dirname(dir_path)
    if parent_dir == DOCS_DIR or parent_dir == "":
        parent_id = ROOT_PAGE_ID
    else:
        parent_id = get_parent_page_id(os.path.join(parent_dir, "placeholder.md"))

    folder_name = get_folder_display_name(dir_path)
    found_id = None
    try:
        response = client.blocks.children.list(block_id=parent_id)
        for block in response.get("results", []):
            if block["type"] == "child_page" and block["child_page"]["title"] == folder_name:
                found_id = block["id"]
                break
    except: pass
        
    if not found_id:
        print(f"📁 创建文件夹: {folder_name}")
        new_page = client.pages.create(
            parent={"page_id": parent_id},
            properties={"title": [{"text": {"content": folder_name}}]},
            icon={"emoji": "📂"}
        )
        found_id = new_page["id"]
    
    folder_cache[dir_path] = found_id
    return found_id

def get_title_and_body(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    lines = content.splitlines()
    title = os.path.basename(file_path)
    
    # 1. 优先从 Frontmatter 获取完整标题
    frontmatter_title_match = re.search(r'^title:\s*["\']?(.*?)["\']?$', content, re.MULTILINE)
    if frontmatter_title_match:
        title = frontmatter_title_match.group(1).strip()

    body_lines = lines
    # 去除 Frontmatter
    if lines and lines[0].strip() == '---':
        try:
            for i in range(1, len(lines)):
                if lines[i].strip() == '---':
                    body_lines = lines[i+1:]
                    break
        except: pass
            
    # 如果没有 Frontmatter 标题，尝试提取 # 标题
    if not frontmatter_title_match:
        found_title = False
        final_body = []
        for line in body_lines:
            if not found_title and line.strip().startswith("# "):
                title = line.strip().replace("# ", "").strip()
                found_title = True
                continue 
            final_body.append(line)
        return title, final_body
    else:
        # 如果用了 Frontmatter 标题，正文里的 # 标题可能重复，过滤掉第一个 #
        final_body = []
        first_h1_skipped = False
        for line in body_lines:
            if not first_h1_skipped and line.strip().startswith("# "):
                first_h1_skipped = True
                continue
            final_body.append(line)
        return title, final_body

def markdown_to_blocks(lines):
    blocks = []
    code_mode = False
    code_content = []
    code_language = "plain text"
    
    # [新功能] 表格模式
    table_mode = False
    table_content = []
    
    for line in lines:
        stripped = line.strip()
        
        # --- 1. 处理代码块 ---
        if stripped.startswith("```"):
            if not code_mode:
                code_mode = True
                lang = stripped.replace("```", "").strip().lower()
                code_language = lang if lang else "plain text"
                continue
            else:
                code_mode = False
                content_str = "\n".join(code_content)
                # 修复 Mermaid 方向
                if code_language == "mermaid" or "graph LR" in content_str:
                    code_language = "mermaid"
                    content_str = content_str.replace("graph LR", "graph TD")

                blocks.append({
                    "object": "block",
                    "type": "code",
                    "code": {
                        "rich_text": [{"type": "text", "text": {"content": content_str[:2000]}}],
                        "language": code_language.split()[0]
                    }
                })
                code_content = []
                continue
        
        if code_mode:
            code_content.append(line) # 保留缩进
            continue

        # --- 2. 处理表格 (转换为 Markdown 代码块以保持格式) ---
        if stripped.startswith("|"):
            table_mode = True
            table_content.append(line)
            continue
        
        if table_mode:
            # 表格结束了
            table_mode = False
            blocks.append({
                "object": "block",
                "type": "code",
                "code": {
                    "rich_text": [{"type": "text", "text": {"content": "\n".join(table_content)[:2000]}}],
                    "language": "markdown" # 用 Markdown 语法高亮
                }
            })
            table_content = []

        if not stripped: continue

        # --- 3. 处理引用 (> text) ---
        if stripped.startswith("> "):
            blocks.append({
                "object": "block",
                "type": "quote",
                "quote": {"rich_text": parse_rich_text(stripped[2:])}
            })
            continue

        # --- 4. 图片处理 ---
        img_match = re.match(r'!\[(.*?)\]\((.*?)\)', stripped)
        if img_match:
            img_url = img_match.group(2)
            if not img_url.startswith("http"):
                clean_url = img_url.lstrip("/")
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

        # --- 5. 标题与文本 ---
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
            
    # 防止文件末尾的表格未提交
    if table_mode and table_content:
        blocks.append({
            "object": "block",
            "type": "code",
            "code": {
                "rich_text": [{"type": "text", "text": {"content": "\n".join(table_content)[:2000]}}],
                "language": "markdown"
            }
        })
            
    return blocks

def sync_file(file_path, root_id):
    parent_id = get_parent_page_id(file_path)
    real_title, body_lines = get_title_and_body(file_path)
    
    if "README" in file_path or "index" in file_path: return

    print(f"处理: {real_title}")
    
    try:
        response = client.blocks.children.list(block_id=parent_id)
        for block in response.get("results", []):
            if block["type"] == "child_page" and block["child_page"]["title"] == real_title:
                return 

        new_page = client.pages.create(
            parent={"page_id": parent_id},
            properties={"title": [{"text": {"content": real_title}}]},
            children=[]
        )
        
        blocks = markdown_to_blocks(body_lines)
        batch_size = 90
        for i in range(0, len(blocks), batch_size):
            client.blocks.children.append(block_id=new_page["id"], children=blocks[i:i+batch_size])
        print("  - ✅")
            
    except Exception as e:
        print(f"  - ❌: {e}")

def main():
    print("🚀 开始 V6.1 查漏补缺版...")
    files = glob.glob(f"{DOCS_DIR}/**/*.md", recursive=True)
    files.sort()
    for file_path in files:
        sync_file(file_path, ROOT_PAGE_ID)

if __name__ == "__main__":
    main()
