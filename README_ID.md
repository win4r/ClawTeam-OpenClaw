<p align="center">
  <a href="README.md">Bahasa Inggris</a> |
  <a href="README_CN.md">Bahasa Cina Sederhana</a> |
  <a href="README_TW.md">Bahasa Cina Tradisional</a> |
  <a href="README_JA.md">Bahasa Jepang</a> |
  <a href="README_KO.md">Bahasa Korea</a> |
  <a href="README_FR.md">Prancis</a> |
  <a href="README_ES.md">Spanyol</a> |
  <a href="README_DE.md">Jerman</a> |
  <a href="README_IT.md">Italia</a> |
  <a href="README_RU.md">Rusia</a> |
  <a href="README_PT-BR.md">Portugis (Brasil)</a>
</p>

<h1 align="center">🦞ClawTeam-OpenClaw</h1>

<p align="center">
  <strong>Koordinasi kawanan multi-agen untuk agen pengkodean CLI — <a href="https://openclaw.ai">OpenClaw</a> sebagai default</strong>
</p>

<p align="center">
  <a href="https://github.com/HKUDS/ClawTeam"><img src="https://img.shields.io/badge/upstream-HKUDS%2FClawTeam-purple?style=for-the-badge" alt="Upstream"></a>
  <a href="#-quick-start"><img src="https://img.shields.io/badge/Quick_Start-3_min-blue?style=for-the-badge" alt="Mulai Cepat"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge" alt="Lisensi"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-≥3.10-blue?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/agents-OpenClaw_%7C_Claude_Code_%7C_Codex_%7C_Hermes_%7C_nanobot-blueviolet" alt="Agen">
  <img src="https://img.shields.io/badge/transport-File_%7C_ZeroMQ_P2P-orange" alt="Transport">
  <img src="https://img.shields.io/badge/version-0.3.0-teal" alt="Versi">
</p>

