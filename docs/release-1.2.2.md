# Osprey 1.2.2 更新公告

发布日期：2026-11-03

## 这次修复

**直接启动 Osprey 不再报 arguments are required: command。**

- 直接运行 osprey.exe（不带参数）现在默认打开可视化编辑器
- 桌面/开始菜单快捷方式不再指向 osprey.bat 菜单，而是直接 osprey.exe gui
- 命令行用法保持不变：osprey doctor/grab/find/run/gui...

之前双击 exe 会进入 argparse 错误，是因为程序强制要求子命令；现在无参数会进入 GUI。

## 同时包含

- 1.2.1 的 UI 动效：淡入、标题栏流光、按钮悬停、状态呼吸灯
- 1.2.0 的深色 Python UI
- AI 对话框按钮完整显示
- 取消模型下载不崩溃
- 3B/7B 下载确认、大小提示、进度条、可取消

## 下载

- Osprey-1.2.2-Setup.exe
- Osprey-1.2.2-win64-portable.zip
