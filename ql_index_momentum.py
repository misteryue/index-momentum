#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""指数动量推送 - 东方财富数据源"""

import sys, os, json, time
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.parse import quote

BARK_SERVER = os.environ.get("BARK_SERVER", "https://api.day.app")
BARK_KEY = os.environ.get("BARK_KEY", "")

INDICES = [
    ("sh.000300", "沪深300"),
    ("sz.399006", "创业板指"),
    ("sh.000016", "上证50"),
    ("sh.000688", "科创50"),
    ("sz.399330", "深证100"),
    ("sh.000905", "中证500"),
]

EM_SECIDS = {
    "sh.000300": "1.000300", "sz.399006": "0.399006",
    "sh.000016": "1.000016", "sh.000688": "1.000688",
    "sz.399330": "0.399330", "sh.000905": "1.000905",
}

LOOKBACK = 20

def fetch_realtime():
    codes = ",".join(EM_SECIDS.values())
    url = f"https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&invt=2&fields=f2,f3,f12,f18&secids={codes}"
    result = {}
    code_map = {v.split(".")[1]: k for k, v in EM_SECIDS.items()}
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"})
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        for item in data.get("data", {}).get("diff", []):
            code = item.get("f12", "")
            if code in code_map:
                result[code_map[code]] = {
                    "close": float(item.get("f2", 0)),
                    "prev_close": float(item.get("f18", 0)),
                    "chg": float(item.get("f3", 0)),
                }
    except Exception as e:
        print(f"[ERROR] 实时数据: {e}")
    return result

def fetch_kline(bs_code, retries=3):
    secid = EM_SECIDS.get(bs_code)
    if not secid:
        return []
    url = f"https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={secid}&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56&klt=101&fqt=1&beg=20260101&end=20991231&smpllt=460&lmt=1000000"
    for i in range(retries):
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"})
            with urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
            return [(l.split(",")[0], float(l.split(",")[2])) for l in data.get("data", {}).get("klines", [])]
        except Exception as e:
            if i < retries - 1:
                time.sleep(2)
            else:
                print(f"[ERROR] K线 {bs_code}: {e}")
    return []

def calc_momentum(klines, n, realtime_close):
    if len(klines) < n + 1 or not realtime_close:
        return None
    base = klines[-(n + 1)][1]
    return round((realtime_close / base - 1) * 100, 2) if base else None

def emoji(pct):
    if pct >= 5: return "++"
    if pct >= 3: return "+"
    if pct >= 1: return ""
    if pct >= 0: return "."
    if pct >= -1: return "-"
    if pct >= -3: return "--"
    return "!!"

def send_bark(title):
    if not BARK_KEY:
        print("[WARN] 无BARK_KEY")
        return
    url = f"{BARK_SERVER}/{BARK_KEY}/{quote(title, safe='')}"
    try:
        with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=10) as r:
            print(f"Bark: {r.read().decode()[:80]}")
    except Exception as e:
        print(f"[ERROR] Bark: {e}")

def main():
    print(f"指数动量 [{datetime.now():%Y-%m-%d %H:%M}]")
    rt = fetch_realtime()
    if not rt:
        print("无数据")
        sys.exit(1)

    results = []
    for code, name in INDICES:
        klines = fetch_kline(code)
        info = rt.get(code, {})
        mom = calc_momentum(klines, LOOKBACK, info.get("close"))
        if mom is None:
            continue
        base_date = klines[-(LOOKBACK + 1)][0] if len(klines) > LOOKBACK else "?"
        print(f"  {emoji(mom)} {name} {mom:+.2f}% ({info.get('chg', 0):+.1f}%) [基准{base_date}]")
        results.append({"name": name, "mom": mom})

    if len(results) < 2:
        print("数据不足")
        sys.exit(1)

    results.sort(key=lambda x: x["mom"], reverse=True)
    title = "  ".join(f"{'★' if i == 0 else ''}{r['name']}{r['mom']:+.1f}%" for i, r in enumerate(results))
    print(f"\n推送: {title}")
    send_bark(title)
    print("完成")

if __name__ == "__main__":
    main()
