"""个性化配置中心核心适配层。
对接 AstrBot API 与 Breeze 本地语音引擎。
保留全部基础插件安装、性格管理、语音绑定及表情包源头透明化管理。
"""
import base64
import glob
import hashlib
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave

PACK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GH_ACCELERATORS = ["https://gh.dpik.top/", "https://hk.gh-proxy.com/", "https://ghfast.top/", "https://gh-proxy.com/", ""]

# 表情包官方开源元数据
KNOWN_MEME_PACKS = [
    {
        "id": "blue-fat-fish-meme-pack",
        "name": "蓝色大肥鱼表情包",
        "repo": "https://github.com/anka-afk/blue-fat-fish-meme-pack",
        "raw_base": "https://raw.githubusercontent.com/anka-afk/blue-fat-fish-meme-pack/v1.0.0/",
        "preview": "https://raw.githubusercontent.com/anka-afk/blue-fat-fish-meme-pack/v1.0.0/previews/cover.jpg",
        "count": "157 张动态表情",
        "description": "收录 157 张蓝色大肥鱼动态表情包，可爱灵动，适合各类聊天场景",
        "tag": "官方精选 / GIF动态"
    },
    {
        "id": "deepseek-fanart-meme-pack",
        "name": "DeepSeek 同人表情包",
        "repo": "https://github.com/anka-afk/deepseek-fanart-meme-pack",
        "raw_base": "https://raw.githubusercontent.com/anka-afk/deepseek-fanart-meme-pack/v1.0.0/",
        "preview": "https://raw.githubusercontent.com/anka-afk/deepseek-fanart-meme-pack/v1.0.0/previews/cover.jpg",
        "count": "174 张插画/表情",
        "description": "收录 174 张 DeepSeek 同人图片/插画/角色趣味表情",
        "tag": "官方精选 / 角色同人"
    }
]

COMMUNITY_INDEX_URL = "https://raw.githubusercontent.com/anka-afk/astrbot-meme-pack-index/main/community-index.json"
COMMUNITY_INDEX_REPO = "https://github.com/anka-afk/astrbot-meme-pack-index"


