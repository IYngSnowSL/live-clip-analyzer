# live-clip-analyzer · 直播切片分析工具

> v0.2.1 · 本地运行 · 个人使用

> **🤖 AI 声明**
> 本软件完全由 AI 编写，仅由用户进行框架设计与需求定义。

## 这是什么？

一款**本地直播录像切片分析工具**：输入一段直播录播视频（FLV / MP4）和可选的
B 站弹幕 XML 文件，全自动完成场景切分、弹幕统计、语音转写、画面理解与
逐段 AI 分析，最终输出：

- 📋 逐段**详细时间轴**（中英双语标题、概述、画面、语音、弹幕、评分）
- ✂️ **长切片候选**（1~5 分钟，可直接发布的完整片段建议）
- 💬 **单句素材候选**（适合二创的原话引用，自带时间戳）
- 📄 **Markdown 报告**（中文 / English）+ 结构化 **JSON 数据**
- 🎬 **视频切片导出**（无损快速剪切 / 重编码精切两种模式）

分析全程在本地完成，不上传视频本体，仅将抽帧图片、音频块与文字材料
发送到你配置的 OpenAI 兼容 API（视觉 / LLM / ASR）。

## 核心功能

| 功能 | 说明 |
|---|---|
| 字幕语义切分 | 从 ASR 转写全文切出「话题段」（纯 Python 预筛 + LLM 命名），作为内容导航目录 |
| 场景切分 | 画面变化驱动（PySceneDetect 优先，FFmpeg 场景滤镜兜底，均不可用则固定时长切分），时长 8~30 秒可配置 |
| 弹幕解析 | 流式解析 B 站 XML 弹幕（大文件低内存），支持时间偏移对齐 |
| 弹幕统计 | 按场景统计数量、热度（密度归一化）、情绪强度、高频弹幕 |
| ASR 转写 | 长音频自动分块（默认 20 分钟/块）转写并合并时间戳；单块失败自动跳过，全部失败才报错 |
| 画面理解 | 按间隔全局抽帧，每场景选取代表帧送视觉模型生成画面描述 |
| 逐段分析 | LLM 为每个场景生成中英标题、概述、有趣度/高光潜力评分、单句素材引用 |
| 综合评分 | 弹幕热度 + 弹幕情绪 + 有趣度 + 高光潜力加权（权重可配置，自动归一化） |
| 候选生成 | 高分场景按间隔合并生成长切片候选；从原话引用生成单句素材候选 |
| 人工复核 | Web 界面微调起止时间、标题、评分、推荐等级，复核值覆盖 AI 生成值 |
| 报告导出 | 中英 Markdown 报告 + JSON 结构化数据 |
| 切片导出 | 单条 / 批量 / 自定义片段；快切（无损流复制）与精切（重编码）两种模式 |
| 视频预览 | 点击时间轴任意时间点，跳转视频预览（HTTP Range 拖动播放） |

## 工作原理

每个任务按以下流水线执行（进度实时显示在任务列表与报告页）：

```
读取视频信息 → 转封装 + 音频切块 + 场景检测（并行，同时解析弹幕）
→ 场景精炼 → 弹幕统计 → 全局抽帧 → ASR 转写 → 字幕语义切分（话题段）
→ 画面理解 → 逐段 LLM 分析 → 综合评分 → 候选生成 → 报告 + JSON 导出
```

- 源视频已是浏览器可播的 MP4（H.264 + AAC/MP3/无音轨）时自动跳过转封装；
  否则无损转封装为 MP4 供网页预览。
- API 请求遇 429 / 5xx 自动指数退避重试；部分接口不支持 JSON 模式时自动回退。
- 服务重启后，上次遗留的运行中任务会被自动标记为失败，不会卡成僵尸任务。

## 环境要求

- Windows / Linux / macOS
- Python 3.10+
- **FFmpeg**（`ffmpeg` 与 `ffprobe` 已加入 PATH）
- 一个 **OpenAI 兼容 API** 的账号，需要具备三种模型能力：
  - 视觉模型（画面理解）
  - 文本 LLM（逐段分析）
  - ASR 语音转写模型

## 安装

```bat
cd /d D:\GitRepository\live-clip-analyzer
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## 配置

配置读取顺序（**后者覆盖前者**）：

```
1. 内置默认值
2. config.yaml           ← 提交到 git，只放占位符
3. config.local.yaml     ← git 忽略，放本机真实 key
4. 环境变量 LCA_*        ← 优先级最高
```

```yaml
# config.yaml 示例（真实 key 请放 config.local.yaml 或环境变量）
ai:
  base_url: https://api.openai.com/v1   # OpenAI 兼容接口地址
  api_key: sk-xxxx                      # 占位符
  vision_model: gpt-4o                  # 视觉模型名
  llm_model: gpt-4o-mini                # 文本模型名
  asr_model: whisper-1                  # ASR 模型名
