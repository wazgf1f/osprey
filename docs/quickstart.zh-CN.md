# 中文上手指南

这份文档只讲怎么用。匹配原理和坐标模型见 [architecture.md](architecture.md)。

## 0. 前提

- Windows 10 / 11
- Python 3.9 以上（3.10 - 3.12 测试最多）
- 不需要管理员权限
- 目标窗口必须在屏幕上可见：截屏取的是屏幕像素，最小化或被完全遮住的窗口不在画面里

## 1. 安装

**用安装包**：双击 Osprey-1.0.1-Setup.exe，阅读使用须知并勾选同意，选择安装路径，完成后从开始菜单打开 Osprey。

**从源码**：打开 PowerShell，进入项目目录：

```bat
cd C:\path\to\osprey
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e .
```

如果激活脚本被 PowerShell 拦住：

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

装完验证：

```bat
osprey --version
```

提示“无法将 osprey 项识别为 cmdlet”时，说明虚拟环境没激活，或者脚本不在 PATH，
用等价写法：

```bat
python -m osprey --version
```

想要更快的匹配（大屏幕提升明显，可选）：

```bat
python -m pip install -e ".[opencv]"
```

## 2. 先自检

```bat
osprey doctor
```

正常输出类似：

```
osprey 1.0.1
python      : 3.12.14
platform    : Windows-11-10.0.26300-SP0 (AMD64)
numpy       : 2.3.5
pillow      : 12.3.0
opencv      : not installed (numpy backend will be used)
dpi aware   : True
dpi scale   : 1.500x
monitor 0   : 2560x1600 at (0, 0)  [primary]
screen      : 2560x1600 at origin (0, 0)
capture ms  : min 36.5  mean 44.5  max 53.6
brightness  : 204.7 (0 means a black or locked screen)
input       : ok (cursor moved and was restored)
status      : ready
```

几个关键行：

| 行 | 含义 | 异常时怎么办 |
|---|---|---|
| `dpi scale` | 系统缩放，1.5 表示 150% | 非 1.0 属正常，Osprey 已做 DPI 感知 |
| `monitor N` | 每块显示器的分辨率和位置 | 确认目标窗口在哪块屏 |
| `capture ms` | 截一张图的耗时 | 超过 100ms 检查是否开了省电/远程桌面 |
| `brightness` | 画面亮度，0 表示黑屏 | 锁屏、UAC 弹窗、最小化 RDP 都会是黑的 |
| `input` | 能否模拟键鼠 | 显示 BLOCKED 时只能 dry-run，见第 9 节 |

## 3. 五分钟跑通识别

### 3.1 截一张全屏图

```bat
osprey grab shot.png
```

用看图软件打开 `shot.png`，确认能看到目标窗口。

### 3.2 把目标控件截成模板

假设按钮在屏幕 (900, 500) 开始、大小 220x64：

```bat
osprey crop button.png --region 900,500,220,64
```

`crop` 截取的是**当前屏幕**的这块区域，所以执行时按钮必须真的在那里。
坐标是桌面绝对像素，可以用 Win+Shift+S 截图时读到的位置。

### 3.3 让 Osprey 自己找

```bat
osprey find button.png --threshold 0.85 --save marked.png
```

输出：

```
x=900 y=500 w=220 h=64 score=0.9987 scale=1.000 desktop=(900,500)
annotated frame saved to marked.png
```

- `x y w h` 是相对截图的坐标
- `desktop=(x, y)` 才是可以点击的桌面坐标
- `score` 越接近 1 越像；0.85 以上通常可用
- 打开 `marked.png` 看红框是否正好框住按钮

这一步成功，说明截屏、匹配、坐标换算都是对的。

## 3.5 图形界面（推荐）

不想写 Python 的话，用可视化编辑器：

```bat
osprey gui
```

安装版可以直接从开始菜单打开 Osprey，选 **8. 可视化编辑器**。

流程：

