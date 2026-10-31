"""AstrBot 角色个性化配置中心 Web 服务端。
基于 Python 原生 http.server，零额外依赖。
"""
import glob
import io
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
import zipfile
from http.server import HTTPServer, BaseHTTPRequestHandler

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# 确保 tools 目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入适配器
from web_adapter import (
    PACK_ROOT,
    KNOWN_MEME_PACKS,
    COMMUNITY_INDEX_URL,
    COMMUNITY_INDEX_REPO,
    GH_ACCELERATORS,
    load_pack_json,
    detect_astrbot_instances,
    test_astrbot_url,
    test_breeze_url,
    detect_napcat,
    sync_napcat_and_astrbot,
    scan_active_astrbot_url,
    check_breeze_environment,
    start_breeze_service,
    check_plugins_completeness,
    save_persona_offline,
    find_ffmpeg_path,
    AstrBotClient,
    BreezeClient,
    get_active_persona_info,
    get_active_voice_info,
    get_meme_manager_data_dir,
    list_local_meme_packs,
    import_and_optimize_meme_pack,
    sync_all_local_memes_to_astrbot,
    delete_local_meme_pack,
)

PORT = 18989

# 全局运行态缓存
STATE = {
    "astrbot_url": "http://127.0.0.1:6185",
    "owner_qq": "",
    "astrbot_client": None,
    "breeze_client": BreezeClient("http://127.0.0.1:8137"),
    "voice_enabled": False,
}


def auto_detect_astrbot():
    if not (STATE.get("astrbot_url") and test_astrbot_url(STATE["astrbot_url"])):
        active_url = scan_active_astrbot_url()
        STATE["astrbot_url"] = active_url

    # 自动保障 client 实例与免密 token 可用
    if not STATE.get("astrbot_client") or STATE["astrbot_client"].root != STATE["astrbot_url"]:
        STATE["astrbot_client"] = AstrBotClient(STATE["astrbot_url"])
    elif not STATE["astrbot_client"].token:
        STATE["astrbot_client"].try_auto_token()

    return detect_astrbot_instances()


def convert_to_wav(audio_bytes, orig_filename):
    ext = os.path.splitext(orig_filename)[1].lower()
    if ext == ".wav":
        return audio_bytes, "audio.wav"
    ff = find_ffmpeg_path()
    if not ff:
        return audio_bytes, orig_filename
    temp_in = os.path.join(tempfile.gettempdir(), f"temp_in_{int(time.time())}{ext}")
    temp_out = os.path.join(tempfile.gettempdir(), f"temp_out_{int(time.time())}.wav")
    try:
        with open(temp_in, "wb") as f:
            f.write(audio_bytes)
        subprocess.run([ff, "-y", "-loglevel", "error", "-i", temp_in, "-ac", "1", "-ar", "24000", temp_out], timeout=30)
        if os.path.exists(temp_out):
            with open(temp_out, "rb") as f:
                data = f.read()
            return data, "audio.wav"
    except Exception:
        pass
    finally:
        for p in (temp_in, temp_out):
            if os.path.exists(p):
                try: os.remove(p)
                except Exception: pass
    return audio_bytes, orig_filename


def parse_multipart(rfile, headers):
    ctype = headers.get("Content-Type", "")
    length = int(headers.get("Content-Length", 0))
    raw_data = rfile.read(length)
    
    boundary = ctype.split("boundary=")[1].strip().strip('"').encode("utf-8")
    boundary_marker = b"--" + boundary
    parts = raw_data.split(boundary_marker)
    fields = {}
    files = {}
    all_files = []
    
    for part in parts:
        if not part or part.strip() in (b"", b"--"):
            continue
        header_part, _, body = part.partition(b"\r\n\r\n")
        body = body.rstrip(b"\r\n")
        header_text = header_part.decode("utf-8", "ignore")
        
        name_match = re.search(r'name="([^"]+)"', header_text)
        if not name_match:
            continue
        field_name = name_match.group(1)
        filename_match = re.search(r'filename="([^"]+)"', header_text)
        if filename_match:
            item = {
                "field": field_name,
                "filename": filename_match.group(1),
                "data": body
            }
            files[field_name] = item
            all_files.append(item)
        else:
            fields[field_name] = body.decode("utf-8", "replace")
            
    return fields, files, all_files


class ConfigRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        sys.stderr.write(f"[{self.log_date_time_string()}] {format % args}\n")

    def send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_static(self, rel_path):
        full_path = os.path.join(PACK_ROOT, "tools", "web_static", rel_path)
        if not os.path.exists(full_path) or os.path.isdir(full_path):
            self.send_error(404, "File not found")
            return
        mime, _ = mimetypes.guess_type(full_path)
        mime = mime or "application/octet-stream"
        with open(full_path, "rb") as f:
            content = f.read()
        self.send_response(200)
        self.send_header("Content-Type", f"{mime}; charset=utf-8" if "text" in mime or "html" in mime else mime)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            self.serve_static("index.html")
            return

        if path == "/api/status":
            instances = auto_detect_astrbot()
            a_ok = test_astrbot_url(STATE["astrbot_url"])
            b_ok = test_breeze_url()
            napcat_info = detect_napcat()
            p_info = get_active_persona_info()
            v_info = get_active_voice_info()
            self.send_json({
                "astrbot_url": STATE["astrbot_url"],
                "astrbot_online": a_ok,
                "breeze_online": b_ok,
                "napcat": napcat_info,
                "owner_qq": p_info.get("owner_qq") or STATE.get("owner_qq", ""),
                "active_persona": p_info.get("persona_id", "大肥鱼"),
                "active_voice": v_info.get("voice_name", "dafeiyu"),
                "voice_enabled": STATE.get("voice_enabled", False) or v_info.get("enabled", False),
                "discovered_instances": instances,
                "has_token": bool(STATE["astrbot_client"] and STATE["astrbot_client"].token)
            })
            return

        if path == "/api/persona/current":
            p_info = get_active_persona_info()
            self.send_json({
                "ok": True,
                "persona_id": p_info.get("persona_id", "大肥鱼"),
                "prompt": p_info.get("prompt", ""),
                "owner_qq": p_info.get("owner_qq", ""),
                "is_custom": p_info.get("is_custom", False),
                "data": p_info
            })
            return

        if path == "/api/persona/get":
            qs = urllib.parse.parse_qs(parsed.query)
            pid = qs.get("persona_id", ["大肥鱼"])[0]
            client = STATE["astrbot_client"]
            if not client or not client.token:
                self.send_json({"ok": False, "message": "尚未登录 AstrBot"}, 401)
                return
            r = client.call("GET", f"/personas/{urllib.parse.quote(pid, safe='')}")
            if client.is_ok(r):
                prompt = r.get("data", {}).get("system_prompt", "")
                self.send_json({"ok": True, "prompt": prompt})
            else:
                self.send_json({"ok": False, "message": r.get("message") or "获取失败"})
            return

        if path == "/api/memes/local":
            packs = list_local_meme_packs()
            self.send_json({"ok": True, "packs": packs})
            return

        if path == "/api/memes/image":
            qs = urllib.parse.parse_qs(parsed.query)
            pack_id = qs.get("pack_id", [""])[0]
            img_rel = qs.get("img", [""])[0].replace("\\", "/")
            if not pack_id or not img_rel or ".." in pack_id or ".." in img_rel:
                self.send_json({"ok": False, "message": "非法路径"}, 400)
                return
            full_img_path = os.path.join(PACK_ROOT, "memes", pack_id, img_rel)
            if not os.path.exists(full_img_path):
                self.send_json({"ok": False, "message": "图片不存在"}, 404)
                return
            ext = os.path.splitext(full_img_path)[1].lower()
            mime = "image/png"
            if ext in (".jpg", ".jpeg"): mime = "image/jpeg"
            elif ext == ".gif": mime = "image/gif"
            elif ext == ".webp": mime = "image/webp"
            try:
                with open(full_img_path, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(content)
            except Exception as e:
                self.send_json({"ok": False, "message": str(e)}, 500)
            return

        if path == "/api/memes":
            client = STATE["astrbot_client"]
            installed_ids = set()
            data_dir = get_meme_manager_data_dir()
            local_path = os.path.join(data_dir, "packs") if data_dir else os.path.join(PACK_ROOT, "memes")

            if client and client.token:
                ext = "/plugins/extensions/meme_manager"
                r = client.call("GET", f"{ext}/packs")
                packs = (r.get("data") if isinstance(r.get("data"), dict) else r).get("packs", [])
                installed_ids = {str(p.get("pack_id") or p.get("id")) for p in packs if isinstance(p, dict)}
                
                # 读取规则判定默认项
                r_rules = client.call("GET", f"{ext}/settings/rules")
                rules = (r_rules.get("data") if isinstance(r_rules.get("data"), dict) else r_rules).get("rules", [])
                default_rule = next((x for x in reversed(rules) if x.get("scope") == "default"), {})
                def_ids = default_rule.get("pack_ids") or ([default_rule["pack_id"]] if default_rule.get("pack_id") else [])
            else:
                def_ids = []

            out_packs = []
            for kp in KNOWN_MEME_PACKS:
                pid = kp["id"]
                out_packs.append({
                    **kp,
                    "installed": pid in installed_ids,
                    "is_default": pid in def_ids
                })

            self.send_json({
                "ok": True,
                "packs": out_packs,
                "index_repo": COMMUNITY_INDEX_REPO,
                "index_url": COMMUNITY_INDEX_URL,
                "local_path": local_path
            })
            return

        if path == "/api/voice/list":
            breeze = STATE["breeze_client"]
            raw_voices = breeze.get_voices()
            voices_list = []
            if isinstance(raw_voices, list):
                for v in raw_voices:
                    if isinstance(v, dict):
                        voices_list.append({
                            "id": v.get("id") or v.get("name"),
                            "name": v.get("name") or v.get("id"),
                            "description": v.get("description", ""),
                            "saved": v.get("saved", True)
                        })

            v_info = get_active_voice_info()
            current_tts_voice = v_info.get("voice_name") or "dafeiyu"
            client = STATE["astrbot_client"]
            if client and client.token:
                cfg = client.get_default_config()
                if cfg:
                    tts_settings = cfg.get("provider_tts_settings", {})
                    current_pid = tts_settings.get("provider_id", "")
                    if current_pid:
                        p_conf = client.call("GET", f"/providers/{urllib.parse.quote(current_pid, safe='')}")
                        if client.is_ok(p_conf):
                            data = (p_conf.get("data") or {}).get("provider", p_conf.get("data", {}))
                            current_tts_voice = data.get("openai-tts-voice", current_tts_voice)

            self.send_json({
                "ok": True,
                "voices": voices_list,
                "current_active_voice": current_tts_voice,
                "voice_enabled": STATE.get("voice_enabled", False) or v_info.get("enabled", False),
                "ffmpeg_available": bool(find_ffmpeg_path())
            })
            return

        if path == "/api/voice/speak_audio":
            qs = urllib.parse.parse_qs(parsed.query)
            voice_name = qs.get("voice_name", ["dafeiyu"])[0]
            text = qs.get("text", ["你好呀，这是我的声音试听，听起来怎么样？"])[0]
            breeze = STATE["breeze_client"]
            ok, wav_data = breeze.speak(voice_name, text)
            if ok:
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(wav_data)))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(wav_data)
            else:
                self.send_json({"ok": False, "message": str(wav_data)}, 500)
            return

        # 检查基础插件完整性
        if path == "/api/plugins/check":
            client = STATE.get("astrbot_client")
            comp = check_plugins_completeness(client)
            self.send_json({"ok": True, "data": comp})
            return

        # 单一权威参考案例：大肥鱼
        if path == "/api/persona/reference":
            ref_path = os.path.join(PACK_ROOT, "persona", "大肥鱼.md")
            content = ""
            if os.path.exists(ref_path):
                with open(ref_path, "r", encoding="utf-8") as f:
                    content = f.read()
            self.send_json({
                "ok": True,
                "persona_id": "大肥鱼",
                "name": "大肥鱼 (傲娇软萌吃货AI少女)",
                "prompt": content
            })
            return

        # 语音模块前置条件环境自检
        if path == "/api/voice/env":
            info = check_breeze_environment()
            v_info = get_active_voice_info()
            info["voice_enabled"] = STATE.get("voice_enabled", False) or v_info.get("enabled", False)
            info["active_voice"] = v_info.get("voice_name", "dafeiyu")
            self.send_json({"ok": True, "data": info})
            return

        if path == "/api/plugins/status":
            client = STATE.get("astrbot_client")
            comp = check_plugins_completeness(client)
            status_map = {k: v["installed"] for k, v in comp["plugins"].items()}
            self.send_json({
                "ok": True,
                "status": status_map,
                "all_ready": comp["is_complete"]
            })
            return

        self.send_error(404, "Not Found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # 1. 登录
        if path == "/api/login":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            base_url = (body.get("base_url") or STATE.get("astrbot_url") or "http://127.0.0.1:6185").rstrip("/")
            username = body.get("username", "astrbot")
            password = body.get("password", "")
            owner_qq = body.get("owner_qq", "")

            # 先快速探测 AstrBot 是否已经启动
            if not test_astrbot_url(base_url):
                # 重新动态探测一次看是否动态分配了新端口
                active_url = scan_active_astrbot_url()
                if test_astrbot_url(active_url):
                    base_url = active_url
                    STATE["astrbot_url"] = active_url
                else:
                    self.send_json({
                        "ok": False,
                        "message": f"无法连接到 AstrBot 服务 ({base_url})。请确认已在电脑上手动启动 AstrBot 实例。"
                    }, 400)
                    return

            client = AstrBotClient(base_url)
            ok, msg = client.login(username, password)
            if ok:
                STATE["astrbot_url"] = base_url
                STATE["astrbot_client"] = client
                STATE["owner_qq"] = owner_qq
                self.send_json({"ok": True, "message": "登录成功"})
            else:
                self.send_json({"ok": False, "message": msg}, 400)
            return

        if path == "/api/astrbot/set_url":
            body = self.read_json()
            new_url = (body.get("url") or "").strip().rstrip("/")
            if not new_url:
                self.send_json({"ok": False, "message": "地址不能为空"}, 400)
                return
            if not test_astrbot_url(new_url):
                self.send_json({"ok": False, "message": f"连接失败：无法访问 {new_url}，请确认 AstrBot 已启动且端口正确"}, 400)
                return
            STATE["astrbot_url"] = new_url
            self.send_json({"ok": True, "message": f"已成功切换 AstrBot 地址为 {new_url}", "url": new_url})
            return

        # 2. 部署基础底座插件（已就绪则跳过，未配置则一键补齐）
        if path == "/api/setup/base":
            client = STATE["astrbot_client"]
            if not client or not client.token:
                self.send_json({"ok": False, "message": "请先在电脑上手动启动 AstrBot，并在上方验证登录"}, 401)
                return

            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            force = body.get("force", False)

            # 先自检当前是否已配置完成
            comp = check_plugins_completeness(client)
            if not force and comp["is_complete"]:
                self.send_json({
                    "ok": True,
                    "already_complete": True,
                    "message": "检测到所有 8 个基础插件及配置已完整就绪，无需重复配置！",
                    "logs": ["✔ 全部基础插件（群聊插话、长期记忆、表情包底座、主动聊天、QQ空间/资料、防串台规则等）均已就绪，无需重新配置。"]
                })
                return

            pack = load_pack_json()
            logs = []
            try:
                # 获取已安装插件
                installed_plugins = client.get_installed_plugins()
                installed_names = {p.get("name") for p in installed_plugins if isinstance(p, dict)}
                
                # 安装市场插件
                for p in pack.get("plugins", []):
                    name = p["name"]
                    if name in installed_names:
                        logs.append(f"✔ 基础插件 [{name}]: 已经存在，跳过安装")
                    else:
                        logs.append(f"▶ 正在安装插件 [{name}] ({p.get('what','')})...")
                        r = client.call("POST", "/plugins/install/github",
                                        {"install_method": "market", "market_plugin_id": p["market_id"]}, timeout=600)
                        if client.is_ok(r):
                            logs.append(f"✔ 插件 [{name}] 安装成功")
                        else:
                            logs.append(f"✘ 插件 [{name}] 安装异常: {r.get('message')}")

                # 安装本地自带插件 (plugins/)
                for plugin_dir in glob.glob(os.path.join(PACK_ROOT, "plugins", "*")):
                    if os.path.isdir(plugin_dir) and os.path.exists(os.path.join(plugin_dir, "metadata.yaml")):
                        bname = os.path.basename(plugin_dir)
                        if bname in installed_names:
                            logs.append(f"✔ 自带插件 [{bname}]: 已安装")
                        else:
                            logs.append(f"▶ 正在从配置包安装自带插件 [{bname}]...")
                            buf = io.BytesIO()
                            import zipfile
                            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                                for dirpath, _, filenames in os.walk(plugin_dir):
                                    for f in filenames:
                                        if f.endswith(".pyc") or "__pycache__" in dirpath: continue
                                        full = os.path.join(dirpath, f)
                                        zf.write(full, os.path.join(bname, os.path.relpath(full, plugin_dir)))
                            payload = buf.getvalue()
                            boundary = uuid.uuid4().hex
                            head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{bname}.zip\"\r\n"
                                    "Content-Type: application/zip\r\n\r\n").encode("utf-8")
                            tail = f"\r\n--{boundary}--\r\n".encode()
                            r = client.call("POST", "/plugins/install/upload", raw_body=head + payload + tail,
                                            content_type=f"multipart/form-data; boundary={boundary}", timeout=600)
                            logs.append(f"✔ 自带插件 [{bname}]: {'成功' if client.is_ok(r) else '失败 ' + str(r.get('message'))}")

                # 全局基础配置注入
                cfg = client.get_default_config()
                if cfg:
                    # 检测并确保 OneBot v11 (NapCatQQ) 平台已接入
                    platforms = cfg.setdefault("platform", [])
                    aiocq = next((p for p in platforms if p.get("type") == "aiocqhttp"), None)
                    nap_info = detect_napcat()
                    if not aiocq:
                        aiocq = {
                            "id": "qq_bot",
                            "type": "aiocqhttp",
                            "enable": True,
                            "ws_reverse_host": "127.0.0.1",
                            "ws_reverse_port": 6199,
                            "ws_reverse_token": nap_info.get("ws_token") or "15241356766"
                        }
                        platforms.append(aiocq)
                        logs.append(f"✔ 自动为 AstrBot 接入 OneBot v11 (NapCatQQ) 平台配置 (端口: 6199)")
                    else:
                        logs.append(f"✔ 平台 OneBot v11 [{aiocq.get('id','aiocqhttp')}]: 已接入 (反向端口: {aiocq.get('ws_reverse_port', 6199)})")

                    platform_id = aiocq.get("id") or "qq_bot"
                    owner = STATE.get("owner_qq") or ""
                    session = f"{platform_id}:FriendMessage:{owner}"
                    chat_id = cfg.get("agent_runner", {}).get("config", {}).get("model", {}).get("provider_id", "")
                    if not chat_id:
                        chats = [p for p in cfg.get("provider", []) if p.get("provider_type", "chat_completion") == "chat_completion" and p.get("enable", True)]
                        chat_id = chats[0]["id"] if chats else ""
                    ctx = {"主人会话": session, "对话模型": chat_id, "唱歌后端": "doubao"}

                    # 分段回复与系统规则
                    for k, v in pack.get("base", {}).items():
                        keys = k.split(".")
                        curr = cfg
                        for step_k in keys[:-1]:
                            if not isinstance(curr.get(step_k), dict): curr[step_k] = {}
                            curr = curr[step_k]
                        val = v
                        if isinstance(val, str):
                            for ck, cv in ctx.items():
                                val = val.replace("{" + ck + "}", cv)
                        curr[keys[-1]] = val
                    
                    # 主人 QQ 权限注入与白名单
                    if owner:
                        admins = cfg.setdefault("admins_id", [])
                        if owner not in admins: admins.append(owner)
                        ps = cfg.setdefault("platform_settings", {})
                        if ps.get("enable_id_white_list"):
                            wl = ps.setdefault("id_whitelist", [])
                            if session not in wl and owner not in wl:
                                wl.append(session)
                    
                    client.update_default_config(cfg)
                    logs.append("✔ 全局设置（分段回复、管理员权限、白名单）已成功注入")

                    # 为已安装插件写入定制参数 (替换 {主人会话} 等)
                    def fill_val(val):
                        if isinstance(val, str):
                            for ck, cv in ctx.items(): val = val.replace("{" + ck + "}", cv)
                            return val
                        if isinstance(val, list): return [fill_val(x) for x in val]
                        if isinstance(val, dict): return {k: fill_val(x) for k, x in val.items()}
                        return val

                    for p in pack.get("plugins", []):
                        pname = p["name"]
                        if pname in installed_names and p.get("config"):
                            r_c = client.call("GET", f"/plugins/config?plugin_id={urllib.parse.quote(pname)}")
                            p_conf = (r_c.get("data") or {}).get("config") if isinstance(r_c.get("data"), dict) else None
                            if isinstance(p_conf, dict):
                                for ck, cv in p["config"].items():
                                    keys = ck.split(".")
                                    curr = p_conf
                                    for step_k in keys[:-1]:
                                        if not isinstance(curr.get(step_k), dict): curr[step_k] = {}
                                        curr = curr[step_k]
                                    curr[keys[-1]] = fill_val(cv)
                                client.call("PUT", "/plugins/config", {"plugin_id": pname, "config": p_conf})
                                client.reload_plugin(pname)
                    logs.append("✔ 插件联动参数（主动聊天主人会话、长期记忆对话模型绑定）已更新并重载生效")

                # 工具权限注入
                for tool, perm in pack.get("tool_permissions", {}).items():
                    client.call("PATCH", f"/tools/{urllib.parse.quote(tool, safe='')}/permission", {"permission": perm})
                logs.append("✔ 工具安全权限（只听主人）已更新")

                self.send_json({"ok": True, "logs": logs})
            except Exception as e:
                logs.append(f"❌ 部署发生异常: {e}")
                self.send_json({"ok": False, "message": str(e), "logs": logs}, 500)
            return

        # 3. 保存性格到 AstrBot
        if path == "/api/persona/save":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            pid = body.get("persona_id", "大肥鱼")
            prompt = body.get("prompt", "")
            owner_qq = body.get("owner_qq") or STATE.get("owner_qq") or ""
            if owner_qq:
                STATE["owner_qq"] = owner_qq
            prompt_final = prompt.replace("{OWNER_QQ}", owner_qq)

            client = STATE.get("astrbot_client")
            online_saved = False
            if client and client.token:
                qid = urllib.parse.quote(pid, safe="")
                cur = client.call("GET", f"/personas/{qid}")
                if client.is_ok(cur) and isinstance(cur.get("data"), dict) and cur["data"].get("persona_id") == pid:
                    req_data = {k: v for k, v in cur["data"].items() if k in ("begin_dialogs", "skills", "folder_id", "sort_order", "custom_error_message")}
                    req_data.update({"system_prompt": prompt_final, "tools": None})
                    r = client.call("PUT", f"/personas/{qid}", req_data)
                else:
                    r = client.call("POST", "/personas", {"persona_id": pid, "system_prompt": prompt_final, "begin_dialogs": [], "tools": None})

                if client.is_ok(r):
                    online_saved = True
                    cfg = client.get_default_config()
                    if cfg:
                        if "agent_runner" not in cfg: cfg["agent_runner"] = {}
                        if "config" not in cfg["agent_runner"]: cfg["agent_runner"]["config"] = {}
                        if "persona" not in cfg["agent_runner"]["config"]: cfg["agent_runner"]["config"]["persona"] = {}
                        cfg["agent_runner"]["config"]["persona"]["persona_id"] = pid
                        client.update_default_config(cfg)

            # 同时直接落盘更新本地数据库与配置文件，离线与在线均 100% 成功
            offline_ok, offline_msg = save_persona_offline(pid, prompt_final)

            if online_saved or offline_ok:
                self.send_json({"ok": True, "message": f"性格「{pid}」已成功保存并导入！"})
            else:
                self.send_json({"ok": False, "message": offline_msg}, 500)
            return

        # 4. Breeze 声音克隆
        if path == "/api/voice/clone":
            fields, files = parse_multipart(self.rfile, self.headers)
            file_item = files.get("audio")
            ref_text = fields.get("ref_text", "").strip()
            voice_name = fields.get("voice_name", "dafeiyu").strip()

            if not file_item or not file_item.get("data"):
                self.send_json({"ok": False, "message": "未接收到音频文件"}, 400)
                return
            if not ref_text:
                self.send_json({"ok": False, "message": "参考文本不能为空"}, 400)
                return

            raw_bytes = file_item["data"]
            processed_bytes, out_name = convert_to_wav(raw_bytes, file_item["filename"])

            breeze = STATE["breeze_client"]
            ok, msg = breeze.clone_voice(voice_name, processed_bytes, out_name, ref_text, f"克隆:{voice_name}")
            if ok:
                self.send_json({"ok": True, "message": f"音色 [{voice_name}] 克隆成功！"})
            else:
                self.send_json({"ok": False, "message": f"Breeze 报错: {msg}"}, 500)
            return

        # 5. 试听生成
        if path == "/api/voice/preview":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            voice_name = body.get("voice_name", "dafeiyu")
            text = body.get("text", "在呢在呢，这么晚还不睡，是不是又在偷偷吃夜宵？")

            breeze = STATE["breeze_client"]
            ok, wav_data = breeze.speak(voice_name, text)
            if ok:
                b64 = base64.b64encode(wav_data).decode("ascii")
                self.send_json({"ok": True, "audio_base64": b64, "voice_name": voice_name})
            else:
                self.send_json({"ok": False, "message": str(wav_data)}, 500)
            return

        # 6. 绑定 Breeze 音色到 AstrBot
        if path == "/api/voice/apply":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            voice_name = body.get("voice_name", "dafeiyu")

            tts_provider_id = f"Breeze语音-{voice_name}"
            conf = {
                "id": tts_provider_id,
                "type": "openai_tts_api",
                "provider": "openai",
                "provider_type": "text_to_speech",
                "enable": True,
                "api_key": "unused",
                "api_base": "http://127.0.0.1:8137/v1",
                "model": "tts-1",
                "openai-tts-voice": voice_name,
                "timeout": 180,
                "proxy": ""
            }

            client = STATE.get("astrbot_client")
            if client and client.token:
                try:
                    pid = urllib.parse.quote(tts_provider_id, safe="")
                    cur = client.call("GET", f"/providers/{pid}")
                    if client.is_ok(cur) and isinstance(cur.get("data"), dict) and cur["data"].get("id") == tts_provider_id:
                        merged = {**cur["data"], **conf}
                        client.call("PUT", f"/providers/{pid}", {"config": merged})
                    else:
                        client.call("POST", "/providers", {"config": conf})

                    cfg = client.get_default_config()
                    if cfg:
                        tts = cfg.setdefault("provider_tts_settings", {})
                        tts.update({
                            "enable": True,
                            "provider_id": tts_provider_id,
                            "trigger_probability": 0.33
                        })
                        client.update_default_config(cfg)
                except Exception:
                    pass

            # 无论在线与否，直接落盘更新 cmd_config.json 保证持久生效
            instances = detect_astrbot_instances()
            if instances and instances[0].get("dir"):
                cand = os.path.join(instances[0]["dir"], "data", "cmd_config.json")
                if not os.path.exists(cand):
                    cand = os.path.join(instances[0]["dir"], "core", "data", "cmd_config.json")
                if os.path.exists(cand):
                    try:
                        cfg_disk = json.load(open(cand, encoding="utf-8-sig"))
                        providers = cfg_disk.setdefault("provider", [])
                        exist_p = next((p for p in providers if p.get("id") == tts_provider_id or p.get("provider_type") == "text_to_speech"), None)
                        if exist_p:
                            exist_p.update(conf)
                        else:
                            providers.append(conf)
                        tts_s = cfg_disk.setdefault("provider_tts_settings", {})
                        tts_s.update({
                            "enable": True,
                            "provider_id": tts_provider_id,
                            "trigger_probability": 0.33
                        })
                        with open(cand, "w", encoding="utf-8") as f:
                            json.dump(cfg_disk, f, ensure_ascii=False, indent=2)
                    except Exception:
                        pass

            STATE["voice_enabled"] = True
            self.send_json({"ok": True, "message": f"已成功将音色 [{voice_name}] 设为 AstrBot 默认语音！"})
            return

        # 6.01 导入与优化自定义表情包
        if path == "/api/memes/upload":
            fields, files, all_files = parse_multipart(self.rfile, self.headers)
            pack_id = (fields.get("pack_id") or "").strip()
            pack_name = (fields.get("pack_name") or "").strip()

            zip_item = next((item for item in all_files if item["filename"].lower().endswith(".zip")), None)
            zip_bytes = zip_item["data"] if zip_item else None

            valid_exts = (".jpg", ".jpeg", ".png", ".gif", ".webp")
            files_map = {item["filename"]: item["data"] for item in all_files if item["filename"].lower().endswith(valid_exts)}

            if not zip_bytes and not files_map:
                self.send_json({"ok": False, "message": "请上传表情图片文件（支持 .jpg, .png, .gif, .webp）或 .zip 压缩包"}, 400)
                return

            if not pack_name and zip_item:
                pack_name = os.path.splitext(zip_item["filename"])[0]

            if not pack_id and pack_name:
                pack_id = pack_name

            if not pack_name: pack_name = "自定义表情包"
            if not pack_id: pack_id = f"custom_meme_{uuid.uuid4().hex[:6]}"

            ok, res = import_and_optimize_meme_pack(pack_id, pack_name, files_map=files_map, zip_bytes=zip_bytes)
            if ok:
                self.send_json({"ok": True, "data": res})
            else:
                self.send_json({"ok": False, "message": str(res)}, 400)
            return

        # 6.02 一键同步全部本地表情包到 AstrBot
        if path == "/api/memes/sync_all":
            ok, msg = sync_all_local_memes_to_astrbot()
            self.send_json({"ok": ok, "message": msg})
            return

        # 6.03 删除本地表情包
        if path == "/api/memes/delete":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            pack_id = (body.get("pack_id") or "").strip()
            if not pack_id:
                self.send_json({"ok": False, "message": "表情包 ID 不能为空"}, 400)
                return
            ok, msg = delete_local_meme_pack(pack_id)
            self.send_json({"ok": ok, "message": msg})
            return

        # 6.1 开启/关闭语音克隆模块
        if path == "/api/voice/toggle":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            enabled = bool(body.get("enabled", False))
            STATE["voice_enabled"] = enabled

            # 如果用户关闭语音模块，且 AstrBot 在线，则关闭 AstrBot TTS 发音
            if not enabled:
                client = STATE.get("astrbot_client")
                if client and client.token:
                    cfg = client.get_default_config()
                    if cfg and "provider_tts_settings" in cfg:
                        cfg["provider_tts_settings"]["enable"] = False
                        client.update_default_config(cfg)

            self.send_json({"ok": True, "voice_enabled": enabled, "message": "已更新语音模块状态"})
            return

        # 6.2 一键启动 Breeze 语音引擎
        if path == "/api/voice/start":
            ok, msg = start_breeze_service()
            self.send_json({"ok": ok, "message": msg}, 200 if ok else 500)
            return

        # 7. 单独下载安装表情包
        if path == "/api/memes/install":
            client = STATE["astrbot_client"]
            if not client or not client.token:
                self.send_json({"ok": False, "message": "尚未登录 AstrBot"}, 401)
                return
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            pack_id = body.get("pack_id")

            logs = [f"准备从 GitHub 社区源安装表情包 [{pack_id}]..."]
            ext = "/plugins/extensions/meme_manager"
            client.call("POST", f"{ext}/community/index/fetch", {}, timeout=60)
            
            # 循环尝试加速代理
            ok = False
            for accel in GH_ACCELERATORS:
                acc_label = accel or "GitHub 直连"
                logs.append(f"尝试使用加速站下载: {acc_label}")
                # 改插件加速地址
                r_cfg = client.call("GET", "/plugins/config?plugin_id=meme_manager")
                p_conf = (r_cfg.get("data") or {}).get("config") if isinstance(r_cfg.get("data"), dict) else {}
                if isinstance(p_conf, dict):
                    if "community" not in p_conf: p_conf["community"] = {}
                    p_conf["community"]["github_accelerator_url"] = accel
                    client.call("PUT", "/plugins/config", {"plugin_id": "meme_manager", "config": p_conf})
                
                r_inst = client.call("POST", f"{ext}/community/install", {"pack_id": pack_id, "set_as_default": False}, timeout=900)
                if client.is_ok(r_inst):
                    ok = True
                    logs.append(f"✔ 表情包 [{pack_id}] 下载解压完成！")
                    break
                else:
                    logs.append(f"  当前加速站未响应，继续尝试下一个加速通道...")

            if ok:
                self.send_json({"ok": True, "logs": logs})
            else:
                self.send_json({"ok": False, "message": "所有加速地址均未成功，请稍后再试或检查网络", "logs": logs}, 500)
            return

        # 8. 单独设置默认表情包
        if path == "/api/memes/enable":
            client = STATE["astrbot_client"]
            if not client or not client.token:
                self.send_json({"ok": False, "message": "尚未登录 AstrBot"}, 401)
                return
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            pack_id = body.get("pack_id")

            ext = "/plugins/extensions/meme_manager"
            r_rules = client.call("GET", f"{ext}/settings/rules")
            rules = (r_rules.get("data") if isinstance(r_rules.get("data"), dict) else r_rules).get("rules", [])
            keep = [x for x in rules if x.get("scope") != "default"]
            new_rule = {"id": "default", "scope": "default", "pack_id": pack_id, "pack_ids": [pack_id]}
            r = client.call("POST", f"{ext}/settings/rules", {"rules": keep + [new_rule]})
            if client.is_ok(r):
                self.send_json({"ok": True, "message": f"已将 [{pack_id}] 设为默认表情包"})
            else:
                self.send_json({"ok": False, "message": r.get("message") or "设置失败"}, 500)
            return

        # 9. 打开本地文件夹
        if path == "/api/open_folder":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            folder_type = body.get("type", "memes")
            
            instances = detect_astrbot_instances()
            target_path = ""
            if folder_type == "memes":
                if instances and instances[0].get("dir"):
                    target_path = os.path.join(instances[0]["dir"], "data", "plugins", "astrbot_plugin_meme_manager", "packs")
                else:
                    target_path = os.path.join(PACK_ROOT, "voice")
            elif folder_type == "napcat":
                nap_info = detect_napcat()
                target_path = nap_info.get("path") or "D:\\NapCat.Shell.Windows.OneKey"
            elif folder_type == "persona":
                target_path = os.path.join(PACK_ROOT, "persona")
            else:
                target_path = PACK_ROOT

            if not os.path.exists(target_path):
                try: os.makedirs(target_path, exist_ok=True)
                except Exception: pass

            if os.name == "nt" and os.path.exists(target_path):
                os.startfile(target_path)
            self.send_json({"ok": True, "path": target_path})
            return

        # 10. 导出性格到本地文件
        if path == "/api/persona/export":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            name = body.get("name", "自定义角色").strip()
            prompt = body.get("prompt", "")
            save_path = os.path.join(PACK_ROOT, "persona", f"{name}.md")
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(prompt)
            self.send_json({"ok": True, "message": f"已成功保存到本地: persona/{name}.md"})
            return

        # 11. 一键对齐与修复 NapCat 与 AstrBot 链路
        if path == "/api/napcat/sync":
            client = STATE.get("astrbot_client")
            ok, msg = sync_napcat_and_astrbot(client)
            if ok:
                self.send_json({"ok": True, "message": msg})
            else:
                self.send_json({"ok": False, "message": msg}, 500)
            return

        self.send_error(404, "Not Found")


def run_server():
    server = HTTPServer(("0.0.0.0", PORT), ConfigRequestHandler)
    print("\n=======================================================")
    print("AstrBot 角色个性化配置中心已在后台启动！")
    print(f"本地访问地址: http://127.0.0.1:{PORT}")
    print("=======================================================\n")
    
    # 尝试在 Windows 下自动打开浏览器
    try:
        import webbrowser
        threading.Thread(target=lambda: (time.sleep(1), webbrowser.open(f"http://127.0.0.1:{PORT}")), daemon=True).start()
    except Exception:
        pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止。")


if __name__ == "__main__":
    threading.Thread(target=auto_detect_astrbot, daemon=True).start()
    run_server()
