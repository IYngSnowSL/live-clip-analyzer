# 🎬 live-clip-analyzer · 直播切片自动打轴工具

> **📢 郑重声明**
> 本软件代码内容全部由 AI 生成。

> v0.4.8 ｜ 本地运行 ｜ Windows / Linux / macOS ｜ [MIT License](LICENSE)

---

## 这是什么？

一款**本地直播录像自动打轴工具**：输入录播视频，AI 自动分析字幕，找出所有值得切的内容点，
输出每个可切片片段的**精确起止时间、标题、推荐理由与评分**——把"反复拖进度条找片段"的活交给 AI，
切片生产者只需挑选、微调、导出。

```
录播视频（FLV / MP4）
    │
    ├─① ASR 全量语音转写 ────────────► 📝 SRT 字幕文件（存视频同目录 [日期]_视频名 文件夹）
    │
    ├─② LLM 分窗找内容点并初步打轴
    │
    ├─③ 内容点合并 + 长度约束（目标 30 秒 ~ 1 小时）
    │
    ├─④ 静音点精修（ffmpeg silencedetect，边界干净不留杂音）
    │
    ▼
   ✂️ 切片轴清单：精确起止 + 标题 + 理由（带时间戳举例）+ 评分
    │
    ├─ 人工复核微调 ──► 🎬 导出切片（快切 / 精切）
    └─ 📄 CSV 导出 ──► 对照剪辑软件打轴
```

## ✨ 功能特性

| 功能 | 说明 |
|---|---|
| **自动打轴** | 唯一核心功能：AI 从字幕中找出名场面/趣点/高光/爆点，给出精确起止时间与内容说明 |
| **SRT 字幕文件** | ASR 完成后自动生成：无表情、句读+情感标点（无句号），可直接插入剪辑软件 |
| **批量处理** | 文件浏览器多选视频，一次创建多个任务并行分析 |
| **重新打轴** | 复用转写结果**不重复计费**，可改目标时长，可选精细分窗模式切得更细 |
| **自动弹幕关联** | 自动查找视频同目录同名 `.xml` 弹幕文件并关联 |
| **人工复核** | 微调每个轴的起止时间与标题，导出以复核值为准 |
| **CSV 导出** | 轴清单（序号/起止/时长/标题/理由/评分），直接对照剪辑软件打轴 |
| **切片导出** | 无损快切（`-c copy`）或重编码精切（精确到帧） |
| **评分说明** | 0~10 分含义图例（9~10 顶级名场面 / 7~8 高光爆点 / 5~6 有趣） |
| **一键复制** | 单轴复制时间标记；「复制全部」导出 **TSV 表格**（粘贴进 Excel / 共享表格直接成表） |
| **弹幕高峰标注** | 关联弹幕后每个轴标注弹幕密度峰值时刻（🔥 可点击跳转视频） |
| **字幕搜索** | 字幕页搜索框：匹配条目列表（带时间戳跳转）+ 全文高亮 |
| **字幕页** | WebUI 内在线预览完整字幕文件 |

## 🚀 快速开始

### 环境要求

- Python 3.10+
- FFmpeg（`ffmpeg` / `ffprobe` 已加入 PATH）
- OpenAI 兼容 API：**LLM**（找内容点，必需）
- ASR 二选一：本地 faster-whisper（免费，NVIDIA 显卡可 CUDA 加速）/ 云端 OpenAI 兼容 ASR API

### 安装

