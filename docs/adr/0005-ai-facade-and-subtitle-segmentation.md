# ADR 0005：AI 能力门面 + 字幕驱动切分（粗切话题段）

- 状态：accepted
- 日期：2026-09-02

## 背景

ADR-0003 确定了主功能转向字幕驱动切分（6 项决策）。本次落地其第一步
（地基 + 粗切话题段），并顺带把 AI 调用整理成统一门面（用户诉求
"AI 配置尽可能整理成一个接口，支持视频解析与文档分析"）。

## 决策

### 1. AI 能力门面

`AIClient` 从"散落的 HTTP 调用"整理为三类语义化能力接口：

| 能力 | 方法 | 用途 |
|---|---|---|
| 文档 / 字幕分析 | `analyze_document(text, instruction, json_mode)` | 字幕切分、话题命名、摘要（LLM） |
| 视频 / 画面解析 | `describe_images(image_paths, prompt)` | 画面理解（视觉模型） |
| 语音转写 | `transcribe(file, language)` | ASR（由 `transcribe_audio` 更名） |

上层模块统一走门面，不再各自拼装 HTTP。`vision.py` 的多图回退逻辑
上收到 `describe_images` 内部，`image_to_data_url` 移入门面。

### 2. 字幕驱动切分（层次化第一级：粗切话题段）

1. **ASR 缓存**：`asr.json` 已存在则复用，避免重复转写计费。
2. **字幕整理**：`subtitle.py` 把 ASR 片段整理成带时间戳文档 + 按时间窗分块。
3. **语义切分**：`segmentation.py` 纯 Python 预筛——相邻窗字符 2-gram 关键词
   Jaccard 相似度低于阈值即视为话题切换点，据此构建无重叠话题段。
4. **话题命名**：LLM 为每个话题段生成标题 / 摘要 / 关键词（走 `analyze_document`）。
5. **数据模型**：新增 `topic_segments` 表，与 scenes / candidates 并存，零迁移。
6. **报告 / API**：`GET /api/tasks/{id}/topics` + Markdown「话题目录」章节 +
   JSON 导出含 `topics`；前端报告页展示话题目录。

## 权衡

- 边界判定暂由纯 Python 相似度决定，未引入 LLM 边界精修（控制成本与复杂度）；
  LLM 仅负责命名。阈值 `window_seconds / overlap_seconds / threshold`
  需在真实数据上调节。
- 2-gram 相似度对短文本敏感，对长窗口（600 秒，数百字）较稳定。
- 话题段与视觉场景并存（ADR-0003 Q1），评分 / 候选仍基于视觉场景，
  话题段独立呈现为导航层。

## 后果

- 细切（切片友好片段，30s~3min）留待下一步，在话题段内进行。
- AI 门面为未来新增能力（如文档识别 OCR）预留统一入口。
- 术语表新增"话题段"落地为 `topic_segments` 表；报告与导出结构新增 topics 字段。
