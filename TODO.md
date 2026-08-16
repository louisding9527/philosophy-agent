# 项目待办

## 待办

- [ ] 分块逻辑升级：按句子边界切分（。！？；）+ 短段落合并，避免句中硬切与碎片化
- [ ] 显存优化备选：分块改小到 400 字（attention 显存 4 倍减负，权衡：检索粒度变细）
- [ ] 长序列性能备选：换 ONNX Runtime DirectML 后端（fused attention，长序列更高效）
- [ ] 大语料扩展：ingest/prune 的全集合扫描改为元数据表（片段数万级后再做）
- [ ] 任务表持久化：服务重启后进行中任务丢失（当前靠幂等重跑兜底）

## 已解决（历史）

- [x] 入库进度不可见（大文档看着像卡死）→ 阶段进度事件 + 分批向量化日志
- [x] AMD GPU 加速 → torch-directml + fp16 + batch 16（~10 倍速）
- [x] 文档新旧自动分辨 → 文件指纹（size+mtime）快跳过 + 片段哈希兜底
- [x] ingest 与 prune 解耦 → prune 显式清理已删除文档
- [x] 入库完成通知 → ntfy 手机推送（成功/失败）
- [x] 多格式文档入库 → markitdown 转 Markdown（pdf/docx/pptx/xlsx/html/GBK 兜底）
