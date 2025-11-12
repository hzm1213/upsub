import os
import re
import json
import yaml
import base64
import random
import requests
from pathlib import Path

# ===================== 配置 =====================
UPSTREAM_REPO = "suiyuan8/clash"
OUTPUT_DIR = "output"

# Telegram 配置
TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID"

# emoji JSON 文件路径
EMOJI_JSON_FILE = "emoji_global.json"

# ===================== 加载 emoji =====================
with open(EMOJI_JSON_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)

FLAGS_MAP = data["flags_map"]           
RANDOM_EMOJI = data["random_emoji_list"]

# ===================== 获取默认分支 =====================
def get_default_branch(repo):
    """获取仓库默认分支"""
    url = f"https://api.github.com/repos/{repo}"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json()["default_branch"]

# ===================== GitHub 文件列表 =====================
def fetch_repo_files(repo):
    """获取上游仓库所有文件的 raw URLs"""
    branch = get_default_branch(repo)
    api_url = f"https://api.github.com/repos/{repo}/git/trees/{branch}?recursive=1"
    r = requests.get(api_url, timeout=20)
    r.raise_for_status()
    files = []
    for item in r.json().get("tree", []):
        if item["type"] == "blob":
            files.append(f"https://raw.githubusercontent.com/{repo}/{branch}/{item['path']}")
    return files

# ===================== 提取订阅链接 =====================
def extract_links_from_content(content):
    """从文本中提取可能的订阅 URL"""
    links = set()
    # 尝试 YAML 解析
    try:
        data = yaml.safe_load(content)
        if isinstance(data, dict):
            proxy_providers = data.get("proxy-providers", {})
            for provider in proxy_providers.values():
                url = provider.get("url")
                if url:
                    links.add(url)
    except Exception:
        pass

    # 尝试 JSON 解析
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            proxy_providers = data.get("proxy-providers", {})
            for provider in proxy_providers.values():
                url = provider.get("url")
                if url:
                    links.add(url)
    except Exception:
        pass

    # 其他格式：正则提取 http(s) 链接
    urls = re.findall(r"https?://[^\s'\"]+", content)
    for u in urls:
        links.add(u.strip())
    return links

# ===================== 获取订阅节点 =====================
def fetch_nodes_from_link(url):
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        content = r.text.strip()
        try:
            decoded = base64.b64decode(content).decode()
            return decoded.splitlines()
        except Exception:
            return content.splitlines()
    except Exception as e:
        print(f"Failed to fetch {url}: {e}")
        return []

# ===================== 节点重命名 =====================
def rename_nodes_from_remark(nodes):
    total = len(nodes)
    if total < 100:
        seq_format = "{:02d}"
    elif total < 1000:
        seq_format = "{:03d}"
    else:
        seq_format = "{:04d}"

    renamed = []
    for idx, node in enumerate(nodes, 1):
        remark = node
        flag_emoji = ""
        region_code = ""
        for emoji_flag, iso in FLAGS_MAP.items():
            if emoji_flag in remark:
                flag_emoji = emoji_flag
                region_code = iso
                break

        rand_emoji = random.choice(RANDOM_EMOJI)
        seq = seq_format.format(idx)
        renamed_node = f"{rand_emoji}{total}{flag_emoji}{region_code}{seq}"
        renamed.append(renamed_node)
    return renamed

# ===================== 保存 base64 文件 =====================
def write_base64_file(nodes, filename):
    b64_content = base64.b64encode("\n".join(nodes).encode()).decode()
    with open(filename, "w", encoding="utf-8") as f:
        f.write(b64_content)
    return b64_content

# ===================== Telegram 消息 =====================
def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        requests.post(url, data=data, timeout=10)
    except Exception as e:
        print("Telegram message failed:", e)

# ===================== 主流程 =====================
os.makedirs(OUTPUT_DIR, exist_ok=True)

print("Fetching repository file list...")
file_urls = fetch_repo_files(UPSTREAM_REPO)
print(f"Total files found: {len(file_urls)}")

all_links = set()
for url in file_urls:
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        content = r.text
        links = extract_links_from_content(content)
        all_links.update(links)
    except Exception as e:
        print(f"Failed to fetch {url}: {e}")

print(f"Found {len(all_links)} unique subscription links")

# 生成 base64 文件
for idx, link in enumerate(sorted(all_links), 1):
    nodes = fetch_nodes_from_link(link)
    nodes = list(dict.fromkeys(nodes))  # 去重
    renamed_nodes = rename_nodes_from_remark(nodes)
    filename = os.path.join(OUTPUT_DIR, f"{idx:03d}.txt")

    if Path(filename).exists():
        with open(filename, "r", encoding="utf-8") as f:
            old_content = f.read()
        new_content = base64.b64encode("\n".join(renamed_nodes).encode()).decode()
        if old_content != new_content:
            write_base64_file(renamed_nodes, filename)
            send_telegram_message(f"仓库文件变化：{filename}")
    else:
        write_base64_file(renamed_nodes, filename)
        send_telegram_message(f"新增订阅文件：{filename}")

print("All subscription files processed.")