def load_pack_json():
    path = os.path.join(PACK_ROOT, "settings", "pack.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    return {}


def launcher_data_dirs():
    dirs = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        try:
            cfg = os.path.join(appdata, "com.github.raven95676.astrbot-launcher", ".data-dir.json")
            if os.path.exists(cfg):
                d = json.load(open(cfg, encoding="utf-8-sig")).get("data_dir", "").strip()
                if d:
                    dirs.append(d)
        except Exception:
            pass
    dirs.append(os.path.join(os.path.expanduser("~"), ".astrbot_launcher"))
    return dirs


def detect_astrbot_instances():
    found = []
    for data_dir in launcher_data_dirs():
        pattern = os.path.join(data_dir, "instances", "*", "core", "data", "cmd_config.json")
        for cfg in glob.glob(pattern):
            try:
                data = json.load(open(cfg, encoding="utf-8-sig"))
                port = data.get("dashboard", {}).get("port")
                name = cfg.split(os.sep)[-4]
                inst_dir = os.path.dirname(os.path.dirname(os.path.dirname(cfg)))
                if port:
                    found.append({"name": name, "port": int(port), "dir": inst_dir})
            except Exception:
                continue
    return found


def detect_napcat():
    """侦测本地 NapCatQQ 安装与运行状态。"""
    res = {
        "installed": False,
        "running": False,
        "path": "",
        "webui_url": "http://127.0.0.1:6099/webui",
        "bot_qq": "",
        "ws_url": "",
        "ws_token": "",
        "connected_to_astrbot": False
    }
    
    # 候选路径扫描
    candidates = [
        "D:\\NapCat.Shell.Windows.OneKey",
        "C:\\NapCat.Shell.Windows.OneKey",
        os.path.expanduser("~\\NapCat"),
        "C:\\NapCat",
        "D:\\NapCat"
    ]
    for c in candidates:
        if os.path.exists(c):
            res["installed"] = True
            res["path"] = c
            configs = glob.glob(os.path.join(c, "**", "onebot11_*.json"), recursive=True)
            for cfg in configs:
                try:
                    data = json.load(open(cfg, encoding="utf-8"))
                    fname = os.path.basename(cfg)
                    bot_qq = fname.replace("onebot11_", "").replace(".json", "")
                    if bot_qq.isdigit():
                        res["bot_qq"] = bot_qq
                    ws_clients = data.get("network", {}).get("websocketClients", [])
                    if ws_clients:
                        res["ws_url"] = ws_clients[0].get("url", "")
                        res["ws_token"] = ws_clients[0].get("token", "")
                except Exception:
                    pass
            break

    # 检测 NapCat WebUI (6099)
    try:
        req = urllib.request.Request("http://127.0.0.1:6099/webui", headers={"User-Agent": "AstrBot-ConfigCenter"})
        with urllib.request.urlopen(req, timeout=0.8) as r:
            if r.status in (200, 302, 301):
                res["running"] = True
    except Exception:
        pass

    # 检测与 AstrBot 的 OneBot v11 接口连接状态 (通常是 6199 端口)
    try:
        if os.name == "nt":
            out = subprocess.run(["netstat", "-ano", "-n", "-p", "TCP"], capture_output=True, text=True, timeout=1.5, errors="replace").stdout
            has_6199_listen = False
            has_6199_established = False
            for line in out.splitlines():
                if ":6199" in line:
                    if "LISTENING" in line.upper(): has_6199_listen = True
                    if "ESTABLISHED" in line.upper(): has_6199_established = True
            res["connected_to_astrbot"] = has_6199_listen and has_6199_established
    except Exception:
        pass

    return res


def test_astrbot_url(url):
    try:
        url = url.rstrip("/")
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        
        # 毫秒级探测端口是否监听，避免无意义的 HTTP 超时等待
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.08)
        ret = s.connect_ex((host, port))
        s.close()
        if ret != 0:
            return False

        req = urllib.request.Request(f"{url}/", headers={"User-Agent": "AstrBot-ConfigCenter"})
        with urllib.request.urlopen(req, timeout=0.8) as r:
            content = r.read(65536).decode("utf-8", "replace")
            return "AstrBot" in content or "astrbot" in content.lower()
    except Exception:
        return False