```

环境变量对照表：

| 环境变量 | 对应配置 |
|---|---|
| `LCA_BASE_URL` | `ai.base_url` |
| `LCA_API_KEY` | `ai.api_key` |
| `LCA_VISION_MODEL` | `ai.vision_model` |
| `LCA_LLM_MODEL` | `ai.llm_model` |
| `LCA_ASR_MODEL` | `ai.asr_model` |

使用 DeepSeek 的示例（PowerShell）：

```powershell
$env:LCA_BASE_URL = "https://api.deepseek.com/v1"
$env:LCA_API_KEY  = "sk-你的key"
$env:LCA_LLM_MODEL = "deepseek-chat"
```

其余可调参数（场景粒度、评分权重、候选数量、导出模式等）见 `config.yaml`
内注释，均有安全默认值，无需修改即可运行。

## 运行

```bat
venv\Scripts\activate
python run.py
```

浏览器打开 **http://127.0.0.1:8000**。

## 使用教程

### 1. 创建任务

在左侧表单填写：

> 视频路径与弹幕路径输入框旁有 📂「浏览」按钮，点击可打开文件选择对话框：
> 从磁盘盘符开始逐级导航目录，点击目标文件后自动回填完整路径。
> 视频路径只显示视频文件、弹幕路径只显示 XML 文件；也可以直接手动输入路径。

| 字段 | 说明 |
|---|---|
| 视频路径 | 本地录播文件，如 `D:\videos\live_001.flv`（也支持 MP4） |
| 弹幕 XML 路径 | B 站弹幕文件，可留空（无弹幕时相关统计为 0） |
| 弹幕偏移（秒） | 弹幕时间与视频时间的偏差，用于对齐（如直播延迟），默认 0 |
| 输出语言 | `中文 + English` / 中文 / English |

点击「开始分析」，任务进入队列，右侧实时显示进度与阶段说明。

### 2. 查看报告

分析完成后报告页包含：

- **详细时间轴**：全部场景按时间排列，含内容概述、画面、语音、弹幕统计、
  评分与推荐等级；可按推荐等级 / 最低评分筛选。
- **长切片候选**：高分场景合并成的 1~5 分钟完整切片建议。
- **单句素材候选**：适合二创的原话引用（5~50 字）及定位时间。
- 点击任意时间段链接 → 打开视频预览页并**自动跳转到对应时间点**。

### 3. 人工复核（可选）

点击候选卡片上的「复核编辑」，可微调：起止时间、标题、评分（0~10）、
推荐等级（高/中/低）。保存后报告与导出均以**复核值**为准。

### 4. 导出

- **报告**：右上角下载中文 / English Markdown、JSON 数据。
- **视频切片**：
  - 「导出此切片」：导出单条候选；
  - 「批量导出全部候选」：一次导出全部；
  - 勾选「精切模式」= 重编码精切（起点精确到帧、较慢）；
    不勾 = 无损快速剪切（流复制、秒级完成、起点对齐关键帧可能略早）。
  - 导出结果在页面底部列出，可直接下载或点击预览。

## 视频切片导出

| 模式 | 原理 | 速度 | 起点精度 | 适用 |
|---|---|---|---|---|
| 快速剪切（默认） | `-c copy` 无损流复制 | 接近文件复制 | 对齐关键帧，可能略早 | 1~5 分钟长切片 |
| 精切 | `libx264 + aac` 重编码 | 慢一个数量级 | 精确到帧 | 几秒的单句素材 |

- 批量导出单个失败不影响其他切片，结果列表逐条标注状态与错误。
- 快速模式遇到无法流复制的源编码时自动回退重编码。
- 同名片段重复导出会自动追加时间戳，不会覆盖旧文件。

## HTTP API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/tasks` | 创建任务（`video_path` / `danmaku_path` / `offset_seconds` / `output_languages`） |
| GET | `/api/tasks` | 任务列表 |
| GET | `/api/tasks/{id}` | 任务详情（状态 / 进度 / 阶段说明） |
| DELETE | `/api/tasks/{id}?force=true` | 删除任务及其产物；运行中任务需加 `force=true` |
| GET | `/api/tasks/{id}/scenes` | 时间轴场景 |
| GET | `/api/tasks/{id}/candidates` | 切片候选 |
| PUT | `/api/tasks/{id}/candidates/{cid}/review` | 人工复核（start/end/title/score/rank） |
| GET | `/api/tasks/{id}/report?lang=zh&download=1` | Markdown 报告 |
| GET | `/api/tasks/{id}/export.json` | JSON 数据 |
| GET | `/api/tasks/{id}/video` | 转封装视频（支持 Range） |
| GET | `/api/tasks/{id}/frames/{filename}` | 抽帧图片 |
| POST | `/api/tasks/{id}/export` | 导出切片：`{"candidate_ids":[1,2], "accurate":false}`；不传则全部；也可 `{"clips":[{"start":100,"end":180,"title":"自定义"}]}` |
| GET | `/api/tasks/{id}/exports` | 导出结果列表 |
| GET | `/api/tasks/{id}/exports/{filename}` | 下载导出文件 |

