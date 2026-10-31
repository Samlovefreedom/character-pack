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
import zipfile

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
    """精确快速扫描当前活跃的 AstrBot 端口。自动适应 AstrBot 启动器动态分配的任意端口。"""
    candidate_ports = []
    
    # 1. 尝试从启动器实例配置端口
    instances = detect_astrbot_instances()
    for inst in instances:
        if inst.get("port") and inst["port"] not in candidate_ports:
            candidate_ports.append(inst["port"])

    # 2. 常用端口与默认端口
    for p in [16979, 17615, 6185, 17614, 17616, 6186, 6187]:
        if p not in candidate_ports:
            candidate_ports.append(p)

    # 3. 扫描本机所有正在监听的 TCP 端口 (AstrBot 启动器会动态分配 10000-65535 的端口)
    try:
        if os.name == "nt":
            out = subprocess.run(["netstat", "-ano", "-n", "-p", "TCP"], capture_output=True, text=True, timeout=1.5, errors="replace").stdout
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 4 and parts[0].upper() == "TCP" and parts[3].upper() == "LISTENING":
                    host, _, port = parts[1].rpartition(":")
                    if host in ("127.0.0.1", "0.0.0.0") and port.isdigit():
                        p_int = int(port)
                        # 排除非 AstrBot 服务的常见端口
                        if p_int not in (18989, 8137, 6099, 3306, 135, 445, 53, 80, 443) and p_int not in candidate_ports:
                            candidate_ports.append(p_int)
    except Exception:
        pass

    # 验证哪个端口是真正的 AstrBot Dashboard
    for p in candidate_ports:
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
        conn = sqlite3.connect(db_path, timeout=15.0)
        cur = conn.cursor()
        cur.execute("PRAGMA busy_timeout = 15000")
        cur.execute("SELECT id FROM personas WHERE persona_id = ?", (persona_id,))
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE personas SET system_prompt = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (prompt, row[0]))
        else:
            cur.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM personas")
            next_sort = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO personas (persona_id, system_prompt, begin_dialogs, tools, skills, sort_order, created_at, updated_at) "
                "VALUES (?, ?, '[]', '[]', '[]', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                (persona_id, prompt, next_sort)
            )
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
        self.try_auto_token()

    def try_auto_token(self):
        """尝试从本地 cmd_config.json 自动提取 jwt_secret 生成免密直连 Token"""
        try:
            import jwt
            import datetime
            instances = detect_astrbot_instances()
            cfg_path = None
            if instances and instances[0].get("dir"):
                cand = os.path.join(instances[0]["dir"], "data", "cmd_config.json")
                if os.path.exists(cand): cfg_path = cand
            if not cfg_path:
                cand = os.path.join(os.path.expanduser("~"), ".astrbot_launcher", "instances", "*", "core", "data", "cmd_config.json")
                matches = glob.glob(cand)
                if matches: cfg_path = matches[0]
            if cfg_path and os.path.exists(cfg_path):
                cfg = json.load(open(cfg_path, encoding="utf-8-sig"))
                secret = cfg.get("dashboard", {}).get("jwt_secret")
                username = cfg.get("dashboard", {}).get("username", "astrbot")
                if secret:
                    payload = {
                        "username": username,
                        "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=7)
                    }
                    self.token = jwt.encode(payload, secret, algorithm="HS256")
                    return True
        except Exception:
            pass
        return False

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
            "response_format": "wav"
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            # 如果本身就是 WAV 格式 (以 RIFF 开头)，直接返回
            if data[:4] == b"RIFF":
                return True, data
            # 否则视作 PCM 补充 WAV 头
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(24000)
                w.writeframes(data)
            return True, buf.getvalue()
        except urllib.error.HTTPError as e:
            return False, e.read().decode("utf-8", "replace")
        except Exception as e:
            return False, str(e)


