"""Tes otomatis. Jalankan:  python3 -m unittest discover -s tests -v

Seluruh tes dirancang berjalan TANPA internet:
  * tes parser hanya membaca berkas playlist di repo,
  * tes checker memakai server HTTP lokal sementara (127.0.0.1),
  * tes bot hanya menjalankan jalur "tautan masih segar" (tidak menyentuh jaringan)
    dan menguji logika penggabungan (merge) secara langsung.
"""
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
import update_rcti  # noqa: E402
import vidio  # noqa: E402


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
    # Hanya berkas yang BENAR-BENAR ada di repo (playlist_super.m3u di root & streams/id.m3u).
    PLAYFILES = ["playlist_super.m3u", "streams/id.m3u"]

    def test_roundtrip_real_playlists(self):
        for rel in self.PLAYFILES:
            with self.subTest(rel=rel):
                pl = m3ulib.parse_file(os.path.join(ROOT, rel))
                self.assertGreater(len(pl), 0, rel)
                again = m3ulib.parse(m3ulib.dumps(pl))
                self.assertEqual(
                    [(e.name, e.url, e.attrs, e.options) for e in pl.entries],
                    [(e.name, e.url, e.attrs, e.options) for e in again.entries], rel)

    def test_counts_match_extinf(self):
        """Jumlah entri terparse = jumlah #EXTINF yang diikuti baris URL.

        Di playlist_super.m3u ada 3 baris URL cadangan TANPA #EXTINF (untuk
        Sportstars/Soccer Channel) yang memang tidak dihitung sebagai entri.
        """
        expected_no_url = {"playlist_super.m3u": 0, "streams/id.m3u": 0}
        for rel, missing in expected_no_url.items():
            with self.subTest(rel=rel):
                with open(os.path.join(ROOT, rel), encoding="utf-8", errors="ignore") as f:
                    text = f.read()
                self.assertEqual(len(m3ulib.parse(text)),
                                 text.count("#EXTINF") - missing, rel)

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

    def test_preserves_manual_options(self):
        """Blok channel manual gaya Vidio (banyak #EXTVLCOPT/#KODIPROP) harus utuh."""
        block = ('#EXTINF:-1 tvg-logo="x" group-title="TV Nasional", SCTV HD\n'
                 '#EXTVLCOPT:http-user-agent=VidioPlayer/6.31.6\n'
                 '#EXTVLCOPT:http-referrer=http://www.vidio.com/\n'
                 '#EXTVLCOPT:http-origin=http://www.vidio.com\n'
                 '#KODIPROP:inputstreamaddon=inputstream.adaptive\n'
                 '#KODIPROP:inputstream.adaptive.license_type=com.widevine.alpha\n'
                 'https://nextgenz.my.id/event/pidio/play.mpd?id=204&type=dash\n')
        pl = m3ulib.parse('#EXTM3U\n' + block)
        e = pl.entries[0]
        self.assertEqual(e.name, "SCTV HD")
        self.assertEqual(e.kind, "dash")
        self.assertEqual(len(e.options), 5)
        self.assertEqual(m3ulib.dumps(pl), '#EXTM3U\n' + block)   # byte-identik


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
            with open(src, "w", encoding="utf-8") as f:
                f.write(f'#EXTM3U\n#EXTINF:-1 group-title="A", Hidup\n{self.u("/ok.m3u8")}\n'
                        f'#EXTINF:-1 group-title="A", Mati\n{self.u("/missing.m3u8")}\n')
            out = os.path.join(d, "out")
            self.assertEqual(check_playlist.main([src, "-o", out, "--retries", "0", "--timeout", "3"]), 0)
            self.assertEqual(len(m3ulib.parse_file(os.path.join(out, "alive.m3u"))), 1)
            self.assertEqual(len(m3ulib.parse_file(os.path.join(out, "dead.m3u"))), 1)
            with open(os.path.join(out, "report.md"), encoding="utf-8") as f:
                self.assertIn("Mati", f.read())
            with open(os.path.join(out, "report.json"), encoding="utf-8") as f:
                self.assertEqual(len(json.load(f)), 2)


