# Changelog

## v0.3.0 — 推倒重建：自动打轴为唯一核心

按用户重新定义的产品定位（切片生产者，产物用于二创发布）推倒重建（ADR-0006）。

### 核心：自动打轴
- 新流水线：ffprobe → 音频提取 + 转封装 → ASR 转写（缓存）→ LLM 分窗找内容点并初步打轴
  → 内容点合并 + 长度约束（目标 1~3 分钟，硬上限 10 分钟）→ **静音点精修**（ffmpeg silencedetect）
  → axles 表保存
- 每个轴输出：精确起止时间 + 标题 + 推荐理由 + 评分
- 大量候选（默认最多 100 个），按评分排序，人工挑选
- 新增 `app/services/axle.py`（核心）、`app/api/axles.py`（列表 / 复核 / CSV）
- **CSV 导出**（BOM，直接对照剪辑软件打轴）
- 人工复核（起止时间 / 标题），导出以复核值为准

### 删除（判为臃肿）
- 视觉场景检测与 8~30 秒时间轴、画面理解（视觉模型调用）
- 弹幕统计、话题段（粗切）、综合加权评分
- 中英双语报告（改为中文轴清单 + CSV）
- 移除模块：scene_detect / vision / danmaku / timeline / scorer / candidates / segmentation / subtitle / report

### 保留
- 任务管理、ASR、AI 门面（LLM / 视觉 / ASR 能力接口）、切片导出（快切 / 精切）、
  视频预览跳转、文件浏览、WebUI 配置页（密钥脱敏）

## v0.2.1 — 配置安全与健壮性

（已废弃，见 v0.3.0）

## v0.2.0 — DeepSeek UI Release

（已废弃，见 v0.3.0）