def sync_napcat_and_astrbot(client, nap_info=None):
    """一键对齐与修复 AstrBot 和 NapCatQQ 之间的 OneBot v11 通信链路（支持 AstrBot 在线或离线状态）。"""
    if not nap_info:
        nap_info = detect_napcat()
    
    cfg = None
    cfg_file = None

    # 1. 尝试在线通过 API 获取配置
    if client and client.token:
        cfg = client.get_default_config()

    # 2. 如果在线不可用（如 AstrBot 离线或未登录），从本地实例读取 cmd_config.json
    if not cfg:
        instances = detect_astrbot_instances()
        for inst in instances:
            for sub in [
                os.path.join(inst["dir"], "core", "data", "cmd_config.json"),
                os.path.join(inst["dir"], "data", "cmd_config.json")
            ]:
                if os.path.exists(sub):
                    try:
                        cfg = json.load(open(sub, encoding="utf-8-sig"))
                        cfg_file = sub
                        break
                    except Exception:
                        pass
            if cfg:
                break
    
    if not cfg:
        return False, "未能读取到 AstrBot 配置（请确认已安装 AstrBot 实例或启动 AstrBot）"
    
    platforms = cfg.setdefault("platform", [])
    aiocq = next((p for p in platforms if isinstance(p, dict) and p.get("type") == "aiocqhttp"), None)
    
    ws_port = 6199
    token = nap_info.get("ws_token") or "15241356766"
    
    if not aiocq:
        aiocq = {
            "id": "qq_bot",
            "type": "aiocqhttp",
            "enable": True,
            "ws_reverse_host": "127.0.0.1",
            "ws_reverse_port": ws_port,
            "ws_reverse_token": token
        }
        platforms.append(aiocq)
    else:
        aiocq["id"] = "qq_bot"
        aiocq["enable"] = True
        aiocq["ws_reverse_host"] = "127.0.0.1"
        aiocq["ws_reverse_port"] = ws_port
        if not aiocq.get("ws_reverse_token"):
            aiocq["ws_reverse_token"] = token
        else:
            token = str(aiocq["ws_reverse_token"])
            
    # 3. 确保 NapCat 本地配置文件中的 token 和 ws 地址与 AstrBot 一致
    napcat_synced = False
    if nap_info.get("path"):
        configs = glob.glob(os.path.join(nap_info["path"], "**", "onebot11_*.json"), recursive=True)
        for c in configs:
            try:
                data = json.load(open(c, encoding="utf-8"))
                net = data.setdefault("network", {})
                ws_clients = net.setdefault("websocketClients", [])
                target_url = f"ws://127.0.0.1:{ws_port}/ws"
                astr_client = next((w for w in ws_clients if "AstrBot" in w.get("name", "") or str(ws_port) in w.get("url", "")), None)
                if astr_client:
                    astr_client["enable"] = True
                    astr_client["url"] = target_url
                    astr_client["token"] = token
                else:
                    ws_clients.append({
                        "enable": True,
                        "name": "AstrBot",
                        "url": target_url,
                        "reportSelfMessage": False,
                        "messagePostFormat": "array",
                        "token": token,
                        "debug": False,
                        "heartInterval": 1000,
                        "reconnectInterval": 1000,
                        "verifyCertificate": True
                    })
                with open(c, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                napcat_synced = True
            except Exception:
                pass

    # 4. 保存 AstrBot 配置
    saved = False
    if cfg_file:
        try:
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            saved = True
        except Exception:
            pass

    if client and client.token:
        r = client.update_default_config(cfg)
        if client.is_ok(r):
            saved = True

    if saved or napcat_synced:
        return True, f"已成功对齐配置！AstrBot 反向 WS 服务端: 127.0.0.1:{ws_port}，Token: {token}（NapCat 配置已就绪）"
    return False, "更新 AstrBot 配置失败"


def scan_active_astrbot_url():
    """精确快速扫描当前活跃的 AstrBot 端口。"""
    ports = set()
    # 1. 尝试从启动器实例配置端口
    instances = detect_astrbot_instances()
    for inst in instances:
        if inst.get("port"): ports.add(inst["port"])

    # 2. 常用端口段 (包含 AstrBot 启动器分配的 17600+ 以及默认 6185+)
    for p in [17615, 6185, 17614, 17616, 6186, 6187]:
        ports.add(p)

    # 3. 扫描本机所有 python 进程监听的端口
    try:
        if os.name == "nt":
            out = subprocess.run(["netstat", "-ano", "-n", "-p", "TCP"], capture_output=True, text=True, timeout=1.5, errors="replace").stdout
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[3].upper() == "LISTENING":
                    host, _, port = parts[1].rpartition(":")
                    if host in ("127.0.0.1", "0.0.0.0") and port.isdigit():
                        p_int = int(port)
                        if (17600 <= p_int <= 17650) or (6185 <= p_int <= 6200):
                            ports.add(p_int)
    except Exception:
        pass

    # 验证哪个端口是真正的 AstrBot Dashboard
    for p in sorted(ports):
        url = f"http://127.0.0.1:{p}"
        if test_astrbot_url(url):
            return url
    return "http://127.0.0.1:6185"


def test_breeze_url(url="http://127.0.0.1:8137"):
    try:
        base = url.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        parsed = urllib.parse.urlparse(base)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 8137
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.08)
        ret = s.connect_ex((host, port))
        s.close()
        if ret != 0:
            return False
            
        req = urllib.request.Request(f"{base}/v1/voices", headers={"User-Agent": "AstrBot-ConfigCenter"})
        with urllib.request.urlopen(req, timeout=0.8) as r:
            return r.status == 200
    except Exception:
        return False


