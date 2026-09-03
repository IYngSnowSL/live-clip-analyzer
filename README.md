# 🎬 直播切片分析 · Live Clip Analyzer

> **📢 声明**：本软件代码内容全部由 AI 生成，依据 [MIT License](LICENSE) 开源。

一款**面向零基础用户的直播录播自动打轴工具**：输入录播视频，AI 自动找出所有值得剪的片段，给出每个片段的**精确起止时间、标题、推荐理由与评分**。你只需要挑、微调、导出，剩下交给剪辑软件。

```
录播视频（FLV / MP4）
      │
      ├─① 语音自动转文字（ASR）
      ├─② AI 找内容点并打轴（标题 / 理由 / 评分 / 起止时间）
      ├─③ 静音点精修（片段头尾干净）
      ▼
  ✂️ 切片轴清单 → 导出切片视频 / CSV 清单（对照剪辑软件剪）
```

---

## 第一步：准备工作（只需一次）

### 1. 安装 Python

1. 打开 <https://www.python.org/downloads/>，点黄色「Download Python」按钮下载
2. 双击安装包，**务必勾选最底部的 `Add python.exe to PATH`**，再点 Install Now 一路下一步

### 2. 获取本软件

1. 打开 <https://github.com/IYngSnowSL/live-clip-analyzer>
2. 点绿色 **Code** 按钮 → **Download ZIP**，下载后解压到任意文件夹（例如 `D:\live-clip-analyzer`）

### 3. 安装依赖（黑窗口，一次就好）

1. 打开解压出来的文件夹，**点击窗口顶部地址栏，输入 `cmd` 后回车**（黑窗口会直接定位到本文件夹）
2. 在黑窗口输入以下命令并回车，等待出现 `Successfully installed ...`：

```bat
pip install -r requirements.txt
```

### 4. 安装 FFmpeg（处理视频必需）

- **方法一（推荐，Win10/11）**：在上面的黑窗口输入 `winget install ffmpeg` 回车，完成后**关掉黑窗口重新开一个**
- **方法二**：去 <https://ffmpeg.org/download.html> 下载 Windows 版，解压后把里面的 `bin` 文件夹路径加入系统 PATH（网上搜「ffmpeg 加入环境变量」有图文教程）

### 5. 准备 AI 接口（打轴的大脑，必须）

本软件用 AI 分析字幕找内容点，需要一个 **OpenAI 兼容接口的 API Key**。推荐国内直连的**硅基流动**（一家通吃，价格低）：

1. 打开 <https://cloud.siliconflow.cn> 注册并登录
2. 左侧菜单「API 密钥」→「新建 API 密钥」→ 复制那串 `sk-` 开头的内容（**妥善保存，只显示一次**）

> 💡 有 NVIDIA 显卡想完全免费转写？先按上面步骤跑通，再看文末「附录 A：启用免费本地转写」。

---

## 第二步：启动软件

1. 再次打开软件文件夹，地址栏输入 `cmd` 回车
2. 输入以下命令回车：

```bat
python run.py
```

3. 看到 `Uvicorn running on http://127.0.0.1:8000` 就是启动成功
4. 浏览器打开 **<http://127.0.0.1:8000>**（黑窗口保持开着别关）

---

## 第三步：第一次配置

1. 点页面**右上角 ⚙️**打开设置
2. 「接口地址 base_url」填：`https://api.siliconflow.cn/v1`
3. 「API Key」粘贴你在第一步第 5 节复制的密钥
4. 点旁边的「**测试连接**」→ 看到 ✅ 和模型列表即成功
5. 「文本模型」输入 `Qwen/Qwen2.5-72B-Instruct`（或点 ▾ 从列表里选）
6. 「ASR 转写引擎」：新手先选**云端**；ASR 模型填 `FunAudioLLM/SenseVoiceSmall`
7. 点「保存」

---

## 第四步：第一次打轴

1. 首页视频路径输入框里输入录播文件完整路径（点 **📂** 可以直接浏览选择，可多选批量处理）
2. 点「**开始打轴**」
3. 左下角「任务列表」实时显示进度：提取音频 → 语音转写 → AI 打轴
4. 任务变成「完成」后，点击该任务查看结果

---

## 第五步：看懂结果、复核与导出

