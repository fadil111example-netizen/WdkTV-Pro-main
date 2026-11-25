#!/usr/bin/env python3
"""update_rcti.py -- penyegar token siaran RCTI+ (RCTI, MNCTV, GTV, iNews).

Latar belakang (perbaikan 2026)
-------------------------------
Versi lama mengambil cookie `visitor_token` dengan membuka https://m.rctiplus.com/.
Sejak situs diubah, server tidak lagi memberi cookie itu kepada bot, sehingga bot
selalu berhenti dengan pesan "Cookie visitor_token tidak diberikan server".

Cara baru memakai dua endpoint publik yang MASIH berfungsi:
  1. GET https://api.rctiplus.com/api/v1/visitor?platform=mweb
        -> balasan JSON: data.access_token  (token "tamu", masa berlaku jam-an)
  2. GET https://api.rctiplus.com/api/v1/live-event/<api_id>/url?appierid=<aid>
        header: Authorization: <access_token>
        -> balasan JSON: data.url = tautan .m3u8 + auth_key

Sifat penting
-------------
  * TIDAK wajib RCTI_APIKEY lagi (tetap dikirim bila ada).
  * HANYA channel yang terdaftar di data/rcti_channels.json yang disentuh.
    Channel manual lain di file yang sama (SCTV, Indosiar, dst.) DIPERTAHANKAN
    apa adanya -- menyegarkan RCTI/MNCTV tidak akan menghapusnya.
  * OPSIONAL: channel ber-"source": "vidio" di data/rcti_channels.json juga
    dibina lewat tools/vidio.py. Sifatnya percobaan & TIDAK pernah fatal:
    bila tautan tak didapat, tautan lama tetap dipakai dan channel tak dihapus.
  * Bila satu channel gagal, tautan lamanya tetap dipakai (tidak dihapus).
  * Bila token tidak didapat, file tidak diubah dan tautan lama dipertahankan.
  * Penulisan file atomik (tidak ada file setengah jadi).
  * Bot 'pintar': bila semua tautan yang dikelola masih berlaku > MIN_REMAINING_SEC,
    bot berhenti tanpa menyentuh jaringan/file (tidak ada commit sampah).

Variabel lingkungan
-------------------
  MIN_REMAINING_SEC  (opsi)  ambang sisa umur, detik. default 1800 (30 menit)
  FORCE_REFRESH      (opsi)  '1' = segarkan walau masih berlaku
  OUTPUT_FILE        (opsi)  file playlist. default streams/id.m3u
  RCTI_APIKEY        (opsi)  tidak wajib; dikirim sebagai header 'apikey' bila diisi
  RCTI_PLATFORM      (opsi)  platform token pertama yang dicoba. default 'mweb'
  APPIER_ID_BASE     (opsi)  awalan appierid. default 23984824

Kode keluar
-----------
  0 = sukses (atau tidak perlu update / tautan lama masih dipakai)
  1 = gagal total dan tidak ada satu pun tautan lama yang bisa dipakai
  2 = konfigurasi salah (mis. data/rcti_channels.json rusak)
"""
from __future__ import annotations

import json
import logging
import os
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE, "tools"))
import m3ulib  # noqa: E402

OUTPUT_FILE = os.environ.get("OUTPUT_FILE", os.path.join(BASE, "streams", "id.m3u"))
CHANNEL_FILE = os.path.join(BASE, "data", "rcti_channels.json")
MIN_REMAINING = int(os.environ.get("MIN_REMAINING_SEC", "1800"))
FORCE = os.environ.get("FORCE_REFRESH") == "1"
APPIER_BASE = os.environ.get("APPIER_ID_BASE", "23984824")

USER_AGENT = ("Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/143.0.0.0 Mobile Safari/537.36")
SITE = "https://m.rctiplus.com/"
VIDIO_SITE = "https://www.vidio.com/"
GROUP = "TV Nasional"
VISITOR_API = "https://api.rctiplus.com/api/v1/visitor?platform={platform}"
LIVE_API = "https://api.rctiplus.com/api/v1/live-event/{api_id}/url"