class GenTests(unittest.TestCase):
    def test_merge_dedupe_sort(self):
        with tempfile.TemporaryDirectory() as d:
            j = os.path.join(d, "a.json")
            with open(j, "w", encoding="utf-8") as f:
                json.dump([{"name": "Zeta", "url": "https://x/1.m3u8", "group": "B"},
                           {"name": "Alfa", "url": "https://x/2.m3u8", "group": "A", "referrer": "https://r/"},
                           {"name": "Kosong", "url": ""}], f)
            c = os.path.join(d, "b.csv")
            with open(c, "w", encoding="utf-8") as f:
                f.write("name,url,group\nDuplikat,https://x/1.m3u8,B\nBeta,https://x/3.m3u8,A\n")
            m = os.path.join(d, "c.m3u")
            with open(m, "w", encoding="utf-8") as f:
                f.write('#EXTM3U\n#EXTINF:-1 group-title="Old", Gamma\nhttps://x/4.m3u8\n')
            out = os.path.join(d, "o.m3u")
            cfg = os.path.join(d, "cfg.json")
            with open(cfg, "w", encoding="utf-8") as f:
                json.dump({"inputs": ["a.json", "b.csv", "c.m3u"], "output": out, "sort": True,
                           "rename_groups": {"Old": "Baru"}, "epg": "https://e/g.xml"}, f)
            self.assertEqual(gen_m3u.main(["--config", cfg]), 0)
            with open(out, encoding="utf-8") as f:
                txt = f.read()
            self.assertTrue(txt.startswith('#EXTM3U url-tvg="https://e/g.xml"'))
            pl = m3ulib.parse_file(out)
            self.assertEqual([e.name for e in pl.entries], ["Alfa", "Beta", "Zeta", "Gamma"])
            self.assertEqual(pl.entries[0].vlc_opt("http-referrer"), "https://r/")
            self.assertEqual(pl.entries[3].group, "Baru")

    def test_tvbro_json_format(self):
        with tempfile.TemporaryDirectory() as d:
            j = os.path.join(d, "t.json")
            with open(j, "w", encoding="utf-8") as f:
                json.dump([{"name": "MNC", "url": "https://x/a.m3u8"}], f)
            out = os.path.join(d, "o.m3u")
            self.assertEqual(gen_m3u.main(["-i", j, "-o", out]), 0)
            self.assertEqual(m3ulib.parse_file(out).entries[0].group, "Tanpa Grup")


