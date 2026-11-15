import csv
import importlib.util
import contextlib
import io
from unittest import mock
from xml.sax.saxutils import escape
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("capture_redheart", ROOT / "scripts" / "capture_redheart.py")
capture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capture)


class ParseTests(unittest.TestCase):
    def test_fixture_extracts_separate_title_artist_and_count(self):
        source = (ROOT / "tests" / "fixtures" / "redheart_page.xml").read_bytes()
        songs, count = capture.parse_ui(source)
        self.assertEqual(count, "3035首")
        self.assertEqual([(title, artist) for _, title, artist in songs], [
            ("历历万乡Demo", "陈粒"),
            ("A Dead Leaf Dance", "As The Stars Fall"),
            ("残酷な天使のテーゼ", "Naorchestra"),
        ])

    def test_rejects_wrong_screen_and_malformed_xml(self):
        for source in (b"<hierarchy/>", b"<bad"):
            with self.assertRaises(capture.CaptureError):
                capture.parse_ui(source)

    def test_legacy_merged_label_split(self):
        self.assertEqual(capture.split_song("黑洞 银河冲浪手"), ("黑洞", "银河冲浪手"))
        self.assertEqual(capture.split_song("A Dead Leaf Dance Escala"), ("A Dead Leaf Dance", "Escala"))


class DeviceTests(unittest.TestCase):
    def test_one_authorized_device(self):
        self.assertEqual(capture.parse_devices("List of devices attached\nfb19aa85 device product:x\n"), "fb19aa85")

    def test_unauthorized_device(self):
        with self.assertRaisesRegex(capture.CaptureError, "授权"):
            capture.parse_devices("List of devices attached\nfb19aa85 unauthorized\n")

    def test_multiple_devices_require_serial(self):
        listing = "List of devices attached\na device\nb device\n"
        with self.assertRaisesRegex(capture.CaptureError, "多台"):
            capture.parse_devices(listing)
        self.assertEqual(capture.parse_devices(listing, "b"), "b")


class ExportTests(unittest.TestCase):
    def test_checkpoint_and_csv_round_trip(self):
        rows = [
            {"raw": "歌,名\n歌手", "title": "歌,名", "artist": "歌手"},
            {"raw": "A\u200b B\nC D", "title": "A B", "artist": "C D"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory) / "douban_fm_redheart"
            checkpoint = Path(directory) / "douban_fm_redheart.checkpoint.json"
            capture.save_checkpoint(checkpoint, rows, 3)
            self.assertEqual(capture.load_checkpoint(checkpoint), {"version": 1, "swipes": 3, "rows": rows})
            csv_path, raw_path = capture.write_exports(prefix, rows)
            with csv_path.open(encoding="utf-8-sig", newline="") as handle:
                self.assertEqual(list(csv.reader(handle)), [
                    ["歌名", "歌手"], ["歌,名", "歌手"], ["A B", "C D"]
                ])
            self.assertTrue(raw_path.read_text(encoding="utf-8-sig").startswith("歌,名 歌手\n"))

    def test_existing_export_requires_explicit_option(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory) / "douban_fm_redheart"
            prefix.with_suffix(".csv").write_text("existing", encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as result:
                    capture.main(["--prefix", str(prefix)])
            self.assertEqual(result.exception.code, 2)
            self.assertEqual(prefix.with_suffix(".csv").read_text(encoding="utf-8"), "existing")

    def test_interrupted_run_resumes_from_checkpoint_without_losing_rows(self):
        def page(*pairs):
            songs = "".join(
                '<node package="com.douban.radio" clickable="true" '
                'long-clickable="true" content-desc="{}&#10;{}" />'.format(
                    escape(title, {'"': '&quot;'}), escape(artist, {'"': '&quot;'}))
                for title, artist in pairs
            )
            return (
                '<hierarchy><node content-desc="我喜欢" />'
                '<node content-desc="歌曲&#10;第 1 个标签，共 4 个" />'
                '<node content-desc="4首" />' + songs + '</hierarchy>'
            ).encode('utf-8')

        class FakeAdb:
            def run(self, *args):
                return "Physical size: 1080x2340" if args == ("shell", "wm", "size") else ""

        a, b, c, d = [(title, "歌手") for title in "甲乙丙丁"]
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory) / "douban_fm_redheart"
            with mock.patch.object(capture, "dump_ui", side_effect=[page(a, b), page(b, c)]), \
                    mock.patch.object(capture.time, "sleep"), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(capture.capture(FakeAdb(), prefix, 1, 2), 3)
            checkpoint = prefix.parent / "douban_fm_redheart.checkpoint.json"
            self.assertEqual(len(capture.load_checkpoint(checkpoint)["rows"]), 3)
            with mock.patch.object(capture, "dump_ui", side_effect=[
                page(a, b), page(b, c), page(c, d), page(d), page(d)
            ]), mock.patch.object(capture.time, "sleep"), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(capture.capture(FakeAdb(), prefix, 10, 2, resume=True), 4)
            with prefix.with_suffix(".csv").open(encoding="utf-8-sig", newline="") as handle:
                self.assertEqual([row[0] for row in list(csv.reader(handle))[1:]], list("甲乙丙丁"))


if __name__ == "__main__":
    unittest.main()
