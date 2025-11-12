import os
import re
import json
import yaml
import base64
import random
import requests
import subprocess
import urllib.parse
import shutil

# ===================== 配置 =====================
UPSTREAM_REPO = "suiyuan8/clash"
OUTPUT_DIR = "output"

TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID"

EMOJI_JSON_FILE = "emoji_global.json"  # 包含 flags_map 和 random_emoji_list
NODE_PROTOCOLS = ["vmess://", "ss://", "trojan://", "vless://"]

# ===================== 加载 emoji =====================
with open(EMOJI_JSON_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)

FLAGS_MAP = data["flags_map"]
RANDOM_EMOJI = data["random_emoji_list"]

# ===================== 获取默认分支 =====================
def get_default_branch(repo):
    url = f"https://api.github.com/repos/{repo}"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json()["default_branch"]

# ===================== 获取文件列表 =====================
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
    try:
        for doc in yaml.safe_load_all(content):
            if isinstance(doc, dict) and "proxy-providers" in doc:
                for provider in doc["proxy-providers"].values():
                    url = provider.get("url")
                    if url:
                        links.add(url)
    except Exception:
        pass
    try:
        data = json.loads(content)
        if isinstance(data, dict) and "proxy-providers" in data:
            for provider in data["proxy-providers"].values():
                url = provider.get("url")
                if url:
                    links.add(url)
    except Exception:
        pass
    urls = re.findall(r"https?://[^\s'\"]+", content)
    links.update(urls)
    return links

# ===================== 获取订阅节点 =====================
def fetch_nodes_from_link(url):
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        content = r.text.strip()
        # 纯文本协议节点
        if any(proto in content for proto in NODE_PROTOCOLS):
            return content.splitlines()
        # base64
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

# ===================== remark 解析 =====================
def get_vmess_remark(node):
    if not node.startswith("vmess://"):
        return ""
    b64_content = node[len("vmess://"):]
    try:
        decoded = base64.b64decode(b64_content).decode()
        data = json.loads(decoded)
        return data.get("ps", "")
    except Exception:
        return ""

def get_generic_remark(node):
    if "#" in node:
        remark = node.split("#",1)[1]
        return urllib.parse.unquote(remark)
    return ""

def fix_tw_remark(remark):
    remark_decoded = urllib.parse.unquote(remark)
    remark_decoded = remark_decoded.replace("🇨🇳TW", "🇹🇼TW")
    remark_decoded = remark_decoded.replace("%F0%9F%87%A8%F0%9F%87%B3TW", "🇹🇼TW")
    return remark_decoded

# ===================== 节点重命名 =====================
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
        remark = get_vmess_remark(node) if node.startswith("vmess://") else get_generic_remark(node)
        remark = fix_tw_remark(remark)

        flag_emoji = "🏳️"
        region_code = "ZZ"

        for emoji_flag, iso in FLAGS_MAP.items():
            if emoji_flag in remark:
                flag_emoji = emoji_flag
                region_code = iso
                break
        if flag_emoji == "🏳️":
            for iso, emoji_flag_candidate in {v:k for k,v in FLAGS_MAP.items()}.items():
                if iso.upper() in remark.upper():
                    flag_emoji = emoji_flag_candidate
                    region_code = iso
                    break

        rand_emoji = random.choice(RANDOM_EMOJI)
        seq = seq_format.format(idx)
        new_remark = f"{rand_emoji}{total}{flag_emoji}{region_code}{seq}"

        if node.startswith("vmess://"):
            b64_content = node[len("vmess://"):]
            try:
                decoded = base64.b64decode(b64_content).decode()
                data = json.loads(decoded)
                data["ps"] = new_remark
                renamed.append("vmess://" + base64.b64encode(json.dumps(data).encode()).decode())
                continue
            except Exception:
                pass
        if "#" in node:
            main_part = node.split("#",1)[0]
            renamed.append(f"{main_part}#{new_remark}")
        else:
            renamed.append(f"{node}#{new_remark}")
    return renamed

# ===================== 写文件 =====================
def write_base64_file(nodes, filename):
    b64_content = base64.b64encode("\n".join(nodes).encode()).decode()
    with open(filename, "w", encoding="utf-8") as f:
        f.write(b64_content)
    return b64_content

# ===================== Telegram =====================
def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode":"HTML"}
    try:
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code == 200:
            print("✅ Telegram message sent.")
        else:
            print(f"❌ Telegram failed: {resp.status_code}, {resp.text}")
    except Exception as e:
        print(f"❌ Telegram exception: {e}")

# ===================== Git 推送 =====================
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
print("🧹 Cleaning output folder...")
if os.path.exists(OUTPUT_DIR):
    shutil.rmtree(OUTPUT_DIR)
os.makedirs(OUTPUT_DIR, exist_ok=True)
print("✅ Output folder fully reset. Numbering will start from 001.")

print("🔎 Fetching repository files...")
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

print(f"🔎 Found {len(all_links)} unique URLs.")

valid_count = 0
for idx, link in enumerate(sorted(all_links), 1):
    nodes = fetch_nodes_from_link(link)
    if not nodes:
        continue  # 跳过无效节点
    nodes = list(dict.fromkeys(nodes))
    renamed_nodes = rename_nodes(nodes)
    filename = os.path.join(OUTPUT_DIR, f"{valid_count+1:03d}.txt")
    write_base64_file(renamed_nodes, filename)
    send_telegram_message(f"订阅文件生成/更新：{filename}")
    valid_count += 1

git_push_changes()
print(f"🎯 All subscription files processed and pushed. Valid subscription count: {valid_count}")
