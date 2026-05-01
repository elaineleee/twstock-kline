# 台股K線早報

Nison 蠟燭形態 + 5 年事件研究的台股觀察清單，移植自港股版的理論架構（同樣的 8 種形態、同樣的 |t|>2／N≥30 過濾門檻、只看昨日已收完的 K 線）。資料源 yfinance，Universe 由 TWSE + TPEx OpenAPI 拉全市場再按近 20 日成交額排序，含上市、上櫃、ETF。

## 結構

```
twstock-kline/
├─ patterns.py          8 種 Nison 形態判定（向量化 pandas Series）
├─ tw_universe.py       TWSE+TPEx OpenAPI → Top N by 20-day turnover
├─ event_study.py       5 年回測，扣 0.585% 來回成本，產 pattern_passlist.json
├─ chart.py             Plotly 預先 render 日／週線 HTML
├─ morning_brief.py     每日主腳本：抓資料 → 判定 → 寫 brief_*.json + 圖
├─ server.py            Flask: /api/brief/{N}、/charts/*、/static/*
├─ static/              app.css、app.js、manifest.json
├─ templates/           index.html
├─ data/
│   ├─ universe/        Top 300 排序快取（按日期）
│   ├─ prices/          5 年價格 panel parquet
│   ├─ briefs/          brief_50/100/200/300.json（前端讀這個）
│   ├─ charts/          每個訊號的日／週線 Plotly HTML
│   └─ pattern_passlist.json   事件研究結果（哪些形態通過 |t|>2）
└─ scripts/
    ├─ com.user.twstock-kline.plist  launchd 排程（每個交易日 14:30）
    └─ start_tunnel.sh               cloudflared 對外 tunnel
```

## 安裝

```bash
cd twstock-kline
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 第一次跑（必要順序）

```bash
# 1) 建 universe（拉 TWSE+TPEx、yfinance 排 Top 300）
.venv/bin/python tw_universe.py

# 2) 跑 5 年事件研究（產 pattern_passlist.json，第一次約 1–2 分鐘）
.venv/bin/python event_study.py

# 3) 產生今日 brief + 圖表（每天要跑一次）
.venv/bin/python morning_brief.py

# 4) 啟動 Flask
.venv/bin/python server.py --host 127.0.0.1 --port 8080
# → 開 http://localhost:8080
```

## 每日自動排程（launchd）

`scripts/com.user.twstock-kline.plist` 設定每個交易日 14:30 自動跑 `morning_brief.py`（台股 13:30 收盤後 +1 小時讓 Yahoo 落帳）。安裝：

```bash
cp scripts/com.user.twstock-kline.plist ~/Library/LaunchAgents/
launchctl load   ~/Library/LaunchAgents/com.user.twstock-kline.plist
launchctl list | grep twstock-kline   # 驗證載入

# 想立刻測一次：
launchctl start com.user.twstock-kline

# 移除：
launchctl unload ~/Library/LaunchAgents/com.user.twstock-kline.plist
```

Log 寫到 `data/launchd.out.log` / `data/launchd.err.log`。

## Cloudflared tunnel（對外）

跟原參考站一樣用 `*.trycloudflare.com` 臨時 URL（不需 Cloudflare 帳號）：

```bash
brew install cloudflared      # 一次性
./scripts/start_tunnel.sh     # 啟動 tunnel，列印公開 URL
```

腳本會接到本機 `127.0.0.1:8080`。把它和 `server.py` 開在不同 terminal。

## 理論架構（跟港股版相同）

- **形態**：早晨之星、看漲孕線、向上窗口、倒錘子線（買入）；流星線、大陰線、看跌吞沒、向下窗口（賣出）
- **指標**：RSI(14)、MA10/20/50/200(日)、MA200(週)
- **過濾器**：對 Top 100、過去 5 年的每次形態觸發，計算 1/3/5/20 日 forward return，扣 **0.585% 來回成本**（手續費 0.1425%×2 + 證交稅 0.3%），門檻 **N≥30 且 |t|>2**，方向需符合形態定義；以 5 日 horizon 為 gate。
- **時間軸**：永遠只看昨日已收完的日 K（避開盤中變動）；週 K 用上週五已收完的整週。

5 年台股 Top 100 跑出來的結果（2026-05 跑的）：
- 日線過關：向上窗口、倒錘子線
- 週線過關：看漲孕線、向上窗口、倒錘子線
- 賣出形態在這個樣本期全部不過——市場長期上漲漂移把空頭信號的淨期望值壓成負。框架本來就會自動屏蔽這類形態，行為跟原版一致。

要重跑事件研究（例如換 universe 或半年後 refresh）：

```bash
.venv/bin/python event_study.py    # 會覆寫 data/pattern_passlist.json
```

## API

- `GET /` — 主頁
- `GET /api/brief/{50|100|200|300}` — 當日 brief JSON
- `GET /charts/{file}.html` — 預先 render 的 Plotly 圖
- `GET /static/{app.css|app.js|manifest.json}` — PWA 靜態檔

Brief JSON shape：

```json
{
  "universe_size": 100,
  "signal_date": "2026-04-30",
  "weekly_signal_date": "2026-04-24",
  "freshness": {"ok": 300, "fail": 0, "total": 300},
  "daily":  [{"code": "...", "name": "...", "pattern": "...", "direction": "...", "close": ..., "rsi": ..., "ma_dist": {...}, "charts": {...}}],
  "weekly": [...]
}
```

## 免責

形態僅為觀察線索，**非交易建議**。
