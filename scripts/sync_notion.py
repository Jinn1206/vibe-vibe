import os
import sys
import glob
import re
import base64
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
    """解析 Markdown 样式"""
    rich_text = []
    pattern = re.compile(r'(\*\*.*?\*\*|`[^`]+`|\[.*?\]\(.*?\))')
    parts = pattern.split(text)
    
    for part in parts:
        if not part: continue
        if part.startswith("**") and part.endswith("**"):
            rich_text.append({"type": "text", "text": {"content": part[2:-2]}, "annotations": {"bold": True}})
        elif part.startswith("`") and part.endswith("`"):
            rich_text.append({"type": "text", "text": {"content": part[1:-1]}, "annotations": {"code": True}})
        elif part.startswith("[") and ")" in part:
            link_match = re.match(r'\[(.*?)\]\((.*?)\)', part)
            if link_match:
                name, url = link_match.groups()
                rich_text.append({"type": "text", "text": {"content": name, "link": {"url": url}}})
            else:
                rich_text.append({"type": "text", "text": {"content": part}})
        else:
            rich_text.append({"type": "text", "text": {"content": part}})
    return rich_text

def create_notion_table_blocks(table_lines):
    """原生表格生成器"""
    try:
        rows = []
        for line in table_lines:
            clean_line = line.strip().strip('|')
            cells = [c.strip() for c in clean_line.split('|')]
            rows.append(cells)
        
        if not rows: return []
        header_row = rows[0]
        has_header = False
        body_start = 1
        if len(rows) > 1 and set(rows[1][0]) <= {'-', ':', ' '}:
             has_header = True
             body_start = 2 
        
        table_children = []
        if has_header:
            cells_json = []
            for cell_text in header_row:
                cells_json.append(parse_rich_text(cell_text))
            table_children.append({"type": "table_row", "table_row": {"cells": cells_json}})
            
        for row in rows[body_start:]:
            cells_json = []
            for cell_text in row:
                cells_json.append(parse_rich_text(cell_text))
            table_children.append({"type": "table_row", "table_row": {"cells": cells_json}})

        return [{
            "object": "block",
            "type": "table",
            "table": {
                "table_width": len(header_row),
                "has_column_header": has_header,
                "has_row_header": False,
                "children": table_children
            }
        }]
    except:
        return [{
            "object": "block",
            "type": "code",
            "code": {
                "rich_text": [{"type": "text", "text": {"content": "\n".join(table_lines)[:2000]}}],
                "language": "markdown"
            }
        }]

def mermaid_to_image_url(mermaid_code):
    """强力正则匹配，强制将横向(LR)改为竖向(TD)"""
    mermaid_code = re.sub(r'(graph|flowchart)\s+(LR|RL)', r'\1 TD', mermaid_code, flags=re.IGNORECASE)
    mermaid_code = re.sub(r'(graph|flowchart)\s+TB', r'\1 TD', mermaid_code, flags=re.IGNORECASE)
    code_bytes = mermaid_code.encode('utf-8')
    base64_bytes = base64.urlsafe_b64encode(code_bytes)
    base64_str = base64_bytes.decode('ascii')
    return f"https://mermaid.ink/img/{base64_str}"

def markdown_to_blocks(lines):
    blocks = []
    code_mode = False
    code_content = []
    code_language = "plain text"
    
    table_mode = False
    table_content = []
    
    for line in lines:
        stripped = line.strip()
        
        # --- 1. 代码块 ---
        if stripped.startswith("```"):
            if not code_mode:
                code_mode = True
                lang = stripped.replace("```", "").strip().lower()
                # [核心修复] 如果语言为空，给一个默认值 "plain text"
                code_language = lang if lang else "plain text"
                continue
            else:
                code_mode = False
                content_str = "\n".join(code_content)
                
                # 如果是 Mermaid，转图片
                if code_language == "mermaid" or "graph " in content_str or "flowchart " in content_str:
                    image_url = mermaid_to_image_url(content_str)
                    blocks.append({
                        "object": "block",
                        "type": "image",
                        "image": {
                            "type": "external",
                            "external": {"url": image_url}
                        }
                    })
                else:
                    # 普通代码块
                    blocks.append({
                        "object": "block",
                        "type": "code",
                        "code": {
                            "rich_text": [{"type": "text", "text": {"content": content_str[:2000]}}],
                            # [兜底] 再次确保语言不为空
                            "language": code_language.split()[0] if code_language else "plain text"
                        }
                    })
                code_content = []
                continue
        
        if code_mode:
            code_content.append(line)
            continue

        # --- 2. 表格 ---
        if stripped.startswith("|"):
            table_mode = True
            table_content.append(line)
            continue
        if table_mode:
            table_mode = False
            blocks.extend(create_notion_table_blocks(table_content))
            table_content = []

        if not stripped: continue

        # --- 3. 引用 ---
        if stripped.startswith("> "):
            blocks.append({
                "object": "block",
                "type": "quote",
                "quote": {"rich_text": parse_rich_text(stripped[2:])}
            })
            continue

        # --- 4. 图片 ---
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
            
    if table_mode and table_content:
        blocks.extend(create_notion_table_blocks(table_content))
            
    return blocks

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
    match = re.search(r'^title:\s*["\']?(.*?)["\']?$', content, re.MULTILINE)
    if match: title = match.group(1).strip()
    body_lines = lines
    if lines and lines[0].strip() == '---':
        try:
            for i in range(1, len(lines)):
                if lines[i].strip() == '---':
                    body_lines = lines[i+1:]
                    break
        except: pass
    if match:
        final_body = []
        skipped = False
        for line in body_lines:
            if not skipped and line.strip().startswith("# "):
                skipped = True
                continue
            final_body.append(line)
        return title, final_body
    return title, body_lines

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
        batch_size = 80
        for i in range(0, len(blocks), batch_size):
            client.blocks.children.append(block_id=new_page["id"], children=blocks[i:i+batch_size])
        print("  - ✅")
    except Exception as e:
        print(f"  - ❌: {e}")

def main():
    print("🚀 开始 V10.0 (容错修复版) 同步...")
    files = glob.glob(f"{DOCS_DIR}/**/*.md", recursive=True)
    files.sort()
    for file_path in files:
        sync_file(file_path, ROOT_PAGE_ID)

if __name__ == "__main__":
    main()
