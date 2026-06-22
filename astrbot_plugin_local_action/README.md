# LocalAction

LocalAction 是 AstrBot 本地快捷动作路由插件。消息命中配置规则后，插件会直接执行本机动作或本机命令，并阻止该消息继续进入大模型流程。

## 配置入口

主要配置入口是 AstrBot 插件页面中的 LocalAction 独立设置页，页面包含 `QuickAction`、`QuickCommand` 和 `高级设置` 三个区域。

AstrBot 原生齿轮设置只作为基础和兼容入口保留。已经由新 UI 管理的重复字段会在旧设置里隐藏，避免同一项配置在两个地方同时编辑；隐藏字段仍会保留在配置结构中，防止 AstrBot 重载时清空已保存数据。

## 默认行为

- `QuickAction` 默认开启，仅管理员可用，内置一条“屏幕截图”规则。
- 默认屏幕截图规则的触发关键词是 `屏幕截图`，匹配方式是 `contains`。
- `QuickCommand` 默认关闭，仅管理员可用，不内置预定义命令。
- `QuickCommand` 默认启用模式级二次确认，确认语为 `确认`，超时 `30` 秒。
- `QuickCommand` 默认与 `QuickAction` 渠道范围保持一致。
- `高级设置` 默认关闭。关闭时，文件大小上限、文件动作白名单路径、休眠/唤醒控制都不生效。
- 启用高级设置并启用休眠/唤醒控制后，休眠状态会持久化。插件重载或重启后会保留永久休眠状态，也会保留仍未过期的临时休眠计时。

## 规则匹配

每条规则通过 `trigger_keywords` 配置一个或多个触发关键词，通过 `match_mode` 配置匹配方式。消息匹配前会去掉首尾空白；多个触发关键词只要任意一个命中，就会触发该规则。

支持的匹配方式：

- `contains`：消息中包含关键词即匹配。
- `exact`：整条消息必须等于关键词。
- `prefix`：消息必须以关键词开头。
- `regex`：关键词按 Python 正则表达式处理。

同一条消息最多只触发一条规则。路由顺序固定为先检查 `QuickAction`，再检查 `QuickCommand`；每个模式内部按规则列表从上到下匹配。命中第一条规则后会立即执行、请求确认或返回拦截提示，不会继续尝试后续规则。

## QuickAction

QuickAction 用于执行本机动作。当前 UI 支持的动作类型包括：

- `screenshot_fullscreen`：截取全屏。
- `screenshot_window`：按窗口选择器截取指定窗口。
- `list_windows`：列出可见窗口。
- `read_file`：读取文件全文。
- `tail_file`：读取文件尾部若干行。
- `send_file`：发送本地文件。
- `close_process`：按窗口选择器找到窗口后关闭所属进程。

QuickAction 模式设置保留：

- 启用开关。
- 仅管理员可用。
- 模式级二次确认。
- 模式级渠道范围。
- 规则列表。
- 通知模板。

文件动作受高级设置控制：高级设置关闭时不检查 `allowed_paths` 和文件大小上限；高级设置开启后，`allowed_paths` 留空表示不启用路径白名单，填写后文件路径必须位于白名单内。文件大小上限留空或填负数表示不限制，填 `0` 表示阻止所有文件动作。

## QuickCommand

QuickCommand 用于执行固定本地命令。当前新 UI 中每条 QuickCommand 规则只支持 `run_command`，动作名称显示为“执行命令”，不再提供动作类型选择。

QuickCommand 模式设置保留：

- 启用开关。
- 仅管理员可用。
- 模式级二次确认。
- 与 QuickAction 渠道范围保持一致。
- 模式级渠道范围。
- Shell 会话模式。
- 规则列表。
- 通知模板。

每条命令规则包含：

- 命令名称。
- 触发关键词和匹配模式。
- 执行命令。
- Shell。
- 超时秒数。

Shell 支持手动输入，也会读取本机已检测到的执行器作为选项。当前检测候选包括 `pwsh`、`powershell`、`cmd`、`bash`、`sh` 和 `wsl`；Windows 下还会检查常见系统路径。

旧配置中的 `run_predefined_command` 会在兼容迁移中转为 `run_command`。当前版本没有默认预定义命令。

## Shell 会话模式

QuickCommand 额外提供 Shell 会话模式。启用后，用户发送触发关键词会进入会话，后续消息会直接作为命令交给配置的 Shell 执行，并返回执行结果。

会话配置包括：