1. 把目标窗口摆在屏幕上，点 **框选模板并添加点击**，拖一个框把按钮框住；
2. 选中步骤，双击可改 **之后等待**、超时、阈值；
3. 用 **添加等待** / **添加按键** 插入停顿和回车、ESC；
4. 要滑动时点 **添加滑动**，填起点、终点（桌面坐标）、时长和鼠标键；
   运行时会按下、拖动、再释放；
5. 选中一步点 **复制步骤**（或 Ctrl+D）可以复制出相同的步骤，副本会保留
   模板、等待、阈值、超时、缩放和滑动坐标；
6. 用 **上移 / 下移** 调整点击顺序；
7. 先点 **试运行**（只识别，不动鼠标），看日志里的顺序和分数；
8. 再点 **真实运行**，会弹确认框；
9. 点 **保存**，得到 plan.json，以后可以直接跑：

```bat
osprey play plan.json
```

每一步的 **之后等待** 就是两步之间的间隔；右上角 **循环** 填 0 表示一直重复，
直到按 F12 或点 **停止**。

## 4. 写第一个任务

目录建议这样放（相对项目根目录）：

```
tasks/
  accept.py
  config.json
  assets/
    accept.png
```

`accept.py`：

```python
from osprey.core.task import Task


class Accept(Task):
    name = "accept"

    def setup(self, ctx):
        # 相对 assets_dir 的路径
        self.template = "accept.png"
        self.clicks = 0

    def step(self, ctx):
        # roi 限定搜索范围：左上角 (600, 300)，大小 1200x700
        # 不写 roi 就全屏搜索，慢一些，也更容易误匹配
        button = ctx.locate(self.template, threshold=0.87, roi=(600, 300, 1200, 700))
        if button is None:
            return

        x, y = ctx.point(button)
        ctx.logger.info("找到按钮：桌面坐标 (%.0f, %.0f)，分数 %.3f", x, y, button.score)
        ctx.click(button)
        self.clicks += 1
        ctx.sleep(0.8)          # 等界面反应；这个 sleep 可被 F12 打断

        if self.clicks >= 3:
            ctx.safety.request_stop("点满三次，收工")
```

`config.json`：

```json
{
  "assets_dir": "tasks/assets",
  "threshold": 0.87,
  "scales": [1.0],
  "fps": 6,
  "max_runtime": 300,
  "abort_keys": ["f12"]
}
```

引擎会按 `fps` 循环：截屏 -> 调 `step(ctx)` -> 执行你排队的点击 -> 进入下一轮。
`setup` 只跑一次，`teardown` 在退出时一定跑。

### 任务里最常用的几个东西

| 写法 | 作用 |
|---|---|
| `ctx.locate(模板, threshold=0.87, roi=(x,y,w,h), scales=(1.0,))` | 找最佳匹配，没有返回 `None` |
| `ctx.locate_all(...)` | 找所有超过阈值的匹配 |
| `ctx.wait_for(模板, timeout=10)` | 阻塞等它出现 |
| `ctx.point(det)` | 把匹配结果换算成桌面坐标 |
| `ctx.click(det, button="left")` | 移动并点击 |
| `ctx.move(det)` | 只移动不点击 |
| `ctx.sleep(秒)` | 可被 F12 打断的等待 |
| `ctx.snapshot("debug.png")` | 存当前画面，排查用 |
| `ctx.safety.request_stop("原因")` | 主动结束 |

## 5. 先 dry-run，再 live

```bat
REM 只识别、只记录，不发送任何键鼠
osprey run tasks/accept.py --config tasks/config.json

REM 确认无误后，才真正点击
osprey run tasks/accept.py --config tasks/config.json --live
```

第一次务必用 dry-run，并且找一个无关紧要的窗口试，不要拿正在编辑的文档试。

结束时输出统计：

```json
{
  "ticks": 42,
  "detections": 3,
  "actions": 3,
  "errors": 0,
  "elapsed": 7.2,
  "fps": 5.8,
  "stop_reason": "点满三次，收工"
}
```

## 6. 常用命令参数

