# AstrBot 角色个性化配置中心 (Breeze 语音版)

这是一个专为 **AstrBot** 设计的开箱即用角色个性化配置套件。通过现代化的 Web 可视化配置中心，你可以将接入 QQ 的 AstrBot 快速打造为你心仪的专属 AI 角色（如傲娇萌妹「大肥鱼」、温柔女仆管家、幽默死党等）。

---

## 🏗️ 整体开源生态分工与协同

本项目深度融合了以下核心开源项目：

```text
[ 用户 QQ 聊天 ] ◀────▶ [ NapCatQQ (OneBot v11) ] ◀────(ws://127.0.0.1:6199/ws)────▶ [ AstrBot (AI大脑中枢) ]
                                                                                                │
                                                                                    (http://127.0.0.1:8137/v1)
                                                                                                ▼
                                                                                   [ 本地 Breeze TTS 2 语音引擎 ]
```

1. **[AstrBot](https://github.com/Soulter/AstrBot)**：AI 核心大脑与对话管理中枢，负责处理大语言模型对话、长期记忆、表情包发送、插件系统调度等。
2. **[NapCatQQ](https://github.com/NapNeko/NapCatQQ)**：现代化的 QQ NT 架构机器人协议端。负责接收 QQ 群聊/私聊消息，并通过 OneBot v11 协议（反向 WebSocket）推送给 AstrBot，同时将 AstrBot 生成的回复/语音/表情发回 QQ。
3. **[Breeze-TTS-2](https://github.com/HoppouAI/Breeze-TTS-2.cpp)**：完全运行在本地显卡上的高品质语音克隆引擎。通过参考音频克隆出高度自然的角色音色，无需付费云端 API。
4. **个性化配置中心（本项目）**：作为三者之间的**可视化桥梁与控制台**，提供独立页面在线定制性格、独立页面声音克隆、一键打通 NapCat ↔ AstrBot 链路、自动部署基础插件与管理表情包。

---

## ✨ 核心特性

- **🤖 NapCatQQ 深度感知与一键链路对齐**：
  - 自动侦测本机 NapCat 安装路径（如 `D:\NapCat.Shell.Windows.OneKey`）与运行状态；
  - 自动读取机器人 QQ 号、反向 WebSocket 路径（`ws://127.0.0.1:6199/ws`）与通信 Token；
  - 配备「⚡ 一键自动对齐/修复链路配置」，自动写入 AstrBot OneBot v11 平台配置，避免配置不匹配导致的连接失败。
- **🎭 性格人设独立页面**：告别手动翻找修改 `.md` 文件。在网页中自由编辑 Prompt、一键切换模板（大肥鱼 / 温柔管家 / 死党好友 / 自定义），支持 `{OWNER_QQ}` 主人变量智能注入并一键推送到 AstrBot。
- **🎙️ 本地 Breeze 声音克隆（固定适配）**：完全收敛并专注于**本地开源 Breeze TTS 2 语音引擎**。无需付费 API，拖入一段 5~15 秒干净参考音频并输入原话，秒级克隆，支持网页即时在线试听，一键绑定为 AstrBot 默认发音人。
- **📦 基础底座插件一键装配**：保留并整合所有关键基础能力（群聊插话、长期记忆、表情包管理底座、主动找主人聊天、QQ空间/资料、防串台标签清理、只听主人安全权限），一次点击即可完成环境初始化。
- **🖼️ 表情包开源源头彻底透明化**：拒绝黑盒！在界面中完整公开所有官方社区表情包的 GitHub 开源仓库地址、社区索引地址与本地实际落盘存储路径，支持用户自主决定单独下载与启用哪一套。

---

## 🛠️ 环境准备与前置步骤

在开始使用本配置包之前，请确保以下基础环境已就绪：

1. **操作系统**：Windows 10 / 11 64 位。
2. **AstrBot 部署**：
   - 推荐使用 [AstrBot 启动器](https://github.com/Soulter/AstrBot) 部署实例；
   - 启动实例后，可以在浏览器中打开后台管理界面。
3. **NapCatQQ 部署（QQ 机器人接入）**：
   - 使用 [NapCatQQ 一键安装包](https://github.com/NapNeko/NapCatQQ)（如解压在 `D:\NapCat.Shell.Windows.OneKey`）；
   - 扫码登录用于做机器人的 QQ 小号，确保 NapCat 处于运行状态（后台 WebUI 端口为 `6099`）。
4. **本地 Breeze TTS 2 语音服务**：
   - 独立显卡推荐显存 3GB 以上（N 卡、A 卡、Intel 核显均可；无独显亦可运行）；
   - 首次使用请双击运行包内的 **`装Breeze语音.bat`** 完成自动部署，并在桌面双击「启动Breeze语音」保持服务运行在 `http://127.0.0.1:8137`。
5. **FFmpeg（推荐）**：
   - 用于在声音克隆时自动将各类格式音频转为标准的 24kHz 单声道 WAV。若未安装，可在终端运行 `winget install Gyan.FFmpeg`。

---

## 🚀 快速上手使用流程

### 第一步：启动配置中心
1. 确保 AstrBot 与 NapCat 均已启动；
2. 双击运行配置包根目录下的 **`启动个性化配置中心.bat`**；
3. 系统将自动检测可用的 Python 环境并拉起服务，稍等 1~2 秒浏览器会自动打开配置中心面板：
   `http://127.0.0.1:18989`

---

### 第二步：分层配置你的专属角色

#### 1. 基础配置与通信链路
- **NapCatQQ 状态识别**：系统会自动扫描到 NapCatQQ 路径与登录的机器人 QQ 号；
- **一键对齐链路**：点击「⚡ 一键自动对齐/修复链路配置」，系统将确保 AstrBot 的 OneBot v11 接口（端口 6199 与 Token）与 NapCat 完全对齐；
- **连接 AstrBot**：系统自动扫描当前活跃的 AstrBot 后台地址（例如 `http://127.0.0.1:17615`），输入后台密码与您的主人 QQ 号，点击「🔑 验证登录并保存连接」；
- **安装基础底座**：点击「🚀 一键安装/修复基础插件底座」，自动完成群聊插话、长期记忆、表情包管理底座、主动聊天、防串台规则等全套基础装配。

#### 2. 🎭 性格设置 (独立页面)
- 可在下拉菜单中直接选择预设人设（如「大肥鱼」），也可选择自定义；
- 在多行编辑器中自由修改性格口吻、回复长短与特定说话习惯；
- 点击「✨ 保存并导入此性格到 AstrBot」，即可秒级生效；
- （可选）点击「💾 另存为本地模板」可备份到本地 `persona/` 目录。

#### 3. 🎙️ Breeze 声音克隆 (独立页面)
- **已有音色库**：若此前已制作过音色，页面上方会直接列出卡片，可直接点击「🔊 试听」或「⭐ 设为发音人」；
- **制作新音色**：
  1. 给音色起一个代号（如 `my_voice`）；
  2. 将一段 5~15 秒无背景音的干净人声录音拖入上传区（支持 MP3/WAV/M4A）；
  3. 在台词框中一字不差输入录音中所说的原话；
  4. 点击「⚡ 开始克隆并注册音色」；
  5. 在下方输入试听句子点击「🔊 合成试听」，满意后点击「✅ 绑定该音色为 AstrBot 默认发音人」。

#### 4. 🖼️ 表情包管理 (来源透明与自选)
- **开源源头透视**：页面清晰展示了表情包的 GitHub 开源地址：
  - 蓝色大肥鱼表情包 (157张)：[anka-afk/blue-fat-fish-meme-pack](https://github.com/anka-afk/blue-fat-fish-meme-pack)
  - DeepSeek 同人表情包 (174张)：[anka-afk/deepseek-fanart-meme-pack](https://github.com/anka-afk/deepseek-fanart-meme-pack)
  - 社区索引地址：[anka-afk/astrbot-meme-pack-index](https://github.com/anka-afk/astrbot-meme-pack-index)
- **直达本地**：提供「📁 在 Windows 资源管理器中打开此文件夹」按钮，可一键定位本地落盘目录；
- **自选安装**：每个表情包卡片独立配备「📥 单独安装」与「⭐ 设为主力套」按钮，按需下载启用。

---

### 第三步：体验新角色
设置完成后，用您的大号在 QQ 上给机器人私聊发送：
```text
/reset
```
清除旧对话上下文，机器人即会以全新的性格设定、克隆语音和表情包开始与你交流！

---

## 📂 项目规范目录结构

```text
character-pack/
├── 启动个性化配置中心.bat        # [主入口] 双击启动可视化 Web 控制台 (推荐)
├── 装Breeze语音.bat            # 一键下载并部署本地 Breeze TTS 2 语音服务
├── README.md                  # 项目使用与配置说明文档
├── LICENSE                    # 开源许可证 (MIT)
├── .gitignore                 # Git 忽略规则
├── persona/                   # 性格预设模板保存目录
│   └── 大肥鱼.md               # 经典大肥鱼角色设定
├── voice/                     # 语音参考音频与试听存放目录
├── settings/
│   └── pack.json              # 基础底座插件列表与默认系统配置清单
├── tools/                     # 工具核心模块
│   ├── web_server.py          # 轻量本地 Web 服务端 (原生 Python，零外部依赖)
│   ├── web_adapter.py         # AstrBot API、NapCat 链路与 Breeze 引擎深度适配层
│   ├── web_static/            # 控制台前端页面资源
│   │   └── index.html         # 响应式控制面板前端
│   └── breeze/
│       ├── install_breeze.ps1 # Breeze 安装脚本
│       └── make_voice.py      # Breeze 制作声音底层辅助
└── plugins/                   # 本地打包的核心插件
    ├── astrbot_plugin_dafeiyu_clean       # 回复防串台与标签清洗插件
    ├── astrbot_plugin_dafeiyu_signature   # 角色个性签名监听与同步插件
    └── astrbot_plugin_dafeiyu_sing        # 角色唱歌能力插件
```

---

## ❓ 常见问题排错 (FAQ)

**Q: 启动配置中心后，网页提示「AstrBot: 未连接」？**  
A: 请确认 AstrBot 实例已经在后台运行。AstrBot 启动器通常会分配动态端口（如 `http://127.0.0.1:17615`），配置中心已具备自动动态扫描能力，若仍未连接，可手动在地址栏填入您的 AstrBot 后台地址。

**Q: 提示「NapCat QQ: 未运行」或消息发到 QQ 机器人没反应？**  
A: 
1. 检查 NapCat 是否已启动并扫码登录 QQ 小号；
2. 确保 NapCat 中配置的反向 WebSocket 客户端目标地址为 `ws://127.0.0.1:6199/ws`，并带有正确的 Token；
3. 您可以在配置中心首屏直接点击「⚡ 一键自动对齐/修复链路配置」，系统将自动修正该项参数。

**Q: 声音克隆页面提示「Breeze语音: 未运行」？**  
A: 请确保已经运行过 `装Breeze语音.bat`，并双击桌面生成的「启动Breeze语音」快捷方式。启动后任务栏中的黑窗口请勿关闭（它在后台提供语音推理服务）。

**Q: 克隆声音对参考音频有什么要求？**  
A: 
1. 时长建议在 5 ~ 15 秒之间；
2. 只能有单人清晰人声，切勿包含背景音乐 (BGM)、杂音或混响；
3. 文本框中必须一字不差录入音频的原话（模型依据此文本与音频对齐发音特征）。

**Q: 新设置导入后，QQ 上感觉角色口吻没有变化？**  
A: 大模型存在旧会话的历史上下文缓存。请在 QQ 上给机器人私聊发送一条 `/reset` 指令，清空历史记忆后即可无缝载入新人格。

---

## 📜 许可证与致谢

- 本配置包核心代码采用 **MIT License** 开源。
- 感谢 [AstrBot](https://github.com/Soulter/AstrBot) 提供的卓越机器人框架生态。
- 感谢 [NapCatQQ](https://github.com/NapNeko/NapCatQQ) 提供的现代 QQ NT 协议端基座。
- 感谢 [Breeze-TTS-2.cpp](https://github.com/HoppouAI/Breeze-TTS-2.cpp) 团队提供的本地低门槛、高表现力语音合成模型。
- 表情包资源版权归各权利人所有，由 [anka-afk](https://github.com/anka-afk) 社区索引整理。