- 触发关键词，默认 `ssh`。
- 退出关键词，默认 `exit`、`退出`。
- 匹配模式，默认 `exact`。
- Shell，默认 `pwsh`。
- 超时秒数，默认 `1000`。

进入会话后，每收到一条非退出消息都会刷新超时时间。收到退出关键词或超时后，会话结束。Shell 会话模式仍受 QuickCommand 的启用状态、管理员限制和模式级渠道范围控制。

## 渠道范围

模式级渠道范围支持：

- `global`：所有渠道可触发。
- `include`：仅包含列表中的渠道可触发。
- `exclude`：排除列表中的渠道不可触发。
- `custom`：按平台名匹配。

QuickCommand 默认与 QuickAction 渠道范围保持一致。关闭该同步后，可以单独设置 QuickCommand 的模式级渠道范围。

本版本不开放单条规则独立渠道范围。旧配置中相关字段会保留为兼容字段，但运行时固定关闭。

## 二次确认

模式级二次确认保留在 QuickAction / QuickCommand 各自的模式设置中，不属于高级设置。

启用后，命中规则时会先提示用户在指定时间内回复确认词，确认词匹配后才执行动作。QuickAction 默认关闭模式级二次确认，QuickCommand 默认开启模式级二次确认。

本版本不开放单条规则独立二次确认。旧配置中相关字段会保留为兼容字段，但运行时固定关闭。

## 高级设置

高级设置当前只控制这些能力：

- 文件大小上限。
- QuickAction 文件动作白名单路径。
- 休眠/唤醒控制。

高级设置不控制模式级二次确认。模式级二次确认在 QuickAction / QuickCommand 各自设置中配置。

## 休眠和唤醒

休眠/唤醒属于高级设置能力，必须先启用高级设置并启用休眠/唤醒控制才会生效。

当前版本只支持全局休眠：

- 临时休眠关键词默认 `休眠`，默认休眠 `3600` 秒。
- 永久休眠关键词默认 `永久休眠`。
- 唤醒关键词默认 `唤醒`。
- 全部唤醒兼容关键词默认 `全部唤醒`、`唤醒全部`。
- 状态查询关键词默认 `休眠状态`，固定按完全匹配处理。
- 默认仅管理员可控制休眠/唤醒。

“休眠”等价于休眠全部 LocalAction 拦截，“唤醒”和全部唤醒兼容关键词都等价于唤醒全部 LocalAction 拦截。模式级休眠、规则级休眠、允许全局休眠开关和持久化休眠状态开关在本版本不开放；高级设置启用时运行时固定为全局休眠且休眠状态持久化。

## 风险提示

首次打开 LocalAction 独立设置页时，会弹出一次风险提示，确认后写入 `risk_ack.json`。

某个用户第一次实际触发 QuickAction 或 QuickCommand 时，插件会在该用户所在会话发送一次风险提醒，然后继续正常执行原指令。这个提醒按 `平台名:用户 ID` 记录，不是按会话记录。

## 本版本不做的功能

当前代码中明确不开放或已移除的功能：

- 单条规则独立渠道范围。
- 单条规则独立二次确认。
- 模式级或规则级独立休眠。
- 允许全局休眠开关。
- 持久化休眠状态开关。
- QuickAction 敏感文件名关键词。
- QuickCommand 命令危险关键词。
- QuickCommand 关闭进程动作保护名单。
- 默认预定义 QuickCommand 命令。

## 窗口选择器

窗口相关动作使用选择器匹配窗口。常用字段包括：

```json
{
  "process": "Code.exe",
  "title_contains": "main.py",
  "class": "Chrome_WidgetWin_1"
}
```

指定窗口截图示例：

```json
{
  "name": "Codex窗口截图",
  "trigger_keywords": ["Codex窗口截图"],
  "match_mode": "exact",
  "action": {
    "type": "screenshot_window",
    "selector": {
      "process": "Codex.exe",
      "title_contains": "Codex"
    }
  }
}
```

关闭匹配窗口所属进程示例：

```json
{
  "name": "关闭目标窗口进程",
  "trigger_keywords": ["关闭目标窗口进程"],
  "match_mode": "exact",
  "action": {
    "type": "close_process",
    "selector": {
      "process": "notepad.exe",
      "title_contains": "临时记录"
    },
    "force": true,
    "include_children": true
  }
}
```

`close_process` 会拒绝关闭当前 AstrBot 插件进程，但不会做额外的保护名单判断。