class BotTests(unittest.TestCase):
    def run_bot(self, env_extra, out_file):
        env = {k: v for k, v in os.environ.items()
               if k not in ("RCTI_APIKEY", "FORCE_REFRESH", "MIN_REMAINING_SEC", "OUTPUT_FILE")}
        env["OUTPUT_FILE"] = out_file
        env.update(env_extra)
        return subprocess.run([sys.executable, "-I", os.path.join(ROOT, "update_rcti.py")],
                              env=env, capture_output=True, text=True, timeout=60)

    def _write_fresh(self, path):
        exp = int(time.time()) + 3600        # berlaku 1 jam ke depan -> dianggap segar
        with open(path, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for n in ["RCTI", "MNCTV", "GTV", "iNews"]:
                f.write(f'#EXTINF:-1 tvg-id="{n}", {n}\n'
                        f'https://h/{n}.m3u8?auth_key={exp}-abc-0-def\n')

    def test_skips_fresh_links_without_apikey(self):
        """RCTI_APIKEY kini opsional: tanpa apikey & tautan masih segar, bot tidak menyentuh apa pun."""
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "id.m3u")
            self._write_fresh(out)
            with open(out, encoding="utf-8") as f:
                before = f.read()
            r = self.run_bot({}, out)                 # SENGAJA tanpa RCTI_APIKEY
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(out, encoding="utf-8") as f:
                self.assertEqual(f.read(), before)     # byte-identik: file tidak disentuh
            self.assertIn("Tidak ada yang diubah", r.stderr)

    def test_merge_never_drops_manual_channels(self):
        """INTI permintaan: SCTV/Indosiar dkk TIDAK boleh hilang saat RCTI/MNCTV disegarkan."""
        channels = [{"api_id": 1, "name": "RCTI", "logo": ""},
                    {"api_id": 2, "name": "MNCTV", "logo": ""}]
        old = [
            m3ulib.Entry(name="SCTV", url="https://indihome/sctv.mpd"),
            m3ulib.Entry(name="RCTI", url="https://linier-rcti/x.m3u8?auth_key=1-a-0-b"),
            m3ulib.Entry(name="Indosiar", url="https://indihome/indosiar.mpd"),
            m3ulib.Entry(name="MNCTV", url="https://linier-mnctv/x.m3u8?auth_key=1-a-0-b"),
            m3ulib.Entry(name="GTV", url="https://linier-gtv/x.m3u8?auth_key=1-a-0-b"),
        ]
        fresh = {"rcti": "https://linier-rcti/x.m3u8?auth_key=2-c-0-d"}   # hanya RCTI berhasil
        result = update_rcti.merge_playlist(channels, old, fresh)
        self.assertEqual([e.name for e in result],
                         ["SCTV", "RCTI", "Indosiar", "MNCTV", "GTV"])
        by = {e.name: e for e in result}
        self.assertEqual(by["SCTV"].url, "https://indihome/sctv.mpd")          # manual: tak diusik
        self.assertEqual(by["Indosiar"].url, "https://indihome/indosiar.mpd")  # manual: tak diusik
        self.assertIn("auth_key=2-c-0-d", by["RCTI"].url)                      # disegarkan
        self.assertIn("auth_key=1-a-0-b", by["MNCTV"].url)                     # gagal -> tautan lama
        self.assertEqual(by["RCTI"].group, "TV Nasional")
        self.assertEqual(by["RCTI"].vlc_opt("http-referrer"), "https://m.rctiplus.com/")

    def test_merge_appends_missing_managed_channel(self):
        channels = [{"api_id": 1, "name": "RCTI", "logo": ""},
                    {"api_id": 4, "name": "iNews", "logo": ""}]
        old = [m3ulib.Entry(name="SCTV", url="https://indihome/sctv.mpd"),
               m3ulib.Entry(name="RCTI", url="https://old/r.m3u8?auth_key=1-a-0-b")]
        fresh = {"rcti": "https://new/r.m3u8?auth_key=2-c-0-d",
                 "inews": "https://new/i.m3u8?auth_key=2-c-0-d"}
        result = update_rcti.merge_playlist(channels, old, fresh)
        self.assertEqual([e.name for e in result], ["SCTV", "RCTI", "iNews"])
        self.assertIn("new/r.m3u8", result[1].url)
        self.assertIn("new/i.m3u8", result[2].url)

    def test_merge_preserves_exact_manual_blocks(self):
        """Reproduksi keluaran user: RCTI/MNCTV/iNews dikelola, GTV di akhir, manual di tengah."""
        channels = [{"api_id": 1, "name": "RCTI", "logo": ""},
                    {"api_id": 2, "name": "MNCTV", "logo": ""},
                    {"api_id": 3, "name": "GTV", "logo": ""},
                    {"api_id": 4, "name": "iNews", "logo": ""}]
        text = (
            '#EXTM3U\n'
            '#EXTINF:-1 tvg-id="RCTI", RCTI\nhttps://linier-rcti/x.m3u8?auth_key=1-a-0-b\n'
            '#EXTINF:-1 tvg-id="MNCTV", MNCTV\nhttps://linier-mnctv/x.m3u8?auth_key=1-a-0-b\n'
            '#EXTINF:-1 tvg-id="iNews", iNews\nhttps://linier-inews/x.m3u8?auth_key=1-a-0-b\n'
            '#EXTINF:-1 group-title="TV Nasional", SCTV HD\n'
            '#EXTVLCOPT:http-user-agent=VidioPlayer/6.31.6\n'
            '#KODIPROP:inputstream.adaptive.license_type=com.widevine.alpha\n'
            'https://nextgenz.my.id/event/pidio/play.mpd?id=204&type=dash\n'
            '#EXTINF:-1 group-title="TV Nasional", Trans TV\n'
            'https://live.cnbcindonesia.com/transtv/smil:transtv.smil/playlist.m3u8\n'
            '#EXTINF:-1 tvg-id="GTV", GTV\nhttps://linier-gtv/x.m3u8?auth_key=1-a-0-b\n')
        old = m3ulib.parse(text).entries
        fresh = {k: v + "?new" for k, v in
                 {"rcti": "https://linier-rcti/x.m3u8", "mnctv": "https://linier-mnctv/x.m3u8",
                  "gtv": "https://linier-gtv/x.m3u8", "inews": "https://linier-inews/x.m3u8"}.items()}
        result = update_rcti.merge_playlist(channels, old, fresh)
        self.assertEqual([e.name for e in result],
                         ["RCTI", "MNCTV", "iNews", "SCTV HD", "Trans TV", "GTV"])
        by = {e.name: e for e in result}
        # entri manual persis sama (opsi & URL) seperti aslinya:
        src = {e.name: e for e in old}
        for n in ("SCTV HD", "Trans TV"):
            self.assertEqual(by[n].url, src[n].url)
            self.assertEqual(by[n].options, src[n].options)
        # yang dikelola memakai tautan baru:
        for n in ("RCTI", "MNCTV", "GTV", "iNews"):
            self.assertTrue(by[n].url.endswith("?new"), n)

    def test_lost_names_guard(self):
        """Pengaman terakhir: kalau ada channel lama akan hilang, harus terdeteksi."""
        old = [m3ulib.Entry(name="RCTI", url="a"), m3ulib.Entry(name="SCTV HD", url="b")]
        ok = [m3ulib.Entry(name="RCTI", url="a2"), m3ulib.Entry(name="SCTV HD", url="b")]
        self.assertEqual(update_rcti.lost_names(old, ok), [])
        bad = [m3ulib.Entry(name="RCTI", url="a2")]
        self.assertEqual(update_rcti.lost_names(old, bad), ["SCTV HD"])

    def test_needs_refresh_rules(self):
        channels = [{"api_id": 1, "name": "RCTI", "logo": ""}]
        now = int(time.time())
        stale = [m3ulib.Entry(name="RCTI", url=f"https://h/r.m3u8?auth_key={now - 10}-a-0-b")]
        fresh = [m3ulib.Entry(name="RCTI", url=f"https://h/r.m3u8?auth_key={now + 7200}-a-0-b")]
        old_force = update_rcti.FORCE
        update_rcti.FORCE = False
        try:
            self.assertTrue(update_rcti.needs_refresh(channels, stale))
            self.assertFalse(update_rcti.needs_refresh(channels, fresh))
            self.assertTrue(update_rcti.needs_refresh(channels, []))       # belum ada entri
        finally:
            update_rcti.FORCE = old_force

    def test_expiry_and_norm_helpers(self):
        self.assertEqual(update_rcti.expiry_of("https://h/a.m3u8?auth_key=1795557888-xy-0-z"), 1795557888)
        self.assertIsNone(update_rcti.expiry_of("https://h/a.m3u8"))
        self.assertEqual(update_rcti.norm("  RCTI  "), "rcti")
        self.assertEqual(update_rcti.norm("MNCTV"), update_rcti.norm("mnctv"))


class VidioTests(unittest.TestCase):
    def test_jwt_exp_offline(self):
        import base64
        payload = base64.urlsafe_b64encode(b'{"exp":123}').decode().rstrip("=")
        self.assertEqual(vidio.jwt_exp(f"h.{payload}.s"), 123)
        self.assertIsNone(vidio.jwt_exp("bukan-jwt"))


if __name__ == "__main__":
    unittest.main()