> **Fork dari [HKUDS/ClawTeam](https://github.com/HKUDS/ClawTeam)** dengan integrasi OpenClaw yang mendalam: agen `openclaw` default, isolasi sesi per-agen, konfigurasi otomatis persetujuan eksekusi, dan backend spawn yang diperkuat untuk produksi. Semua perbaikan dari hulu disinkronkan.

Anda menetapkan tujuan. Gerombolan agen menangani sisanya — memunculkan pekerja, membagi tugas, berkoordinasi, dan menggabungkan hasil.

Bekerja dengan [OpenClaw](https://openclaw.ai) (default), [Claude Code](https://claude.ai/claude-code), [Codex](https://openai.com/codex), [Hermes Agent](https://github.com/NousResearch/hermes-agent), [nanobot](https://github.com/HKUDS/nanobot), [Cursor](https://cursor.com), dan agen CLI apa pun.

## Dukungan Platform

- Linux dan macOS mempertahankan alur kerja `tmux`-pertama yang asli.
- Windows 10/11 didukung dengan fallback otomatis ke backend `subprocess`.
- Penguncian tugas, pemeriksaan kelangsungan proses, dan pendaftaran sinyal dialihkan melalui lapisan kompatibilitas bersama sehingga perilaku khusus Unix yang tidak didukung menurun dengan aman di Windows.
- `board attach` masih memerlukan `tmux`, jadi di Windows sebaiknya menggunakan `clawteam board serve` untuk pemantauan langsung.
- Jika Anda ingin alur kerja tmux asli di Windows, jalankan ClawTeam di dalam WSL.

---

## Mengapa ClawTeam?

Agen AI saat ini sangat kuat tetapi bekerja secara **terpisah**. ClawTeam memungkinkan agen untuk mengatur diri sendiri menjadi tim — membagi pekerjaan, berkomunikasi, dan mencapai hasil tanpa pengelolaan manusia secara mikro.

| | ClawTeam | Kerangka multi-agen lainnya |
|---|---------|----------------------------|
| **Siapa yang menggunakannya** | Agen AI itu sendiri | Manusia yang menulis kode orkestrasi |
| **Pengaturan** | `pip install` + satu prompt | Docker, API cloud, konfigurasi YAML |
| **Infrastruktur** | Sistem berkas + tmux | Redis, antrean pesan, basis data |
| **Dukungan agen** | Agen CLI apa pun | Hanya khusus kerangka kerja |
| **Isolasi** | Worktree Git (cabang nyata) | Kontainer atau lingkungan virtual |

---

## Bagaimana Cara Kerjanya

<table>
<tr>
<td width="33%">

### Agen Memunculkan Agen
Pemimpin memanggil `clawteam spawn` untuk membuat pekerja. Masing-masing mendapatkan **git worktree**, **sesi backend spawn**, dan **identitas** mereka sendiri.

```bash
clawteam spawn --team my-team "}
  --agent-name worker1 "}
  --tugas "Implementasikan modul otentikasi"
```

</td>
<td width="33%">

### Agen Berbicara dengan Agen
Pekerja memeriksa kotak masuk, memperbarui tugas, dan melaporkan hasil — semuanya melalui perintah CLI **yang disuntikkan otomatis** ke dalam prompt mereka.

```bash
daftar tugas clawteam my-team --pemilik saya
kotak masuk clawteam kirim pemimpin tim saya "
Otentikasi selesai. Semua tes lulus.
```

</td>
<td width="33%">

### Kamu Tinggal Menonton
Pantau kawanan dari tampilan tmux berubin atau antarmuka Web. Pemimpin menangani koordinasi.

```bash
clawteam board serve --port 8080
# Atau, di Linux/macOS/WSL dengan tmux:
papan clawteam lampirkan tim-saya
```

</td>
</tr>
</table>

---

## Mulai Cepat

### Opsi 1: Biarkan Agen Mengemudi (Disarankan)

Instal ClawTeam, lalu minta agen Anda:

```
Buat aplikasi web. Gunakan clawteam untuk membagi pekerjaan di antara beberapa agen.
```

Agen secara otomatis membuat tim, memunculkan pekerja, menetapkan tugas, dan mengoordinasikan — semuanya melalui `clawteam` CLI.

### Opsi 2: Mengemudikannya Secara Manual

```bash
# Buat tim
clawteam tim spawn-tim tim-saya -d "Bangun modul otentikasi" -n pemimpin

# Spawn pekerja — masing-masing mendapat git worktree serta sesi backend sendiri
clawteam spawn --team tim-saya --agent-name alice --task "Implementasikan alur OAuth2"
clawteam spawn --team tim-saya --agent-name bob --task "Tulis tes unit untuk auth"

# Saksikan mereka bekerja
clawteam board serve --port 8080
clawteam papan lampirkan tim-saya   # Linux/macOS/WSL dengan tmux
```

### Agen yang Didukung

| Agen | Perintah Spawn | Status |
|-------|--------------|--------|
| [OpenClaw](https://openclaw.ai) | `clawteam spawn --team ...` | **Default** |
| [Claude Code](https://claude.ai/claude-code) | `clawteam spawn claude --team ...` | Dukungan penuh |
| [Codex](https://openai.com/codex) | `clawteam spawn codex --team ...` | Dukungan penuh |
| [nanobot](https://github.com/HKUDS/nanobot) | `clawteam spawn nanobot --team ...` | Dukungan penuh |
| [Agen Hermes](https://github.com/NousResearch/hermes-agent) | `clawteam spawn hermes --team ...` | Dukungan penuh (tmux + subprocess) |
| [Cursor](https://cursor.com) | `clawteam spawn subprocess cursor --team ...` | Eksperimental |
| Skrip kustom | `clawteam spawn subprocess python --team ...` | Dukungan penuh |

---

## Instal

### Langkah 1: Prasyarat

ClawTeam membutuhkan **Python 3.10+** dan setidaknya satu agen pemrograman CLI (OpenClaw, Claude Code, Codex, dll.). Di Linux/macOS, alur kerja visual penuh juga membutuhkan **tmux**. Di Windows, `tmux` bersifat opsional karena ClawTeam menggunakan backend `subprocess` secara default.

**Periksa apa yang sudah Anda miliki:**

```bash
python --version    # Membutuhkan 3.10+
tmux -V             # Hanya untuk Linux/macOS/WSL
openclaw --version  # Atau: claude --version / codex --version
```

**Pasang prasyarat yang hilang:**

| Alat | Windows | macOS | Ubuntu/Debian |
|------|---------|-------|---------------|
| Python 3.10+ | Instal dari [python.org](https://www.python.org/downloads/windows/) | `brew install python@3.12` | `sudo apt update && sudo apt install python3 python3-pip` |
| tmux | Opsional | `brew install tmux` | `sudo apt install tmux` |
| OpenClaw | `pip install openclaw` | `pip install openclaw` | `pip install openclaw` |

> Jika menggunakan Claude Code atau Codex alih-alih OpenClaw, pasanglah sesuai dokumen mereka masing-masing. OpenClaw adalah default tetapi tidak harus digunakan.

Di Windows, setelah instalasi Anda dapat memverifikasi pilihan backend dengan:

```powershell
clawteam config get default_backend
```

### Pengaturan Asli Windows

Gunakan jalur ini untuk PowerShell atau Windows Terminal:

```powershell
py -3 -m pip install -e .
clawteam config get default_backend   # seharusnya mencetak subprocess
clawteam spawn --team demo --agent-name worker1 --task "Melakukan pekerjaan"
clawteam board serve --port 8080
```

Jika Anda ingin pengalaman tmux yang lengkap, instal dan jalankan ClawTeam di dalam WSL sebagai gantinya.

### Langkah 2: Instal ClawTeam

> **⚠️ Jangan jalankan `pip install clawteam` atau `npm install -g clawteam` secara langsung:**
> - `pip install clawteam` menginstal versi PyPI hulu, yang defaultnya `claude` dan tidak memiliki adaptasi OpenClaw.
> - `npm install -g clawteam` menginstal paket name-squatting yang tidak terkait (oleh `a9logic`). Jika `clawteam --version` menunjukkan "Coming Soon", Anda memasang yang salah — jalankan `npm uninstall -g clawteam`.
>
> **Gunakan tiga perintah di bawah ini — langkah `pip install -e .` diperlukan. Ini menginstal dari repositori lokal, bukan dari PyPI.**

```bash
git clone https://github.com/win4r/ClawTeam-OpenClaw.git
cd ClawTeam-OpenClaw
pip install -e .    # ← Wajib! Menginstal dari repo lokal, BUKAN sama dengan pip install clawteam
```

Opsional — Transportasi P2P (ZeroMQ):

```bash
python -m pip install -e ".[p2p]"
```

### Langkah 3: Pastikan `clawteam` ada di PATH

Agen yang dibuat berjalan di shell baru yang mungkin tidak memiliki direktori bin pip di PATH. Sebuah symlink di `~/bin` memastikan `clawteam` selalu dapat diakses:

```bash
mkdir -p ~/bin
ln -sf "$(which clawteam)" ~/bin/clawteam
```

Jika `which clawteam` tidak mengembalikan apapun, temukan biner secara manual:

```bash
# Lokasi umum:
# ~/.local/bin/clawteam
# /opt/homebrew/bin/clawteam
# /usr/local/bin/clawteam
# /Library/Frameworks/Python.framework/Versions/3.*/bin/clawteam
find / -name clawteam -type f 2>/dev/null | head -5
```

Kemudian pastikan `~/bin` ada dalam PATH Anda — tambahkan ini ke `~/.zshrc` atau `~/.bashrc` jika belum ada:

```bash
ekspor PATH="$HOME/bin:$PATH"
```

Di Windows asli, biasanya Anda tidak perlu langkah symlink `~/bin`. Sebagai gantinya, pastikan direktori `Scripts` Python yang berisi `clawteam.exe` ada di `PATH`, atau aktifkan lingkungan virtual tempat Anda menginstal ClawTeam sebelum menjalankan agen.

### Langkah 4: Pasang skill OpenClaw (hanya untuk pengguna OpenClaw)

File keterampilan ini mengajarkan agen OpenClaw bagaimana menggunakan ClawTeam melalui bahasa alami. Lewati langkah ini jika Anda tidak menggunakan OpenClaw.

```bash
mkdir -p ~/.openclaw/workspace/skills/clawteam
cp skills/openclaw/SKILL.md ~/.openclaw/workspace/skills/clawteam/SKILL.md
```

### Langkah 5: Konfigurasikan persetujuan exec (hanya untuk pengguna OpenClaw)

Agen OpenClaw yang dibuat perlu izin untuk menjalankan perintah `clawteam`. Tanpa ini, agen akan terhenti pada prompt izin interaktif.

```bash
# Pastikan mode keamanan adalah "allowlist" (bukan "full")
python3 -c ""
import json, pathlib
p = pathlib.Path.home() / '.openclaw' / 'exec-approvals.json'
jika p.ada():
    d = json.loads(p.read_text())
    d.setdefault('defaults', {})['security'] = 'allowlist'
    p.tulis_teks(json.dumps(d, indent=2))
    print('exec-approvals.json diperbarui: keamanan = daftar-izin')
lain:
    print('exec-approvals.json tidak ditemukan — jalankan openclaw sekali terlebih dahulu, lalu jalankan kembali langkah ini')
"

# Tambahkan clawteam ke daftar izinkan (gunakan jalur absolut — OpenClaw 4.2+ memerlukannya)
openclaw approvals allowlist add --agent "*" "$(which clawteam)"
```

> Jika `openclaw approvals` gagal, gateway OpenClaw mungkin tidak berjalan. Mulai terlebih dahulu, lalu coba lagi.

### Langkah 5b: Pasang kemampuan Hermes (hanya untuk pengguna Agen Hermes)

Berkas keahlian mengajarkan Agen Hermes bagaimana menggunakan ClawTeam melalui bahasa alami -- termasuk kapan harus mengarahkan ke ClawTeam (vs `delegate_task`), bendera spawn yang benar, dan ekspektasi waktu. Lewati langkah ini jika Anda tidak menggunakan Hermes.

```bash
mkdir -p ~/.hermes/skills/openclaw-imports/clawteam
cp skills/hermes/SKILL.md ~/.hermes/skills/openclaw-imports/clawteam/SKILL.md
```

> Verifikasi dengan `hermes skills list | grep clawteam`. Skill tersebut seharusnya muncul di bawah `openclaw-imports` (Hermes secara otomatis mengarahkan skill dari direktori tersebut).

**Hal-hal utama yang diajarkan keterampilan ini kepada Hermes:**

- Rutekan kueri multi-agen/gerombolan/tim ke clawteam (bukan `delegate_task`)
- Gunakan `--team-name` (bukan `--team`), `-g`/`--goal`, `--force` pada `launch`
- Selalu sertakan `--command hermes` pada `launch` -- template default adalah `openclaw`
- Pada `spawn`, lewati `hermes` sebagai argumen posisi trailing (bukan `--command hermes`)
- Tunggu `sleep 60` setelah peluncuran untuk memulai pekerja, lalu periksa papan setiap 30 detik
- Jangan pernah mengintip kotak masuk dalam 60 detik pertama (mereka akan kosong)
- Baca kotak masuk dan buat laporan gabungan sebelum `clawteam team cleanup`

Pekerja Hermes yang dibuat secara otomatis mewarisi server MCP yang dikonfigurasi di `~/.hermes/config.yaml`, sehingga setiap otak pengetahuan atau pengaturan alat tersedia untuk setiap pekerja.

### Langkah 6: Verifikasi

```bash
clawteam --version          # Harus mencetak versi
clawteam config health      # Harus menampilkan semua hijau
```

Jika menggunakan OpenClaw, juga periksa apakah keterampilan sudah dimuat:

```bash
daftar keterampilan openclaw | grep clawteam
```

### Pemasang otomatis

Langkah 2–6 di atas juga tersedia sebagai satu skrip:

```bash
git clone https://github.com/win4r/ClawTeam-OpenClaw.git
cd ClawTeam-OpenClaw
bash scripts/install-openclaw.sh
```

Skrip ini ditujukan untuk shell Linux, macOS, dan WSL, bukan PowerShell asli.

### Pemecahan Masalah

| Masalah | Penyebab | Perbaikan |
|---------|-------|-----|
| `clawteam: command not found` | direktori bin pip tidak ada di PATH | Jalankan Langkah 3 dan pastikan baik `~/bin` atau direktori `Scripts` Python Anda ada di PATH |
| Agen yang dibuat tidak dapat menemukan `clawteam` | Agen berjalan di shell baru tanpa PATH pip | Pastikan `clawteam` ada di PATH di shell baru; di Windows periksa direktori `Scripts` Python atau virtualenv yang aktif |
| `openclaw approvals` gagal | Gateway tidak berjalan | Mulai `openclaw gateway` terlebih dahulu, lalu coba lagi Langkah 5 |
| `exec-approvals.json tidak ditemukan` | OpenClaw belum dijalankan | Jalankan `openclaw` sekali untuk membuat konfigurasi, lalu coba lagi Langkah 5 |
| Agen memblokir pada permintaan izin | Persetujuan eksekusi keamanan adalah "penuh" | Jalankan Langkah 5 untuk beralih ke "daftar diizinkan" |
| `pip install -e .` gagal | Kurang dependensi build | Jalankan `pip install hatchling` terlebih dahulu |
| `clawteam --version` menunjukkan "Segera Hadir" | Terpasang paket npm name-squatting (`a9logic`, tidak terkait dengan proyek ini) | `npm uninstall -g clawteam`, kemudian pasang kembali sesuai Langkah 2 |

---

## Kasus Penggunaan

### 1. Penelitian ML Otonom — 8 Agen x 8 GPU

Berdasarkan [@karpathy/autoresearch](https://github.com/karpathy/autoresearch). Satu prompt meluncurkan 8 agen penelitian di H100 yang merancang lebih dari 2000 eksperimen secara otonom.

```
Manusia: "Gunakan 8 GPU untuk mengoptimalkan train.py. Baca program.md untuk instruksi."

Agen pemimpin:
├── Memunculkan 8 agen, masing-masing ditugaskan pada arah penelitian (kedalaman, lebar, LR, ukuran batch...)
├── Setiap agen mendapatkan worktree git sendiri untuk eksperimen yang terisolasi
├── Setiap 30 menit: memeriksa hasil, menyalin konfigurasi terbaik ke agen baru
├── Menetapkan ulang GPU saat agen selesai — agen baru memulai dari konfigurasi terbaik yang diketahui
└── Hasil: val_bpb 1.044 → 0.977 (peningkatan 6,4%) di 2430 eksperimen dalam ~30 jam GPU
```

Hasil lengkap: [novix-science/autoresearch](https://github.com/novix-science/autoresearch)

### 2. Rekayasa Perangkat Lunak Agenik

```
Manusia: "Buat aplikasi todo full-stack dengan autentikasi, database, dan frontend React."

Agen pemimpin:
├── Membuat tugas dengan rantai ketergantungan (skema API → autentikasi + DB → frontend → pengujian)
├── Memunculkan 5 agen (arsitek, 2 backend, frontend, penguji) di worktree yang terpisah
├── Penyelesaian otomatis dependensi: arsitek selesai → backend terbuka → penguji terbuka
├── Agen berkoordinasi melalui kotak masuk: "Ini spesifikasi OpenAPI", "Endpoint autentikasi siap"
└── Pemimpin menggabungkan semua worktree ke main saat selesai
```

### 3. Dana Lindung Nilai AI — Peluncuran Template

Sebuah template TOML menghasilkan tim investasi lengkap dengan 7 agen hanya dengan satu perintah:

```bash
clawteam meluncurkan hedge-fund --tim fund1 --tujuan "Menganalisis AAPL, MSFT, NVDA untuk Q2 2026"
```

Total tujuh agen: 5 analis (nilai, pertumbuhan, teknikal, fundamental, sentimen) bekerja secara paralel, seorang manajer risiko menyintesis semua sinyal, dan seorang manajer portofolio membuat keputusan akhir.

Template adalah file TOML — **buat sendiri** untuk domain apa pun.

---

## Fitur

<table>
<tr>
<td width="50%">

### Swakelola Agen
- Pemimpin memunculkan dan mengelola pekerja
- Prompt koordinasi auto-injected — tanpa pengaturan manual
- Pekerja melaporkan sendiri status dan keadaan menganggur
- Agen CLI manapun dapat berpartisipasi

### Isolasi Workspace
- Setiap agen mendapatkan **git worktree** sendiri
- Tidak ada konflik penggabungan antara agen paralel
- Perintah checkpoint, gabungkan, dan bersihkan
- Penamaan cabang: `clawteam/{team}/{agent}`

### Pelacakan Tugas dengan Ketergantungan
- Kanban bersama: `pending` → `sedang_dikerjakan` → `selesai` / `terblokir`
- `--blocked-by` mengaitkan dengan pembukaan otomatis saat selesai
- `task wait` memblokir hingga semua tugas selesai

</td>
<td width="50%">

### Pesan Antar-Agen
- Kotak masuk titik-ke-titik (kirim, terima, intip)
- Siarkan ke semua anggota tim
- Berbasis file (default) atau transport P2P ZeroMQ

### Pemantauan & Dasbor
- `board show` — kanban terminal
- `board live` — dasbor yang menyegarkan otomatis
- `board attach` — tampilan tmux bersusun dari semua agen (Linux/macOS/WSL)
- `board serve` — Antarmuka Web dengan pembaruan waktu nyata

### Template Tim
- File TOML mendefinisikan arketipe tim (peran, tugas, prompt)
- Satu perintah: `clawteam launch <template>`
- Penggantian variabel: `{goal}`, `{team_name}`, `{agent_name}`

</td>
</tr>
</table>

### v0.3.0 — Intelijen Produksi *(Baru)*
- **Dukungan Agen Hermes** — target spawn asli di seluruh NativeCliAdapter, tmux, dan backend subprocess. Secara otomatis menyisipkan subperintah `chat` dan meneruskan `--source tool` (kebersihan sesi membutuhkan patch Hermes hulu yang dijelaskan di `skills/hermes/SKILL.md` — ClawTeam meneruskan flag dengan benar; Hermes ≤ 0.8.0 mengabaikannya).
- **Dasbor Biaya** — token/biaya waktu nyata berdasarkan agen, model, dan tugas (`clawteam board cost`). Tidak ada pesaing yang memiliki ini.
- **Pemutus Sirkuit** — sehat → menurun → terbuka tri-status dengan pengujian setengah terbuka
- **Coba Lagi dengan Penundaan** — `spawn_with_retry()` untuk pembentukan agen yang tangguh
- **Kunci Idempoten** — deduplikasi untuk `create()` dan `send()`
- **Prompt Berbasis Niat** — C2 militer Auftragstaktik: agen mendapatkan `niat` + `keadaan_akhir` + `kendala`
- **Aturan Munculnya Boid** — Aturan kawanan Reynolds 1986 yang disesuaikan untuk agen LLM
- **Penilaian Diri Metakognitif** — agen memberi tanda tingkat kepercayaan mereka sendiri
- **Resolusi Model Per-Agen** — rantai prioritas 7 tingkat, gabungan Claude/GPT/Qwen dalam satu tim
- **Penyisipan Langsung saat Runtime** — `runtime inject/state/watch` untuk pengiriman pesan ke agen yang sedang berjalan

**Juga:** alur kerja persetujuan rencana, manajemen siklus hidup yang elegan, output `--json` pada semua perintah, dukungan lintas mesin (NFS/SSHFS atau P2P), penamaan ruang multi-pengguna, validasi spawn dengan pemulihan otomatis, penguncian file `fcntl` untuk keamanan bersamaan.

---

## Integrasi OpenClaw

Fork ini menjadikan [OpenClaw](https://openclaw.ai) sebagai **agen default**. Tanpa ClawTeam, setiap agen OpenClaw bekerja secara terpisah. ClawTeam mengubahnya menjadi platform multi-agen.

| Kemampuan | OpenClaw Saja | OpenClaw + ClawTeam |
|-----------|---------------|-------------------|
| **Penugasan tugas** | Pesan manual per agen | Pemimpin secara mandiri membagi, menugaskan, memantau |
| **Pengembangan paralel** | Direktori kerja bersama | Worktree git terisolasi per agen |
| **Dependensi** | Pemantauan manual | `--blocked-by` dengan buka blokir otomatis |
| **Komunikasi** | Hanya melalui relay AGI | Kotak masuk langsung titik-ke-titik + siaran |
| **Observabilitas** | Membaca log | Papan Kanban + tampilan tmux berbentuk ubin |

Setelah keterampilan terpasang, bicaralah dengan bot OpenClaw Anda di saluran mana pun:

| Apa yang Anda katakan | Apa yang terjadi |
|-------------|-------------|
| "Buat tim 5 agen untuk membangun aplikasi web" | Membuat tim, tugas, dan menghasilkan 5 agen dengan backend yang dikonfigurasi |
| "Luncurkan tim analisis hedge fund" | `clawteam launch hedge-fund` dengan 7 agen |
| "Periksa status tim agen saya" | `clawteam board show` dengan output kanban |

```
  Anda (Telegram/Discord/TUI)
         │
         ▼
  ┌──────────────────┐
  │  Gerbang Cakar Terbuka │  ← mengaktifkan keterampilan clawteam
  └────────┬─────────┘
           │
           ▼
  ┌──────────────────┐     spawn tim cakar     ┌─────────────────┐
  │  Agen Pemimpin    │ ─────────────────────► │  openclaw tui   │
  │  (openclaw)      │ ──┐                    │  (jendela tmux)  │
  │                  │   │                    │  git worktree   │
  │  Mengelola kawanan   │   ├──────────────────► ├─────────────────┤
  │  melalui clawteam    │   │                    │  openclaw tui   │
  │  CLI             │   ├──────────────────► ├─────────────────┤
  └──────────────────┘   │                    │  openclaw tui   │
                         └──────────────────► └─────────────────┘
Semua koordinasi melalui
~/.clawteam/ (tugas, kotak masuk)
```

---

## Integrasi Agen Hermes

ClawTeam mengirimkan dukungan kelas satu untuk [Hermes Agent](https://github.com/NousResearch/hermes-agent) — agen CLI yang dapat meningkatkan dirinya sendiri dari Nous Research. Pekerja Hermes muncul melalui jalur adaptor yang sama seperti OpenClaw (tmux atau subprocess), tetapi menggunakan bendera perintah asli Hermes (`hermes chat --yolo --source tool -q "<task>"`).

Pekerja Hermes secara otomatis mewarisi semua server MCP yang dikonfigurasi di `~/.hermes/config.yaml`, sehingga alat apa pun yang telah Anda sambungkan ke Hermes tersedia untuk setiap pekerja yang dibuat.

| Kemampuan | Hermes Saja | Hermes + Tim Cakar |
|-----------|--------------|-------------------|
| **Paralelisme** | Sesi tunggal | Jalankan N pekerja di jendela tmux |
| **Koordinasi** | Manual | Kanban + kotak masuk + ketergantungan tugas |
| **Isolasi** | Direktori kerja bersama | Git worktrees per agen |
| **Kebersihan sesi** | Campur dengan sesi pengguna | Tag `--source tool` diteruskan ke Hermes (memerlukan perbaikan hulu — lihat SKILL.md `Masalah hulu yang diketahui`) |

**Menggunakan Hermes dengan ClawTeam:**

Semua templat bawaan (`hedge-fund`, `research-paper`, `code-review`, `strategy-room`) secara default akan membuat pekerja OpenClaw. Pengguna Hermes melewati `--command hermes` untuk menggantinya:

```bash
clawteam meluncurkan hedge-fund --team-name <name> --goal "..." --command hermes --force
```

Atau jalankan secara manual, dengan melewatkan `hermes` sebagai argumen posisi terakhir:

```bash
clawteam spawn --team <team> --agent-name <name> --task "..." --no-workspace hermes
```

Catatan: template bawaan dirancang berdasarkan pola koordinasi OpenClaw `clawteam inbox send`. Pekerja Hermes kadang menyelesaikan analisis mereka tanpa mengeksekusi perintah inbox-send. Jika `clawteam inbox peek` mengembalikan kosong sementara kanban menunjukkan `COMPLETED`, tangkap scrollback tmux secara langsung:

```bash
tmux capture-pane -t clawteam-<team>:<window-index> -p -S -500
```

**Instalasi:** lihat Langkah 5b di bagian Instalasi.

---

## Arsitektur

```
Manusia: "Optimalkan LLM ini"
         │
         ▼
  ┌──────────────┐     timcakar muncul     ┌──────────────┐
  │  Pemimpin      │ ──────────────────────► │  Pekerja      │
  │  (agen apa pun) │ ──────┐                │  git worktree │
  │              │       ├──────────────► │  jendela tmux  │
  │  spawn       │       │                ├──────────────┤
  │  buat tugas │       ├──────────────► │  Pekerja      │
  │  kirim kotak masuk  │       │                │  pohon kerja git │
  │  tampilan papan  │       └──────────────► │  jendela tmux  │
  └──────────────┘                        └──────────────┘
                                                 │
                                                 ▼
                                      ┌─────────────────────┐
                                      │    ~/.clawteam/     │
                                      │ ├── tim/   (siapa) │
                                      │ ├── tasks/   (apa)│
                                      │ ├── kotak masuk/ (bicara)│
                                      │ └── ruang-kerja/    │
                                      └─────────────────────┘
```

Semua status tersimpan di `~/.clawteam/` sebagai file JSON. Tidak ada basis data, tidak ada server. Penulisan atomik dengan penguncian file lintas platform memastikan keamanan jika terjadi crash.

| Pengaturan | Variabel Lingkungan | Default |
|---------|---------|---------|
| Direktori data | `CLAWTEAM_DATA_DIR` | `~/.clawteam` |
| Transportasi | `CLAWTEAM_TRANSPORT` | `file` |
| Mode ruang kerja | `CLAWTEAM_WORKSPACE` | `otomatis` |
| Spawn backend | `CLAWTEAM_DEFAULT_BACKEND` | `tmux` di Linux/macOS, `subprocess` di Windows |

---

## Referensi Perintah

<detail terbuka>
<summary><strong>Perintah Inti</strong></summary>

```bash
# Siklus hidup tim
clawteam tim spawn-tim <team> -d "deskripsi" -n <pemimpin>
clawteam tim temukan                    # Daftar semua tim
status tim clawteam <team>               # Tampilkan anggota
clawteam tim pembersihan <team> --force      # Hapus tim

# Memunculkan agen (catatan: `spawn` menggunakan --team; `launch` menggunakan --team-name)
clawteam spawn --team <team> --agent-name <name> --task "lakukan ini"
clawteam spawn codex --team <team> --agent-name <name> --task "lakukan ini"
clawteam spawn --team <team> --agent-name <name> --task "lakukan ini" hermes
clawteam spawn subprocess hermes --team <team> --agent-name <name> --task "lakukan ini"

# Manajemen tugas
clawteam task create <tim> "subjek" -o <pemilik> --blocked-by <id1>,<id2>
pembaruan tugas clawteam <team> <id> --status selesai   # otomatis-membuka blokir dependensi
daftar tugas clawteam <team> --status diblokir --pemilik worker1
clawteam task wait <team> --timeout 300

# Pesan
clawteam inbox kirim <team> <to> "pesan"
siaran kotak masuk clawteam <team> "pesan"
clawteam inbox terima <team>             # konsumsi pesan
clawteam inbox intip <team>                # baca tanpa mengonsumsi

# Pemantauan
papan clawteam tampilkan <team>                # kanban terminal
clawteam board live <team> --interval 3   # penyegaran otomatis
clawteam papan pasang <team>              # tampilan tmux bertingkat (Linux/macOS/WSL)
clawteam board serve --port 8080          # antarmuka web
```

</details>

<detail>
<summary><strong>Ruang Kerja, Rencana, Siklus Hidup, Konfigurasi</strong></summary>

```bash
# Workspace (manajemen git worktree)
daftar ruang kerja clawteam <team>
clawteam workspace checkpoint <team> <agent>    # auto-commit
clawteam workspace merge <team> <agent>         # gabungkan kembali ke utama
pembersihan ruang kerja clawteam <team> <agent>       # hapus worktree

# Persetujuan rencana
clawteam rencana kirim <team> <agent> "rencana" --ringkasan "TL;DR"
clawteam rencana setujui <team> <plan-id> <agent> --umpan balik "LGTM"
clawteam plan reject <team> <plan-id> <agent> --feedback "Revisi X"

# Siklus Hidup
clawteam lifecycle request-shutdown <team> <agent> --reason "selesai"
clawteam siklus-hidup setujui-matikan <team> <request-id> <agent>
clawteam siklus hidup diam <team>

# Template
clawteam luncurkan <template> --team <name> --goal "Bangun X"
daftar template clawteam

# Konfigurasi
tampilkan konfigurasi clawteam
clawteam config set transport p2p
clawteam konfigurasi kesehatan
```

</details>

---

## Penugasan Model Per-Agen

Tetapkan model yang berbeda ke peran agen yang berbeda untuk mendapatkan keseimbangan biaya/kinerja yang lebih baik dalam swarm multi-agen. Menggunakan **rantai prioritas 7 level**: CLI > model agen > tingkat agen > strategi template > model template > default konfigurasi > Tidak Ada.

**Model per-agen dalam templat:**
```toml
[template]
nama = "tim-saya"
perintah = ["buka cakar"]
model = "sonnet-4.6"              # default untuk semua agen
model_strategy = "auto"           # atau: leaders→kuat, workers→seimbang

[template.pemimpin]
nama = "lead"
model = "opus"                    # ganti untuk pemimpin

[[template.agents]]
nama = "pekerja"
model_tier = "murah"              # tingkat biaya: kuat / seimbang / murah
```

**Bendera CLI:**
```bash
clawteam spawn --model opus                          # agen tunggal
clawteam launch my-template --model gpt-5.4          # timpa semua agen
clawteam luncurkan my-template --model-strategy auto     # penugasan otomatis berdasarkan peran
```

---


## Peta Jalan

| Versi | Apa | Status |
|---------|------|--------|
| v0.2 | Agen default OpenClaw, overlay ruang kerja, deteksi zombie, README 11 bahasa | Dikirim |
| v0.3 | Intelijen berbasis riset, dasbor biaya, pemutus sirkuit, model per-agen, injeksi waktu jalan | **Dirilis** |
| v0.4 | Dukungan penuh Windows, integrasi Gateway A2A | Sedang Berlangsung |
| v0.5 | Pasar template agen — template TOML yang disumbangkan oleh komunitas | Direncanakan |
| v0.6 | Integrasi mendalam memori — berbagi pengetahuan per-tim/per-tugas | Direncanakan |
| v1.0 | Tingkat produksi — otentikasi, izin, log audit | Menjelajahi |

---

## Berkontribusi

Kami menyambut kontribusi! Lihat [CONTRIBUTING.md](CONTRIBUTING.md) untuk panduan pengaturan, gaya kode, dan PR.

Bidang-bidang yang kami ingin dibantu:

- **Integrasi agen** — dukungan untuk lebih banyak agen CLI
- **Template tim** — Template TOML untuk domain baru
- **Backend transportasi** — Redis, NATS, dll.
- **Peningkatan dashboard** — UI Web, Grafana
- **Dokumentasi** — tutorial dan praktik terbaik

---

## Ucapan Terima Kasih

- [@karpathy/autoresearch](https://github.com/karpathy/autoresearch) — kerangka penelitian ML otonom
- [OpenClaw](https://openclaw.ai) — backend agen default
- [Hermes Agent](https://github.com/NousResearch/hermes-agent) — Agen CLI yang dapat meningkatkan diri sendiri dari Nous Research
- [Claude Code](https://claude.ai/claude-code) dan [Codex](https://openai.com/codex) — agen AI pengkodean yang didukung
- [ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) — inspirasi template hedge fund
- [CLI-Anything](https://github.com/HKUDS/CLI-Anything) — proyek saudara

## Lisensi

MIT — bebas digunakan, dimodifikasi, dan didistribusikan.

---

<div align="center">

**ClawTeam** — *Intelijen Swarm Agen.*

</div>
