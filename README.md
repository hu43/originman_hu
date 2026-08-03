# OriginMan VLA —— 视觉语言动作机器人

> 基于 OriginMan 硬件平台的多模态大模型交互机器人，支持视觉理解、联网搜索、离线语音识别、动作执行与语音播报。

## 功能特性

- **多模态视觉交互**：摄像头实时捕捉画面，结合用户指令通过大模型生成理解
- **联网搜索**：内置 Web Search 插件，模型可自动判断并查询实时信息（新闻、天气、日期等）
- **离线语音识别**：基于 sherpa-onnx（Paraformer 中文模型），本地运行无需联网、无需 API Key
- **动作执行**：支持 16 种机器人动作（站立、前进、后退、左右移动、旋转、鞠躬、挥手、扭腰、庆祝、下蹲、踢腿、仰卧起坐、咏春拳、起立等）
- **语音播报**：edge-tts 合成中文语音，通过 aplay 播放
- **三种输入模式**：
  - `text`（默认）：键盘输入文本指令
  - `voice`：语音输入，自动录音转写
  - `hybrid`：键盘输入，或直接回车开始语音录音
- **智能退出**：支持"退出/退下/离开/再见/拜拜/exit/quit"等指令退出，自动关闭 AI 调用避免额度消耗
- **启动语音**：成功启动后播报欢迎语；额度用完或启动失败也有相应语音提示

## 目录结构

```
originman_hu/
├── VLA/
│   ├── vision_integrated_chat_node.py   # 主程序（视觉+联网+语音+动作）
│   ├── vision_chat_node.py              # 纯视觉聊天（无动作/语音）
│   └── integrated_chat_node.py          # 纯文本+动作（无视觉/语音）
├── originman_llm_chat/                  # ROS2 LLM 聊天节点（外部调用）
├── originman_audio_control/             # 音频控制节点
├── originman_vision/                    # 视觉相关
├── originman_kick_ball/                 # 踢球动作
├── sherpa_models/                       # 离线语音识别模型（~233MB）
├── _vendor/                             # Python 依赖包（edge_tts, sherpa_onnx, aiohttp 等）
├── web/                                 # 网页控制器（浏览器控制机器人动作）
├── TonyPi-API-20241116_no_key/          # TonyPi 动作 API
├── bin/                                 # 工具脚本
└── README.md                            # 本文件
```

<img width="357" height="816" alt="606161188-9090d9b1-6e2e-436e-a13a-55fe0013d1b4" src="https://github.com/user-attachments/assets/cf778dc5-01e2-4656-a065-6fe88d5291dd" />


## 环境要求

- **硬件**：OriginMan 机器人（aarch64，带摄像头、麦克风、扬声器）
- **系统**：Ubuntu 20.04+（aarch64）
- **Python**：3.10
- **网络**：需要联网（用于大模型 API 调用和 Web Search）
- **音频**：ALSA（`aplay`/`arecord`），默认设备 `plughw:0,0`

## 快速开始

### 1. 配置 API Key

创建 `.env` 文件（参考 `.env.example`）：

```bash
cd /userdata/dev_ws/src/originman/originman_hu
cp .env.example .env
nano .env
```

填入你的 Ark API Key：
```
ARK_API_KEY=your-ark-api-key-here
```

> **注意**：`VLA/vision_integrated_chat_node.py` 中的 `api_key` 已移除硬编码默认值，必须通过环境变量或 `.env` 文件配置。**不要把 API Key 提交到 Git 仓库！**

### 2. 运行主程序

```bash
# 文本模式（默认）
python3 VLA/vision_integrated_chat_node.py

# 语音模式（自动录音）
VISION_INPUT_MODE=voice python3 VLA/vision_integrated_chat_node.py

# 混合模式（打字或按回车说话）
VISION_INPUT_MODE=hybrid python3 VLA/vision_integrated_chat_node.py
```

### 3. 交互方式

- **文本模式**：输入指令如"向前走一步然后挥手"
- **语音模式**：听到"请说话…"后说出指令，说完停顿 1.5 秒自动结束录音
- **混合模式**：打字输入指令，或直接按回车开始语音录音
- **退出**：说"退出/退下/离开/再见/拜拜"或输入 `exit`/`quit`

### 4. 可选环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `VISION_INPUT_MODE` | 输入模式：`text`/`voice`/`hybrid` | `text` |
| `ARK_API_KEY` | 火山方舟 API Key | （必填） |
| `VISION_CAMERA_INDEX` | 摄像头索引 | `0`（自动探测） |
| `VISION_ASR_DEVICE` | 麦克风设备 | `hw:0,0` |
| `AUDIO_DEVICE` | 音频播放设备 | `plughw:0,0` |

