import os
import sys
import glob
import re
from notion_client import Client

# VibeVibe 的 GitHub 仓库原始文件地址 (用于图片显示)
GITHUB_RAW_URL = "https://raw.githubusercontent.com/datawhalechina/vibe-vibe/main"

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
ROOT_PAGE_ID = os.environ.get("NOTION_PAGE_ID")
DOCS_DIR = "docs"

if not NOTION_TOKEN or not ROOT_PAGE_ID:
    print("Error: 缺少 NOTION_TOKEN 或 NOTION_PAGE_ID")
    sys.exit(1)

client = Client(auth=NOTION_TOKEN)

def get_title_and_body(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    title = os.path.basename(file_path)
    body_lines = lines
    
    # 1. 去除 Frontmatter
    if lines and lines[0].strip() == '---':
        try:
            for i in range(1, len(lines)):
                if lines[i].strip() == '---':
                    body_lines = lines[i+1:]
                    break
        except:
            pass
            
    # 2. 提取真正的标题
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
        
        # 代码块处理
        if stripped.startswith("```"):
            if not code_mode:
                code_mode = True
                code_language = stripped.replace("```", "").strip() or "javascript"
                continue
            else:
                code_mode = False
                blocks.append({
                    "object": "block",
                    "type": "code",
                    "code": {
                        "rich_text": [{"type": "text", "text": {"content": "".join(code_content)[:2000]}}],
                        "language": code_language.split()[0] if code_language else "plain text"
                    }
                })
                code_content = []
                continue
        
        if code_mode:
            code_content.append(line)
            continue
            
        if not stripped: continue

        # 图片处理 (转为 GitHub 链接)
        img_match = re.match(r'!\[(.*?)\]\((.*?)\)', stripped)
        if img_match:
            img_url = img_match.group(2)
            if not img_url.startswith("http"):
                clean_url = img_url.lstrip("/")
                # 修复路径: docs/images -> docs/public/images
                base_path = "docs/public" if "public" not in clean_url else "docs"
                if "/images/" in clean_url and "public" not in clean_url:
                     # 针对 VibeVibe 的特殊路径修复
                     clean_url = clean_url.replace("images/", "public/images/")
                     if clean_url.startswith("docs/"): clean_url = clean_url[5:]
                
                img_url = f"{GITHUB_RAW_URL}/docs/{clean_url}"
                # 再次兜底修复
                img_url = img_url.replace("/docs/docs/", "/docs/")

            blocks.append({
                "object": "block",
                "type": "image",
                "image": {
                    "type": "external",
                    "external": {"url": img_url}
                }
            })
            continue

        # 标题与文本处理
        if stripped.startswith("## "):
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": [{"type": "text", "text": {"content": stripped[3:]}}]}
            })
        elif stripped.startswith("### "):
            blocks.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": {"rich_text": [{"type": "text", "text": {"content": stripped[4:]}}]}
            })
        elif stripped.startswith("- ") or stripped.startswith("* "):
            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": stripped[2:]}}]}
            })
        else:
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": stripped[:2000]}}]}
            })
            
    return blocks

def sync_file(file_path, parent_id):
    real_title, body_lines = get_title_and_body(file_path)
    print(f"处理: {real_title}")
    
    # 查重 (遇到已存在则跳过)
    try:
        response = client.blocks.children.list(block_id=parent_id)
        for block in response.get("results", []):
            if block["type"] == "child_page" and block["child_page"]["title"] == real_title:
                print(f"  - 跳过 (已存在)")
                return 
    except:
        pass

    try:
        # 1. 创建页面
        new_page = client.pages.create(
            parent={"page_id": parent_id},
            properties={"title": [{"text": {"content": real_title}}]},
            children=[]
        )
        page_id = new_page["id"]
        
        # 2. 转换并上传内容
        blocks = markdown_to_blocks(body_lines)
        
        # 分批上传 (Notion 限制)
        batch_size = 90
        for i in range(0, len(blocks), batch_size):
            batch = blocks[i:i+batch_size]
            client.blocks.children.append(block_id=page_id, children=batch)
            print(f"  - 上传批次 {i//batch_size + 1}")
            
        print(f"  - ✅ 成功")
    except Exception as e:
        print(f"  - ❌ 失败: {e}")

def main():
    print("🚀 开始 V4.0 同步...")
    files = glob.glob(f"{DOCS_DIR}/**/*.md", recursive=True)
    files.sort()
    
    for file_path in files:
        if "README" in file_path or "index" in file_path: continue
        sync_file(file_path, ROOT_PAGE_ID)

if __name__ == "__main__":
    main()
