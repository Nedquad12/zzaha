stock_score_bot/
├── main.py
├── config.py
├── api.py
├── cache.py
├── scorer.py
├── tight.py          ← baru
├── chart.py
├── storage.py
├── formatter.py
└── indicators/
    ├── __init__.py
    ├── vsa.py
    ├── rsi.py
    ├── macd.py
    ├── ma.py
    ├── ip.py
    └── sr.py

Trigger /9 — 3 Fase
main.py
  └── baca stock.txt → ["NVDA", "AAPL", "ORCL", ...]
  └── reset cache (hapus semua file JSON lama)
  │
  ├── FASE 1 — Fetch Data
  │     loop tiap ticker (jeda 8 detik):
  │       └── api.py    → fetch OHLCV 200 hari dari Massive.com
  │       └── cache.py  → simpan ke /home/ec2-user/cache/NVDA.json
  │
  ├── FASE 2 — Scan Tight (1x untuk semua saham)
  │     └── tight.py → scan_tight()
  │           └── baca semua file JSON dari cache
  │           └── hitung MA 3/5/10/20 dari data close
  │           └── cek jarak harga ke setiap MA
  │           └── pisahkan ke vt_set dan t_set
  │                 vt_set = ticker yang jarak ke semua MA < 5%
  │                 t_set  = ticker yang jarak ke semua MA 5–7%
  │
  └── FASE 3 — Hitung Skor
        loop tiap ticker:
          └── tight.py  → score_tight() → dapat tight_score
          └── scorer.py → calculate_all_scores() → dapat semua skor
          └── kalau total > 4 → kirim alert ke grup
        └── storage.py  → simpan ke xlsx
        └── formatter.py → format top 50 & bottom 50
        └── kirim ke grup

Detail Fase 2 — tight.py
scan_tight()
  └── list_cached()     → dapat semua ticker yang ada di cache
  └── per ticker:
        └── cache_load()          → baca DataFrame dari JSON
        └── hitung MA 3/5/10/20   → np.mean(closes[-N:])
        └── cek 3 syarat:
              1. close > semua MA (harga di atas semua MA)
              2. nilai transaksi (close × volume) >= 0.5 miliar
              3. jarak ke semua MA:
                   < 5%      → masuk vt_list
                   5% – 7%   → masuk t_list
  └── return (vt_list, t_list)

Detail Fase 3 — Skoring
scorer.py — calculate_all_scores(ticker, df, tight_score)
  ├── indicators/vsa.py   → avg volume 7 hari vs 30 hari  → -2 s/d +2
  ├── indicators/rsi.py   → RSI 14, cek zona              → -1 s/d +2
  ├── indicators/macd.py  → MACD (12,26,9), 2 kondisi     → -2 s/d +2
  ├── indicators/ma.py    → berapa MA yang dilewati harga  → -2 s/d +2
  ├── indicators/ip.py    → MACD+Stoch × 3 timeframe      → -2 s/d +2
  └── tight_score         → dari tight.py                 → -1 s/d +2
        masuk VT+T  → +2
        masuk VT    → +1
        masuk T     → 0
        tidak masuk → -1
  │
  └── total = vsa + rsi + macd + ma + ip_score + tight_score

Command /vtus dan /tus
main.py (terima /vtus atau /tus)
  └── tight.py → scan_tight() → dapat vt_list dan t_list
        └── baca dari cache yang sudah ada
        └── kalau cache kosong → hasilnya juga kosong
  └── tight.py → format_vt() / format_t() → tabel teks
  └── kirim ke user
Catatan: /vtus dan /tus hanya bisa dipakai setelah /9 pernah jalan, karena datanya diambil dari cache. Kalau cache kosong, hasilnya akan kosong.

Command /ip TICKER
main.py
  └── cache.py  → coba baca dari cache dulu
        └── kalau tidak ada → api.py fetch dari API
  └── tight.py  → scan_tight() real-time dari cache → dapat tight_score
  └── scorer.py → hitung semua skor termasuk tight
  └── formatter.py → fmt_detail() → kirim ke user

Ringkasan Aliran Data
stock.txt
    ↓
api.py (fetch OHLCV) → cache.py (simpan JSON)
                            ↓
                       tight.py (scan VT/T)
                            ↓
                       scorer.py
                     ├── vsa / rsi / macd / ma / ip
                     └── tight_score
                            ↓
              ┌─────────────┴─────────────┐
         storage.py                  formatter.py
          (xlsx)                   (Telegram alert,
                                  top/bottom, tabel)

/vtus → tight.py (scan cache) → format_vt() → Telegram
/tus  → tight.py (scan cache) → format_t()  → Telegram
/chart → cache.py → sr.py → chart.py → PNG → Telegram