def find_ffmpeg_path():
    """查找本地可用的 FFmpeg 程序路径。"""
    p = shutil.which("ffmpeg")
    if p:
        return p
    for cand in [
        os.path.expanduser("~\\scoop\\shims\\ffmpeg.exe"),
        "C:\\ffmpeg\\bin\\ffmpeg.exe",
        "D:\\ffmpeg\\bin\\ffmpeg.exe",
        "C:\\ProgramData\\chocolatey\\bin\\ffmpeg.exe"
    ]:
        if os.path.exists(cand):
            return cand
    return None


def check_breeze_environment():
    """检测 Breeze TTS 2 本地语音环境的完整性（安装目录、模型、转码依赖、运行状态）。"""
    res = {
        "installed": False,
        "install_path": "",
        "exe_path": "",
        "has_model": False,
        "model_name": "",
        "has_ffmpeg": False,
        "ffmpeg_path": "",
        "running": False,
        "start_cmd": "",
        "ready": False
    }

    # 1. 查找 Breeze 安装目录与主程序
    candidates = [
        "D:\\breeze-tts",
        "C:\\breeze-tts",
        "E:\\breeze-tts",
        os.path.expanduser("~\\breeze-tts")
    ]
    for d in candidates:
        if os.path.exists(d):
            exes = glob.glob(os.path.join(d, "**", "breeze-server.exe"), recursive=True)
            models = glob.glob(os.path.join(d, "**", "*.gguf"), recursive=True)
            if exes:
                res["installed"] = True
                res["install_path"] = d
                res["exe_path"] = exes[0]
                if models:
                    res["has_model"] = True
                    res["model_name"] = os.path.basename(models[0])
                cmd = os.path.join(d, "start-breeze.cmd")
                if os.path.exists(cmd):
                    res["start_cmd"] = cmd
                break

    # 2. 检查 FFmpeg
    ff = find_ffmpeg_path()
    if ff:
        res["has_ffmpeg"] = True
        res["ffmpeg_path"] = ff

    # 3. 检查服务运行状态
    res["running"] = test_breeze_url()

    # 4. 全部前置条件是否就绪 (已安装且有模型且服务已在运行)
    res["ready"] = res["installed"] and res["has_model"] and res["running"]
    return res


def start_breeze_service():
    """在后台拉起 Breeze 本地语音引擎。"""
    import time
    info = check_breeze_environment()
    if info["running"]:
        return True, "Breeze 语音服务已经在运行中 (8137)"
    
    start_cmd = info.get("start_cmd")
    work_dir = info.get("install_path")
    if not start_cmd or not os.path.exists(start_cmd):
        return False, "未找到 Breeze 启动脚本 start-breeze.cmd，请先安装 Breeze 本地语音环境"

    try:
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_CONSOLE
        subprocess.Popen(
            ["cmd.exe", "/c", start_cmd],
            cwd=work_dir,
            creationflags=creationflags
        )
        for _ in range(16):
            time.sleep(0.5)
            if test_breeze_url():
                return True, "Breeze 语音服务已成功启动！(端口 8137)"
        return True, "启动指令已发出，模型正在加载预热中（稍候 10~20 秒将自动就绪）"
    except Exception as e:
        return False, f"拉起 Breeze 失败: {e}"


