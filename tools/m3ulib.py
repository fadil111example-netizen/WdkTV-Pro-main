"""m3ulib: parser & penulis M3U kecil tanpa dependensi (hanya stdlib).

Dipakai bersama oleh check_playlist.py, gen_m3u.py, dan update_rcti.py.
Satu 'Entry' = satu channel: baris #EXTINF + baris opsi (#EXTVLCOPT, #KODIPROP, ...) + URL.
Baris opsi disimpan apa adanya supaya tidak ada informasi yang hilang saat ditulis ulang.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

ATTR_RE = re.compile(r'([A-Za-z0-9_\-]+)="([^"]*)"')


@dataclass
class Entry:
    name: str = ""
    url: str = ""
    duration: str = "-1"
    attrs: dict = field(default_factory=dict)      # tvg-id, tvg-logo, group-title, ...
    options: list = field(default_factory=list)    # baris '#EXTVLCOPT:...' / '#KODIPROP:...' dll.

    # ---- helper properti ----
    @property
    def group(self) -> str:
        return self.attrs.get("group-title", "")

    @group.setter
    def group(self, v: str) -> None:
        self.attrs["group-title"] = v

    def vlc_opt(self, key: str) -> str | None:
        """Ambil nilai '#EXTVLCOPT:<key>=<nilai>' (mis. http-referrer)."""
        prefix = f"#EXTVLCOPT:{key}="
        for line in self.options:
            if line.lower().startswith(prefix.lower()):
                return line[len(prefix):].strip()
        return None

    def set_vlc_opt(self, key: str, value: str) -> None:
        prefix = f"#EXTVLCOPT:{key}="
        self.options = [o for o in self.options if not o.lower().startswith(prefix.lower())]
        self.options.append(f"{prefix}{value}")

    @property
    def clean_url(self) -> str:
        """URL tanpa akhiran gaya Kodi '|User-Agent=...&Referer=...'."""
        return self.url.split("|", 1)[0].strip()

    @property
    def url_pipe_headers(self) -> dict:
        """Header dari akhiran '|Key=Val&Key2=Val2' (format yang dipakai tv-bro.html)."""
        if "|" not in self.url:
            return {}
        out = {}
        for part in self.url.split("|", 1)[1].split("&"):
            if "=" in part:
                k, v = part.split("=", 1)
                out[k.strip()] = v.strip()
        return out

    def request_headers(self) -> dict:
        """Header HTTP yang seharusnya dikirim pemutar untuk channel ini."""
        h = dict(self.url_pipe_headers)
        ua = self.vlc_opt("http-user-agent")
        ref = self.vlc_opt("http-referrer")
        org = self.vlc_opt("http-origin")
        if ua:
            h["User-Agent"] = ua
        if ref:
            h["Referer"] = ref
        if org:
            h["Origin"] = org
        return h

    @property
    def kind(self) -> str:
        u = self.clean_url.lower().split("?", 1)[0]
        if u.endswith(".m3u8"):
            return "hls"
        if u.endswith(".mpd"):
            return "dash"
        if u.startswith(("rtmp://", "rtsp://", "udp://", "rtp://")):
            return "other"
        return "direct"

    def to_lines(self) -> list:
        attrs = " ".join(f'{k}="{v}"' for k, v in self.attrs.items())
        head = f"#EXTINF:{self.duration}" + (f" {attrs}" if attrs else "") + f", {self.name}"
        return [head, *self.options, self.url]


@dataclass
class Playlist:
    header: str = "#EXTM3U"
    entries: list = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.entries)


def _parse_extinf(line: str) -> Entry:
    body = line[len("#EXTINF:"):]
    attrs = dict(ATTR_RE.findall(body))
    rest = ATTR_RE.sub("", body)            # buang atribut -> sisa '-1 , Nama'
    if "," in rest:
        dur, name = rest.split(",", 1)
    else:
        dur, name = rest, ""
    dur = dur.strip() or "-1"
    return Entry(name=name.strip(), duration=dur.split()[0] if dur.split() else "-1", attrs=attrs)


def parse(text: str) -> Playlist:
    pl = Playlist()
    cur: Entry | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTM3U"):
            pl.header = line
        elif line.startswith("#EXTINF:"):
            cur = _parse_extinf(line)
        elif line.startswith("#"):
            # baris opsi (#EXTVLCOPT, #KODIPROP, #EXTGRP, ...); komentar bebas sebelum entri diabaikan
            if cur is not None:
                cur.options.append(line)
        else:
            if cur is not None:
                cur.url = line
                pl.entries.append(cur)
                cur = None
    return pl


def parse_file(path: str) -> Playlist:
    with open(path, encoding="utf-8", errors="ignore") as f:
        return parse(f.read())


def dumps(pl: Playlist | Iterable[Entry], header: str | None = None) -> str:
    entries = pl.entries if isinstance(pl, Playlist) else list(pl)
    head = header or (pl.header if isinstance(pl, Playlist) else "#EXTM3U")
    lines = [head]
    for e in entries:
        lines.extend(e.to_lines())
    return "\n".join(lines) + "\n"


def write_file(path: str, pl: Playlist | Iterable[Entry], header: str | None = None) -> None:
    import os
    import tempfile

    data = dumps(pl, header)
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")      # tulis atomik: tidak ada file setengah jadi
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(data)
    os.replace(tmp, path)