# Urutan platform yang dicoba untuk memperoleh token tamu.
_platform_first = os.environ.get("RCTI_PLATFORM", "").strip()
PLATFORMS = [p for p in (_platform_first, "mweb", "web", "android", "ios") if p]
PLATFORMS = list(dict.fromkeys(PLATFORMS))  # buang duplikat, jaga urutan

log = logging.getLogger("update_rcti")


def norm(name: str) -> str:
    """Kunci pencocokan nama channel: rapatkan spasi + huruf kecil."""
    return re.sub(r"\s+", " ", (name or "").strip()).casefold()


def expiry_of(url: str):
    """Waktu kedaluwarsa (epoch) dari auth_key=<epoch>-<hash>-...; None bila tak ada."""
    m = re.search(r"auth_key=(\d{9,11})-", url or "")
    return int(m.group(1)) if m else None


def request_with_retry(session: requests.Session, url: str, *, tries: int = 3, **kw):
    """GET dengan percobaan ulang pada galat jaringan / status 5xx."""
    last = None
    for i in range(tries):
        try:
            r = session.get(url, timeout=20, **kw)
            if r.status_code < 500:
                return r
            last = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            last = e
        wait = min(2 ** i, 8)
        log.warning("percobaan %d/%d gagal (%s); tunggu %ds", i + 1, tries, last, wait)
        time.sleep(wait)
    raise RuntimeError(f"gagal menghubungi {url}: {last}")


