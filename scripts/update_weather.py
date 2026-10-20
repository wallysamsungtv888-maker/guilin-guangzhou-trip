#!/usr/bin/env python3
"""TR-004 天氣卡自動更新（GitHub Actions 定時執行，亦可本機手動行）。

由 Open-Meteo 攞每日預報，改寫 index.html 入面嘅靜態天氣數值：
  * <!-- wx:auto:start --> 同 <!-- wx:auto:end --> 之間嘅天氣卡
  * 行程入面 <span class="wx-note" data-wx-date=...> 嘅天氣備註
地點座標讀自 index.html 嘅 <script type="application/json" id="wx-cfg">。
只更新今日（香港時間）或之後嘅日子；過咗嘅日子保留最後數值。
數值冇變就唔寫檔（GitHub Actions 就唔會 commit）。
只用 Python 標準庫，唔使任何 secret。
"""
import datetime as dt
import html
import json
import math
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "index.html"
API = "https://api.open-meteo.com/v1/forecast"
HKT = dt.timezone(dt.timedelta(hours=8))

# WMO weather code → (廣東話標籤, SVG symbol id)
WMO = {
    0: ("晴", "sun"), 1: ("大致天晴", "sun"), 2: ("多雲", "cloudy"), 3: ("陰", "overcast"),
    45: ("有霧", "fog"), 48: ("有霧", "fog"),
    51: ("毛毛雨", "drizzle"), 53: ("毛毛雨", "drizzle"), 55: ("毛毛雨", "drizzle"),
    56: ("毛毛雨", "drizzle"), 57: ("毛毛雨", "drizzle"),
    61: ("小雨", "rain"), 63: ("中雨", "rain"), 65: ("大雨", "heavyrain"),
    66: ("小雨", "rain"), 67: ("大雨", "heavyrain"),
    71: ("落雪", "overcast"), 73: ("落雪", "overcast"), 75: ("落雪", "overcast"), 77: ("落雪", "overcast"),
    80: ("陣雨", "rain"), 81: ("陣雨", "rain"), 82: ("大陣雨", "heavyrain"),
    85: ("落雪", "overcast"), 86: ("落雪", "overcast"),
    95: ("雷暴", "thunder"), 96: ("雷暴", "thunder"), 99: ("雷暴", "thunder"),
}


def wmo(code):
    if code in WMO:
        return WMO[code]
    return ("多雲", "cloudy")


def rain_tip(code, prob):
    if code >= 95:
        return "可能有雷暴，帶遮，避開空曠位"
    if prob >= 70 or code in (65, 67, 82):
        return "好大機會落雨，帶遮"
    if prob >= 50:
        return "可能落雨，帶遮"
    if code >= 51 and prob >= 30:
        return "間中有雨，帶把縮骨遮"
    if code in (45, 48):
        return "有霧，睇景未必清"
    return ""


def temp_tip(lo, hi, code, mtn):
    if mtn and lo <= 16:
        return "山上早晚凍，帶薄外套"
    if hi >= 33:
        return "好熱，多飲水、做足防曬"
    if hi >= 30:
        return "下晝熱，記得飲水防曬"
    if lo <= 16 or (lo <= 18 and hi - lo >= 9):
        return "早晚涼，帶件薄外套"
    if code <= 2:
        return "日頭曬，帶帽同防曬"
    return "天氣舒服，帶定水"


def make_tip(lo, hi, code, prob, mtn):
    r = rain_tip(code, prob)
    t = temp_tip(lo, hi, code, mtn)
    if r and t in ("日頭曬，帶帽同防曬", "天氣舒服，帶定水"):
        t = ""
    return "；".join(x for x in (r, t) if x)


def summarise(daily_list, date):
    """合併一個或多個地點同一日嘅數值（最低溫取最低、最高溫取最高、天氣取最差）。"""
    los, his, codes, probs = [], [], [], []
    for d in daily_list:
        if date not in d["time"]:
            return None
        i = d["time"].index(date)
        vals = (d["temperature_2m_min"][i], d["temperature_2m_max"][i], d["weather_code"][i])
        if any(v is None for v in vals):
            return None
        los.append(vals[0]); his.append(vals[1]); codes.append(int(vals[2]))
        probs.append(d["precipitation_probability_max"][i] or 0)
    return {"lo": round_half_up(min(los)), "hi": round_half_up(max(his)),
            "code": max(codes), "prob": int(max(probs))}


def round_half_up(x):
    # 同 JS Math.round 一致
    return int(math.floor(x + 0.5))


