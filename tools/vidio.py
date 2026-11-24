#!/usr/bin/env python3
"""vidio.py -- (OPSIONAL) pengambil info/tautan siaran vidio.com.

Hasil uji langsung (2026) terhadap endpoint vidio:
  1. Kunci API anonim:  POST https://www.vidio.com/auth
         body kosong, header 'Referer: https://www.vidio.com/'
         -> {"api_key":"<JWT>", "api_key_expires_at": ...}
     (GET ke URL itu 404; HARUS POST. Kunci berlaku ~1x24 jam.)
  2. Metadata siaran:   GET https://www.vidio.com/api/livestreamings/<id>/detail
         header 'X-API-KEY: <jwt>'
         -> title, image, is_premium, is_drm, need_login, dst.
  3. Tautan video final:GET https://api.vidio.com/livestreamings/<id>/stream?initialize=true
         butuh header 'X-Signature' yang DIHITUNG oleh JavaScript situs.
         Tanpa itu server membalas 403 {"title":"invalid_signature"}.
         Channel premium (mis. Indosiar 205, SCTV 204: is_premium=true) juga
         butuh login langganan.

Karena tautan final butuh tanda tangan/akun, modul ini dirancang AMAN:
  * mengembalikan None bila tautan tak didapat (pemanggil mempertahankan tautan lama),
  * TIDAK PERNAH menghapus/menimpa channel yang sudah ada,
  * hanya dipakai bila sebuah channel diberi "source": "vidio" di data/rcti_channels.json.

Pemakaian CLI:
  python3 tools/vidio.py meta 205                 # lihat metadata Indosiar
  python3 tools/vidio.py stream 205               # coba ambil tautan (umumnya gagal utk premium)
  python3 tools/vidio.py entry 205 --name Indosiar  # cetak satu entri M3U (bila tautan ada)
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import sys

import requests

AUTH_URL = "https://www.vidio.com/auth"
DETAIL_URL = "https://www.vidio.com/api/livestreamings/{vid}/detail"
STREAM_URL = "https://api.vidio.com/livestreamings/{vid}/stream?initialize=true"
SITE = "https://www.vidio.com/"
USER_AGENT = ("Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/143.0.0.0 Mobile Safari/537.36")

log = logging.getLogger("vidio")


class VidioError(Exception):
    pass


def _headers(key: str) -> dict:
    return {"User-Agent": USER_AGENT, "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/vnd.api+json", "Origin": SITE.rstrip("/"),
            "Referer": SITE, "X-API-KEY": key, "X-Api-Platform": "web-desktop"}


def jwt_exp(token: str):
    """Baca klaim 'exp' dari JWT tanpa verifikasi tanda tangan; None bila gagal."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload)).get("exp")
    except Exception:  # noqa: BLE001
        return None


def fetch_api_key(session: requests.Session, timeout: float = 20) -> str:
    """Ambil kunci API anonim (POST /auth). Melempar VidioError bila gagal."""
    r = session.post(AUTH_URL, data=b"", timeout=timeout,
                     headers={"User-Agent": USER_AGENT, "Referer": SITE,
                              "Origin": SITE.rstrip("/"),
                              "Content-Type": "application/json",
                              "Accept": "application/json"})
    if r.status_code != 200:
        raise VidioError(f"POST /auth -> HTTP {r.status_code}")
    try:
        key = r.json().get("api_key")
    except ValueError as e:
        raise VidioError(f"balasan /auth bukan JSON: {e}") from e
    if not key:
        raise VidioError("balasan /auth tanpa api_key")
    return key


def fetch_detail(session: requests.Session, key: str, vidio_id, timeout: float = 20) -> dict:
    """Metadata siaran (title, image, is_premium, ...). Kembalikan dict (mungkin kosong)."""
    r = session.get(DETAIL_URL.format(vid=vidio_id), headers=_headers(key), timeout=timeout)
    if r.status_code != 200:
        raise VidioError(f"/detail -> HTTP {r.status_code}")
    data = r.json() or {}
    return (data.get("livestreamings") or [{}])[0]


def fetch_stream_url(session: requests.Session, key: str, vidio_id, timeout: float = 20):
    """Coba ambil tautan .m3u8/.mpd. Kembalikan (url|None, alasan).

    Umumnya mengembalikan (None, 'invalid_signature ...') karena endpoint ini
    memerlukan X-Signature dari JavaScript situs.
    """
    try:
        r = session.get(STREAM_URL.format(vid=vidio_id), headers=_headers(key), timeout=timeout)
    except requests.RequestException as e:
        return None, type(e).__name__
    if r.status_code != 200:
        reason = f"HTTP {r.status_code}"
        try:
            err = (r.json().get("errors") or [{}])[0].get("title")
            if err:
                reason += f" ({err})"
        except ValueError:
            pass
        return None, reason
    attrs = ((r.json().get("data") or {}).get("attributes")) or {}
    return attrs.get("hls") or attrs.get("dash"), ""


def resolve(session: requests.Session, key: str, vidio_id):
    """Kembalikan (meta, url|None, catatan). Aman: tidak melempar ke pemanggil."""
    meta, url, note = {}, None, ""
    try:
        meta = fetch_detail(session, key, vidio_id)
    except Exception as e:  # noqa: BLE001
        return {}, None, str(e)
    url, note = fetch_stream_url(session, key, vidio_id)
    if not url and (meta.get("is_premium") or meta.get("need_login")):
        note = (note or "tautan tak tersedia") + " (channel premium: butuh akun langganan)"
    return meta, url, note


def build_entry(ch: dict, meta: dict, url: str):
    """Entri M3U siap tulis untuk satu channel Vidio."""
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import m3ulib
    e = m3ulib.Entry(name=ch["name"], url=url)
    e.attrs = {"tvg-id": ch.get("tvg_id") or ch["name"],
               "tvg-name": ch["name"],
               "group-title": ch.get("group") or "TV Nasional"}
    logo = ch.get("logo") or meta.get("image")
    if logo:
        e.attrs["tvg-logo"] = logo
    e.set_vlc_opt("http-referrer", SITE)
    e.set_vlc_opt("http-user-agent", USER_AGENT)
    return e


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Alat bantu vidio.com (opsional)")
    ap.add_argument("mode", choices=["meta", "stream", "entry"])
    ap.add_argument("vidio_id", help="id siaran vidio (mis. 205 = Indosiar, 204 = SCTV)")
    ap.add_argument("--name", default="", help="nama channel untuk mode 'entry'")
    ap.add_argument("--group", default="TV Nasional")
    ap.add_argument("--logo", default="")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    s = requests.Session()
    key = fetch_api_key(s)
    print(f"api_key OK (exp={jwt_exp(key)})")
    meta = fetch_detail(s, key, args.vidio_id)
    if args.mode == "meta":
        print(json.dumps(meta, ensure_ascii=False, indent=2))
        return 0
    url, note = fetch_stream_url(s, key, args.vidio_id)
    if not url:
        print(f"Tautan tidak tersedia: {note}", file=sys.stderr)
        return 1
    if args.mode == "stream":
        print(url)
        return 0
    e = build_entry({"name": args.name or meta.get("title") or args.vidio_id,
                     "group": args.group, "logo": args.logo}, meta, url)
    import m3ulib
    print(m3ulib.dumps([e]), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
