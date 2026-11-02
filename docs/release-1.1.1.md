# Osprey 1.1.1 更新公告

发布日期：2026-11-02

## 这次修复

**首次下载本地模型时，F12 可以中止。**

本地 Qwen-VL 第一次运行会自动执行 ollama pull，3B 约 3 GB，7B 约 6 GB。之前下载过程是阻塞的，按 F12 不能立即停止；现在会轮询安全状态：

- 按 F12 后立即终止 ollama pull
- 已经下载的部分由 Ollama 自己处理
- 不会让 Osprey 卡在模型下载里

## 包含的 1.1.0 内容

- 本地 Qwen-VL 3B（能用）/ 7B（精准）
- 整屏截图 + OCR 编号标注
- 模型只返回 element_id，点击用 OCR 框中心
- 自动安装/启动 Ollama，自动 pull 模型
- AI 对话框模型选择、安装 Ollama 按钮
- 命令行 OSPREY_AI_PROVIDER=qwen-local

## 下载

- Osprey-1.1.1-Setup.exe
- Osprey-1.1.1-win64-portable.zip

## 使用前

1. 安装 [Ollama](https://ollama.com/download)
2. 打开 AI 指令框，选择本地 Qwen-VL 3B 或 7B
3. 第一次运行会下载模型；按 F12 可以中止

## 已知限制

- 3B 复杂页面可能选错，优先 7B。
- 本地推理速度取决于显卡；CPU 更慢。
- 底部 OCR 细扫约 19 秒/帧。