```bat
cd /d D:\GitRepository\live-clip-analyzer
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

本地 ASR 引擎（可选，不用云端 ASR 时安装）：

```bat
:: CPU 版
pip install faster-whisper
:: CUDA 版（NVIDIA 显卡，8GB 显存以上推荐；自带 cuDNN，无需单独装 CUDA Toolkit）
pip install "ctranslate2[cuda12]" faster-whisper
```

模型文件放到 `config.yaml` 里 `asr.local_model_path` 指向的目录（也可直接复用
卡卡字幕助手已下载的模型目录）。

### 配置 AI 接口

运行后点击页面右上角 **⚙️ 设置**：

1. 填入 `base_url` 与 `API Key`（设置页顶部有**带日期的 API 推荐**，首选硅基流动一家通吃）
2. 点「测试连接」——连通后模型名输入框即可**下拉选择**供应商的全部模型
3. 「高级设置」支持三个模型（文本/视觉/ASR）**各自独立接口与密钥**（留空继承全局）

配置读取顺序（后者覆盖前者）：内置默认值 < `config.yaml` < `config.local.yaml`（放真 key，已 gitignore）< `LCA_*` 环境变量。

### 运行

```bat
python run.py
```

浏览器打开 **http://127.0.0.1:8000**。

## 🧭 使用教程

### 第一步：创建任务

首页中央填入视频路径（📂 浏览可**勾选多个视频**批量处理，选择后以标签形式展示、可逐个移除），
点击「开始打轴」。

> 💡 未填弹幕时，会自动查找视频同目录的同名 `.xml` 弹幕文件并关联。

### 第二步：等待分析

任务在左下角「任务列表」显示进度。流程：提取音频 → ASR 转写（生成字幕文件）→ LLM 找内容点 → 打轴。

### 第三步：查看轴

分析完成后点击「查看」，报告窗口按评分从高到低展示全部切片轴：

| 字段 | 含义 |
|---|---|
| 时间 | `[HH:MM:SS - HH:MM:SS]`，点击跳转视频预览 |
| 标题 | 切片标题建议 |
| 理由 | 为什么值得切，**含片段内具体时间戳与原话举例** |
| 评分 | 0~10（点「ℹ️ 评分说明」看图例），可按最低评分筛选 |

窗口内「📝 字幕文件」标签页可在线查看完整 SRT 字幕。

### 第四步：复核、重新打轴与分享

- **复核打轴**：微调起止时间与标题，导出以复核值为准
- **重新打轴**：复用已转写结果**不重复计费**——可改目标时长（30 秒~1 小时），
  勾选「精细模式」以更细分窗切出更多更细的轴（会重新调用 AI，少量费用）
- **一键复制**：单轴「复制」按钮复制时间标记；顶部「📋 复制全部」以
  **TSV 表格格式**复制整份轴清单——粘贴进 Excel / 飞书 / 腾讯文档直接成表，方便分享
- **弹幕高峰**：任务关联弹幕时，每个轴标注弹幕密度最高的时刻（🔥 可点击跳视频确认）

### 第五步：导出

- **CSV**：右上角「导出 CSV」→ 对照剪辑软件打轴
- **切片**：单轴「导出此切片」/「批量导出全部」；勾选「精切模式」重编码精确到帧，
  不勾则无损快切（秒级，起点对齐关键帧）

## ⚙️ 关键配置

```yaml
# config.yaml（真 key 请放 config.local.yaml，勿提交）
ai:
  base_url: https://api.siliconflow.cn/v1   # 推荐：硅基流动（一家通吃 LLM/视觉/ASR）
  api_key: sk-xxxx
  llm_model: Qwen/Qwen2.5-72B-Instruct     # 文本（打轴核心）
  asr_model: FunAudioLLM/SenseVoiceSmall   # ASR（中文转写性价比高）
  endpoints:                                # 高级：每个模型可单独指定接口与密钥
    llm: {base_url: "", api_key: ""}
    vision: {base_url: "", api_key: ""}
    asr: {base_url: "", api_key: ""}

axle:
  target_min_seconds: 30      # 目标最短（秒）
  target_max_seconds: 3600    # 目标最长（秒）= 1 小时
  hard_max_seconds: 3600      # 硬上限，超过自动拆分
  window_seconds: 600         # LLM 找内容点的分窗大小
  max_axles: 100              # 最多输出轴数
  silence_threshold_db: -35   # 静音检测阈值

asr:                          # 本地 faster-whisper（engine: local 时生效）
  engine: local               # local=本地（免费）/ api=云端 OpenAI 兼容 ASR
  local_model_path: D:\AdobE\VideoCaptioner\AppData\models\faster-whisper-large-v2
  local_device: cuda          # cuda / cpu（CUDA 不可用时自动回退 CPU）
  local_compute_type: float16 # CUDA: float16 / int8_float16；CPU: int8
  subtitle_max_chars: 30      # 字幕每行最大字符数（卡卡式精细化断句）
