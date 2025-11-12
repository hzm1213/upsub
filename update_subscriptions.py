import os
import re
import json
import yaml
import base64
import random
import requests
import subprocess
import urllib.parse
from pathlib import Path

# ===================== 配置 =====================
UPSTREAM_REPO = "suiyuan8/clash"
OUTPUT_DIR = "output"

# Telegram 配置
TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID"

# emoji JSON 文件路径
EMOJI_JSON_FILE = "emoji_global.json"

# 节点协议列表
NODE_PROTOCOLS = ["vmess://", "ss://", "trojan://", "vless://"]

# ===================== 加载 emoji =====================
with open(EMOJI_JSON_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)

FLAGS_MAP = data["flags_map"]           # 旗帜 emoji -> ISO
RANDOM_EMOJI = data["random_emoji_list"] # 随机 emoji
ISO_TO_FLAG = {v: k for k, v in FLAGS_MAP.items()}  # ISO -> 旗帜

# ===================== 获取默认分支 =====================
def get_default_branch(repo):
    url = f"https://api.github.com/repos/{repo}"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json()["default_branch"]

# ===================== GitHub 文件列表 =====================
def fetch_repo_files(repo):
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
    links = set()
    # YAML 多文档解析
    try:
        for doc in yaml.safe_load_all(content):
            if isinstance(doc, dict) and "proxy-providers" in doc:
                for provider in doc["proxy-providers"].values():
                    url = provider.get("url")
                    if url:
                        links.add(url)
    except Exception:
        pass
    # JSON 解析兜底
    try:
        data = json.loads(content)
        if isinstance(data, dict) and "proxy-providers" in data:
            for provider in data["proxy-providers"].values():
                url = provider.get("url")
                if url:
                    links.add(url)
    except Exception:
        pass
    # 正则提取 URL 兜底
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
        # 如果内容包含节点协议直接返回
        if any(proto in content for proto in NODE_PROTOCOLS):
            return content.splitlines()
        # 尝试 base64 解码后再检查协议
        try:
            decoded = base64.b64decode(content).decode()
            if any(proto in decoded for proto in NODE_PROTOCOLS):
                return decoded.splitlines()
        except Exception:
            pass
        return []
    except Exception as e:
        print(f"Failed to fetch {url}: {e}")
        return []

# ===================== 解析 VMESS remark =====================
def get_vmess_remark(node):
    if not node.startswith("vmess://"):
        return ""
    b64_content = node[len("vmess://"):]
    try:
        decoded = base64.b64decode(b64_content).decode()
        data = json.loads(decoded)
        remark = data.get("ps", "")
        return urllib.parse.unquote(remark)
    except Exception:
        return ""

# ===================== 解析其他协议 remark =====================
def get_generic_remark(node):
    if "#" in node:
        remark = node.split("#",1)[1]
        return urllib.parse.unquote(remark)
    return ""

# ===================== 节点重命名（保留协议，只改 remark） =====================
def rename_nodes(nodes):
    total = len(nodes)
    if total < 100:
        seq_format = "{:02d}"
    elif total < 1000:
        seq_format = "{:03d}"
    else:
        seq_format = "{:04d}"

    renamed = []
    for idx, node in enumerate(nodes, 1):
        if node.startswith("vmess://"):
            remark = get_vmess_remark(node)
        else:
            remark = get_generic_remark(node)

        # 尝试获取旗帜和国家缩写
        flag_emoji = ""
        region_code = ""

        for emoji_flag, iso in FLAGS_MAP.items():
            if emoji_flag in remark:
                flag_emoji = emoji_flag
                region_code = iso
                break

        if not flag_emoji:
            for iso in ISO_TO_FLAG:
                if iso.upper() in remark.upper():
                    flag_emoji = ISO_TO_FLAG[iso]
                    region_code = iso
                    break

        if not flag_emoji:
            flag_emoji = "🏳️"
            region_code = "ZZ"

        rand_emoji = random.choice(RANDOM_EMOJI)
        seq = seq_format.format(idx)
        new_remark = f"{rand_emoji}{total}{flag_emoji}{region_code}{seq}"

        if node.startswith("vmess://"):
            # 修改 VMESS 的 ps 字段并重新编码
            b64_content = node[len("vmess://"):]
            try:
                decoded = base64.b64decode(b64_content).decode()
                data = json.loads(decoded)
                data["ps"] = new_remark
                new_node = "vmess://" + base64.b64encode(json.dumps(data).encode()).decode()
                renamed.append(new_node)
                continue
            except Exception:
                pass
        # 其它协议直接修改 remark
        if "#" in node:
            main_part = node.split("#",1)[0]
            renamed.append(f"{main_part}#{new_remark}")
        else:
            renamed.append(f"{node}#{new_remark}")
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

# ===================== Git 提交并推送 =====================
def git_push_changes():
    try:
        subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
        subprocess.run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"], check=True)
        subprocess.run(["git", "add", OUTPUT_DIR], check=True)
        result = subprocess.run(["git", "diff", "--cached", "--quiet"])
        if result.returncode != 0:
            subprocess.run(["git", "commit", "-m", "Update subscription files [skip ci]"], check=True)
            subprocess.run(["git", "push"], check=True)
            print("Changes pushed to repository.")
        else:
            print("No changes to commit.")
    except Exception as e:
        print("Git push failed:", e)

# ===================== 主流程 =====================

# 清空 output 目录
os.makedirs(OUTPUT_DIR, exist_ok=True)
for f in os.listdir(OUTPUT_DIR):
    if f.endswith(".txt"):
        os.remove(os.path.join(OUTPUT_DIR, f))

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

for idx, link in enumerate(sorted(all_links), 1):
    nodes = fetch_nodes_from_link(link)
    if not nodes:
        continue
    nodes = list(dict.fromkeys(nodes))  # 去重
    renamed_nodes = rename_nodes(nodes)
    filename = os.path.join(OUTPUT_DIR, f"{idx:03d}.txt")
    write_base64_file(renamed_nodes, filename)
    send_telegram_message(f"订阅文件生成/更新：{filename}")

git_push_changes()
print("All subscription files processed and pushed to repository.")