def acquire_token(apikey: str, session: requests.Session) -> str | None:
    """Ambil token tamu dari endpoint /visitor. Coba beberapa platform."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json",
               "Referer": SITE, "Origin": SITE.rstrip("/")}
    if apikey:
        headers["apikey"] = apikey
    last = None
    for platform in PLATFORMS:
        url = VISITOR_API.format(platform=platform)
        try:
            r = request_with_retry(session, url, headers=headers, tries=2)
            if r.status_code != 200:
                last = f"HTTP {r.status_code}"
            else:
                token = (r.json().get("data") or {}).get("access_token")
                if token:
                    log.info("Token tamu diperoleh (platform=%s)", platform)
                    return token
                last = "balasan tanpa data.access_token"
        except Exception as e:  # noqa: BLE001
            last = e
        log.warning("Token lewat platform '%s' gagal: %s", platform, last)
    log.error("Tidak bisa memperoleh token tamu dari %s (%s)", VISITOR_API.format(platform=PLATFORMS[0]), last)
    return None


def load_channels() -> list:
    with open(CHANNEL_FILE, encoding="utf-8") as f:
        data = json.load(f)
    channels = []
    for ch in data:
        name = ch.get("name")
        if not name:
            continue
        source = (ch.get("source") or "rcti").lower()
        if source == "vidio":
            if ch.get("vidio_id") is None:
                continue
            channels.append({"source": "vidio", "vidio_id": int(ch["vidio_id"]),
                             "name": name, "logo": ch.get("logo", ""),
                             "tvg_id": ch.get("tvg_id", ""), "group": ch.get("group", "")})
        elif ch.get("api_id") is not None:
            channels.append({"source": "rcti", "api_id": int(ch["api_id"]),
                             "name": name, "logo": ch.get("logo", ""),
                             "tvg_id": ch.get("tvg_id", ""), "group": ch.get("group", "")})
    if not channels:
        raise SystemExit(f"data/rcti_channels.json kosong / tidak valid: {CHANNEL_FILE}")
    return channels


def current_entries() -> list:
    if not os.path.exists(OUTPUT_FILE):
        return []
    return m3ulib.parse_file(OUTPUT_FILE).entries


def needs_refresh(channels: list, existing: list) -> bool:
    if FORCE:
        return True
    rcti = [ch for ch in channels if ch.get("source", "rcti") == "rcti"]
    if not rcti:
        return True                       # hanya ada channel vidio: selalu dicoba saat dijalankan
    by_name = {norm(e.name): e for e in existing}
    now = time.time()
    for ch in rcti:
        e = by_name.get(norm(ch["name"]))
        exp = expiry_of(e.url) if e else None
        if exp is None or exp - now < MIN_REMAINING:
            log.info("%s: perlu disegarkan (sisa %s detik)", ch["name"],
                     "?" if exp is None else int(exp - now))
            return True
    return False


def make_entry(ch: dict, stream_url: str) -> m3ulib.Entry:
    e = m3ulib.Entry(name=ch["name"], url=stream_url)
    e.attrs = {"tvg-id": ch.get("tvg_id") or ch["name"], "tvg-name": ch["name"],
               "group-title": ch.get("group") or GROUP}
    if ch.get("logo"):
        e.attrs["tvg-logo"] = ch["logo"]
    if ch.get("source") == "vidio":
        e.set_vlc_opt("http-referrer", VIDIO_SITE)
        e.set_vlc_opt("http-user-agent", USER_AGENT)
    else:
        e.set_vlc_opt("http-referrer", SITE)
        e.set_vlc_opt("http-user-agent", USER_AGENT)
    return e


def fetch_vidio(session: requests.Session, ch: dict):
    """(nama, url|None, catatan). PENTING: tidak pernah melempar keluar.

    Butuh tools/vidio.py. Bila modul/tautan tidak tersedia, kembalikan None agar
    pemanggil memakai tautan lama (channel tidak pernah dihapus).
    """
    try:
        import vidio
    except Exception as e:  # noqa: BLE001
        return ch["name"], None, f"modul vidio tidak tersedia: {e}"
    try:
        key = vidio.fetch_api_key(session)
        _meta, url, note = vidio.resolve(session, key, ch["vidio_id"])
        return ch["name"], url, note
    except Exception as e:  # noqa: BLE001
        return ch["name"], None, str(e)


def fetch_channel(session: requests.Session, ch: dict, token: str, apikey: str):
    """Kembalikan (nama, url|None, catatan). url None = pakai tautan lama."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json, text/plain, */*",
               "Origin": SITE.rstrip("/"), "Referer": SITE, "authorization": token}
    if apikey:
        headers["apikey"] = apikey
    aid = f"{APPIER_BASE}_{random.randint(0, 10**10)}"
    url = LIVE_API.format(api_id=ch["api_id"])
    try:
        r = request_with_retry(session, url, headers=headers, params={"appierid": aid}, tries=3)
    except Exception as e:  # noqa: BLE001
        return ch["name"], None, str(e)
    if r.status_code != 200:
        return ch["name"], None, f"HTTP {r.status_code}"
    try:
        data = r.json() or {}
    except ValueError:
        return ch["name"], None, "balasan bukan JSON"
    got = (data.get("data") or {}).get("url")
    if not got:
        status = (data.get("status") or {})
        return ch["name"], None, status.get("message_client") or "tautan kosong di balasan"
    return ch["name"], got.replace("\\/", "/"), ""


def merge_playlist(channels: list, old_entries: list, fresh: dict) -> list:
    """Bangun playlist baru.

    Urutan mengikuti playlist LAMA (agar channel manual tidak berubah posisi).
    Channel terkelola memakai tautan baru bila ada, jika tidak tautan lama;
    channel manual disalin apa adanya. Channel terkelola yang belum ada di file
    ditambahkan di akhir.
    """
    cs = {norm(ch["name"]): ch for ch in channels}
    used: set = set()
    result: list = []
    for e in old_entries:
        key = norm(e.name)
        if key in cs:
            used.add(key)
            url = fresh.get(key)
            if url:
                result.append(make_entry(cs[key], url))
            else:
                result.append(e)          # pertahankan tautan lama
        else:
            result.append(e)              # channel manual: jangan diganggu
    for ch in channels:                   # yang belum ada sama sekali
        key = norm(ch["name"])
        if key in used:
            continue
        url = fresh.get(key)
        if url:
            result.append(make_entry(ch, url))
        else:
            log.warning("%s: tidak ada tautan baru maupun lama; dilewati", ch["name"])
    return result