```bat
osprey run 任务.py --config 配置.json     REM 用配置跑
osprey run 任务.py --fps 10               REM 覆盖帧率
osprey run 任务.py --duration 60          REM 最多跑 60 秒
osprey run 任务.py --max-runtime 600      REM 安全上限，到点强制停
osprey run 任务.py --live                 REM 真正发送输入
osprey run 任务.py --assets-dir tasks/assets
```

`--duration` 是正常结束，`--max-runtime` 是兜底保险，两个都可以不写。

## 7. 调参：找不到、点不准、太慢

| 现象 | 先调什么 |
|---|---|
| 完全找不到 | 用 `crop` 在**这台机器、这个缩放比例**下重截模板；确认 ROI 没框错；阈值降到 0.8 试试 |
| 找得到但点偏 | 跑 `osprey doctor` 看 `dpi aware` 是否 True；点击一律用 `ctx.click(det)`，不要自己加减坐标 |
| 误点别的控件 | 提高阈值到 0.9；加 ROI；或者换更有辨识度的模板（按钮局部而不是整个窗口） |
| 太慢 | 加 ROI；`scales` 只留必要的；降 `fps`；装 opencv |
| 改了分辨率后行为异常 | 重启任务即可，截屏缓冲会自动重建；ROI 坐标要按新分辨率重算 |
| 换一台电脑就找不到 | 模板是在旧缩放比例下截的，用 `crop` 重截，或配置里加 `"scales": [1.0, 1.25, 1.5]` |

阈值经验：同机同缩放，0.86 - 0.92 很稳；跨主题/深色模式，0.78 - 0.85；低于 0.75 误匹配会明显变多。

## 8. 怎么停下来

- **F12**：全局急停，任何时候都有效，任务在 sleep 里也能停
- 配置文件里的 `stop_file`：创建那个文件，下一轮就退出
- `--max-runtime`：到时间强制结束
- Ctrl+C：命令行中断
- 退出时会自动释放还按着的键和鼠标

## 9. 多显示器、分辨率、输入被拦

**多显示器**：默认只截主屏。目标可能在副屏时：

```bat
osprey grab all.png --all-screens
osprey find button.png --all-screens
```

或在配置里写 `"all_screens": true`，让 `osprey run` 也截全部屏幕。

**分辨率变化**：运行中改分辨率、插拔显示器，截屏缓冲会自动重建；
如果指定的 ROI 放不下了，会直接报错，不会悄悄截错位置。

**input BLOCKED**：`doctor` 显示这行，说明当前桌面拒绝合成输入。
常见于部分 RDP 会话、沙箱、锁定的 kiosk。截屏和 dry-run 仍然可用；
要真实点击，请在本地正常的交互式桌面上运行。

## 10. 常见报错

| 报错 | 原因 | 解决 |
|---|---|---|
| `ModuleNotFoundError: No module named 'osprey'` | 没激活虚拟环境 | `.venv\Scripts\activate`，或设 `PYTHONPATH=src` |
| `osprey 不是内部或外部命令` | 脚本不在 PATH | 用 `python -m osprey ...` |
| `config file not found` | 路径相对当前目录 | 在项目根目录执行，或写绝对路径 |
| `template not found` | 模板路径不对 | 检查 `assets_dir` 和文件名 |
| `no scale fits` | 模板比画面还大 | 重新截小一点的模板 |
| `region ... is outside the desktop` | ROI 超出屏幕 | 用 `doctor` 看实际分辨率 |

## 11. 自检与演示

```bat
REM 验证本机截屏 + 匹配是否准确（不改动任何东西）
python tools/selftest.py

REM 生成演示用目标卡片，然后用看图软件打开它
python tools/make_target.py
start examples\assets\target.png

REM 找它并点击（默认 dry-run）
python examples\click_demo.py
python examples\click_demo.py --live
```

## 12. 边界

只在你拥有或获授权的系统上使用。自动化游戏/服务通常违反其服务条款，
反作弊也可能检测到合成输入。本项目明确不用于伪造上课出勤、观看时长、
考试或任何学术考核。
