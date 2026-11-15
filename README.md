# 豆瓣FM 红心歌单导出SKILL (ADB · Android · USB 调试)

> Export your Douban FM "红心 / 我喜欢" (red-heart) playlist to a local CSV — via ADB UI scraping on an Android phone with **开发者选项 + USB 调试** enabled.

**本仓库用来把豆瓣FM（`com.douban.radio`，现由酷我运营）的「红心 / 我喜欢」歌单，导出成一份本地 CSV 备份。**

⚠️ 豆瓣FM **没有任何官方导出功能**。本方案是目前唯一验证可行的路径：借助 **ADB（Android Debug Bridge）** 驱动一台已开启「开发者选项 + USB 调试」的安卓手机，自动滚屏抓取红心列表界面上显示的歌名 / 歌手，再清洗去重，输出干净的 CSV。

> **同一天拿到了自己豆瓣电影 + 豆瓣FM 的数字资产。** 🎬🎵
> 电影部分用的是另一套工具（见文末「推荐：豆瓣电影导出」），FM 红心部分就是本仓库。两份个人数据，都在同一天本地化落地。

---

## 📋 前置条件（必备）

| 条件 | 说明 |
|---|---|
| 一台安卓手机（或安卓模拟器） | 能登录豆瓣FM，且**红心列表里确实有歌**（登录后先肉眼确认非空；2023 年停运换酷我运营，部分老账号历史红心可能未迁移而丢失） |
| 一台电脑（Win / macOS / Linux） | 已安装 `platform-tools`（含 `adb`）；Windows 用 PowerShell，macOS 用 Python 3 |
| USB 数据线（非纯充电线） | 真机路径必需；模拟器可走本地 adb |
| 开发者选项 + USB 调试 | `adb devices` 能看到设备且状态为 `device` |
| **MIUI / 部分定制系统：额外开启「USB 调试（安全设置）」** | 否则 `adb shell input swipe` 会被系统拦截、界面不滚动（报 `INJECT_EVENTS` 错误） |
| Python 3 | macOS 抓取脚本和清洗去重脚本均使用 Python 标准库 |

### 必备硬件
- 安卓设备 1 台（真机推荐屏幕大的，如平板；或 Windows 上的雷电 / MuMu / BlueStacks 模拟器）
- 电脑 1 台
- USB 数据线 1 根（真机必需）
- 稳定电量 / 常亮屏（实测每 2000 首约 25 分钟，建议预留 25–35 分钟；全程需亮屏不锁屏，见下方实测说明）

---

## ⏱ 实测耗时与可获取范围

### 每 2000 首需要多久？

2026-11-15 使用 Redmi K20 Pro 和 Apple Silicon Mac 抓取时，**2711 条独立歌曲共耗时 36 分 57 秒**，包括到列表末尾后的停止检查。日志显示第 2000 条出现在第 368 次滑动；按全程平均每屏约 4.1 秒推算，达到 2000 首约需 **25 分钟**。日志没有逐屏时间戳，因此这是估算值，不是第 2000 首的精确耗时。实际使用建议**每 2000 首预留 25–35 分钟**；手机性能、App 响应、转储重试和列表末尾检查都会影响速度。

### 每 2000 首可能有多少首获取不到？

**无法给出固定数量或可靠比例。** 这次 App 显示 3035，实际导出 2711，差 324（约 10.7%）。但页面计数可能包括歌曲以外的收藏，导出又会按歌名和歌手去重；**324 不是已证实漏抓的歌曲数**，也不能推算为每 2000 首约漏 214 首。

与之前的 2700 行 CSV 比对，2679 条在清除零宽字符并合并字段后完全匹配；另外 21 条疑似歌曲资料变化、11 条只在新列表出现。**目前没有确认旧歌漏抓，但 21 条仍需人工复核，这也不能证明漏抓数一定为零。** 此方法只能读取当前登录账号的歌曲列表里实际显示的文字；未显示、已失效或未迁移的历史歌曲无法由 UI 抓取，也无法仅凭 App 计数算出其数量。核对时应确认列表确实滚动到底，并与自己的旧备份逐条比对。

---

## 🔒 隐私与操作风险（必读）

**隐私风险：** 本方案**不索取账号密码、不索取登录 token**，只读取「设备当前已登录界面上显示的文字」，隐私风险低。产出的 CSV 含你的音乐偏好，属个人信息，分享前请自行确认。

**操作风险速查：**
- **MIUI 拦截注入事件**：报 `SecurityException: Injecting to another application requires INJECT_EVENTS permission` → 设置 → 更多设置 → 开发者选项 → 开启「USB 调试（安全设置）」（普通「USB 调试」不够；该项灰色时先登录小米账号、等几分钟、部分机型需插 SIM 卡）。
- **设备中途掉线** `no devices/emulators found` → 重插 USB / 换线 / 通知栏 USB 用途改「传输文件 (MTP)」/ 撤销并重新授权 USB 调试。
- **中文乱码**：务必用 `adb pull` 落地 + UTF-8 读取，不要用 `adb exec-out cat` + 正则（GBK 会毁中文）。
- **数量核对**：App 的 `N首` 可能包含「歌曲 / 专辑 / 歌单 / 视频」等收藏，不能单独用它判定漏抓。应检查列表确实到底、连续多屏无新增，并核对最后一首；相同歌名与歌手也会去重。
- **外文 / 日韩歌切分不可靠**：App 把「歌名 歌手」压进同一个 `content-desc` 节点，外文歌无法靠空格 100% 切准 → 这类歌整串存歌名、歌手留空，绝不乱切（原始串另存备份可回溯）。