def check_plugins_completeness(client=None):
    """检测 8 大基础插件及系统配置是否已完整就绪。"""
    required = {
        "astrbot_plugin_group_chat_plus": "群聊插话与打字模拟",
        "astrbot_plugin_livingmemory": "长期记忆对话沉淀",
        "meme_manager": "表情包发送与规则配置",
        "astrbot_plugin_qzone": "QQ空间说说管理",
        "astrbot_plugin_qqprofile": "QQ签名与资料维护",
        "astrbot_plugin_proactive_chat": "定时主动找主人私聊",
        "astrbot_plugin_dafeiyu_clean": "防串台与系统标签清理",
        "astrbot_plugin_dafeiyu_signature": "防伪签名规则"
    }

    installed_set = set()
    configured_set = set()

    # 1. 在线获取
    if client and client.token:
        try:
            r = client.get_installed_plugins()
            for p in r:
                if isinstance(p, dict) and p.get("name"):
                    installed_set.add(p["name"])
        except Exception:
            pass

    # 2. 从本地实例目录读取（离线或辅助验证）
    instances = detect_astrbot_instances()
    if instances:
        inst_dir = instances[0]["dir"]
        for cand in [os.path.join(inst_dir, "core", "data"), os.path.join(inst_dir, "data")]:
            p_cand = os.path.join(cand, "plugins")
            c_cand = os.path.join(cand, "config")
            if os.path.exists(p_cand):
                for name in os.listdir(p_cand):
                    installed_set.add(name)
            if os.path.exists(c_cand):
                for name in os.listdir(c_cand):
                    base_name = name.replace("_config.json", "")
                    configured_set.add(base_name)

    plugin_status = {}
    missing = []
    unconfigured = []

    for pid, desc in required.items():
        is_inst = pid in installed_set
        is_conf = (pid in configured_set) or (pid in ("astrbot_plugin_dafeiyu_clean", "astrbot_plugin_dafeiyu_signature"))
        
        plugin_status[pid] = {
            "name": pid,
            "desc": desc,
            "installed": is_inst,
            "configured": is_conf if is_inst else False
        }
        if not is_inst:
            missing.append(pid)
        elif not is_conf:
            unconfigured.append(pid)

    all_done = (len(missing) == 0) and (len(unconfigured) == 0)

    return {
        "is_complete": all_done,
        "total": len(required),
        "installed_count": len(required) - len(missing),
        "missing_plugins": missing,
        "unconfigured_plugins": unconfigured,
        "plugins": plugin_status
    }


def save_persona_offline(persona_id, prompt):
    """直接落盘更新 AstrBot SQLite 数据库 (data_v4.db) 与 cmd_config.json（离线与在线均生效）。"""
    instances = detect_astrbot_instances()
    if not instances:
        return False, "未找到 AstrBot 实例目录"
    
    inst_dir = instances[0]["dir"]
    db_path = None
    cfg_path = None
    for sub in [os.path.join(inst_dir, "core", "data"), os.path.join(inst_dir, "data")]:
        db_cand = os.path.join(sub, "data_v4.db")
        cfg_cand = os.path.join(sub, "cmd_config.json")
        if os.path.exists(db_cand): db_path = db_cand
        if os.path.exists(cfg_cand): cfg_path = cfg_cand

    if not db_path:
        return False, "未找到 AstrBot 数据库 data_v4.db"

    try:
        import sqlite3
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT id FROM personas WHERE persona_id = ?", (persona_id,))
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE personas SET system_prompt = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (prompt, row[0]))
        else:
            cur.execute("INSERT INTO personas (persona_id, system_prompt, begin_dialogs, tools, skills, created_at, updated_at) VALUES (?, ?, '[]', '[]', '[]', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)", (persona_id, prompt))
        conn.commit()
        conn.close()

        if cfg_path and os.path.exists(cfg_path):
            with open(cfg_path, "r", encoding="utf-8-sig") as f:
                cfg = json.load(f)
            ar = cfg.setdefault("agent_runner", {}).setdefault("config", {}).setdefault("persona", {})
            ar["persona_id"] = persona_id
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)

        return True, f"已成功保存人格 [{persona_id}] 到 AstrBot 本地实例"
    except Exception as e:
        return False, f"离线保存人格失败: {e}"


