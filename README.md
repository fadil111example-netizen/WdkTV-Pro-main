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
├── tests/test_tools.py       16 tes otomatis, tanpa internet
├── android/                  aplikasi pemutar M3U (Kotlin + Media3/ExoPlayer)
├── docs/peta-kerja.html      diagram interaktif cara kerja
├── tv-bro.html               alat web lama: JSON -> M3U
└── .github/workflows/        auto-update (tiap 5 mnt + saat push), cek per jam, tes, build APK
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

Variabel lingkungan: `MIN_REMAINING_SEC` (default 1800), `FORCE_REFRESH` (`1` = paksa),
`OUTPUT_FILE`, `RCTI_APIKEY` (opsional), `RCTI_PLATFORM`, `APPIER_ID_BASE`.

### Channel manual tidak akan hilang (channel safety)

Channel manual yang Anda tambah sendiri (SCTV, Indosiar, Trans TV, Trans 7, ANTV, dst.)
**tidak pernah** dihapus atau diubah saat RCTI/MNCTV/GTV/iNews disegarkan. Ada 3 lapis
pengaman:

1. `merge_playlist()` menyalin setiap entri lama apa adanya dan hanya mengganti channel
   yang terdaftar di `data/rcti_channels.json`.
2. Bila sebuah channel gagal disegarkan, tautan lamanya tetap dipakai.
3. **Verifikasi akhir**: sebelum menulis file, bot memastikan tidak ada satu pun nama
   channel lama yang hilang; jika ada, penulisan dibatalkan (`exit 1`) dan file lama
   dibiarkan utuh. Jadi mustahil channel manual terhapus.

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
3. Selesai — **tidak perlu klik apa pun**. Bot token RCTI berjalan otomatis:
   - tiap 5 menit (jadwal),
   - setiap kali Anda push perubahan `streams/id.m3u` atau `data/rcti_channels.json`,
   - dan saat Anda menekan "Run workflow" (kolom `force` sudah berisi `0`; tidak wajib diubah).
4. `RCTI_APIKEY` **tidak lagi wajib**. Bila ingin memakainya, tambahkan sebagai
   repository secret `RCTI_APIKEY`: Settings > Secrets and variables > Actions.

> Catatan: GitHub Actions hanya berjalan pada repo publik (gratis). Untuk repo privat,
> Actions tetap berjalan tetapi memakai kuota menit akun Anda.

### Batas & kuota GitHub (penting)
- **Mendekati "2 menit"**: GitHub hanya menjalankan jadwal `cron` paling cepat **tiap
  5 menit** (batas platform — 2 menit tidak mungkin). Jadi workflow ini memakai
  `*/5 * * * *`. Karena bot hanya benar-benar menyegarkan ketika token hampir habis,
  sebagian besar run selesai cepat dan tidak membuat commit.
- **Repo publik**: gratis, 5 menit aman.
- **Repo privat**: tiap run tetap memakai kuota menit. Bila kuota menipis, ubah jadwal
  di `auto-update-m3u.yml` menjadi lebih jarang (mis. `0 * * * *` tiap jam). Tautan
  tetap tidak akan mati karena bot menyegarkan jauh sebelum kedaluwarsa
  (`MIN_REMAINING_SEC` = 30 menit), asalkan dijalankan minimal tiap ~2 jam.
- Jadwal `schedule` tidak ikut jalan bila repo sudah tidak aktif 60 hari (aturan
  GitHub); aktifkan lagi dari tab Actions bila perlu.

### Update di aplikasi TV (TiviMate / TVMate)
TiviMate **tidak** menarik ulang otomatis di latar belakang; ia memuat ulang saat
playlist di-refresh. Agar tautan tidak pernah mati:
- Bot menyegarkan token jauh sebelum kedaluwarsa (`MIN_REMAINING_SEC` = 30 menit),
  jadi link selalu segar saat Anda membuka aplikasi.
- Di TiviMate aktifkan kunci playlist otomatis/pull-to-refresh, atau buka
  Settings > Playlists > pilih playlist > **Update**. Setelah itu channel RCTI dkk.
  memakai tautan terbaru dari URL raw GitHub.

## Aplikasi Android
Build lewat GitHub: Actions > "Build APK Android (debug)" > Run workflow, lalu unduh artifact `WdkTVPlayer-debug`.
Di aplikasi, tempel URL raw playlist, tekan **Muat playlist**, ketuk channel.
Build lokal butuh JDK 17 + Android SDK: `cd android && ./gradlew assembleDebug`.
Aplikasi belum bisa memutar channel ber-DRM (clearkey).

## Catatan penting
- Link siaran dan apikey berasal dari layanan pihak ketiga tanpa izin resmi; bisa berhenti kapan saja dan bisa melanggar syarat layanan mereka. Pakai untuk uji pribadi, jangan disebarkan.
- Jangan commit apikey/token ke repo. Pakai GitHub Secrets.
