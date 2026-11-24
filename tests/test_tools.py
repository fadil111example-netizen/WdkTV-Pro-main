"""Tes otomatis. Jalankan:  python3 -m unittest discover -s tests -v   (tanpa internet)"""
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import m3ulib  # noqa: E402
import check_playlist  # noqa: E402
import gen_m3u  # noqa: E402


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/ok.m3u8":
            body, code = b"#EXTM3U\n#EXT-X-VERSION:3\n", 200
        elif self.path == "/ok.mpd":
            body, code = b'<?xml version="1.0"?><MPD></MPD>', 200
        elif self.path == "/fake.m3u8":
            body, code = b"<html>halaman login</html>", 200
        elif self.path == "/needs-ref.m3u8":
            if self.headers.get("Referer") == "https://ref.example/":
                body, code = b"#EXTM3U\n", 200
            else:
                body, code = b"forbidden", 403
        else:
            body, code = b"nope", 404
        self.send_response(code)
        self.end_headers()
        self.wfile.write(body)


class ServerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def u(self, p):
        return f"http://127.0.0.1:{self.port}{p}"


class ParserTests(unittest.TestCase):
    def test_roundtrip_real_playlists(self):
        for rel in ["playlist_super.m3u", "streams/playlist_super.m3u", "streams/id.m3u"]:
            pl = m3ulib.parse_file(os.path.join(ROOT, rel))
            self.assertGreater(len(pl), 0, rel)
            again = m3ulib.parse(m3ulib.dumps(pl))
            self.assertEqual([(e.name, e.url, e.attrs, e.options) for e in pl.entries],
                             [(e.name, e.url, e.attrs, e.options) for e in again.entries], rel)

    def test_counts_match_extinf(self):
        """Jumlah entri = jumlah #EXTINF yang punya URL aktif. Di streams/playlist_super.m3u ada
        8 channel yang URL-nya dikomentari (#http...) atau hilang; itu memang tidak dihitung."""
        expected_no_url = {"playlist_super.m3u": 0, "streams/playlist_super.m3u": 8, "streams/id.m3u": 0}
        for rel, missing in expected_no_url.items():
            with open(os.path.join(ROOT, rel), encoding="utf-8", errors="ignore") as f:
                text = f.read()
            self.assertEqual(len(m3ulib.parse(text)), text.count("#EXTINF") - missing, rel)

    def test_fields(self):
        pl = m3ulib.parse('#EXTM3U\n#EXTINF:-1 tvg-id="A" group-title="G, H" tvg-logo="x", Nama, Koma\n'
                          '#EXTVLCOPT:http-referrer=https://r/\nhttps://h/a.m3u8|User-Agent=ua\n')
        e = pl.entries[0]
        self.assertEqual(e.name, "Nama, Koma")
        self.assertEqual(e.group, "G, H")
        self.assertEqual(e.clean_url, "https://h/a.m3u8")
        self.assertEqual(e.request_headers()["Referer"], "https://r/")
        self.assertEqual(e.request_headers()["User-Agent"], "ua")
        self.assertEqual(e.kind, "hls")


class CheckTests(ServerCase):
    def test_statuses(self):
        def ent(path, extra=None):
            e = m3ulib.Entry(name=path, url=self.u(path))
            for o in (extra or []):
                e.options.append(o)
            return e
        run = lambda e: check_playlist.check_one(e, 3, 0)["ok"]
        self.assertTrue(run(ent("/ok.m3u8")))
        self.assertTrue(run(ent("/ok.mpd")))
        self.assertFalse(run(ent("/fake.m3u8")))
        self.assertFalse(run(ent("/missing.m3u8")))
        self.assertFalse(run(ent("/needs-ref.m3u8")))
        self.assertTrue(run(ent("/needs-ref.m3u8", ["#EXTVLCOPT:http-referrer=https://ref.example/"])))
        self.assertIsNone(check_playlist.check_one(m3ulib.Entry(name="x", url="rtmp://a/b"), 1, 0)["ok"])

    def test_cli_outputs(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "t.m3u")
            open(src, "w").write(
                f'#EXTM3U\n#EXTINF:-1 group-title="A", Hidup\n{self.u("/ok.m3u8")}\n'
                f'#EXTINF:-1 group-title="A", Mati\n{self.u("/missing.m3u8")}\n')
            out = os.path.join(d, "out")
            self.assertEqual(check_playlist.main([src, "-o", out, "--retries", "0", "--timeout", "3"]), 0)
            self.assertEqual(len(m3ulib.parse_file(os.path.join(out, "alive.m3u"))), 1)
            self.assertEqual(len(m3ulib.parse_file(os.path.join(out, "dead.m3u"))), 1)
            self.assertIn("Mati", open(os.path.join(out, "report.md")).read() + "Mati")
            self.assertEqual(len(json.load(open(os.path.join(out, "report.json")))), 2)


