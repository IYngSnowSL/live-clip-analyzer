# live-clip-analyzer 直播切片分析工具

个人用户使用的本地直播录像切片分析工具。输入本地 FLV 视频 + B站 XML 弹幕文件，自动：

- 场景切分 + 详细时间轴
- 弹幕解析与热度/情绪统计
- ASR 语音转写
- 画面内容理解（多模态视觉模型）
- 逐段生成中/英双语分析文段
- 输出长切片候选 + 单句二创素材候选
- Web 页面人工复核微调
- 导出 Markdown 报告 + JSON 数据

## 环境要求

- Windows / Linux / macOS
- Python 3.10+
- FFmpeg（已加入 PATH）
- OpenAI 兼容 API（视觉模型 / LLM / ASR 使用同一个 base_url，不同 model 名）

## 安装

```bat
cd /d D:\GitRepository\live-clip-analyzer
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## 配置

编辑 `config.yaml`：

```yaml
ai:
  base_url: https://api.openai.com/v1   # OpenAI 兼容接口地址
  api_key: sk-xxxx                      # 你的 API Key
  vision_model: gpt-4o                  # 视觉模型
  llm_model: gpt-4o-mini                # 文本模型
  asr_model: whisper-1                  # 语音转写模型
```

## 运行

```bat
venv\Scripts\activate
python run.py
```

浏览器打开 `http://127.0.0.1:8000`。

## 使用

1. 在网页中填写：
   - 视频路径：例如 `D:\videos\live_001.flv`
   - 弹幕路径：例如 `D:\videos\live_001.xml`
   - 弹幕时间偏移：弹幕时间与视频时间的偏差秒数，默认 0
   - 输出语言：`zh` / `en` / `zh,en`
2. 创建任务后等待分析完成（长视频耗时主要在 ASR 和逐段 LLM 分析）。
3. 查看报告页：详细时间轴、长切片候选、单句素材候选。
4. 对候选进行人工微调（起止时间、标题、评分、推荐等级）。
5. 导出 Markdown / JSON。

## 创建私密 GitHub 仓库

本地已准备为 git 仓库结构。在 GitHub 网页上新建 **private** 仓库后，执行：

```bat
cd /d D:\GitRepository\live-clip-analyzer
git init
git add .
git commit -m "init: live clip analyzer"
git branch -M main
git remote add origin https://github.com/<你的用户名>/live-clip-analyzer.git
git push -u origin main
```

## 目录结构

```
live-clip-analyzer/
├── app/
│   ├── main.py                  # FastAPI 入口
│   ├── config.py                # 配置加载
│   ├── database.py              # SQLite
│   ├── models.py                # 数据访问
│   ├── api/                     # 接口
│   ├── services/                # 核心业务：弹幕/场景/ASR/视觉/评分/报告
│   ├── workers/                 # 后台任务主流程
│   └── web/                     # 前端页面
├── data/                        # 任务产物（默认 gitignore）
├── config.yaml
├── requirements.txt
└── run.py
```

## 视频导出预留

当前不实现视频导出。`app/services/` 下已预留结构，后续可新增 `exporter.py`，调用 FFmpeg 按候选起止时间裁剪视频。