def get_active_persona_info():
    """获取 AstrBot 当前生效的性格名称、提示词以及绑定的主人 QQ。保证不会每次都重置到初始模版。"""
    instances = detect_astrbot_instances()
    if not instances:
        return {"persona_id": "大肥鱼", "prompt": "", "owner_qq": "", "is_custom": False}

    inst_dir = instances[0]["dir"]
    db_path = None
    cfg_path = None
    for sub in [os.path.join(inst_dir, "core", "data"), os.path.join(inst_dir, "data")]:
        db_cand = os.path.join(sub, "data_v4.db")
        cfg_cand = os.path.join(sub, "cmd_config.json")
        if os.path.exists(db_cand): db_path = db_cand
        if os.path.exists(cfg_cand): cfg_path = cfg_cand

    active_id = "大肥鱼"
    owner_qq = ""
    if cfg_path and os.path.exists(cfg_path):
        try:
            cfg = json.load(open(cfg_path, encoding="utf-8-sig"))
            active_id = cfg.get("agent_runner", {}).get("config", {}).get("persona", {}).get("persona_id") or "大肥鱼"
            admins = cfg.get("admins_id", [])
            wl = cfg.get("platform_settings", {}).get("id_whitelist", [])
            if admins:
                owner_qq = str(admins[0])
            elif wl:
                m = re.search(r"\d{5,12}", str(wl[0]))
                if m: owner_qq = m.group(0)
        except Exception:
            pass

    prompt = ""
    if db_path and os.path.exists(db_path):
        try:
            import sqlite3
            conn = sqlite3.connect(db_path, timeout=5.0)
            cur = conn.cursor()
            cur.execute("SELECT system_prompt FROM personas WHERE persona_id = ?", (active_id,))
            row = cur.fetchone()
            if row and row[0]:
                prompt = row[0]
            conn.close()
        except Exception:
            pass

    # 若数据库尚未存入该性格，回退至大肥鱼参考范式
    if not prompt:
        ref_file = os.path.join(PACK_ROOT, "persona", "大肥鱼.md")
        if os.path.exists(ref_file):
            with open(ref_file, "r", encoding="utf-8") as f:
                prompt = f.read()

    return {
        "persona_id": active_id,
        "prompt": prompt,
        "owner_qq": owner_qq,
        "is_custom": bool(prompt and active_id != "大肥鱼")
    }


def get_active_voice_info():
    """获取 AstrBot 当前生效的 TTS 语音设置与音色名称"""
    instances = detect_astrbot_instances()
    if not instances:
        return {"enabled": False, "voice_name": "dafeiyu", "provider_id": ""}
    
    inst_dir = instances[0]["dir"]
    cfg_path = None
    for sub in [os.path.join(inst_dir, "core", "data"), os.path.join(inst_dir, "data")]:
        cfg_cand = os.path.join(sub, "cmd_config.json")
        if os.path.exists(cfg_cand):
            cfg_path = cfg_cand
            break

    if not cfg_path or not os.path.exists(cfg_path):
        return {"enabled": False, "voice_name": "dafeiyu", "provider_id": ""}

    try:
        cfg = json.load(open(cfg_path, encoding="utf-8-sig"))
        tts_settings = cfg.get("provider_tts_settings", {})
        enabled = bool(tts_settings.get("enable", False))
        active_provider_id = tts_settings.get("provider_id", "")
        
        voice_name = ""
        for pr in cfg.get("provider", []):
            if pr.get("id") == active_provider_id or pr.get("provider_type") == "text_to_speech":
                v = pr.get("openai-tts-voice") or pr.get("voice") or ""
                if v:
                    voice_name = v
                    break

        if not voice_name:
            voice_name = "dafeiyu"

        return {
            "enabled": enabled,
            "voice_name": voice_name,
            "provider_id": active_provider_id
        }
    except Exception:
        return {"enabled": False, "voice_name": "dafeiyu", "provider_id": ""}


