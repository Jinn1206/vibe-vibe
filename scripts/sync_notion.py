import os
import sys
import traceback

print("🔍 正在启动 V13.1 诊断模式...")

# 1. 检查依赖库
try:
    import glob
    import re
    import base64
    from notion_client import Client
    print("✅ 依赖库加载成功")
except ImportError as e:
    print(f"❌ 依赖库缺失: {e}")
    sys.exit(1)

# 2. 检查环境变量
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
ROOT_PAGE_ID = os.environ.get("NOTION_PAGE_ID")

if not NOTION_TOKEN:
    print("❌ 错误: 找不到 NOTION_TOKEN。请检查 GitHub Settings -> Secrets 是否配置正确，或者 YAML 文件里的 env 部分是否缺失。")
    sys.exit(1)
else:
    print(f"✅ NOTION_TOKEN 已读取 (长度: {len(NOTION_TOKEN)})")

if not ROOT_PAGE_ID:
    print("❌ 错误: 找不到 NOTION_PAGE_ID。")
    sys.exit(1)
else:
    print(f"✅ NOTION_PAGE_ID 已读取: {ROOT_PAGE_ID}")

# --- 以下是核心逻辑 ---
GITHUB_RAW_URL = "https://raw.githubusercontent.com/datawhalechina/vibe-vibe/main"
DOCS_DIR = "docs"
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
    if not text: return []
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
            cells_json = [parse_rich_text(c) for c in header_row]
            table_children.append({"type": "table_row", "table_row": {"cells": cells_json}})
        for row in rows[body_start:]:
            cells_json = [parse_rich_text(c) for c in row]
            table_children.append({"type": "table_row", "table_row": {"cells": cells_json}})
        return [{"object": "block", "type": "table", "table": {"table_width": len(header_row), "has_column_header": has_header, "children": table_children}}]
    except:
        return [{"object": "block", "type": "code", "code": {"rich_text": [{"type": "text", "text": {"content": "\n".join(table_lines)[:2000]}}], "language": "markdown"}}]

def process_mermaid_content(content_str):
    content_str = re.sub(r'(graph|flowchart)[ \t]+(LR|RL)', r'\1 TD', content_str, flags=re.IGNORECASE)
    content_str = re.sub(r'(graph|flowchart)[ \t]+TB', r'\1 TD', content_str, flags=re.IGNORECASE)
    content_str = re.sub(r'(graph TD)[ \t]*(subgraph)', r'\1\n\2', content_str, flags=re.IGNORECASE)
    code_bytes = content_str.encode('utf-8')
    base64_bytes = base64.urlsafe_b64encode(code_bytes)
    base64_str = base64_bytes.decode('ascii')
    url = f"https://mermaid.ink/img/{base64_str}"
    if len(url) > 1900:
        print(f"    ⚠️ 图片过大 (URL长度 {len(url)})，跳过显示。")
        return None
    return url

def markdown_to_blocks(lines):
    blocks = []
    code_mode = False
    code_content = []
    code_language = "plain text"
    table_mode = False
    table_content = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            if not code_mode:
                code_mode = True
                lang = stripped.replace("```", "").strip().lower()
                code_language = lang if lang else "plain text"
                continue
            else:
                code_mode = False
                content_str = "\n".join(code_content)
                if not content_str: content_str = " "
                if code_language == "mermaid" or "graph " in content_str or "flowchart " in content_str:
                    image_url = process_mermaid_content(content_str)
                    if image_url:
                        blocks.append({"object": "block", "type": "image", "image": {"type": "external", "external": {"url": image_url}}})
                else:
                    blocks.append({"object": "block", "type": "code", "code": {"rich_text": [{"type": "text", "text": {"content": content_str[:2000]}}], "language": code_language.split()[0]}})
                code_content = []
                continue
        if code_mode:
            code_content.append(line)
            continue
        if stripped.startswith("|"):
            table_mode = True
            table_content.append(line)
            continue
        if table_mode:
            table_mode = False
            blocks.extend(create_notion_table_blocks(table_content))
            table_content = []
        if not stripped: continue
        if stripped.startswith("> "):
            blocks.append({"object": "block", "type": "quote", "quote": {"rich_text": parse_rich_text(stripped[2:])}})
            continue
        img_match = re.match(r'!\[(.*?)\]\((.*?)\)', stripped)
        if img_match:
            img_url = img_match.group(2)
            if not img_url.startswith("http"):
                clean_url = img_url.lstrip("/")
                if "/images/" in clean_url and "public" not in clean_url:
                     clean_url = clean_url.replace("images/", "public/images/")
                     if clean_url.startswith("docs/"): clean_url = clean_url[5:]
                img_url = f"{GITHUB_RAW_URL}/docs/{clean_url}".replace("/docs/docs/", "/docs/")
            blocks.append({"object": "block", "type": "image", "image": {"type": "external", "external": {"url": img_url}}})
            continue
        if stripped.startswith("## "):
            blocks.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": parse_rich_text(stripped[3:])}})
        elif stripped.startswith("### "):
            blocks.append({"object": "block", "type": "heading_3", "heading_3": {"rich_text": parse_rich_text(stripped[4:])}})
        elif stripped.startswith("- ") or stripped.startswith("* "):
            blocks.append({"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": parse_rich_text(stripped[2:])}})
        else:
            blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": parse_rich_text(stripped[:2000])}})
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
        new_page = client.pages.create(parent={"page_id": parent_id}, properties={"title": [{"text": {"content": folder_name}}]}, icon={"emoji": "📂"})
        found_id = new_page["id"]
    folder_cache[dir_path] = found_id
    return found_id

def get_title_and_body(file_path):
    with open(file_path, "r", encoding="utf-8") as f: content = f.read()
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
    try:
        parent_id = get_parent_page_id(file_path)
        real_title, body_lines = get_title_and_body(file_path)
        if "README" in file_path or "index" in file_path: return
        print(f"处理: {real_title}")
        
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
        batch_size = 50
        for i in range(0, len(blocks), batch_size):
            batch = blocks[i:i+batch_size]
            try:
                client.blocks.children.append(block_id=new_page["id"], children=batch)
            except Exception as e:
                print(f"  ⚠️ 批次失败，尝试逐个上传: {e}")
                for block in batch:
                    try:
                        client.blocks.children.append(block_id=new_page["id"], children=[block])
                    except: pass 
        print("  - ✅")
    except Exception as e:
        print(f"  ❌ 同步文件失败 {file_path}: {e}")
        # traceback.print_exc()

def main():
    print("🚀 开始 V13.1 ...")
    try:
        files = glob.glob(f"{DOCS_DIR}/**/*.md", recursive=True)
        files.sort()
        for file_path in files:
            sync_file(file_path, ROOT_PAGE_ID)
    except Exception as e:
        print(f"❌ 主程序崩溃: {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