```

环境变量：`LCA_BASE_URL` / `LCA_API_KEY` / `LCA_LLM_MODEL` / `LCA_ASR_MODEL` 等。

## 🔌 HTTP API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/tasks` | 创建任务 |
| POST | `/api/tasks/batch` | 批量创建（多视频并行，最多 20 个） |
| GET | `/api/tasks` / `/api/tasks/{id}` | 任务列表 / 详情（含 `srt_path`） |
| DELETE | `/api/tasks/{id}?force=true` | 删除任务；运行中需 `force=true` |
| GET | `/api/tasks/{id}/axles` | 打轴结果列表 |
| PUT | `/api/tasks/{id}/axles/{axle_id}/review` | 复核（起止时间/标题） |
| POST | `/api/tasks/{id}/reaxle` | 重新打轴（复用转写，可改参数+精细模式） |
| GET | `/api/tasks/{id}/axles.csv` | 轴清单 CSV |
| GET | `/api/tasks/{id}/subtitle` | SRT 字幕内容与路径 |
| GET | `/api/tasks/{id}/video` | 视频预览（支持 Range 跳转） |
| POST | `/api/tasks/{id}/export` | 导出切片（`axle_ids` 或自定义 `clips`） |
| GET | `/api/tasks/{id}/exports` | 导出结果列表 |
| GET | `/api/tasks/{id}/exports/{filename}` | 下载导出切片 |
| GET/PUT | `/api/config` | 配置读写（密钥脱敏） |
| POST | `/api/config/test-connection` | 连通测试，返回供应商模型列表 |
| GET | `/api/files/ls?path=…` | 本地文件浏览 |
| GET | `/api/files/drives` | 磁盘盘符列表 |
| GET | `/api/files/sibling-danmaku?video_path=…` | 查找视频同目录同名弹幕 |
| GET | `/api/files/media-info?path=…` | 读取视频时长等媒体信息 |

## 🛡️ 隐私与安全

- 密钥只存本机（`config.local.yaml` / 环境变量），不会打印、不会进 git
- 视频本体不上传；仅音频块（ASR）与文字（LLM）发送给你配置的 `base_url`
- 服务默认只绑定 `127.0.0.1`；**请勿改 `host` 为 0.0.0.0**（会无鉴权暴露文件浏览接口）

## 📁 目录结构

```
live-clip-analyzer/
├── app/
│   ├── main.py                  # FastAPI 入口
│   ├── config.py                # 配置加载（四级优先级）
│   ├── database.py              # SQLite（tasks + axles）
│   ├── models.py                # 数据访问
│   ├── api/                     # 任务 / 轴 / 导出 / 配置 / 文件浏览
│   ├── services/
│   │   ├── axle.py              # ★ 自动打轴核心（找内容点 + 合并 + 静音精修）
│   │   ├── asr.py               # 云端 ASR + SRT 字幕生成
│   │   ├── local_asr.py         # 本地 faster-whisper（CUDA 加速，自动回退 CPU）
│   │   ├── danmaku.py           # 弹幕流式解析 + 密度高峰标注
│   │   ├── ai_client.py         # AI 能力门面（三模型可独立端点）
│   │   ├── ffmpeg_utils.py      # ffmpeg 封装
│   │   └── exporter.py          # 切片导出
│   ├── workers/                 # 后台任务流水线（含重新打轴）
│   └── web/                     # 前端（深色 DeepSeek 风格，无构建步骤）
├── docs/adr/                    # 架构决策记录（0001~0006）
├── data/                        # 任务产物（gitignore）
└── config.yaml
```

## 📚 项目文档

- [`docs/adr/`](docs/adr/)：架构决策记录（0006 推倒重建为当前架构基准）
- [`CONTEXT.md`](CONTEXT.md)：领域术语表（轴 / 内容点 / 打轴 / 复核等定义）

## ⚖️ 许可

本软件代码内容全部由 AI 生成，依据 **[MIT License](LICENSE)** 开源共享——
任何人可自由使用、修改与分发（含商用），只需保留版权声明与许可文本。
