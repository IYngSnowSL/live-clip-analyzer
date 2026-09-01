# Changelog

## v0.2.1 — 配置安全与健壮性

### 配置安全
- 配置改为四级优先级：默认值 < `config.yaml` < `config.local.yaml` < `LCA_*` 环境变量
- 新增 `config.local.yaml` 覆盖机制（git 忽略，放真实 key）
- 支持 `LCA_BASE_URL` / `LCA_API_KEY` / `LCA_VISION_MODEL` / `LCA_LLM_MODEL` / `LCA_ASR_MODEL`

### 修复
- LLM 时间轴分析不再输出冗余 `rank` 字段（rank 统一由评分计算）
- `refine_scenes` 合并判断清理死代码，行为不变
- 服务重启后遗留的 running/pending 任务自动标记 failed，不再产生僵尸任务
- 删除任务接口支持 `?force=true` 强制删除
- 导出结果列表刷新后保留标题（新增 `exports_meta.json` 持久化）
- 同名片段重复导出时自动追加时间戳，避免覆盖旧文件
- 单句素材候选的双语报告统一显示原话引用

### 优化
- 源视频已是浏览器可播的 MP4（H.264 + AAC/MP3/无音轨）时跳过转封装
- 清理未使用的 `python-multipart` 依赖

### 仓库卫生
- 移除一次性个人脚本 `setup_github_private.bat` / `push_to_github.bat` / `git_diag.bat`
- 修复 `.gitignore` 中文注释乱码

### 文档
- 新增 `CONTEXT.md` 领域术语表
- 新增 `docs/adr/` 架构决策记录（切片导出策略、配置密钥优先级）
- 新增 `docs/features/subtitle-first-segmentation.md`：字幕驱动切分新功能设计讨论
- README 重写：配置说明、目录结构、文档索引

## v0.2.0 — DeepSeek UI Release

### Web UI
- 全新浅色 DeepSeek 风格界面
- 左侧任务栏 + 右侧报告区布局
- 移动端侧栏抽屉
- 空状态引导页
- 任务高亮、删除后自动回到空状态
- 视频预览页同步改为浅色风格

### 视频切片导出
- 新增 `app/services/exporter.py`
- 快速模式：`-c copy` 无损剪切
- 精切模式：H.264 + AAC 重编码
- 支持单个 / 批量 / 自定义片段导出
- 新增导出结果列表与下载接口

### 稳定性
- 长 FLV 音频提取改为整段提取 + 快速切块
- ASR 单块失败自动跳过，全部失败才终止
- API 429 / 5xx 自动重试
- 评分权重自动归一化
- 路径穿越防护
- 场景检测失败自动降级为固定时长切分
