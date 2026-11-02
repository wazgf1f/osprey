# Osprey 1.1.0 更新公告

发布日期：2026-11-02

## 这次新增：本地 Qwen-VL 视觉决策

现在 AI 有两种模式：

- **DeepSeek 文本**：OCR 文本 + 坐标发给 DeepSeek。
- **本地 Qwen-VL 3B / 7B**：整个桌面截图发给本地 Qwen-VL，模型真正看见屏幕，但点击坐标仍来自 OCR 框。

### 两档模型

| 档位 | 模型 | 模型大小 | 适合 |
|---|---|---:|---|
| 能用 | Qwen2.5-VL 3B | 约 3 GB | 普通配置，简单页面 |
| 精准 | Qwen2.5-VL 7B | 约 6 GB | 复杂页面，建议 8 GB+ 显存 |

### 使用方式

1. 安装 [Ollama](https://ollama.com/download)。
2. 打开 Osprey 的 **AI 指令…**，选择“本地 Qwen-VL 3B（能用）”或“7B（精准）”。
3. 第一次运行会自动执行 ollama pull 下载模型并启动 Ollama。
4. 输入自然语言指令，先试运行，再真实运行。

截图、模型和推理都在本机，不会把屏幕内容发给云端。

### 精准操作

模型看到的是带 OCR 编号的截图，只返回 element_id：

    截图 → OCR 框 + 编号 → Qwen-VL 选择 id → Osprey 点击 OCR 框中心

模型不直接猜像素坐标，因此不会因为目测而点偏。

## 命令行

    set OSPREY_AI_PROVIDER=qwen-local
    set OSPREY_AI_MODEL=7b
    osprey run examples/ai_agent.py --config examples/ai_agent.json --live

## 其他

- OCR 仍默认使用 Windows 自带引擎，可选 RapidOCR。
- 1.0.2–1.0.6 的 OCR/滚动/认证/超时修复全部包含。
- 当前本地模式需要先安装 Ollama；模型权重由 Ollama 管理。

## 已知限制

- 3B 在复杂页面或小控件上可能选错，优先试 7B。
- 本地模型推理速度取决于显卡；CPU 会明显更慢。
- 底部细扫会让单帧 OCR 约 19 秒，准确性优先。
- 需要 DeepSeek Key 的只有 DeepSeek 文本模式；本地模式不需要云端 Key。

## 反馈

如果本地模型选错元素，请附上：

- 选择的模型档位（3B/7B）
- 日志最后一条 click
- 目标文字和实际点击位置
