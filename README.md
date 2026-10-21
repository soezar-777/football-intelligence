# ⚽ FOOTBALL INTELLIGENCE

ဘောလုံးပွဲ ခန့်မှန်းချက် စနစ် — Poisson model နဲ့ ဂိုးရလဒ်ခန့်မှန်းတာ၊ ရလဒ်အမှန်နဲ့ ပြန်စစ်တာ၊ မော်ဒယ်စွမ်းဆောင်ရည် တိုင်းတာတာ။ အခမဲ့ services တွေပဲသုံးထားတယ်။

**English summary:** A professional football match-prediction app. Poisson-based goal model produces 1X2, Over/Under, BTTS, Asian Handicap and Correct Score probabilities; predictions are graded against actual results and model performance is tracked. 100% free stack — no paid plans.

---

## ဗိသုကာ (Architecture)

```
+------------------+   scheduler (06:00 & 18:00 Yangon)        +------------------+
| football-data.org+------------------------------------------->+  GitHub Pages    |
| (free API tier)  |   fetch -> predict -> verify -> performance |  static dashboard|
+------------------+                                            |  (Burmese / EN)  |
                                                                +------------------+
```

- **Backend:** Python (stdlib + `requests` only) — `backend/`
- **Frontend:** static HTML/CSS/JS, no framework, no build step — `docs/` (single-file PWA, `docs/index.html`)
- **Data sync:** scheduled job, twice daily (06:00 & 18:00 Yangon) — data sync လုပ်ပြီး `docs/data/` ကို update လုပ်တယ်
- **Hosting:** GitHub Pages (free)
- **Database:** none — JSON files (`data/*.json` published to `docs/data/` for GitHub Pages)

## စတင်ရန် (Setup)

1. **API key ယူရန်:** [football-data.org](https://www.football-data.org/client/register) မှာ အခမဲ့ register လုပ်ပါ (ကတ် မလို)။
2. **Pages ဖွင့်ရန်:** GitHub repo → *Settings → Pages* → *Build and deployment* → Source: **Deploy from a branch** → Branch: `main`, folder: `/docs` → Save. ဒါဆိုရင် dashboard ကို ဖုန်းကနေ ကြည့်လို့ရပြီ: `https://soezar-777.github.io/football-intelligence/`
3. **Data sync:** Muse က 06:00 နဲ့ 18:00 (Yangon) တိုင်း data ဆွဲပြီး repo ကို အလိုအလျောက် update လုပ်ပေးတယ် — ဘာမှလုပ်စရာမလိုဘူး။

> ⚠️ API key ကို ဘယ် file ထဲမှာမှ မသိမ်းပါနဲ့။ `FOOTBALL_DATA_API_KEY` env var (သို့) local dev အတွက် `/home/hatch/.config/football-intelligence/api_key` (mode 600) ကပဲ ဖတ်ပါတယ်။

## Local dev

```bash
pip install -r backend/requirements.txt
export FOOTBALL_DATA_API_KEY="your_key_here"   # သို့မဟုတ် 600-file fallback
python3 backend/run_daily.py --competitions PL  # စမ်းရန်: PL တစ်ခုတည်း
python3 -m pytest tests/ -q
# frontend ကို ကြည့်ရန်:
cp data/*.json docs/data/   # သို့မဟုတ် samples သုံးမည်
python3 -m http.server -d docs 8000
# → http://localhost:8000
```

## Project structure

```
football-intelligence/
├── backend/
│   ├── config.py        # API base, key loading, competitions, rate limits
│   ├── fetch_data.py    # polite football-data.org v4 client (10 req/min)
│   ├── poisson.py       # core model: strengths → xG → score matrix → markets
│   ├── predict.py       # predictions for all scheduled fixtures
│   ├── verify.py        # grade picks vs actual results
│   ├── performance.py   # hit rates, rolling-30, Brier score
│   └── run_daily.py     # orchestrator: fetch → predict → verify → performance
├── docs/
│   ├── index.html       # single-file PWA app (GitHub Pages root)
│   ├── i18n/my.json / en.json           # Burmese default, EN toggle
│   └── data/            # published JSON (filled by the sync jobs)
├── data/samples/        # tiny samples so UI renders before first sync
└── tests/               # pytest: model math + verification grading
```

## Model အကျဉ်းချုပ်

- Team attack/defense strengths — home/away ခွဲ၊ 180-day half-life recency weight၊ data နည်းရင် league average ဘက် ပြန်ဆွဲ။
- `hxg = home_attack × away_defense × league_avg_home_goals` (away အတွက်လည်း ထို့အတူ)။
- Poisson score matrix (0–8 × 0–8) → 1X2, O/U 1.5/2.5/3.5, BTTS, top-5 correct scores, Asian Handicap (−1.5…+1.5)။
- Probability set တိုင်း sum = 1.0 ဖြစ်အောင် normalize လုပ်ထားတယ်။
- Pick တစ်ခုချင်းစီက threshold (1X2 ≥ 45%, O/U & BTTS & AH ≥ 55%) ကျော်မှ ထုတ်ပြန်တယ်။

## Roadmap

- [ ] Backtest mode (သမိုင်းနဲ့ model စမ်းသပ်ရန်)
- [ ] xG data (Understat) နဲ့ ပေါင်းစပ်ရန်
- [ ] Elo ratings နဲ့ ရောစပ်ရန်
- [ ] Telegram pre-match alerts
- [ ] Odds comparison (value detection)
- [ ] ပိုများသော လိဂ်များ (API free-tier limit အတွင်း)