### 5. 机器人连接wifi

用ssh将自己的机器人连接到自己范围内的wifi Sudo NMCLI设备WiFi列表# 列出找到的wifi网络 sudo wifi_connect “WiFi用户名” “WiFi密码” # Linux连wifi

## 大模型配置

本项目使用 **火山方舟**（Volcano Ark）的 `doubao-seed-2-0-pro-260215` 模型：

- **端点**：`https://ark.cn-beijing.volces.com/api/v3/responses`
- **功能**：支持视觉（图片输入）+ 联网搜索（Web Search）+ 文本输出
- **计费**：按 token 用量计费；Web Search 插件按实际调用次数计费

开通步骤：
1. 注册 [火山方舟](https://www.volcengine.com/product/ark) 账号
2. 在控制台开通 `doubao-seed-2-0-pro-260215` 模型
3. 开通「联网内容插件」（服务组件库 → 联网内容插件 → 开通）
4. 创建 API Key 并填入 `.env`

## 语音技术栈

| 环节 | 技术 | 说明 |
|------|------|------|
| 语音输入 | **sherpa-onnx** (Paraformer) | 离线中文语音识别，无需联网、无需 Key |
| 语音输出 | **edge-tts** (XiaoyiNeural) | 微软 Edge 在线语音合成，中文女声 |
| VAD 降噪 | **webrtcvad** + ffmpeg | 48k 录音 → 降噪 → 16k 单声道 → 识别 |

> sherpa-onnx 即 [py-xiaozhi](https://github.com/huangjunsen0406/py-xiaozhi) 同款语音引擎，本项目使用其完整 ASR 能力（非仅唤醒词）。

## 网页控制器

在 `web/` 目录下提供独立的网页控制服务：

```bash
cd web
./start_web_controller.sh
# 或
python3 web_robot_controller.py --host 0.0.0.0 --port 8000
```

浏览器打开 `http://<机器人IP>:8000/`，点击按钮即可发送动作指令。

## 动作列表

支持的动作函数：

| 动作 | 函数 | 描述 |
|------|------|------|
| 站立 | `stand()` | 恢复站立姿态 |
| 前进 | `move_forward()` | 前进一步 |
| 后退 | `move_back()` | 后退一步 |
| 左移 | `move_left()` | 向左平移 |
| 右移 | `move_right()` | 向右平移 |
| 左转 | `turn_left()` | 向左旋转 |
| 右转 | `turn_right()` | 向右旋转 |
| 鞠躬 | `bow()` | 鞠躬行礼 |
| 挥手 | `wave()` | 挥手打招呼 |
| 扭腰 | `twist()` | 扭腰动作 |
| 庆祝 | `celebrate()` | 捶胸庆祝 |
| 下蹲 | `squat()` | 下蹲 |
| 踢右脚 | `right_shot()` | 右脚踢 |
| 踢左脚 | `left_shot()` | 左脚踢 |
| 仰卧起坐 | `sit_ups()` | 仰卧起坐 |
| 咏春拳 | `wing_chun()` | 佛山叶问咏春拳 |
| 前趴起立 | `stand_up_front()` | 从前倾趴卧起立 |
| 后躺起立 | `stand_up_back()` | 从后仰躺倒起立 |

## 常见问题

**Q: 启动时提示"未探测到任何可用摄像头"？**
> 检查摄像头硬件连接和驱动。可用 `ls /dev/video*` 查看设备。

**Q: 语音识别不准确？**
> sherpa-onnx 的 paraformer-zh 模型适合近场清晰语音。确保麦克风正常、环境噪音不大。可用 `VISION_ASR_DEVICE` 指定正确麦克风。

**Q: AI 额度用完怎么办？**
> 模型会播报"我AI额度用光了，叫我主人给我充点钱，才能用我噢"。请前往火山方舟控制台充值或升级套餐。

**Q: 首次启动时模型下载失败或太慢？**
> 自动下载源是 hf-mirror.com（国内镜像）。如果下载失败：
> 1. 检查网络连接
> 2. 手动从 GitHub Releases 下载 `sherpa-paraformer-zh-2023-09-14.tar.gz`
> 3. 解压到 `sherpa_models/paraformer-zh/` 目录
> 4. 重新运行程序

**Q: 语音播报没声音？**
> 检查 ALSA 音频设备：`aplay -l` 列出设备，确认 `plughw:0,0` 正确。可用 `AUDIO_DEVICE` 环境变量覆盖。

**Q: 可以换用其他大模型吗？**
> 当前代码针对火山方舟 Responses API 编写。换其他模型需修改 `VLA/vision_integrated_chat_node.py` 中的 `_call_vision_model` 方法。

## 安全提示

⚠️ **永远不要将 API Key 提交到 Git 仓库！**

本项目已移除所有硬编码 API Key，统一通过环境变量读取。请确保：
- `.env` 文件已添加到 `.gitignore`
- 定期轮换 API Key
- 不要在公开场合分享你的 Key

## 参考资料

- [OriginMan 官方教程](https://originman.guyuehome.com/zh/guide/quick_guide/)
- [子豪兄TonyPi机器人交付 - 飞书云文档](https://my.feishu.cn/docx/Z0dkdyNpTojSXWx06zZcjTjXndg)
- [Originman程序分享链接](https://vscode.dev/github/xiaobairisk/originman/blob/main/originman_kick_ball)
- [py-xiaozhi](https://github.com/huangjunsen0406/py-xiaozhi/blob/main/README.zh.md)
- [火山方舟文档](https://www.volcengine.com/docs/82379/)
- [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)
- [edge-tts](https://github.com/rany2/edge-tts)

## 联系

如有问题，欢迎提 Issue 或联系：2533764649@qq.com
有问题问AI，有问题问AI,可以把本github网址丢给ai让他帮你操作
我的也是ai帮我写好的：）

---
## Release 资源

本项目 GitHub Releases 提供以下资源：

| 文件 | 说明 | 大小 |
|------|------|------|
| `originman_hu.tar.gz` | 完整代码包（不含模型） | ~65MB |
| `sherpa-paraformer-zh-2023-09-14.tar.gz` | 语音识别模型（备用下载） | ~215MB |

**Release 下载地址**：`https://github.com/hu43/originman_hu/releases`

### 手动安装模型步骤

```bash
# 1. 下载代码
git clone https://github.com/hu43/originman_hu.git
cd originman_hu

# 2. 下载模型（从 Release 页面或自动下载）
# 方式 A：首次运行时自动下载（推荐）
python3 VLA/vision_integrated_chat_node.py

# 方式 B：从 Release 手动下载并解压
wget https://github.com/hu43/originman_hu/releases/download/v1.0.0/sherpa-paraformer-zh-2023-09-14.tar.gz
tar xzf sherpa-paraformer-zh-2023-09-14.tar.gz -C sherpa_models/
```

*本项目由 AI 辅助开发，感谢 OriginMan 社区和各位开源贡献者。*


### ai提示词内容

1、<img width="268" height="352" alt="606159711-94dcd202-56cd-4e27-8bdf-f33a605cd4bd" src="https://github.com/user-attachments/assets/70cb9b74-d670-49c5-a9be-7b5c9bf209f5" />

2、参考orginman_hu文件夹内的originman_vision和integrated_chat_node内的代码，另起一份新的python运行文件，要实现摄像头与大模型的功能整合。功能要求实现大模型视觉识别：视觉理解：机器人不仅仅是一个执行者，它还拥有一双“眼睛”，能够观察和理解周围的世界。 实现方式： 持续观察: 机器人通过摄像头以固定频率捕捉图像，并将其发布到 ROS 网络中，为系统提供实时的视觉输入。 图像与问题的结合: 当您提出一个关于视觉的问题，例如“你看到了什么？”，机器人会获取最新的摄像头图像，并将其与您的问题文本一起发送给多模态大模型。 生成描述性回答: 大模型能够理解图像内容和文本问题的关联，并生成一段详细的、人性化的描述性文字作为回答，例如“我看到了桌子上有一个红色的苹果...”等。
所有任务行为只能在orginman_hu内进行，不能处理这个文件夹外的文件，并且要保证原orginman_hu内的所有功能能正常运行。

3、在/userdata/dev_ws/src/originman/originman_hu/web文件夹内另起一份新的python运行文件，帮我实现用网页控制机器人的程序，要求：用户可以打开浏览器，在页面中输入对应网址后，通过点击网址内的对应动作按钮，实现对机器人基础动作功能的控制。
所有任务行为只能在originman_hu/web文件夹内进行，不能处理这个文件夹外的文件，并且要保证原originman_hu内的所有功能能正常运行。