交互式 API 文档：运行后访问 `/docs`。

## 隐私与安全

**API Key 的处理**

- 密钥只保存在本机（`config.local.yaml` 或环境变量），`config.yaml` 保持占位符，不会进 git。
- 代码中密钥仅用于请求头 `Authorization: Bearer …`，**不会**打印到日志、错误信息或任何导出文件。
- WebUI 设置页读取时密钥**脱敏显示**，后端接口永不回传完整密钥。

**数据流向**

- 视频**本体不上传**；仅将「音频块（ASR）、抽帧图片（视觉）、文字材料（LLM）」发送给你配置的 `base_url`。
- 分析产物（数据库、音频、抽帧、报告）都存放在本地 `data/` 目录，已被 gitignore。
- 程序无任何遥测、埋点或第三方数据收集，所有请求只发往你指定的 AI 接口。

**安全边界**

- 服务默认只绑定 `127.0.0.1`（仅本机可访问）。**请勿将 `host` 改为 `0.0.0.0`**：
  那样会无鉴权地对局域网开放整个界面（含文件浏览接口，能枚举任意本地目录）。
- 若分析的是敏感/涉密录像，请注意其抽帧图与音频会发送给 AI 服务商。

## 任务状态与常见问题

**任务状态**：`pending`（排队）→ `running`（分析中）→ `done`（完成）/ `failed`（失败）。
失败时任务列表会显示具体原因（如"视频文件不存在"、API 报错信息）。

| 现象 | 处理 |
|---|---|
| 启动时提示找不到 ffmpeg / ffprobe | 安装 FFmpeg 并加入 PATH |
| 创建任务报"视频文件不存在" | 检查路径（Windows 可用 `D:\videos\xxx.flv` 形式） |
| 弹幕时间对不上视频 | 调整「弹幕偏移」秒数后重新创建任务 |
| ASR 转写全部失败 | 检查 `asr_model` 配置与 API Key；无音轨视频会自动跳过 ASR |
| LLM / 视觉分析部分场景为空 | 单场景失败不会中断全片；检查对应模型配置 |
| 服务重启后任务显示"失败" | 预期行为：遗留任务被自动标记，重新创建即可 |
| 运行中任务无法删除 | 调用 `DELETE /api/tasks/{id}?force=true` |
| API 429 / 5xx | 内置指数退避自动重试，无需干预 |

## 目录结构

```
live-clip-analyzer/
├── app/
│   ├── main.py                  # FastAPI 入口（启动时初始化数据库、清理中断任务）
│   ├── config.py                # 配置加载（四级优先级）
│   ├── database.py              # SQLite 连接与建表
│   ├── models.py                # 数据访问层
│   ├── api/                     # HTTP 接口：任务 / 报告 / 导出
│   ├── services/                # 核心业务：弹幕 / 场景 / ASR / 视觉 / 评分 / 报告 / 导出
│   ├── workers/                 # 后台任务流水线
│   └── web/                     # 前端页面（index / preview / 样式 / 脚本）
├── docs/
│   ├── adr/                     # 架构决策记录（ADR）
│   └── features/                # 新功能设计讨论
├── data/                        # 任务产物（gitignore）：数据库、音频、抽帧、报告、导出
├── CONTEXT.md                   # 领域术语表
├── config.yaml                  # 配置（占位符）
├── requirements.txt
└── run.py                       # 启动脚本
```

## 项目文档

- [`CONTEXT.md`](CONTEXT.md)：领域术语表（任务 / 场景 / 候选 / 评分体系等定义）
- [`docs/adr/`](docs/adr/)：架构决策记录（切片导出策略、配置密钥优先级、主功能方向）
- [`docs/features/subtitle-first-segmentation.md`](docs/features/subtitle-first-segmentation.md)：字幕驱动切分的完整设计

## 字幕驱动切分（主功能，进行中）

已实现**第一步**：从 ASR 转写全文切出「话题段」——纯 Python 预筛（相邻窗关键词
相似度）找话题切换点，LLM 为每个话题段生成标题 / 摘要 / 关键词；话题段与视觉场景
并存，作为内容导航目录展示在报告页与 Markdown 报告。

下一步：在话题段内做「切片友好片段」细切（30 秒~3 分钟，可直接发布）。
完整设计见 [`docs/features/subtitle-first-segmentation.md`](docs/features/subtitle-first-segmentation.md)。

## 许可

个人学习与自用项目，未选择开源许可证。代码完全由 AI 编写、用户框架设计，
如需修改或再分发，请自行评估。
