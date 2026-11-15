#!/usr/bin/env python3
"""Capture Douban FM liked songs from an Android phone with ADB.

The Windows PowerShell implementation remains available as capture_redheart.ps1.
This version uses only the Python standard library and Android platform-tools.
"""

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

REMOTE_XML = "/sdcard/douban_redheart_ui.xml"
SONG_COUNT = re.compile(r"^\d+首$")
SIZE = re.compile(r"(\d+)x(\d+)")


class CaptureError(Exception):
    """A recoverable setup or capture failure."""


def clean(value):
    """Remove zero-width characters and normalize whitespace."""
    value = "".join(char for char in value if unicodedata.category(char) != "Cf")
    return " ".join(value.replace("\u00a0", " ").replace("\u3000", " ").split())


def split_song(raw):
    """Prefer the app's title/artist newline; support its older merged label."""
    if "\n" in raw:
        title, artist = raw.split("\n", 1)
    else:
        first = raw.split(" ", 1)[0]
        if " " not in raw:
            title, artist = raw, ""
        elif re.search(r"[\u4e00-\u9fff]", first):
            title, artist = raw.split(" ", 1)
        else:
            title, artist = raw.rsplit(" ", 1)
    return clean(title), clean(artist)


def parse_ui(xml_bytes):
    """Return song labels and the visible count from a Douban FM UI XML dump."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise CaptureError("手机返回的 UI XML 无法解析") from exc
    nodes = list(root.iter("node"))
    labels = [node.get("content-desc", "") for node in nodes]
    if "我喜欢" not in labels or not any(
        label.startswith("歌曲") and "第 1 个标签" in label for label in labels
    ):
        raise CaptureError("当前不是豆瓣 FM 的“我喜欢 → 歌曲”页面")
    count = next((label for label in labels if SONG_COUNT.fullmatch(label)), "")
    songs = []
    for node in nodes:
        if node.get("package") != "com.douban.radio":
            continue
        if node.get("clickable") != "true" or node.get("long-clickable") != "true":
            continue
        raw = node.get("content-desc", "").strip()
        if not raw or raw.startswith("添加到\n"):
            continue
        title, artist = split_song(raw)
        if title and ("\n" in raw or artist):
            songs.append((raw, title, artist))
    return songs, count


def parse_devices(output, serial=None):
    """Choose one authorized device, requiring --serial when there are several."""
    devices = {}
    for line in output.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0] != "List" and fields[1] in {
            "device", "unauthorized", "offline", "recovery", "sideload"
        }:
            devices[fields[0]] = fields[1]
    if serial:
        if serial not in devices:
            raise CaptureError(f"找不到指定设备 {serial}；请运行 adb devices -l")
        if devices[serial] != "device":
            raise CaptureError(f"设备 {serial} 状态为 {devices[serial]}，请在手机上授权 USB 调试")
        return serial
    ready = [name for name, state in devices.items() if state == "device"]
    if len(ready) > 1:
        raise CaptureError("检测到多台已连接设备，请用 --serial 指定一台")
    if len(ready) == 1:
        return ready[0]
    if any(state == "unauthorized" for state in devices.values()):
        raise CaptureError("手机尚未授权 USB 调试；请解锁手机并允许这台电脑")
    raise CaptureError("没有已授权的 Android 设备；请检查 USB 连接和 adb devices -l")


class Adb:
    def __init__(self, executable, serial):
        self.executable = executable
        self.serial = serial

    def run(self, *args):
        command = [self.executable]
        if self.serial:
            command += ["-s", self.serial]
        command += list(args)
        try:
            result = subprocess.run(command, capture_output=True, check=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            detail = getattr(exc, "stderr", b"") or b""
            message = detail.decode("utf-8", "replace").strip() if isinstance(detail, bytes) else str(detail)
            raise CaptureError(f"ADB 命令失败：{' '.join(args)}\n{message}") from exc
        if b"SecurityException" in result.stderr or b"SecurityException" in result.stdout:
            raise CaptureError("手机拒绝模拟触摸；请开启“USB 调试（安全设置）”")
        return result.stdout.decode("utf-8", "replace")


def dump_ui(adb, local_xml):
    """Remove the previous dump so a failed attempt cannot return stale data."""
    adb.run("shell", "rm", "-f", REMOTE_XML)
    for attempt in range(5):
        output = adb.run("shell", "uiautomator", "dump", REMOTE_XML)
        if "UI hierchary dumped to:" in output:
            adb.run("pull", REMOTE_XML, str(local_xml))
            try:
                return local_xml.read_bytes()
            except OSError as exc:
                raise CaptureError(f"无法读取拉取的 UI 文件：{local_xml}") from exc
        if attempt < 4:
            time.sleep(1)
    raise CaptureError("手机 UI 连续 5 次无法转储；请暂停播放并保持列表静止")


def atomic_text(path, contents, encoding="utf-8"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding=encoding, dir=path.parent,
                                     prefix=f".{path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(contents)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def save_checkpoint(path, rows, swipes):
    data = {"version": 1, "swipes": swipes, "rows": rows}
    atomic_text(path, json.dumps(data, ensure_ascii=False))


def load_checkpoint(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if (data["version"] != 1 or not isinstance(data["rows"], list)
                or not isinstance(data["swipes"], int)):
            raise ValueError("unsupported checkpoint")
        return data
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise CaptureError(f"无法读取断点文件 {path}") from exc


def write_exports(prefix, rows):
    csv_path = prefix.with_suffix(".csv")
    raw_path = prefix.parent / (prefix.name + "_raw.txt")
    with tempfile.NamedTemporaryFile("w", encoding="utf-8-sig", newline="",
                                     dir=csv_path.parent, prefix=f".{csv_path.name}.",
                                     delete=False) as handle:
        csv_temp = Path(handle.name)
        writer = csv.writer(handle)
        writer.writerow(["歌名", "歌手"])
        writer.writerows((row["title"], row["artist"]) for row in rows)
        handle.flush()
        os.fsync(handle.fileno())
    raw_lines = [row["raw"].replace("\r", " ").replace("\n", " ") for row in rows]
    atomic_text(raw_path, "\n".join(raw_lines) + "\n", encoding="utf-8-sig")
    os.replace(csv_temp, csv_path)
    return csv_path, raw_path


def capture(adb, prefix, max_swipes, stable_stop, resume=False):
    checkpoint = prefix.parent / (prefix.name + ".checkpoint.json")
    previous = load_checkpoint(checkpoint) if resume else {"rows": [], "swipes": 0}
    rows = previous["rows"]
    prior_swipes = previous["swipes"]
    seen = {(row["title"], row["artist"]) for row in rows}
    anchor = (rows[-1]["title"], rows[-1]["artist"]) if rows else None
    anchor_found = anchor is None
    stable = 0
    size = adb.run("shell", "wm", "size")
    match = SIZE.search(size)
    width, height = (int(match.group(1)), int(match.group(2))) if match else (1080, 2400)
    expected_count = None
    with tempfile.TemporaryDirectory(prefix="douban-fm-") as temp:
        local_xml = Path(temp) / "ui.xml"
        for swipe in range(max_swipes + 1):
            songs, count = parse_ui(dump_ui(adb, local_xml))
            if count:
                expected_count = int(count[:-1])
            if not songs and swipe == 0 and not rows:
                raise CaptureError("歌曲列表为空，未创建导出文件")
            current = {(title, artist) for _, title, artist in songs}
            if anchor in current and swipe >= max(0, prior_swipes - 20):
                anchor_found = True
            added = 0
            for raw, title, artist in songs:
                key = title, artist
                if key not in seen:
                    seen.add(key)
                    rows.append({"raw": raw, "title": title, "artist": artist})
                    added += 1
            save_checkpoint(checkpoint, rows, swipe if anchor_found else prior_swipes)
            print(f"[{swipe:04d}] 本屏 {len(songs)} | 新增 {added} | 累计 {len(rows)} | 页面 {count}", flush=True)
            if anchor_found:
                stable = stable + 1 if added == 0 else 0
                if stable >= 3 and expected_count and len(rows) < expected_count * .8:
                    raise CaptureError("列表未前进且抓取数量远少于页面总数；请检查 USB 调试（安全设置）")
                if stable >= stable_stop:
                    print("连续无新增，已到列表末尾。", flush=True)
                    break
            if swipe == max_swipes:
                if not anchor_found:
                    raise CaptureError("未重新扫到断点位置；请将歌曲列表滑回顶部后重试 --resume")
                print("已达到最大滑动次数，结果为部分导出。", flush=True)
                break
            adb.run("shell", "input", "swipe", str(width // 2), str(int(height * .70)),
                    str(width // 2), str(int(height * .30)), "400")
            time.sleep(0.5)
    csv_path, raw_path = write_exports(prefix, rows)
    print(f"已保存 {len(rows)} 首：{csv_path}；原始备份：{raw_path}", flush=True)
    return len(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default=os.environ.get("ADB", "adb"), help="ADB 可执行文件路径")
    parser.add_argument("--serial", help="多台设备时指定 adb 序列号")
    parser.add_argument("--prefix", type=Path, default=Path("douban_fm_redheart"), help="输出文件名前缀")
    parser.add_argument("--max-swipes", type=int, default=1000)
    parser.add_argument("--stable-stop", type=int, default=30)
    parser.add_argument("--resume", action="store_true", help="从断点恢复；请先将歌曲列表滑回顶部")
    parser.add_argument("--overwrite", action="store_true", help="明确覆盖已有导出并重新开始")
    args = parser.parse_args(argv)
    if args.max_swipes < 0 or args.stable_stop < 1:
        parser.error("--max-swipes 必须 >= 0，--stable-stop 必须 >= 1")
    if args.resume and args.overwrite:
        parser.error("--resume 与 --overwrite 不能同时使用")
    prefix = args.prefix.resolve()
    csv_path = prefix.with_suffix(".csv")
    raw_path = prefix.parent / (prefix.name + "_raw.txt")
    checkpoint = prefix.parent / (prefix.name + ".checkpoint.json")
    if args.resume:
        if not checkpoint.exists():
            parser.error(f"断点文件不存在：{checkpoint}")
    elif not args.overwrite and any(path.exists() for path in (csv_path, raw_path, checkpoint)):
        parser.error("输出或断点文件已存在；使用 --resume 恢复，或 --overwrite 明确覆盖")
    if not shutil.which(args.adb) and not Path(args.adb).is_file():
        parser.error(f"找不到 ADB：{args.adb}；请安装 Android platform-tools 或使用 --adb")
    try:
        serial = parse_devices(Adb(args.adb, None).run("devices", "-l"), args.serial)
        print(f"设备：{serial}", flush=True)
        capture(Adb(args.adb, serial), prefix, args.max_swipes, args.stable_stop, args.resume)
    except KeyboardInterrupt:
        print("已中断；断点保存在 .checkpoint.json，回到列表顶部后用 --resume 继续。", file=sys.stderr)
        return 130
    except CaptureError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