---

## 🚀 快速开始

```bash
# 1. 安装 adb（Windows 最省事）
winget install Google.PlatformTools
# 或官网 ZIP: https://developer.android.com/tools/releases/platform-tools
adb devices   # 必须看到一行 "<序列号>  device"
```

1. 手机：开发者选项开 **USB 调试** + **「USB 调试（安全设置）」**，连电脑，弹窗点「一律允许」。
2. 打开豆瓣FM → 我的 → 红心 → **手动滑到列表最顶** → 保持亮屏、关自动锁屏。
3. 先验证：把 `scripts/capture_redheart.ps1` 里 `$maxSwipes` 改成 `3` 跑一次，确认无 `UI hierchary` 且每屏有新增。
4. 全量：`$maxSwipes` 改回 `1000`，在电脑上运行（PowerShell）：
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts/capture_redheart.ps1
   ```
   产出 `douban_fm_redheart.csv`（歌名,歌手）+ `douban_fm_redheart_raw.txt`（原始串备份，防切错可回溯）。
5. 清洗去重：
   ```bash
   python3 scripts/clean_dedup.py douban_fm_redheart_raw.txt douban_fm_redheart_dedup.csv
   ```
   产出 `douban_fm_redheart_dedup.csv`（歌名,歌手，UTF-8-sig，Excel 直开不乱码）。

### macOS（Apple Silicon / Intel）

安装 Python 3 和 Android platform-tools，并确认手机授权：

```bash
brew install android-platform-tools python
adb devices -l                 # 状态应为 device，而非 unauthorized
python3 --version
```

如果已用其他方式安装 ADB，可把可执行文件路径传给 `--adb`。在手机上打开「我的 → 喜欢 → 歌曲」，滑到最顶并保持亮屏。先进行三次滑动的试抓，使用独立前缀避免覆盖正式文件：

```bash
python3 scripts/capture_redheart.py --max-swipes 3 --prefix trial_redheart
```

确认每屏有新增、CSV 的歌名和歌手正常后，重新进入歌曲列表顶部，运行全量抓取：

```bash
python3 scripts/capture_redheart.py
python3 scripts/clean_dedup.py douban_fm_redheart_raw.txt douban_fm_redheart_dedup.csv
```

多台设备同时连接时，先运行 `adb devices -l`，再加 `--serial <序列号>`。脚本每屏原子保存 `douban_fm_redheart.checkpoint.json`；中断后把列表滑回顶部，再用 `--resume` 重新扫描到断点并继续。已有导出文件时，脚本会拒绝直接覆盖；确认需要重抓时使用 `--overwrite`。可用 `--max-swipes`、`--stable-stop` 调整上限和到底判定。

macOS 脚本从 UI 节点中的换行直接读取歌名和歌手，生成与 Windows 脚本同名的 CSV 和原始 TXT。清洗去重仍使用原有的 `clean_dedup.py`。原始 TXT 保留合并文字以便回溯；该清洗脚本对外文歌采取保守策略，去重 CSV 的外文歌手列可能为空，直接抓取的 CSV 则保留可辨认的歌手。

---

## 📁 文件说明
- `scripts/capture_redheart.ps1` — ADB 自动滚屏抓取脚本（屏幕自适应滑动坐标）
- `scripts/capture_redheart.py` — macOS 原生 Python 抓取脚本（设备检查、断点恢复、防覆盖）
- `scripts/clean_dedup.py` — 清洗 + 去重（剥离零宽空格 U+200B 等、按「歌名 + 歌手」去重，保留不同版本）
- `SKILL.md` — 给 AI Agent 用的技能说明（含完整前置 / 硬件 / 隐私 / 操作风险 / 流程）
- `README.md` — 本文档

---

## 🎬 推荐：豆瓣电影导出工具

> 上面这套是**音乐（豆瓣FM）**。如果你也想把**自己的豆瓣电影评分 + 短评**下载到本地，「获取电影的插件」推荐这几个（非本项目，但同一天用上的好搭档）：

**豆瓣电影数据导出工具 (Douban Movie Export Tool) ** https://github.com/byJming/douban-movie-exporter
-
-一个强大的油猴 (Tampermonkey) 脚本，用于将你的豆瓣“看过”电影列表导出为 Excel (.xlsx) 或 JSON 文件。 

> **同一天拿到了自己豆瓣电影 + 豆瓣FM 的数字资产。** 电影用上面的导出工具，FM 红心用本仓库——两份个人数据都在同一天本地化落地，可以做成一个「我的豆瓣记忆库」。

---

## 📜 License
MIT © yunhaiming1542