def render(s, mtn):
    label, icon = wmo(s["code"])
    if mtn and s["lo"] <= 16 and icon in ("sun", "cloudy"):
        icon = "cool"
    cond = label + ("，較涼" if mtn and s["lo"] <= 16 else "")
    pp = s["prob"]
    return {
        "icon": icon,
        "t": f'{s["lo"]}–{s["hi"]}<small>°C</small>',
        "c": cond + (f'<span class="wx-pp">降雨概率 {pp}%</span>' if pp >= 20 else ""),
        "tip": make_tip(s["lo"], s["hi"], s["code"], pp, mtn),
        "label": label,
    }


def fetch(cfg):
    names = list(cfg.keys())
    lat = ",".join(str(cfg[n][0]) for n in names)
    lon = ",".join(str(cfg[n][1]) for n in names)
    url = (f"{API}?latitude={lat}&longitude={lon}"
           "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
           "&timezone=Asia%2FShanghai&forecast_days=16")
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "tr004-weather/1.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.load(r)
            if isinstance(data, dict):
                data = [data]
            return {n: data[i]["daily"] for i, n in enumerate(names)}
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(5 * (attempt + 1))
    raise SystemExit(f"Open-Meteo fetch failed: {last}")


LI_RE = re.compile(r'<li class="wx-day[^"]*"[^>]*>.*?</li>', re.S)
NOTE_RE = re.compile(r'<span class="wx-note"[^>]*>[^<]*</span>')


def attrs(tag):
    return dict(re.findall(r'data-wx-([a-z]+)="([^"]*)"', tag))


def main():
    src = INDEX.read_text(encoding="utf-8")
    m = re.search(r'<script type="application/json" id="wx-cfg">(.*?)</script>', src, re.S)
    if not m:
        raise SystemExit("wx-cfg not found")
    cfg = json.loads(m.group(1))["locs"]
    start = src.index("<!-- wx:auto:start -->")
    end = src.index("<!-- wx:auto:end -->")

    now = dt.datetime.now(HKT)
    today = now.strftime("%Y-%m-%d")
    daily = fetch(cfg)

    def day_for(a):
        if a["date"] < today:
            return None
        return summarise([daily[l] for l in a["loc"].split(",")], a["date"])

    def sub_li(mo):
        li = mo.group(0)
        a = attrs(li[: li.index(">") + 1])
        s = day_for(a)
        if not s:
            return li
        r = render(s, a.get("mtn") == "1")
        li = re.sub(r'<use href="#wx-[a-z]+"/>', f'<use href="#wx-{r["icon"]}"/>', li, count=1)
        li = re.sub(r'<span class="wx-t">.*?</span>(?=<span class="wx-c">)', f'<span class="wx-t">{r["t"]}</span>', li, count=1, flags=re.S)
        li = re.sub(r'<span class="wx-c">.*?</span>(?=<span class="wx-tip">)', f'<span class="wx-c">{r["c"]}</span>', li, count=1, flags=re.S)
        li = re.sub(r'<span class="wx-tip">.*?</span>', f'<span class="wx-tip">{r["tip"]}</span>', li, count=1, flags=re.S)
        return li

    def sub_note(mo):
        tag = mo.group(0)
        a = attrs(tag)
        s = day_for(a)
        if not s:
            return tag
        mtn = a.get("mtn") == "1"
        r = render(s, mtn)
        text = f'天氣（{html.unescape(a.get("place", ""))}）：{r["label"]}，{s["lo"]}–{s["hi"]}°C；{r["tip"]}。'
        return tag[: tag.index(">") + 1] + text + "</span>"

    card = src[start:end]
    new_card = LI_RE.sub(sub_li, card)
    new_src = src[:start] + new_card + src[end:]
    new_src = NOTE_RE.sub(sub_note, new_src)

    if new_src == src:
        print("weather values unchanged; nothing to write")
        return 0

    stamp_d = now.strftime("%d/%m")
    stamp = now.strftime("%d/%m %H:%M")
    new_src = re.sub(r'(<p class="wx-src"><b>)[^<]*(</b>)', rf'\g<1>{stamp_d} 預報\g<2>', new_src, count=1)
    new_src = re.sub(r'(<span class="wx-upd">)[^<]*(</span>)', rf'\g<1>{stamp}\g<2>', new_src, count=1)
    INDEX.write_text(new_src, encoding="utf-8")
    print(f"index.html updated ({stamp} HKT)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
