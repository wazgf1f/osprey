# Osprey 1.2.3 更新公告

发布日期：2026-11-03

## 新增：单实例，不再重复打开

现在每次双击快捷方式启动 Osprey 时，会先检查是否已有编辑器在运行：

- **已有实例**：直接把现有窗口从后台调到前台
- **窗口已最小化**：自动恢复
- **没有实例**：正常启动新编辑器
- 不会出现多个 Osprey 编辑器窗口

实现方式：

- 使用 Windows 命名互斥量 Local\Osprey.Editor.Instance 判断实例
- 已有实例时用 FindWindow 找到 “Osprey 计划编辑器”
- ShowWindow / BringWindowToTop / SetForegroundWindow 恢复并置前

## 本地 Qwen-VL 修复

- 3B 默认只有 4096 context，之前 1 万多 tokens 会直接 HTTP 400
- 现在请求显式设置 num_ctx=16384，并把 OCR 元素限制在 80 个
- 兼容 3B 的 terminate / left_click / scroll_down 别名和 coordinate 输出，
  最终仍映射到 OCR 元素点击
- 模型改用单行协议 CLICK / WAIT / SCROLL / DONE；如果 3B 仍输出无效内容，
  Osprey 会用 OCR 文本匹配做兜底，不再每帧报错空转

### 7B 的 8G 显存优化

7B 现在自动使用低显存档：

- num_ctx 从 16384 降到 8192
- 截图宽度从 1600 降到 1024
- OCR 元素从 80 降到 50
- num_batch 64，降低峰值显存
- 启动 Ollama 时默认开启 FlashAttention、q8 KV cache、单并发

如果 Ollama 已经由桌面程序常驻，需要重启 Ollama 才能应用新的环境变量。
- 已用真实 qwen2.5vl:3b 跑通 dry-run：0 错误，并产生动作

## 日志

每次启动在 %LOCALAPPDATA%\Osprey\logs 写独立文本日志，可用 osprey logs --open 查看。

## 同时包含

- 1.2.2：无参数启动默认打开 GUI，快捷方式直接 osprey.exe gui
- 1.2.1：窗口淡入、标题栏流光、按钮悬停、状态呼吸灯
- 深色 Python UI
- AI 模型下载确认、大小提示、进度条、取消
- 取消下载不崩溃

## 下载

- Osprey-1.2.3-Setup.exe
- Osprey-1.2.3-win64-portable.zip
