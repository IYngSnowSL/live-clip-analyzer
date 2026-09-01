# live-clip-analyzer · 直播切片分析工具

> v0.3.0 · 本地运行 · 个人使用

> **🤖 AI 声明**
> 本软件完全由 AI 编写，仅由用户进行框架设计与需求定义。

## 这是什么？

一款**本地直播录像自动打轴工具**，核心目的：

> **为切片二创自动"打轴"：输入录播视频，自动分析字幕，找出所有值得切的内容点，
> 输出每个可切片片段的精确起止时间、标题与推荐理由——把手工反复拖进度条找片段的活
> 交给 AI，切片生产者只需挑选和微调。**

输入一段直播录播视频（FLV / MP4），全自动完成：

- 🎙️ ASR 全量语音转写（结果缓存，重跑不重复计费）
- 🤖 LLM 分窗分析字幕，找出名场面 / 趣点 / 高光 / 爆点并初步打轴
- ✂️ 内容点合并与长度约束（目标 1~3 分钟，硬上限 10 分钟）
- 🔇 **静音点精修**：用 ffmpeg 静音检测微调每个轴的起止，切出来的片子头尾干净
- 📋 每个轴：精确起止时间 + 标题 + 推荐理由 + 评分
- ✅ 人工复核：微调起止时间与标题，导出以复核值为准
- 📄 **CSV 导出**：序号 / 起止时间 / 时长 / 标题 / 理由 / 评分，直接对照剪辑软件打轴
- 🎬 **切片导出**：单个 / 批量导出视频文件（无损快切 / 精切重编码）

分析全程在本地完成，不上传视频本体，仅将音频块与文字材料发送到你配置的
OpenAI 兼容 API（LLM / ASR）。

## 环境要求

- Windows / Linux / macOS
- Python 3.10+
- FFmpeg（`ffmpeg` 与 `ffprobe` 已加入 PATH）
- OpenAI 兼容 API：需要 **LLM**（找内容点）与 **ASR**（语音转写）两种模型

## 安装

```bat
cd /d D:\GitRepository\live-clip-analyzer
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## 配置

配置读取顺序（**后者覆盖前者**）：内置默认值 < `config.yaml` < `config.local.yaml` < `LCA_*` 环境变量。

WebUI 左下角「⚙️ 设置」可图形化配置（保存后下一个任务生效，密钥脱敏显示）。

```yaml
# config.yaml 关键项（真实 key 请放 config.local.yaml 或环境变量）
ai:
  base_url: https://api.openai.com/v1   # OpenAI 兼容接口
  api_key: sk-xxxx
  llm_model: gpt-4o-mini                # 文本模型（找内容点/打轴）
  asr_model: whisper-1                  # ASR 模型（语音转写）

axle:
  target_min_seconds: 60                # 目标最短时长（秒）= 1 分钟
  target_max_seconds: 180               # 目标最长时长（秒）= 3 分钟
  hard_max_seconds: 600                 # 硬上限（秒）= 10 分钟
  max_axles: 100                        # 最多输出轴数
```

环境变量：`LCA_BASE_URL` / `LCA_API_KEY` / `LCA_LLM_MODEL` / `LCA_ASR_MODEL` 等。

## 运行

```bat
python run.py
```

浏览器打开 **http://127.0.0.1:8000**。

## 使用教程

### 1. 创建任务

左侧表单填视频路径（可用 📂 浏览选择），点击「开始打轴」。

### 2. 查看轴

分析完成后，报告页按评分排序展示全部切片轴：

| 字段 | 说明 |
|---|---|
| 时间 | `[HH:MM:SS - HH:MM:SS]`，点击跳转视频预览（自动定位到起点） |
| 标题 | 这个片段的切片标题 |
| 理由 | 为什么值得切（名场面 / 趣点 / 爆点…） |
| 评分 | 0~10，LLM 评定，可按最低评分筛选 |

### 3. 复核（可选）

点「复核打轴」微调起止时间与标题；保存后导出以复核值为准。

### 4. 导出

- **CSV**：右上角「导出 CSV」——直接对照剪辑软件打轴。
- **切片**：「导出此切片」/「批量导出全部」；勾选精切模式 = 重编码（起点精确到帧），
  不勾 = 无损快速剪切（秒级完成，起点对齐关键帧）。

## 视频切片导出

| 模式 | 原理 | 速度 | 起点精度 |
|---|---|---|---|
| 快速剪切（默认） | `-c copy` 无损流复制 | 接近文件复制 | 对齐关键帧，可能略早 |
| 精切 | `libx264 + aac` 重编码 | 慢一个数量级 | 精确到帧 |

## HTTP API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/tasks` | 创建任务（`video_path` / `danmaku_path` / `offset_seconds`） |
| GET | `/api/tasks` | 任务列表 |
| GET | `/api/tasks/{id}` | 任务详情 |
| DELETE | `/api/tasks/{id}?force=true` | 删除任务；运行中需 `force=true` |
| GET | `/api/tasks/{id}/axles` | 打轴结果列表 |
| PUT | `/api/tasks/{id}/axles/{axle_id}/review` | 复核（start/end/title） |
| GET | `/api/tasks/{id}/axles.csv` | 轴清单 CSV 导出 |
| GET | `/api/tasks/{id}/video` | 视频预览（支持 Range 跳转） |
| POST | `/api/tasks/{id}/export` | 导出切片：`{"axle_ids":[1,2]}` 或自定义 `{"clips":[{"start":100,"end":180}]}` |
| GET | `/api/tasks/{id}/exports` | 导出结果列表 |
| GET | `/api/tasks/{id}/exports/{filename}` | 下载导出文件 |
| GET/PUT | `/api/config` | WebUI 配置读写（密钥脱敏） |
| GET | `/api/files/ls?path=…&filter=video` | 本地文件浏览 |

## 隐私与安全

- 密钥只存本机（`config.local.yaml` / 环境变量），不会打印、不会进 git。
- 视频本体不上传；仅音频块（ASR）与文字（LLM）发送给你配置的 `base_url`。
- 服务默认只绑定 `127.0.0.1`；**请勿改 `host` 为 0.0.0.0**（会无鉴权暴露文件浏览接口）。

## 目录结构

```
live-clip-analyzer/
├── app/
│   ├── main.py                  # FastAPI 入口
│   ├── config.py                # 配置加载（四级优先级）
│   ├── database.py              # SQLite（tasks + axles）
│   ├── models.py                # 数据访问
│   ├── api/                     # 任务 / 轴 / 导出 / 配置 / 文件浏览
│   ├── services/
│   │   ├── axle.py              # ★ 自动打轴核心（LLM 找点 + 合并 + 静音精修）
│   │   ├── asr.py               # 语音转写
│   │   ├── ai_client.py         # AI 能力门面
│   │   ├── ffmpeg_utils.py      # ffmpeg 封装
│   │   └── exporter.py          # 切片导出
│   ├── workers/                 # 后台任务流水线
│   └── web/                     # 前端
├── docs/adr/                    # 架构决策记录
├── data/                        # 任务产物（gitignore）
└── config.yaml
```

## 项目文档

- [`docs/adr/`](docs/adr/)：架构决策记录（含 0006 推倒重建、0005 AI 门面等）
- [`CONTEXT.md`](CONTEXT.md)：领域术语表（轴 / 任务 / 复核等定义）

## 许可

个人学习与自用项目，未选择开源许可证。代码完全由 AI 编写、用户框架设计。
