import os
import yaml
import base64
import requests
import random
from pathlib import Path
import json

# ===================== 配置 =====================
UPSTREAM_REPO_RAW = "https://raw.githubusercontent.com/suiyuan8/clash/master/"
LOCAL_DIR = "upstream_clash"
OUTPUT_DIR = "output"

# Telegram 配置
TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID"

# emoji JSON 文件路径
EMOJI_JSON_FILE = "emoji_global.json"

# ===================== 加载 emoji =====================
with open(EMOJI_JSON_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)

FLAGS_MAP = data["flags_map"]           # 国家旗帜 -> ISO
RANDOM_EMOJI = data["random_emoji_list"] # 非旗帜随机 emoji

# ===================== 辅助函数 =====================
def fetch_yaml(url):
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return yaml.safe_load(r.text)

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
        # 通过 remark 匹配旗帜
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

def write_base64_file(nodes, filename):
    b64_content = base64.b64encode("\n".join(nodes).encode()).decode()
    with open(filename, "w", encoding="utf-8") as f:
        f.write(b64_content)
    return b64_content

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        requests.post(url, data=data, timeout=10)
    except Exception as e:
        print("Telegram message failed:", e)

# ===================== 主流程 =====================
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 假设已知 YAML 文件列表
upstream_yaml_files = ["config.yaml"]

all_links = set()
for f in upstream_yaml_files:
    url = UPSTREAM_REPO_RAW + f
    data = fetch_yaml(url)
    proxy_providers = data.get("proxy-providers", {})
    for provider in proxy_providers.values():
        link = provider.get("url")
        if link:
            all_links.add(link)

print(f"Found {len(all_links)} unique subscription links")

# 遍历每条链接生成订阅文件
for idx, link in enumerate(sorted(all_links), 1):
    nodes = fetch_nodes_from_link(link)
    nodes = list(dict.fromkeys(nodes))  # 去重
    renamed_nodes = rename_nodes_from_remark(nodes)
    filename = os.path.join(OUTPUT_DIR, f"{idx:03d}.txt")

    # 文件变化检测
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