def lost_names(old_entries: list, result: list) -> list:
    """Nama entri lama yang tidak lagi ada di hasil.

    Pengaman terakhir: daftar ini HARUS kosong. Kalau tidak, berarti ada channel
    (mis. SCTV/Indosiar/manual) yang akan hilang dan penulisan harus dibatalkan.
    """
    new_names = {norm(e.name) for e in result}
    return [e.name for e in old_entries if norm(e.name) not in new_names]


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    apikey = os.environ.get("RCTI_APIKEY", "").strip()

    try:
        channels = load_channels()
    except SystemExit as e:
        log.error("%s", e)
        return 2
    old_entries = current_entries()
    if not needs_refresh(channels, old_entries):
        log.info("Semua tautan terkelola masih berlaku > %d detik. Tidak ada yang diubah.",
                 MIN_REMAINING)
        return 0

    log.info("Menyegarkan %d channel: %s", len(channels),
             ", ".join(ch["name"] for ch in channels))
    session = requests.Session()
    rcti = [ch for ch in channels if ch.get("source", "rcti") == "rcti"]
    vidio_ch = [ch for ch in channels if ch.get("source") == "vidio"]
    fresh: dict = {}
    ok = 0

    # --- Sumber RCTI+ (wajib token tamu) ---
    if rcti:
        token = acquire_token(apikey, session)
        if not token:
            log.warning("Token RCTI+ tidak didapat; channel RCTI+ memakai tautan lama.")
        else:
            with ThreadPoolExecutor(max_workers=min(8, len(rcti))) as ex:
                futs = [ex.submit(fetch_channel, session, ch, token, apikey) for ch in rcti]
                for fut in futs:
                    name, url, note = fut.result()
                    if url:
                        fresh[norm(name)] = url
                        ok += 1
                        exp = expiry_of(url)
                        log.info("%s: OK (berlaku sekitar %s menit)", name,
                                 int((exp - time.time()) / 60) if exp else "?")
                    else:
                        log.error("%s: gagal disegarkan (%s); tautan lama dipakai", name, note)

    # --- Sumber vidio.com (OPSIONAL, tidak pernah fatal) ---
    for ch in vidio_ch:
        name, url, note = fetch_vidio(session, ch)
        if url:
            fresh[norm(name)] = url
            ok += 1
            log.info("%s (vidio): OK", name)
        else:
            log.warning("%s (vidio): %s; tautan lama dipakai", name, note or "tautan tak tersedia")

    if ok == 0:
        log.error("Tidak satu pun tautan berhasil diperbarui. File TIDAK diubah.")
        return 0 if old_entries else 1

    result = merge_playlist(channels, old_entries, fresh)
    if not result:
        log.error("Tidak ada entri untuk ditulis. File TIDAK diubah.")
        return 1

    # Lapisan pengaman terakhir: setiap NAMA entri lama (khususnya channel manual)
    # harus tetap ada di hasil. Hanya channel terkelola yang boleh "diganti", dan
    # namanya tetap sama. Bila ada nama yang hilang, batalkan penulisan.
    lost = lost_names(old_entries, result)
    if lost:
        for m in lost:
            log.error("DIBATALKAN: channel lama akan hilang -> %s", m)
        log.error("Penulisan DIBATALKAN demi keamanan: %d channel lama tidak boleh hilang.",
                  len(lost))
        return 1

    m3ulib.write_file(OUTPUT_FILE, result, "#EXTM3U")
    log.info("Selesai: %d/%d terkelola diperbarui; total %d entri -> %s",
             ok, len(channels), len(result), OUTPUT_FILE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
