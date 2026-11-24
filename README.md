# WdkTV-Pro

Playlist IPTV + bot penyegar token + alat bantu + aplikasi pemutar Android.

```
WdkTV-Pro/
├── update_rcti.py            bot penyegar link RCTI/MNCTV/GTV/iNews (+ vidio opsional)
├── data/rcti_channels.json   daftar channel bot (mudah diedit)
├── streams/ , playlist_super.m3u   playlist: id.m3u (diperbarui bot) + super (statis)
├── tools/
│   ├── m3ulib.py             parser/penulis M3U (stdlib saja)
│   ├── check_playlist.py     uji hidup/mati ratusan link, hasilkan alive.m3u + laporan
│   ├── gen_m3u.py            gabung JSON/CSV/M3U -> satu M3U (dedupe, urut, EPG)
│   └── vidio.py              (opsional) metadata/tautan siaran vidio.com
├── tests/test_tools.py       13 tes otomatis, tanpa internet
├── android/                  aplikasi pemutar M3U (Kotlin + Media3/ExoPlayer)
├── docs/peta-kerja.html      diagram interaktif cara kerja
├── tv-bro.html               alat web lama: JSON -> M3U
└── .github/workflows/        auto-update (2 jam), cek mingguan, tes, build APK
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
python3 tools/check_playlist.py playlist_super.m3u -o out --workers 20 --limit 50
cat out/report.md          # ringkasan; out/alive.m3u = hanya yang hidup

# 3. Generate M3U dari banyak sumber
python3 tools/gen_m3u.py -i playlist_super.m3u streams/id.m3u -o build/all.m3u --sort
python3 tools/gen_m3u.py -i data/contoh.json data/contoh.csv -o build/contoh.m3u --sort --check

# 4. Bot RCTI (RCTI_APIKEY opsional, tidak wajib)
python3 update_rcti.py                  # berhenti sendiri bila link masih berlaku
FORCE_REFRESH=1 python3 update_rcti.py  # paksa segarkan

# 5. (opsional) Info channel vidio
python3 tools/vidio.py meta 205         # metadata Indosiar (205) / SCTV (204)
```

Catatan `--check` dan `check_playlist.py`: hanya memeriksa apakah server menjawab, tidak mengunduh video.

## Bot RCTI (update_rcti.py)

Versi 2026 memakai dua endpoint publik RCTI+ yang masih berfungsi (versi lama
memakai cookie `visitor_token` yang sudah tidak diberikan server dan selalu gagal):

1. `GET https://api.rctiplus.com/api/v1/visitor?platform=mweb` -> token tamu.
2. `GET https://api.rctiplus.com/api/v1/live-event/<api_id>/url` (header `authorization`)
   -> `data.url` = tautan `.m3u8` + `auth_key` (berlaku sekitar 3 jam).

Sifat penting:
- `RCTI_APIKEY` **opsional** (dikirim sebagai header `apikey` bila diisi). Tidak ada
  API key yang diwajibkan.
- Hanya channel yang terdaftar di `data/rcti_channels.json` yang disentuh. Channel
  manual lain di file yang sama (SCTV, Indosiar, dst.) **tidak pernah** dihapus
  atau dipindah saat RCTI/MNCTV/GTV/iNews disegarkan.
- Bila satu channel gagal, tautan lamanya dipertahankan (tidak pernah dihapus).
- Penulisan file atomik (tidak ada file setengah jadi).
- Bot "pintar": bila semua tautan yang dikelola masih berlaku > `MIN_REMAINING_SEC`,
  bot berhenti tanpa menyentuh jaringan/file (tidak ada commit sampah).

Variabel lingkungan: `MIN_REMAINING_SEC` (default 900), `FORCE_REFRESH` (`1` = paksa),
`OUTPUT_FILE`, `RCTI_APIKEY` (opsional), `RCTI_PLATFORM`, `APPIER_ID_BASE`.

### Channel vidio.com (opsional)

Entri di `data/rcti_channels.json` boleh memakai `"source": "vidio"` + `"vidio_id"`
(mis. `204` SCTV, `205` Indosiar). Bot akan memakai `tools/vidio.py` untuk mengambil
kunci API anonim (`POST https://www.vidio.com/auth`) lalu metadata siaran.

Hasil uji: pengambilan kunci API & metadata berhasil, tetapi **tautan siaran final**
dari `api.vidio.com/.../stream` memerlukan header `X-Signature` yang dihitung
JavaScript situs (tanpa itu server membalas `403 invalid_signature`), dan channel
premium (SCTV/Indosiar: `is_premium: true`) juga memerlukan akun langganan. Karena
itu modul vidio bersifat percobaan dan **tidak pernah fatal**: bila tautan tak
didapat, tautan lama tetap dipakai dan channel tidak dihapus.

## Pasang di GitHub
1. Upload isi folder ini ke repo.
2. Settings > Actions > General > Workflow permissions: **Read and write**.
3. Tab Actions > "Auto Update Token RCTI" > Run workflow (isi `force` = 1 untuk paksa).
   Hijau = berhasil. Jadwal otomatis tiap 2 jam sudah aktif.
4. `RCTI_APIKEY` **tidak lagi wajib**. Bila ingin memakainya, tambahkan sebagai
   repository secret `RCTI_APIKEY`: Settings > Secrets and variables > Actions.

## Aplikasi Android
Build lewat GitHub: Actions > "Build APK Android (debug)" > Run workflow, lalu unduh artifact `WdkTVPlayer-debug`.
Di aplikasi, tempel URL raw playlist, tekan **Muat playlist**, ketuk channel.
Build lokal butuh JDK 17 + Android SDK: `cd android && ./gradlew assembleDebug`.
Aplikasi belum bisa memutar channel ber-DRM (clearkey).

## Catatan penting
- Link siaran dan apikey berasal dari layanan pihak ketiga tanpa izin resmi; bisa berhenti kapan saja dan bisa melanggar syarat layanan mereka. Pakai untuk uji pribadi, jangan disebarkan.
- Jangan commit apikey/token ke repo. Pakai GitHub Secrets.
