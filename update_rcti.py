#!/usr/bin/env python3
"""update_rcti.py -- penyegar token link siaran (versi rapi).

Perbedaan dari versi lama:
  * apikey TIDAK lagi ditulis di kode. Ambil dari environment variable RCTI_APIKEY
    (di GitHub: Settings > Secrets and variables > Actions > New repository secret).
  * Tidak ada token JWT cadangan yang tertanam di kode.
  * 'Pintar': bila semua link di streams/id.m3u masih punya sisa umur cukup
    (default 15 menit), bot berhenti tanpa menyentuh file -> tidak ada commit sampah.
  * Satu channel gagal TIDAK menghapus channel itu: link lamanya dipertahankan.
  * Percobaan ulang dengan jeda bertahap, log berwaktu, penulisan file atomik.
  * Daftar channel dipindah ke data/rcti_channels.json (mudah diedit).

Variabel lingkungan:
  RCTI_APIKEY        (wajib)  kunci API
  MIN_REMAINING_SEC  (opsi)   ambang sisa umur link sebelum disegarkan, default 900
  FORCE_REFRESH      (opsi)   '1' = segarkan walau link masih berlaku
  OUTPUT_FILE        (opsi)   default streams/id.m3u

Kode keluar: 0 = sukses/tidak perlu update, 1 = tidak ada link yang berhasil, 2 = konfigurasi salah.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import uuid

import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))
import m3ulib  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.environ.get("OUTPUT_FILE", os.path.join(BASE, "streams", "id.m3u"))
CHANNEL_FILE = os.path.join(BASE, "data", "rcti_channels.json")
MIN_REMAINING = int(os.environ.get("MIN_REMAINING_SEC", "900"))
FORCE = os.environ.get("FORCE_REFRESH") == "1"

USER_AGENT = ("Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/143.0.0.0 Mobile Safari/537.36")
SITE = "https://m.rctiplus.com/"
API = "https://toutatis.rctiplus.com/video/live/api/v1/live/{api_id}/url"
M3U8_RE = re.compile(r'(https://[^"\'\s<>]+\.m3u8[^"\'\s<>]*)')

log = logging.getLogger("update_rcti")


def expiry_of(url: str) -> int | None:
    """Ambil waktu kedaluwarsa (epoch) dari auth_key=<epoch>-<hash>-... ; None bila tak ada."""
    m = re.search(r"auth_key=(\d{9,11})-", url)
    return int(m.group(1)) if m else None


def get_with_retry(session: requests.Session, url: str, *, tries: int = 3, **kw):
    last = None
    for i in range(tries):
        try:
            r = session.get(url, timeout=15, **kw)
            if r.status_code < 500:
                return r
            last = RuntimeError(f"HTTP {r.status_code}")
        except requests.RequestException as e:
            last = e
        wait = 2 ** i
        log.warning("percobaan %d/%d gagal (%s); tunggu %ds", i + 1, tries, last, wait)
        time.sleep(wait)
    raise last  # type: ignore[misc]


def load_channels() -> list:
    with open(CHANNEL_FILE, encoding="utf-8") as f:
        return json.load(f)


def current_entries() -> dict:
    if not os.path.exists(OUTPUT_FILE):
        return {}
    return {e.name: e for e in m3ulib.parse_file(OUTPUT_FILE).entries}


def needs_refresh(channels: list, existing: dict) -> bool:
    if FORCE:
        return True
    now = time.time()
    for ch in channels:
        e = existing.get(ch["name"])
        exp = expiry_of(e.url) if e else None
        if exp is None or exp - now < MIN_REMAINING:
            log.info("%s: perlu disegarkan (sisa %s detik)", ch["name"],
                     "?" if exp is None else int(exp - now))
            return True
    return False


def make_entry(ch: dict, stream_url: str) -> m3ulib.Entry:
    e = m3ulib.Entry(name=ch["name"], url=stream_url)
    e.attrs = {"tvg-id": ch["name"], "tvg-name": ch["name"],
               "tvg-logo": ch["logo"], "group-title": "TV Nasional"}
    e.set_vlc_opt("http-referrer", SITE)
    e.set_vlc_opt("http-user-agent", USER_AGENT)
    return e


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    apikey = os.environ.get("RCTI_APIKEY", "").strip()
    if not apikey:
        log.error("RCTI_APIKEY belum diisi. Set sebagai GitHub Secret / export RCTI_APIKEY=...")
        return 2

    channels = load_channels()
    existing = current_entries()
    if not needs_refresh(channels, existing):
        log.info("Semua link masih berlaku > %d detik. Tidak ada yang diubah.", MIN_REMAINING)
        return 0

    session = requests.Session()
    try:
        get_with_retry(session, SITE, headers={"User-Agent": USER_AGENT})
    except Exception as e:  # noqa: BLE001
        log.error("Gagal membuka %s: %s", SITE, e)
        return 1
    token = session.cookies.get("visitor_token")
    if not token:
        log.error("Cookie visitor_token tidak diberikan server (format situs mungkin berubah).")
        return 1

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json, text/plain, */*",
               "Origin": SITE.rstrip("/"), "Referer": SITE,
               "apikey": apikey, "authorization": token}
    device_id = str(uuid.uuid4())

    result, ok_count = [], 0
    for ch in channels:
        entry = existing.get(ch["name"])           # default: pertahankan link lama
        try:
            r = get_with_retry(session, API.format(api_id=ch["api_id"]), headers=headers,
                               params={"appierid": device_id})
            if r.status_code != 200:
                log.error("%s: API menjawab HTTP %s", ch["name"], r.status_code)
            else:
                m = M3U8_RE.search(json.dumps(r.json()))
                if m:
                    entry = make_entry(ch, m.group(1).replace("\\/", "/"))
                    ok_count += 1
                    exp = expiry_of(entry.url)
                    log.info("%s: OK (berlaku sekitar %s menit)", ch["name"],
                             int((exp - time.time()) / 60) if exp else "?")
                else:
                    log.error("%s: tidak ada link .m3u8 di jawaban API", ch["name"])
        except Exception as e:  # noqa: BLE001
            log.error("%s: %s", ch["name"], e)
        if entry:
            result.append(entry)

    if ok_count == 0:
        log.error("Tidak satu pun link berhasil diperbarui. File TIDAK diubah.")
        return 1
    m3ulib.write_file(OUTPUT_FILE, result)
    log.info("Selesai: %d/%d channel diperbarui -> %s", ok_count, len(channels), OUTPUT_FILE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
