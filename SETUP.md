# Deploy 設置指南（Render + GitHub Actions）

整體架構：
```
你 push 程式 → GitHub repo
                ↓
         Render 自動 deploy → twstock-xxx.onrender.com（公開網址）
                ↑
GitHub Actions 排程 14:30 TWT 跑 morning_brief.py
                ↓ commit data/briefs + data/charts
         GitHub repo（觸發 Render redeploy）
```

整套全免費。流程跑通後你只要每隔幾個月手動 push 一次 `pattern_passlist.json` 重新校正即可（事件研究結果緩慢變化）。

---

## 一次性設定（10 分鐘）

### 步驟 1 — 初始化 git repo

```bash
cd /Users/RONANFU/Downloads/test/twstock-kline
git init
git add .
git commit -m "initial commit: twstock kline"
```

### 步驟 2 — 建 GitHub repo 並推上去

1. 到 https://github.com/new 建一個新 repo（名字隨意，例如 `twstock-kline`）
   - **Visibility**：Private 或 Public 都行
   - **不要**勾 README / .gitignore / license（會跟本地衝突）
2. 在 GitHub 拿到 repo URL，回到 terminal：

```bash
git remote add origin https://github.com/<你的帳號>/twstock-kline.git
git branch -M main
git push -u origin main
```

### 步驟 3 — 開啟 GitHub Actions 寫入權限

GitHub repo 預設 Action 只能讀，不能 push 回去。要改：

1. 進到 repo 頁 → **Settings** → **Actions** → **General**
2. 拉到最下面 **Workflow permissions**
3. 選 **Read and write permissions**
4. **Save**

### 步驟 4 — 部署到 Render

1. 註冊／登入 https://render.com（用 GitHub 帳號登入最快）
2. 右上 **New** → **Blueprint**
3. 選你剛才推上去的 repo
4. Render 會偵測到 `render.yaml` 並把所有設定填好
5. 點 **Apply** → 等第一次 deploy 完成（~3 分鐘）
6. 拿到網址：`https://twstock-kline.onrender.com`（或類似的）

### 步驟 5 — 驗證

開瀏覽器訪問你的 Render 網址，應該看到 dark 風的台股 K 線早報，跟本地一樣。

打開 GitHub repo 的 **Actions** tab，會看到 `Daily morning brief` workflow。手動觸發一次：
1. 點 **Daily morning brief** → **Run workflow** → **Run workflow**
2. 等綠勾，commit 完之後 Render 會自動重 deploy 一次
3. 重新整理你的 Render 網址，meta 的 `run_time` 會變成最新時間

---

## 之後每天會發生什麼

- **14:30 TWT（06:30 UTC）週一到週五**：GitHub Actions 自動觸發
- Action 跑 `morning_brief.py`：抓 yfinance、判形態、產 brief JSON + chart HTML
- 把 `data/briefs/` + `data/charts/` commit + push 回 main
- Render 偵測到 push，30–60 秒內 redeploy
- 你的網址自動拿到新資料

---

## 常見問題

**Q：GitHub Actions cron 為什麼有時延遲？**
A：GitHub 排程不保證準點（用流量低時段優先），可能延遲 5–15 分鐘。台股 13:30 收盤、Yahoo 約 14:00 落帳，14:30 排程留 30 分緩衝。如果經常太晚，可以改 `.github/workflows/daily.yml` 的 cron 為 `30 7 * * 1-5`（15:30 TWT）。

**Q：Render 免費版會「sleep」嗎？**
A：會。閒置 15 分鐘 server 會睡，下一個訪問要等 ~30 秒喚醒。如果你想常駐，升級 Render Starter（$7/月）或改用 Fly.io。

**Q：`pattern_passlist.json` 多久要重跑一次？**
A：建議每 3–6 個月。手動跑：

```bash
.venv/bin/python event_study.py
git add data/pattern_passlist.json
git commit -m "refresh pattern passlist"
git push
```

**Q：自選股（watchlist）資料會跨裝置同步嗎？**
A：不會，存在瀏覽器 `localStorage`。手機跟電腦各看各的。要跨裝置同步需要加後端帳號系統（不在這版範圍）。

**Q：可以綁自訂網域嗎？**
A：可以。Render 後台 → 你的 service → Settings → Custom Domain → 填你的網域 → 照它指示在 DNS 加 CNAME。免費。

**Q：第一次 deploy 之後，本地的 `morning_brief.py` 還要跑嗎？**
A：不用了。如果你想在 Render 之外另開本地版玩 / 測 launchd，照舊跑沒問題，但本地產出不會自動上 GitHub（除非你手動 push）。

---

## 除錯

**deploy 失敗：**
- Render → service → **Logs** tab 看錯誤訊息
- 通常是 requirements.txt 沒裝起來，或 `gunicorn server:app` 找不到 `app`（檢查 `server.py` 末段）

**Action 執行失敗：**
- GitHub repo → Actions → 點失敗的 run → 看哪一步紅
- 最常見是 yfinance rate-limit；重新觸發即可

**頁面 503 / `brief_xxx.json not generated yet`：**
- 第一次 deploy 之前必須先在本地跑過 `morning_brief.py` 並 commit 出 `data/briefs/*.json`（你已經跑過）
- 如果你 reset repo 把 brief 拿掉，要重新跑一次再 push