def get_meme_manager_data_dir():
    """定位 AstrBot 中 meme_manager 插件的数据目录"""
    instances = detect_astrbot_instances()
    if not instances:
        return ""
    inst_dir = instances[0]["dir"]
    candidates = [
        os.path.join(inst_dir, "core", "data", "plugin_data", "meme_manager"),
        os.path.join(inst_dir, "data", "plugin_data", "meme_manager"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return candidates[0]


DEFAULT_MEME_CATEGORIES = {
    "happy": "在高兴、喜悦、开心、庆祝或赞同时发送",
    "angry": "在生气、吐槽、暴怒、抗议或抓狂时发送",
    "sad": "在难过、委屈、哭泣、失落或无奈时发送",
    "confused": "在疑惑、发问号、发懵、思考或不知如何回答时发送",
    "surprised": "在震惊、惊讶、目瞪口呆或事情出乎意料时发送",
    "shy": "在害羞、脸红、被夸奖或不好意思时发送",
    "break_ice": "在群聊冷场、长时间无人发言或气氛尴尬时打破沉默、活跃气氛",
    "打破冷场": "在群聊冷场、长时间无人发言或气氛尴尬时打破沉默、活跃气氛",
    "greeting": "在打招呼、刚上线、冒泡、挥手或向大家问好时发送",
    "sleep": "在犯困、想睡觉、休息或道晚安时发送",
    "food": "在讨论美食、干饭、想吃东西或饭点时发送",
    "affection": "在表达喜爱、摸摸头、夸奖、撒娇或示好时发送",
    "teasing": "在开玩笑、调侃、看戏、吃瓜或假装正经时发送",
    "reply": "在肯定、拒绝、点头或直接回应对方时发送"
}


def optimize_and_convert_image(raw_bytes, orig_filename, max_dim=800):
    """
    接收任意格式的图像字节（JPG, PNG, GIF, WEBP, BMP, TIFF, HEIC, JFIF 等），
    自动转换为 AstrBot meme 插件原生兼容的标准格式（.png / .jpg / .gif / .webp），
    清洗 EXIF 隐私信息并做尺寸轻量化优化。
    返回 (clean_bytes, output_ext)
    """
    valid_direct_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    try:
        from PIL import Image as PILImage, ImageSequence
        bio = io.BytesIO(raw_bytes)
        with PILImage.open(bio) as img:
            # 判断是否为动图（多帧）
            is_animated = getattr(img, "is_animated", False) and getattr(img, "n_frames", 1) > 1
            if is_animated:
                frames = []
                durations = []
                anim_dim = min(max_dim, 500)
                for frame in ImageSequence.Iterator(img):
                    f = frame.copy().convert("RGBA")
                    if max(f.size) > anim_dim:
                        f.thumbnail((anim_dim, anim_dim), PILImage.Resampling.LANCZOS)
                    frames.append(f)
                    durations.append(frame.info.get("duration", 100))

                out_bio = io.BytesIO()
                p_frames = [f.convert("P", palette=PILImage.Palette.ADAPTIVE) for f in frames]
                p_frames[0].save(
                    out_bio,
                    format="GIF",
                    save_all=True,
                    append_images=p_frames[1:],
                    duration=durations,
                    loop=img.info.get("loop", 0),
                    optimize=True
                )
                return out_bio.getvalue(), ".gif"

            # 静态图处理
            if max(img.size) > max_dim:
                img.thumbnail((max_dim, max_dim), PILImage.Resampling.LANCZOS)

            has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
            out_bio = io.BytesIO()
            if has_alpha:
                converted = img.convert("RGBA")
                converted.save(out_bio, format="PNG", optimize=True)
                return out_bio.getvalue(), ".png"
            else:
                converted = img.convert("RGB")
                converted.save(out_bio, format="JPEG", quality=88, optimize=True)
                return out_bio.getvalue(), ".jpg"
    except Exception:
        ext = os.path.splitext(orig_filename)[1].lower()
        if ext in valid_direct_exts:
            return raw_bytes, ext
        raise ValueError(f"无法识别或转换图片格式: {orig_filename}")


def sanitize_category_name(category_name):
    """规范化分类名称，支持中文、英文字母、数字、下划线及横杠，滤除路径特殊符号"""
    cat = (category_name or "").strip()
    clean = re.sub(r'[\/\\:\*\?"<>\|\.]', '_', cat).strip(" _")
    return clean or "happy"


def list_local_meme_packs():
    """扫描项目根目录下 memes/ 存放的自定义表情包，并标记其在 AstrBot 中的同步状态与各分类详情"""
    memes_root = os.path.join(PACK_ROOT, "memes")
    if not os.path.exists(memes_root):
        os.makedirs(memes_root, exist_ok=True)
        return []

    # 读取 AstrBot registry.json 中已安装的表情包列表
    astr_registered = set()
    data_dir = get_meme_manager_data_dir()
    if data_dir:
        reg_file = os.path.join(data_dir, "registry.json")
        if os.path.exists(reg_file):
            try:
                reg_data = json.load(open(reg_file, encoding="utf-8"))
                for p in reg_data.get("installed_packs", []):
                    if isinstance(p, dict) and p.get("id"):
                        astr_registered.add(p["id"])
            except Exception:
                pass

    packs = []
    valid_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    for item in os.listdir(memes_root):
        item_path = os.path.join(memes_root, item)
        if not os.path.isdir(item_path):
            continue

        pack_id = item
        manifest_file = os.path.join(item_path, "manifest.json")
        name = pack_id
        description = "本地自定义导入表情包"
        mani_categories = {}
        if os.path.exists(manifest_file):
            try:
                mani = json.load(open(manifest_file, encoding="utf-8"))
                name = mani.get("name") or name
                description = mani.get("description") or description
                if isinstance(mani.get("categories"), dict):
                    mani_categories = mani["categories"]
            except Exception:
                pass

        # 扫描图片文件及各分类目录
        images_dir = os.path.join(item_path, "memes")
        scan_dir = images_dir if os.path.exists(images_dir) else item_path
        all_imgs = []
        cat_counts = {}

        if os.path.exists(scan_dir):
            for entry in os.listdir(scan_dir):
                entry_path = os.path.join(scan_dir, entry)
                if os.path.isdir(entry_path):
                    # 分类子目录
                    cat_name = entry
                    c_imgs = []
                    for root, _, files in os.walk(entry_path):
                        for f in sorted(files):
                            ext = os.path.splitext(f)[1].lower()
                            if ext in valid_exts and not f.startswith("."):
                                rel = os.path.relpath(os.path.join(root, f), item_path).replace("\\", "/")
                                c_imgs.append(rel)
                                all_imgs.append(rel)
                    cat_counts[cat_name] = len(c_imgs)
                elif os.path.isfile(entry_path):
                    ext = os.path.splitext(entry)[1].lower()
                    if ext in valid_exts and not entry.startswith("."):
                        rel = os.path.relpath(entry_path, item_path).replace("\\", "/")
                        all_imgs.append(rel)
                        cat_counts["default"] = cat_counts.get("default", 0) + 1

        # 汇总分类信息
        categories_list = []
        all_cat_names = set(cat_counts.keys()) | set(mani_categories.keys())
        for cname in sorted(all_cat_names):
            desc = ""
            if cname in mani_categories:
                meta = mani_categories[cname]
                desc = meta.get("description") if isinstance(meta, dict) else str(meta)
            if not desc:
                desc = DEFAULT_MEME_CATEGORIES.get(cname, f"分类「{cname}」的表情图片")
            categories_list.append({
                "id": cname,
                "name": cname,
                "count": cat_counts.get(cname, 0),
                "description": desc
            })

        # 检查是否已同步至 AstrBot 实例
        is_synced = False
        if data_dir:
            astr_pack_dir = os.path.join(data_dir, "packs", pack_id)
            is_synced = (pack_id in astr_registered) or os.path.exists(astr_pack_dir)

        packs.append({
            "id": pack_id,
            "name": name,
            "description": description,
            "count": len(all_imgs),
            "categories": categories_list,
            "preview_samples": all_imgs[:6],
            "is_synced": is_synced,
            "local_path": item_path
        })

    return packs


def import_and_optimize_meme_pack(pack_id, pack_name, files_map=None, zip_bytes=None, category=None, category_desc=None):
    """
    导入并优化表情包：
    1. 支持指定或自动创建分类（如打破冷场、开心、生气等）
    2. 支持任意格式自动转码与轻量化优化（BMP, TIFF, HEIC, PNG, JPG, GIF 等）
    3. MD5 智能去重
    4. 规范化落盘到项目 memes/<pack_id>/memes/<category>/
    5. 自动生成与更新标准 manifest.json 及 memes_data.json
    6. 自动同步到 AstrBot 的 plugin_data/meme_manager/packs/<pack_id>/ 并注册启用
    """
    safe_id = re.sub(r"[^\w\-_]", "", pack_id.strip()) or f"pack_{uuid.uuid4().hex[:8]}"
    clean_name = pack_name.strip() or safe_id
    clean_cat = sanitize_category_name(category or "happy")
    cat_desc = (category_desc or "").strip() or DEFAULT_MEME_CATEGORIES.get(clean_cat, f"在表达{clean_cat}情绪或语境时发送")

    memes_root = os.path.join(PACK_ROOT, "memes")
    target_dir = os.path.join(memes_root, safe_id)
    target_memes_dir = os.path.join(target_dir, "memes")
    os.makedirs(target_memes_dir, exist_ok=True)

    # 读取已有 manifest（如果是向现有包追加表情）
    manifest_file = os.path.join(target_dir, "manifest.json")
    existing_manifest = {}
    if os.path.exists(manifest_file):
        try:
            existing_manifest = json.load(open(manifest_file, encoding="utf-8"))
        except Exception:
            existing_manifest = {}

    existing_categories = existing_manifest.get("categories", {}) if isinstance(existing_manifest.get("categories"), dict) else {}

    raw_items = []  # [(filename, raw_data, target_category)]
    manifest_meta = {}

    # 1. 如果上传了 ZIP 压缩包，解压提取
    if zip_bytes:
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
                for zinfo in z.infolist():
                    if zinfo.is_dir() or zinfo.filename.startswith("__MACOSX") or "/." in zinfo.filename:
                        continue
                    base_fname = os.path.basename(zinfo.filename)
                    if base_fname == "manifest.json":
                        try:
                            manifest_meta = json.loads(z.read(zinfo).decode("utf-8", "ignore"))
                        except Exception:
                            pass
                        continue

                    # 判断该文件在 zip 中是否位于某个子分类目录内
                    parts = [p for p in zinfo.filename.replace("\\", "/").split("/") if p]
                    item_cat = clean_cat
                    if len(parts) >= 2:
                        # 类似 memes/<cat>/img.png 或 <pack>/<cat>/img.png
                        cand_cat = parts[-2]
                        if cand_cat not in ("memes", "previews", safe_id):
                            item_cat = sanitize_category_name(cand_cat)

                    data = z.read(zinfo)
                    raw_items.append((base_fname, data, item_cat))
        except Exception as e:
            return False, f"解析表情包 ZIP 压缩包失败: {e}"

    if manifest_meta.get("name") and (not pack_name or pack_name.strip() in ("", "我的自定义表情包")):
        clean_name = manifest_meta["name"].strip()
    if manifest_meta.get("categories") and isinstance(manifest_meta["categories"], dict):
        for k, v in manifest_meta["categories"].items():
            existing_categories[k] = v

    # 2. 如果上传了单独的图片文件字典 {filename: bytes}
    if files_map:
        for fname, data in files_map.items():
            raw_items.append((os.path.basename(fname), data, clean_cat))

    if not raw_items:
        return False, "未发现有效的表情图片文件或压缩包内容"

    # 3. 图像格式转换、MD5 智能去重与规范落盘
    # 先收集目标目录中已存在的所有图片哈希，支持断点追加去重
    seen_hashes = set()
    for root, _, files in os.walk(target_memes_dir):
        for f in files:
            p = os.path.join(root, f)
            try:
                with open(p, "rb") as ef:
                    seen_hashes.add(hashlib.md5(ef.read()).hexdigest())
            except Exception:
                pass

    saved_count = 0
    dup_count = 0
    saved_files = []

    for orig_name, data, it_cat in raw_items:
        if not data or len(data) == 0:
            continue

        # 智能转码与优化
        try:
            opt_data, opt_ext = optimize_and_convert_image(data, orig_name)
        except Exception:
            continue

        h = hashlib.md5(opt_data).hexdigest()
        if h in seen_hashes:
            dup_count += 1
            continue
        seen_hashes.add(h)

        # 确保对应分类文件夹存在
        cat_dir = os.path.join(target_memes_dir, it_cat)
        os.makedirs(cat_dir, exist_ok=True)

        clean_base = re.sub(r"[^\w\-_.]", "_", os.path.splitext(orig_name)[0]).strip("_")
        if not clean_base:
            clean_base = f"img_{uuid.uuid4().hex[:6]}"
        save_filename = f"{clean_base}{opt_ext}"
        save_path = os.path.join(cat_dir, save_filename)

        # 避免重名覆盖
        if os.path.exists(save_path):
            save_filename = f"{clean_base}_{uuid.uuid4().hex[:4]}{opt_ext}"
            save_path = os.path.join(cat_dir, save_filename)

        with open(save_path, "wb") as f:
            f.write(opt_data)

        rel_img = f"memes/{it_cat}/{save_filename}"
        saved_files.append(rel_img)
        saved_count += 1

        # 记录分类描述
        if it_cat not in existing_categories:
            desc = cat_desc if it_cat == clean_cat else DEFAULT_MEME_CATEGORIES.get(it_cat, f"分类「{it_cat}」表情")
            existing_categories[it_cat] = {"description": desc}

    # 总是确保本次指定的分类有描述记录
    if clean_cat not in existing_categories:
        existing_categories[clean_cat] = {"description": cat_desc}

    # 4. 重新统计全部有效图片并生成标准 manifest.json 及 memes_data.json
    all_current_images = []
    valid_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    for root, _, files in os.walk(target_memes_dir):
        for f in sorted(files):
            ext = os.path.splitext(f)[1].lower()
            if ext in valid_exts and not f.startswith("."):
                rel = os.path.relpath(os.path.join(root, f), target_dir).replace("\\", "/")
                all_current_images.append(rel)

    total_count = len(all_current_images)
    if total_count == 0:
        return False, "未能成功保存任何有效的表情图片"

    manifest = {
        "schema_version": 1,
        "id": safe_id,
        "name": clean_name,
        "version": existing_manifest.get("version", "1.0.0"),
        "description": f"收录 {total_count} 个表情，包含 {len(existing_categories)} 个分类，已完成智能转码与 MD5 去重优化。",
        "author": existing_manifest.get("author", "用户导入"),
        "tags": ["custom", "imported"],
        "icon": all_current_images[0] if all_current_images else "",
        "previews": all_current_images[:6],
        "total_count": total_count,
        "categories": existing_categories
    }

    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # 写入 memes_data.json 供 AstrBot CategoryManager 使用
    memes_data_path = os.path.join(target_dir, "memes_data.json")
    memes_data_dict = {}
    for c, meta in existing_categories.items():
        if isinstance(meta, dict):
            memes_data_dict[c] = meta.get("description", "请添加描述")
        else:
            memes_data_dict[c] = str(meta)
    with open(memes_data_path, "w", encoding="utf-8") as f:
        json.dump(memes_data_dict, f, ensure_ascii=False, indent=2)

    # 5. 同步写入 AstrBot 实例
    sync_ok, sync_msg = sync_single_pack_to_astrbot(safe_id, clean_name, target_dir)

    msg = f"成功导入表情包「{clean_name}」！归入分类「{clean_cat}」，本次新增 {saved_count} 张表情（自动剔除 {dup_count} 张重复项），全包共 {total_count} 张表情。"
    if sync_ok:
        msg += " 已直接同步并注册至 AstrBot！"
    else:
        msg += f" (提示: 暂未同步到 AstrBot: {sync_msg})"

    return True, {
        "pack_id": safe_id,
        "name": clean_name,
        "category": clean_cat,
        "saved_count": saved_count,
        "total_count": total_count,
        "duplicates_removed": dup_count,
        "message": msg
    }


def sync_single_pack_to_astrbot(pack_id, pack_name, source_pack_dir):
    """将指定的表情包目录同步到 AstrBot 的 plugin_data/meme_manager/packs 并更新 registry.json"""
    data_dir = get_meme_manager_data_dir()
    if not data_dir:
        return False, "未找到 AstrBot 实例目录"

    os.makedirs(data_dir, exist_ok=True)
    astr_packs_dir = os.path.join(data_dir, "packs")
    os.makedirs(astr_packs_dir, exist_ok=True)

    dest_dir = os.path.join(astr_packs_dir, pack_id)
    if os.path.exists(dest_dir):
        shutil.rmtree(dest_dir, ignore_errors=True)
    shutil.copytree(source_pack_dir, dest_dir)

    reg_file = os.path.join(data_dir, "registry.json")
    registry = {"schema_version": 1, "installed_packs": []}
    if os.path.exists(reg_file):
        try:
            registry = json.load(open(reg_file, encoding="utf-8"))
        except Exception:
            registry = {"schema_version": 1, "installed_packs": []}

    installed = registry.setdefault("installed_packs", [])
    found = False
    for p in installed:
        if isinstance(p, dict) and p.get("id") == pack_id:
            p["name"] = pack_name
            p["enabled"] = True
            found = True
            break
    if not found:
        from datetime import datetime, timezone
        installed.append({
            "id": pack_id,
            "name": pack_name,
            "version": "1.0.0",
            "enabled": True,
            "installed_at": datetime.now(timezone.utc).isoformat()
        })

    with open(reg_file, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)

    # 同步激活到 selection_rules.json，确保 AstrBot 对话中能生效
    rules_file = os.path.join(data_dir, "selection_rules.json")
    if os.path.exists(rules_file):
        try:
            rules_data = json.load(open(rules_file, encoding="utf-8"))
            for r in rules_data.get("rules", []):
                pids = r.setdefault("pack_ids", [])
                if pack_id not in pids:
                    pids.append(pack_id)
                if not r.get("pack_id"):
                    r["pack_id"] = pack_id
            with open(rules_file, "w", encoding="utf-8") as f:
                json.dump(rules_data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    return True, "同步成功"


def sync_all_local_memes_to_astrbot():
    """一键将项目 memes/ 下所有表情包全部同步到 AstrBot"""
    memes_root = os.path.join(PACK_ROOT, "memes")
    if not os.path.exists(memes_root):
        return True, "项目表情包目录为空"

    synced_count = 0
    for item in os.listdir(memes_root):
        item_path = os.path.join(memes_root, item)
        if os.path.isdir(item_path):
            name = item
            mf = os.path.join(item_path, "manifest.json")
            if os.path.exists(mf):
                try:
                    name = json.load(open(mf, encoding="utf-8")).get("name") or name
                except Exception:
                    pass
            sync_single_pack_to_astrbot(item, name, item_path)
            synced_count += 1

    return True, f"已成功将 {synced_count} 个本地表情包同步至 AstrBot！"


def delete_local_meme_pack(pack_id):
    """删除本地表情包，并同步从 AstrBot 中解绑/删除"""
    memes_root = os.path.join(PACK_ROOT, "memes")
    target_dir = os.path.join(memes_root, pack_id)
    if os.path.exists(target_dir):
        shutil.rmtree(target_dir, ignore_errors=True)

    data_dir = get_meme_manager_data_dir()
    if data_dir:
        astr_pack_dir = os.path.join(data_dir, "packs", pack_id)
        if os.path.exists(astr_pack_dir):
            shutil.rmtree(astr_pack_dir, ignore_errors=True)
        reg_file = os.path.join(data_dir, "registry.json")
        if os.path.exists(reg_file):
            try:
                reg_data = json.load(open(reg_file, encoding="utf-8"))
                reg_data["installed_packs"] = [
                    p for p in reg_data.get("installed_packs", [])
                    if isinstance(p, dict) and p.get("id") != pack_id
                ]
                with open(reg_file, "w", encoding="utf-8") as f:
                    json.dump(reg_data, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

        rules_file = os.path.join(data_dir, "selection_rules.json")
        if os.path.exists(rules_file):
            try:
                rules_data = json.load(open(rules_file, encoding="utf-8"))
                for r in rules_data.get("rules", []):
                    r["pack_ids"] = [x for x in r.get("pack_ids", []) if x != pack_id]
                    if r.get("pack_id") == pack_id:
                        r["pack_id"] = r["pack_ids"][0] if r["pack_ids"] else ""
                with open(rules_file, "w", encoding="utf-8") as f:
                    json.dump(rules_data, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

    return True, f"表情包 [{pack_id}] 已删除"


def download_and_import_github_meme(repo_url, pack_id=None, pack_name=None):
    """
    从 GitHub 仓库或 ZIP 下载链接拉取表情包，并执行自动化过滤、去重、归档与同步注册
    """
    clean_url = (repo_url or "").strip()
    if not clean_url:
        return False, "GitHub 地址不能为空"

    # 规范化 GitHub 链接
    clean_url = clean_url.rstrip("/")
    if clean_url.endswith(".git"):
        clean_url = clean_url[:-4]

    # 提取仓库名称作为候选 ID 和 Name
    repo_name = ""
    owner = ""
    m = re.search(r"github\.com/([^/]+)/([^/]+)", clean_url)
    if m:
        owner = m.group(1)
        repo_name = m.group(2).split("#")[0].split("?")[0]
        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]

    if not repo_name:
        repo_name = clean_url.split("/")[-1].replace(".zip", "") or "github_pack"

    final_id = (pack_id or "").strip() or re.sub(r"[^\w\-_]", "_", repo_name)
    final_name = (pack_name or "").strip() or repo_name

    candidate_urls = []
    if clean_url.lower().endswith(".zip") or "/archive/" in clean_url or "/releases/download/" in clean_url:
        candidate_urls.append(clean_url)
    elif owner and repo_name:
        candidate_urls.append(f"https://github.com/{owner}/{repo_name}/archive/refs/heads/main.zip")
        candidate_urls.append(f"https://github.com/{owner}/{repo_name}/archive/refs/heads/master.zip")
        candidate_urls.append(f"https://github.com/{owner}/{repo_name}/archive/refs/tags/v1.0.0.zip")
        candidate_urls.append(f"https://github.com/{owner}/{repo_name}/archive/refs/tags/v1.0.zip")
    else:
        candidate_urls.append(clean_url)

    mirrors = ["https://hk.gh-proxy.com/", "https://gh-proxy.com/", "https://mirror.ghproxy.com/", ""]
    zip_bytes = None
    last_err = ""

    for target_url in candidate_urls:
        for m_prefix in mirrors:
            fetch_url = m_prefix + target_url if m_prefix else target_url
            try:
                req = urllib.request.Request(
                    fetch_url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    }
                )
                with urllib.request.urlopen(req, timeout=180) as r:
                    header = r.read(4)
                    if header != b"PK\x03\x04":
                        last_err = "下载的文件不是有效的 ZIP 格式"
                        continue
                    chunks = [header]
                    while True:
                        buf = r.read(1024 * 512)
                        if not buf:
                            break
                        chunks.append(buf)
                    zip_bytes = b"".join(chunks)
                    break
            except Exception as e:
                last_err = str(e)
        if zip_bytes:
            break

    if not zip_bytes:
        return False, f"从 GitHub 下载表情包失败: {last_err}，请检查仓库地址是否正确或网络是否畅通。"

    return import_and_optimize_meme_pack(final_id, final_name, zip_bytes=zip_bytes)

