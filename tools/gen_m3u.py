#!/usr/bin/env python3
"""gen_m3u: bangun satu file M3U dari banyak sumber (otomatis).

Sumber yang dikenali (dari ekstensi file):
  .json  daftar objek:  [{"name":"RCTI","url":"https://...","group":"TV Nasional",
                          "logo":"...","tvg_id":"RCTI","referrer":"...","user_agent":"..."}]
         (format sederhana dari tv-bro.html -- hanya name & url -- juga diterima)
  .csv   kolom: name,url,group,logo,tvg_id,referrer,user_agent   (baris pertama = judul kolom)
  .m3u   playlist M3U biasa (digabung apa adanya)

Fitur: gabung, buang duplikat (URL sama), urutkan, ganti nama grup, buang channel kosong,
       tambah header EPG (url-tvg), dan opsi --check untuk menyaring link yang mati.

Contoh:
  python3 tools/gen_m3u.py -i data/sources.json streams/id.m3u -o build/all.m3u --sort --epg https://x/guide.xml.gz
  python3 tools/gen_m3u.py -i data/channels.csv -o out.m3u --default-group "Lainnya"
  python3 tools/gen_m3u.py --config data/gen_config.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m3ulib  # noqa: E402
from m3ulib import Entry  # noqa: E402


def _from_record(rec: dict, default_group: str) -> Entry | None:
    name = (rec.get("name") or rec.get("title") or "").strip()
    url = (rec.get("url") or "").strip()
    if not name or not url:
        return None
    e = Entry(name=name, url=url)
    if rec.get("tvg_id") or rec.get("tvg-id"):
        e.attrs["tvg-id"] = rec.get("tvg_id") or rec.get("tvg-id")
    e.attrs["tvg-name"] = name
    if rec.get("logo"):
        e.attrs["tvg-logo"] = rec["logo"]
    e.attrs["group-title"] = (rec.get("group") or default_group).strip()
    if rec.get("referrer"):
        e.set_vlc_opt("http-referrer", rec["referrer"])
    if rec.get("user_agent"):
        e.set_vlc_opt("http-user-agent", rec["user_agent"])
    return e


def load_source(path: str, default_group: str) -> list:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".m3u" or ext == ".m3u8":
        return m3ulib.parse_file(path).entries
    if ext == ".json":
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):                   # dukung {"channels":[...]}
            data = data.get("channels", [])
        return [e for e in (_from_record(r, default_group) for r in data) if e]
    if ext == ".csv":
        with open(path, encoding="utf-8", newline="") as f:
            return [e for e in (_from_record(r, default_group) for r in csv.DictReader(f)) if e]
    raise SystemExit(f"Format sumber tidak dikenali: {path}")


def build(entries: list, *, dedupe: bool, sort: bool, rename: dict) -> list:
    out, seen = [], set()
    for e in entries:
        if not e.name or not e.clean_url:
            continue
        if e.group in rename:
            e.group = rename[e.group]
        if dedupe:
            key = e.clean_url
            if key in seen:
                continue
            seen.add(key)
        out.append(e)
    if sort:
        out.sort(key=lambda e: (e.group.lower(), e.name.lower()))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Generate playlist M3U dari banyak sumber")
    ap.add_argument("-i", "--input", nargs="*", default=[], help="file sumber (.json/.csv/.m3u)")
    ap.add_argument("-o", "--output", help="file M3U hasil")
    ap.add_argument("--config", help="file JSON berisi {inputs, output, epg, sort, dedupe, rename_groups, default_group}")
    ap.add_argument("--epg", default="", help="URL EPG (XMLTV) untuk header url-tvg")
    ap.add_argument("--default-group", default="Tanpa Grup")
    ap.add_argument("--sort", action="store_true", help="urutkan per grup lalu nama")
    ap.add_argument("--no-dedupe", action="store_true", help="jangan buang URL duplikat")
    ap.add_argument("--check", action="store_true", help="saring link mati (butuh jaringan)")
    args = ap.parse_args(argv)

    cfg = {}
    if args.config:
        with open(args.config, encoding="utf-8") as f:
            cfg = json.load(f)
    inputs = args.input or cfg.get("inputs", [])
    output = args.output or cfg.get("output")
    epg = args.epg or cfg.get("epg", "")
    default_group = cfg.get("default_group", args.default_group)
    do_sort = args.sort or cfg.get("sort", False)
    do_dedupe = not args.no_dedupe and cfg.get("dedupe", True)
    rename = cfg.get("rename_groups", {})
    if not inputs or not output:
        ap.error("butuh -i <sumber...> dan -o <output> (atau --config)")

    base = os.path.dirname(os.path.abspath(args.config)) if args.config else os.getcwd()
    entries: list = []
    for p in inputs:
        path = p if os.path.isabs(p) or os.path.exists(p) else os.path.join(base, p)
        got = load_source(path, default_group)
        print(f"  + {path}: {len(got)} channel")
        entries.extend(got)

    result = build(entries, dedupe=do_dedupe, sort=do_sort, rename=rename)

    if args.check:
        from concurrent.futures import ThreadPoolExecutor
        import check_playlist
        with ThreadPoolExecutor(max_workers=20) as ex:
            res = list(ex.map(lambda e: check_playlist.check_one(e, 8.0, 1), result))
        before = len(result)
        result = [e for e, r in zip(result, res) if r["ok"] is not False]
        print(f"  --check: {before - len(result)} link mati dibuang")

    header = "#EXTM3U" + (f' url-tvg="{epg}"' if epg else "")
    m3ulib.write_file(output, result, header)
    print(f"Selesai: {len(result)} channel -> {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
