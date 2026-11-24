# WdkTV-Pro

Playlist IPTV + bot penyegar token + alat bantu + aplikasi pemutar Android.

```
WdkTV-Pro/
├── update_rcti.py            bot penyegar link RCTI/MNCTV/GTV/iNews (versi rapi)
├── data/rcti_channels.json   daftar channel bot (mudah diedit)
├── streams/ , playlist_super.m3u   playlist (statis) + id.m3u (diperbarui bot)
├── tools/
│   ├── m3ulib.py             parser/penulis M3U (stdlib saja)
│   ├── check_playlist.py     uji hidup/mati ratusan link, hasilkan alive.m3u + laporan
│   └── gen_m3u.py            gabung JSON/CSV/M3U -> satu M3U (dedupe, urut, EPG)
├── tests/test_tools.py       9 tes otomatis, tanpa internet
├── android/                  aplikasi pemutar M3U (Kotlin + Media3/ExoPlayer)
├── docs/peta-kerja.html      diagram interaktif cara kerja
├── tv-bro.html               alat web lama: JSON -> M3U
└── .github/workflows/        auto-update (5 mnt), cek mingguan, tes, build APK
```

## Jalankan di Debian proot (Termux)

```bash
apt update && apt install -y python3 python3-venv python3-pip unzip
cd ~/WdkTV-Pro
python3 -m venv ~/venv && . ~/venv/bin/activate
pip install -r requirements.txt

# 1. Tes otomatis (tanpa internet)
python3 -m unittest discover -s tests -v

# 2. Uji link playlist (butuh internet)
python3 tools/check_playlist.py streams/playlist_super.m3u -o out --workers 20 --limit 50
cat out/report.md          # ringkasan; out/alive.m3u = hanya yang hidup

# 3. Generate M3U dari banyak sumber
python3 tools/gen_m3u.py -i playlist_super.m3u streams/playlist_super.m3u -o build/all.m3u --sort
python3 tools/gen_m3u.py -i data/contoh.json data/contoh.csv -o build/contoh.m3u --sort --check

# 4. Bot RCTI (butuh RCTI_APIKEY milikmu)
export RCTI_APIKEY='isi-apikey'
python3 update_rcti.py                  # berhenti sendiri bila link masih berlaku
FORCE_REFRESH=1 python3 update_rcti.py  # paksa segarkan
```

Catatan `--check` dan `check_playlist.py`: hanya memeriksa apakah server menjawab, tidak mengunduh video.

## Pasang di GitHub
1. Upload isi folder ini ke repo.
2. Settings > Secrets and variables > Actions > New repository secret: `RCTI_APIKEY`.
3. Settings > Actions > General > Workflow permissions: **Read and write**.
4. Tab Actions > "Auto Update Token RCTI" > Run workflow. Hijau = berhasil.

## Aplikasi Android
Build lewat GitHub: Actions > "Build APK Android (debug)" > Run workflow, lalu unduh artifact `WdkTVPlayer-debug`.
Di aplikasi, tempel URL raw playlist, tekan **Muat playlist**, ketuk channel.
Build lokal butuh JDK 17 + Android SDK: `cd android && ./gradlew assembleDebug`.
Aplikasi belum bisa memutar channel ber-DRM (clearkey).

## Status bot RCTI
Pada uji 24 Nov 2026, server RCTI+ tidak lagi memberi `visitor_token` ke bot (error: "Cookie visitor_token tidak diberikan server"). Itu berarti akses otomatis ditolak oleh pihak RCTI+. Jadwal otomatis dimatikan supaya workflow tidak gagal terus; bot tidak diubah untuk menembus penolakan itu.

## Catatan penting
- Link siaran dan apikey berasal dari layanan pihak ketiga tanpa izin resmi; bisa berhenti kapan saja dan bisa melanggar syarat layanan mereka. Pakai untuk uji pribadi, jangan disebarkan.
- Jangan commit apikey/token ke repo. Pakai GitHub Secrets.
