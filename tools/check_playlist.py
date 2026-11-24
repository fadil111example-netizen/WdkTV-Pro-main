#!/usr/bin/env python3
"""check_playlist: uji ratusan link playlist M3U secara paralel.

Untuk tiap channel dikirim satu permintaan HTTP dengan header yang sama seperti yang dipakai
pemutar (Referer / User-Agent dari baris #EXTVLCOPT), lalu dinilai:

  HLS  (.m3u8)  -> hidup bila isinya diawali '#EXTM3U'
  DASH (.mpd)   -> hidup bila isinya mengandung '<MPD'
  lainnya       -> hidup bila status HTTP < 400

Skrip ini hanya memeriksa APAKAH link menjawab. Ia tidak mengunduh video dan tidak memakai
kunci DRM apa pun.

Contoh:
  python3 tools/check_playlist.py playlist_super.m3u -o out/ --workers 30
  python3 tools/check_playlist.py streams/id.m3u --limit 20 --group "TV Nasional"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m3ulib  # noqa: E402

DEFAULT_UA = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36"
READ_BYTES = 4096


def check_one(entry: m3ulib.Entry, timeout: float, retries: int) -> dict:
    headers = {"User-Agent": DEFAULT_UA, **entry.request_headers()}
    url = entry.clean_url
    result = {"name": entry.name, "group": entry.group, "url": url, "kind": entry.kind,
              "ok": False, "status": None, "ms": None, "reason": ""}
    if not url.lower().startswith(("http://", "https://")):
        result["reason"] = "skema tidak didukung untuk uji (bukan http/https)"
        result["ok"] = None       # None = dilewati, tidak dihitung mati
        return result

    for attempt in range(retries + 1):
        t0 = time.monotonic()
        try:
            with requests.get(url, headers=headers, timeout=timeout, stream=True,
                              allow_redirects=True) as r:
                result["status"] = r.status_code
                chunk = next(r.iter_content(READ_BYTES), b"")
                result["ms"] = int((time.monotonic() - t0) * 1000)
                text = chunk.decode("utf-8", errors="ignore")
                if r.status_code >= 400:
                    result["reason"] = f"HTTP {r.status_code}"
                elif entry.kind == "hls":
                    result["ok"] = text.lstrip().startswith("#EXTM3U")
                    result["reason"] = "" if result["ok"] else "isi bukan playlist HLS"
                elif entry.kind == "dash":
                    result["ok"] = "<MPD" in text or "<mpd" in text
                    result["reason"] = "" if result["ok"] else "isi bukan manifest DASH"
                else:
                    result["ok"] = True
                return result
        except requests.RequestException as e:
            result["reason"] = type(e).__name__
            result["ms"] = int((time.monotonic() - t0) * 1000)
        if attempt < retries:
            time.sleep(0.5 * (attempt + 1))
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Uji kehidupan link pada playlist M3U")
    ap.add_argument("playlist", help="file .m3u yang diuji")
    ap.add_argument("-o", "--outdir", default="out", help="folder hasil (default: out)")
    ap.add_argument("--workers", type=int, default=20, help="jumlah uji paralel (default 20)")
    ap.add_argument("--timeout", type=float, default=8.0, help="detik per permintaan (default 8)")
    ap.add_argument("--retries", type=int, default=1, help="ulang bila gagal jaringan (default 1)")
    ap.add_argument("--limit", type=int, default=0, help="uji hanya N channel pertama (0 = semua)")
    ap.add_argument("--group", default="", help="uji hanya group-title ini (cocok persis, huruf besar/kecil diabaikan)")
    args = ap.parse_args(argv)

    pl = m3ulib.parse_file(args.playlist)
    entries = pl.entries
    if args.group:
        entries = [e for e in entries if e.group.lower() == args.group.lower()]
    if args.limit:
        entries = entries[: args.limit]
    if not entries:
        print("Tidak ada channel untuk diuji.", file=sys.stderr)
        return 2

    print(f"Menguji {len(entries)} channel dengan {args.workers} pekerja ...", flush=True)
    results: dict[int, dict] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(check_one, e, args.timeout, args.retries): i for i, e in enumerate(entries)}
        done = 0
        for fut in as_completed(futs):
            results[futs[fut]] = fut.result()
            done += 1
            if done % 25 == 0 or done == len(entries):
                print(f"  {done}/{len(entries)}", flush=True)

    ordered = [results[i] for i in range(len(entries))]
    alive = [e for e, r in zip(entries, ordered) if r["ok"] is True]
    dead = [e for e, r in zip(entries, ordered) if r["ok"] is False]
    skipped = [e for e, r in zip(entries, ordered) if r["ok"] is None]

    os.makedirs(args.outdir, exist_ok=True)
    m3ulib.write_file(os.path.join(args.outdir, "alive.m3u"), alive, pl.header)
    m3ulib.write_file(os.path.join(args.outdir, "dead.m3u"), dead, pl.header)
    with open(os.path.join(args.outdir, "report.json"), "w", encoding="utf-8") as f:
        json.dump(ordered, f, ensure_ascii=False, indent=2)

    # ringkasan per grup
    groups: dict[str, list] = {}
    for r in ordered:
        g = groups.setdefault(r["group"] or "(tanpa grup)", [0, 0])
        if r["ok"] is True:
            g[0] += 1
        elif r["ok"] is False:
            g[1] += 1
    lines = [
        "# Laporan uji playlist", "",
        f"- Sumber: `{args.playlist}`",
        f"- Diuji: **{len(entries)}** | Hidup: **{len(alive)}** | Mati: **{len(dead)}** | Dilewati: {len(skipped)}",
        "", "| Grup | Hidup | Mati |", "|---|---:|---:|",
    ]
    for g, (a, d) in sorted(groups.items(), key=lambda kv: -(kv[1][0] + kv[1][1])):
        lines.append(f"| {g} | {a} | {d} |")
    reasons: dict[str, int] = {}
    for r in ordered:
        if r["ok"] is False:
            reasons[r["reason"] or "?"] = reasons.get(r["reason"] or "?", 0) + 1
    if reasons:
        lines += ["", "## Penyebab mati", ""] + [f"- {k}: {v}" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])]
    with open(os.path.join(args.outdir, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"\nHidup {len(alive)} | Mati {len(dead)} | Dilewati {len(skipped)}  ->  {args.outdir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
