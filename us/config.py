
# ── API ──────────────────────────────────────────────
MASSIVE_API_KEY    = "rCaGoYtQokzcP6WUxW1dJy33xq2wDZQ5"
MASSIVE_BASE_URL   = "https://api.massive.com/v2"
DEEPSEEK_API_KEY   = "sk-590b45d323d340b8802c2b77f7549d56"   

# ── Telegram ─────────────────────────────────────────
TELEGRAM_BOT_TOKEN = "8303744754:AAFNSiPveDsMtF1u6qwh_0lIn0kniVuoARI"
GROUP_ID           = -1002738891883
TOPIC_ID           = 27537
ADMIN_ID           = 5751902978

# ── Path ─────────────────────────────────────────────
STOCK_FILE         = "/home/ec2-user/us/stock/stock.txt"
OUTPUT_DIR         = "/home/ec2-user/us"
CACHE_DIR          = "/home/ec2-user/us/cache"
OHLCV_500_DIR      = "/home/ec2-user/us/500"       
TRAIN_DIR          = "/home/ec2-user/us/train"     
FOREX_FILE         = "/home/ec2-user/etf/stock/forex.txt"
FOREX_CACHE_DIR    = "/home/ec2-user/cache_forex"
FOREX_500_DIR      = "/home/ec2-user/us/forex_500"     
FOREX_TRAIN_DIR    = "/home/ec2-user/us/forex_train"    
FOREX_WEIGHTS_DIR  = "/home/ec2-user/us/forex_weights"  

# ── Behaviour ────────────────────────────────────────
HISTORY_DAYS           = 500   # bar maksimal dari API (hard limit ~501)
SCORE_WARMUP           = 200   # bar warmup sebelum score dihitung (MA200)
SCORE_BARS             = 300   # bar yang punya score (500 - 200)
DELAY_BETWEEN_STOCKS   = 12    # detik jeda antar saham
ALERT_SCORE_THRESHOLD  = 4     # skor minimum untuk alert ke grup
TOP_N                  = 50    # jumlah saham top/bottom list
FOREX_HISTORY_DAYS = 500 

# ── Chart ────────────────────────────────────────────
CHART_CANDLES      = 120       # jumlah candle ditampilkan di chart S&R

# S&R detection methods
SR_METHOD_DONCHIAN = "Donchian"
SR_METHOD_PIVOTS   = "Pivots"
SR_METHOD_CSID     = "CSID"
SR_METHOD_ZIGZAG   = "ZigZag"

SR_SENSITIVITY     = 10        # default sensitivity (lookback / deviation%)
SR_ATR_PERIOD      = 200
SR_ATR_MULT        = 0.5       # zone depth multiplier
SR_MAX_LEVELS      = 5         # max active S&R levels ditampilkan

# ── Akses Control ────────────────────────────────────
# /chart → semua member
# /9, /ip → hanya ID di ALLOWED_IDS
ALLOWED_IDS        = {5751902978, 6208519947}   # tambah ID lain jika perlu