class AstrBotClient:
    def __init__(self, base_url):
        self.root = base_url.rstrip("/")
        self.token = None

    def call(self, method, path, body=None, raw_body=None, content_type="application/json", timeout=120):
        url = self.root + "/api/v1" + path
        data = raw_body if raw_body is not None else (
            json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None)
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", content_type)
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                text = r.read().decode("utf-8", "replace")
                code = r.status
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
            code = e.code
        except Exception as e:
            err_str = str(e)
            if "10061" in err_str or "积极拒绝" in err_str or "Connection refused" in err_str:
                return {
                    "status": "error",
                    "message": "无法连接到 AstrBot 服务（目标计算机积极拒绝）。请确认已先在电脑上手动启动 AstrBot，并且后台端口正确。",
                    "_http": 0
                }
            return {"status": "error", "message": f"连接失败: {err_str}", "_http": 0}

        try:
            out = json.loads(text) if text else {}
        except ValueError:
            out = {"status": "error", "message": text[:300]}
        if not isinstance(out, dict):
            out = {"status": "ok", "data": out}
        out["_http"] = code
        return out

    def is_ok(self, r):
        return r.get("_http", 200) < 400 and r.get("status", "ok") != "error"

    def login(self, username, password):
        for pw in (password, hashlib.md5(password.encode()).hexdigest()):
            r = self.call("POST", "/auth/login", {"username": username, "password": pw})
            data = r.get("data")
            if isinstance(data, dict) and data.get("token"):
                self.token = data["token"]
                return True, "登录成功"
        return False, r.get("message") or "用户名或密码错误"

    def get_default_config(self):
        r = self.call("GET", "/config-profiles/default")
        if self.is_ok(r):
            return r.get("data", {}).get("config", {})
        return None

    def update_default_config(self, cfg):
        return self.call("PUT", "/config-profiles/default", cfg)

    def get_installed_plugins(self):
        r = self.call("GET", "/plugins")
        if self.is_ok(r):
            data = r.get("data") or []
            return [p for p in data if isinstance(p, dict)]
        return []

    def reload_plugin(self, plugin_name):
        return self.call("POST", "/plugins/reload", {"plugin_id": plugin_name}, timeout=180)


class BreezeClient:
    def __init__(self, base_url="http://127.0.0.1:8137"):
        base = base_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        self.base = base

    def get_voices(self):
        url = f"{self.base}/v1/voices"
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            return []

    def clone_voice(self, name, audio_bytes, filename, ref_text, description=""):
        boundary = uuid.uuid4().hex
        parts = []
        for k, v in [("ref_text", ref_text), ("name", name), ("description", description)]:
            if v:
                parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode("utf-8"))
        
        ext = os.path.splitext(filename)[1] or ".wav"
        head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"ref_audio\"; filename=\"ref{ext}\"\r\n"
                "Content-Type: application/octet-stream\r\n\r\n").encode("utf-8")
        body = b"".join(parts) + head + audio_bytes + f"\r\n--{boundary}--\r\n".encode()

        req = urllib.request.Request(f"{self.base}/v1/voices", data=body, method="POST")
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return True, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return False, e.read().decode("utf-8", "replace")
        except Exception as e:
            return False, str(e)

    def speak(self, voice_name, text):
        url = f"{self.base}/v1/audio/speech"
        payload = json.dumps({
            "model": "tts-1",
            "voice": voice_name,
            "input": text,
            "response_format": "pcm"
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                pcm = r.read()
            # 转为 wav 格式以便浏览器播放
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(24000)
                w.writeframes(pcm)
            return True, buf.getvalue()
        except urllib.error.HTTPError as e:
            return False, e.read().decode("utf-8", "replace")
        except Exception as e:
            return False, str(e)