- 每个**轴**就是一个可剪片段，显示：`[开始 - 结束]` 时间、标题、推荐理由、评分（9~10 顶级名场面，7~8 高光爆点，5~6 有趣）
- 点时间可**跳转视频预览**确认内容；「📋 复制」一键复制时间标记
- 不满意就点「**复核打轴**」微调起止时间/标题，或「**重新打轴**」改目标时长重跑（复用转写结果不重复计费）
- **导出**：
  - `导出 CSV`：带时间/标题/理由/评分的表格，直接对照剪辑软件打轴
  - `批量导出全部`：直接导出剪好的视频文件（勾「精切模式」帧级精确但慢；不勾无损快切、秒级完成）

---

## 常见问题（FAQ）

| 现象 | 解决 |
|---|---|
| 黑窗口提示 `python 不是内部或外部命令` | Python 重装并勾选 `Add python.exe to PATH`，装完**重开黑窗口** |
| 启动报找不到 `ffmpeg` / `ffprobe` | 回到第一步第 4 节安装 FFmpeg，重开黑窗口 |
| 「测试连接」失败 | 检查 base_url 末尾是 `/v1`、密钥无空格；公司网络可能需要代理 |
| 浏览器打不开 127.0.0.1:8000 | 黑窗口是否还开着？`Uvicorn running` 那行出现了吗 |
| 提示端口 8000 被占用 | 关掉上一个还在运行的黑窗口（或重启电脑） |
| 转写很慢 | 云端引擎取决于网络；有 NVIDIA 显卡请启用本地转写（附录 A） |
| 没有独立显卡能用吗 | 能。ASR 引擎保持「云端」即可，所有功能不受影响 |
| 分析结果不满意 | 点「重新打轴」调整目标时长，或开启「精细模式」切出更多更细的轴 |

---

## 附录 A：启用免费本地转写（可选，需 NVIDIA 显卡）

本软件的本地转写复用**卡卡字幕助手（VideoCaptioner）**的引擎与模型，实现零 API 费用：

1. 下载安装卡卡字幕助手：<https://github.com/WEIFENG2333/VideoCaptioner/releases>（选最新版 exe）
2. 打开卡卡字幕助手 → 设置 → Faster Whisper → 下载 **large-v2** 模型（保持默认位置，约 3GB）
3. 回到本软件设置页：ASR 引擎选「**本地 faster-whisper（CUDA 加速）**」，保存
4. 本地模型路径默认已自动填好（`D:\AdobE\VideoCaptioner\AppData\models\faster-whisper-large-v2`），一般无需修改

本地转写的高级参数（显存紧张改 `int8_float16`、专名梗词加热词等）在 `config.yaml` 的 `asr:` 段调整，文件内有中文注释说明。

---

## 附录 B：高级配置速览

所有配置都能在设置页完成；如需更细控制，编辑软件文件夹里的 `config.yaml`（真密钥请写进 `config.local.yaml`，不会被上传到 git）：

```yaml
ai:
  base_url: https://api.siliconflow.cn/v1   # 打轴 AI 接口
  llm_model: Qwen/Qwen2.5-72B-Instruct     # 文本模型（打轴核心）
  asr_model: FunAudioLLM/SenseVoiceSmall   # 云端 ASR 模型

asr:
  engine: local            # local=本地免费转写 / api=云端 ASR
  local_device: cuda       # NVIDIA 显卡用 cuda；没有就写 cpu
  local_batched: true      # 批解码加速（默认开）
  local_hotwords: ""       # 热词：专名/梗词空格分隔，可提高识别率

axle:
  target_min_seconds: 30   # 目标最短片段（秒）
  target_max_seconds: 3600 # 目标最长片段（秒）
```

---

## 🛡️ 隐私与安全

- 密钥只存在你自己的电脑上（`config.local.yaml`），不会上传、不会进 git
- 本地转写模式下，视频和音频**完全不离开你的电脑**（只有字幕文字发给 AI 打轴）
- 云端 ASR 模式只会把音频块发给 ASR 接口
- 服务只监听本机 127.0.0.1，其他设备无法访问

## ⚖️ 许可

本软件代码内容全部由 AI 生成，依据 **[MIT License](LICENSE)** 开源共享——任何人可自由使用、修改与分发（含商用），只需保留版权声明与许可文本。