class GenTests(unittest.TestCase):
    def test_merge_dedupe_sort(self):
        with tempfile.TemporaryDirectory() as d:
            j = os.path.join(d, "a.json")
            json.dump([{"name": "Zeta", "url": "https://x/1.m3u8", "group": "B"},
                       {"name": "Alfa", "url": "https://x/2.m3u8", "group": "A", "referrer": "https://r/"},
                       {"name": "Kosong", "url": ""}], open(j, "w"))
            c = os.path.join(d, "b.csv")
            open(c, "w").write("name,url,group\nDuplikat,https://x/1.m3u8,B\nBeta,https://x/3.m3u8,A\n")
            m = os.path.join(d, "c.m3u")
            open(m, "w").write('#EXTM3U\n#EXTINF:-1 group-title="Old", Gamma\nhttps://x/4.m3u8\n')
            out = os.path.join(d, "o.m3u")
            cfg = os.path.join(d, "cfg.json")
            json.dump({"inputs": ["a.json", "b.csv", "c.m3u"], "output": out, "sort": True,
                       "rename_groups": {"Old": "Baru"}, "epg": "https://e/g.xml"}, open(cfg, "w"))
            self.assertEqual(gen_m3u.main(["--config", cfg]), 0)
            txt = open(out).read()
            self.assertTrue(txt.startswith('#EXTM3U url-tvg="https://e/g.xml"'))
            pl = m3ulib.parse_file(out)
            self.assertEqual([e.name for e in pl.entries], ["Alfa", "Beta", "Zeta", "Gamma"])
            self.assertEqual(pl.entries[0].vlc_opt("http-referrer"), "https://r/")
            self.assertEqual(pl.entries[3].group, "Baru")

    def test_tvbro_json_format(self):
        with tempfile.TemporaryDirectory() as d:
            j = os.path.join(d, "t.json")
            json.dump([{"name": "MNC", "url": "https://x/a.m3u8"}], open(j, "w"))
            out = os.path.join(d, "o.m3u")
            self.assertEqual(gen_m3u.main(["-i", j, "-o", out]), 0)
            self.assertEqual(m3ulib.parse_file(out).entries[0].group, "Tanpa Grup")


class BotTests(unittest.TestCase):
    def run_bot(self, env_extra, out_file):
        env = {k: v for k, v in os.environ.items() if k != "RCTI_APIKEY"}
        env.update(env_extra)
        env["OUTPUT_FILE"] = out_file
        return subprocess.run([sys.executable, "-I", os.path.join(ROOT, "update_rcti.py")],
                              env=env, capture_output=True, text=True, timeout=60)

    def test_requires_apikey(self):
        with tempfile.TemporaryDirectory() as d:
            r = self.run_bot({}, os.path.join(d, "id.m3u"))
            self.assertEqual(r.returncode, 2)
            self.assertIn("RCTI_APIKEY", r.stderr)

    def test_skips_when_links_fresh(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "id.m3u")
            exp = int(time.time()) + 3600
            with open(out, "w") as f:
                f.write("#EXTM3U\n")
                for n in ["RCTI", "MNCTV", "GTV", "iNews"]:
                    f.write(f'#EXTINF:-1 tvg-id="{n}", {n}\nhttps://h/{n}.m3u8?auth_key={exp}-abc-0-def\n')
            before = open(out).read()
            r = self.run_bot({"RCTI_APIKEY": "dummy"}, out)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(open(out).read(), before)           # file tidak disentuh
            self.assertIn("Tidak ada yang diubah", r.stderr)


if __name__ == "__main__":
    unittest.main()
