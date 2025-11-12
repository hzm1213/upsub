import os
import re
import base64
import requests
import yaml
import shutil
from urllib.parse import unquote
from subprocess import run

# ========== 配置部分 ==========
OUTPUT_DIR = "output"
TIMEOUT = 15
HEADERS = {"User-Agent": "Mozilla/5.0 (Clash-AutoScript)"}


# ========== 工具函数 ==========

def safe_rmtree(path):
    """安全删除文件夹"""
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        pass


def fetch_url(url):
    """获取订阅或配置文件内容"""
    try:
        res = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        res.raise_for_status()
        return res.text.strip()
    except Exception as e:
        print(f"⚠️ Failed to fetch {url}: {e}")
        return None


def extract_links_from_content(content):
    """从文本中提取所有 HTTP(S) 链接"""
    pattern = re.compile(r'https?://[^\s\'"<>]+')
    return list(set(pattern.findall(content)))


def decode_base64(data):
    """安全 Base64 解码"""
    try:
        data = data.strip()
        missing_padding = len(data) % 4
        if missing_padding:
            data += '=' * (4 - missing_padding)
        return base64.b64decode(data).decode('utf-8', errors='ignore')
    except Exception:
        return ""


def extract_nodes_from_content(content):
    """从任意订阅内容中提取节点"""
    decoded = decode_base64(content)
    full_text = content + "\n" + decoded

    node_pattern = re.compile(r'(?:(?:vmess|vless|trojan|ss)://[^\s]+)')
    nodes = node_pattern.findall(full_text)

    # 尝试解析 YAML 格式的 Clash 节点
    if not nodes:
        try:
            data = yaml.safe_load(full_text)
            if isinstance(data, dict) and "proxies" in data:
                for item in data["proxies"]:
                    nodes.append(str(item))
        except Exception:
            pass

    # 节点 remark 优化
    fixed_nodes = []
    for n in nodes:
        n = unquote(n)
        n = n.replace("🇨🇳TW", "🇹🇼TW").replace("%F0%9F%87%A8%F0%9F%87%B3TW", "🇹🇼TW")

        # 没有地区信息的补 🏳️ZZ
        if not re.search(r'🇦🇺|🇨🇦|🇨🇳|🇹🇼|🇭🇰|🇯🇵|🇺🇸|🇸🇬|🇰🇷|🇻🇳|🇬🇧|🇫🇷|🇩🇪|🇲🇾|🇹🇭|🇮🇩|🇵🇭|🇮🇳|🇹🇷', n):
            n += "#🏳️ZZ"
        fixed_nodes.append(n)
    return fixed_nodes


# ========== 主流程 ==========

if __name__ == "__main__":
    print("🧹 Cleaning output folder...")
    safe_rmtree(OUTPUT_DIR)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print("✅ Output folder fully reset. Numbering will start from 001.\n")

    # 从仓库读取所有文件内容
    repo_files = run(["git", "ls-files"], capture_output=True, text=True).stdout.splitlines()

    all_links = []
    for file_path in repo_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
                all_links += extract_links_from_content(content)
        except Exception:
            pass

    unique_links = sorted(set(all_links))
    print(f"🔎 Found {len(unique_links)} unique URLs.\n")

    valid_index = 0  # 有效订阅编号计数器

    for link in unique_links:
        print(f"📥 Processing: {link}")
        content = fetch_url(link)
        if not content:
            print(f"⚠️ Skipped (fetch failed): {link}\n")
            continue

        nodes = extract_nodes_from_content(content)
        if not nodes:
            print(f"⚠️ Skipped (no valid nodes): {link}\n")
            continue

        # 只有有节点的链接才编号
        valid_index += 1
        filename = f"{OUTPUT_DIR}/{valid_index:03}.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write("\n".join(nodes))
        print(f"✅ Saved {filename} ({len(nodes)} nodes)\n")

    # ========== Git 自动提交 ==========
    print("🪶 Committing & pushing changes...")
    run(["git", "config", "user.name", "github-actions[bot]"])
    run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"])
    run(["git", "add", OUTPUT_DIR], check=False)
    run(["git", "commit", "-m", "Update subscription files [skip ci]"], check=False)
    run(["git", "push"], check=False)

    print(f"\n🎯 All done! Valid subscription count: {valid_index}")
