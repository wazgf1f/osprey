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
- 已用真实 qwen2.5vl:3b 跑通 dry-run：1 次动作、0 错误

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
