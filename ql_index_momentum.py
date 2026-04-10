#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
指数动量信号推送 - GitHub Actions 版
===============================================================
策略：每周五推送6个A股指数过去20个交易日涨幅排名，
     并标注当前应持仓的最强指数。

数据源：东方财富（实时+K线同源，与TongDaXin一致）
推送方式：Bark

环境变量配置（在 GitHub Secrets 中设置）：
    BARK_KEY = 你的 Bark Device Key
"""

import sys, os, json
from datetime import datetime, timedelta
from urllib.request import Request, urlopen

# ============================================================
#  ⚙️ 配置
# ============================================================
BARK_SERVER = os.environ.get("BARK_SERVER", "https://api.day.app")
BARK_KEY    = os.environ.get("BARK_KEY", "")
# ============================================================

# 六大指数
INDICES = [
    ("sh.000300", "沪深300"),
    ("sz.399006", "创业板指"),
    ("sh.000016", "上证50"),
    ("sh.000688", "科创50"),
    ("sz.399330", "深证100"),
    ("sh.000905", "中证500"),
]

# 东方财富代码映射
EM_SECIDS = {
    "sh.000300": "1.000300",
    "sz.399006": "0.399006",
    "sh.000016": "1.000016",
    "sh.000688": "1.000688",
    "sz.399330": "0.399330",
    "sh.000905": "1.000905",
}

LOOKBACK = 20   # 计算N日动量


def is_last_trading_day() -> bool:
    """检查今天是否为本周最后一个交易日（仅周五推送）"""
    tz_env = os.environ.get("TZ", "")
    if "Asia/Shanghai" not in tz_env and "PRC" not in tz_env:
        today = datetime.now() + timedelta(hours=8)
    else:
        today = datetime.now()
    weekday = today.weekday()
    print(f"[DEBUG] 当前北京时间: {today.strftime('%Y-%m-%d %H:%M')} 周{['一','二','三','四','五','六','日'][weekday]}")

    try:
        url = "https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&invt=2&fields=f2,f12&secids=1.000001"
        req = Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"})
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        items = data.get("data", {}).get("diff", [])
        if not items or float(items[0].get("f2", 0)) <= 0:
            print("[INFO] 今天非交易日（无行情）")
            return False
    except Exception as e:
        print(f"[WARN] 交易日检查失败: {e}，默认继续")
        if weekday >= 5:
            return False

    if weekday == 4:
        return True
    print(f"[INFO] 今天是周{['一','二','三','四','五','六','日'][weekday]}，非周五，跳过")
    return False


def fetch_realtime() -> dict:
    """东方财富实时行情"""
    codes_str = ",".join(EM_SECIDS.values())
    url = f"https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&invt=2&fields=f2,f3,f12,f18&secids={codes_str}"
    result = {}
    bs_map = {v.split(".")[1]: k for k, v in EM_SECIDS.items()}
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"})
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for item in data.get("data", {}).get("diff", []):
            code = item.get("f12", "")
            bs_code = bs_map.get(code, "")
            if bs_code:
                result[bs_code] = {
                    "close":      float(item.get("f2", 0)),
                    "prev_close": float(item.get("f18", 0)),
                    "today_chg":  float(item.get("f3", 0)),
                }
        print(f"[INFO] 实时行情: {len(result)} 只成功")
    except Exception as e:
        print(f"[WARN] 东方财富实时接口失败: {e}")
    return result


def fetch_history_em(bs_code: str) -> list:
    """
    东方财富日K线接口，返回 [(date_str, close_float), ...]
    与TongDaXin同源，保证20日动量计算基准一致。
    K线字段：date,open,close,high,low,...
    """
    secid = EM_SECIDS.get(bs_code, "")
    if not secid:
        return []
    # 取足够多的数据（提前2个月）
    url = (
        f"https://push2his.eastmoney.com/api/qt/stock/kline/get"
        f"?secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
        f"&fields2=f51,f52,f53,f54,f55,f56"
        f"&klt=101&fqt=1&beg=20260101&end=20991231"
        f"&smplmt=460&lmt=1000000"
    )
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"})
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        klines = data.get("data", {}).get("klines", [])
        # 解析：date,open,close,high,low,...
        rows = []
        for line in klines:
            parts = line.split(",")
            if len(parts) >= 4:
                rows.append((parts[0], float(parts[2])))
        return rows
    except Exception as e:
        print(f"[WARN] 东方财富K线失败 ({bs_code}): {e}")
        return []


def calc_momentum(hist: list, n: int = 20, realtime_close: float = None) -> float:
    """
    计算N日动量：实时价 / N交易日前收盘 - 1。
    注意：TongDaXin "N日前" 指数从1开始（含今天为1），
    故 Python 数组取 hist[-(n+1)]，即第 n+1 根K线（从后数）。
    """
    if len(hist) < n + 1 or realtime_close is None:
        return None
    # hist[-1]=今天, hist[-2]=昨天, ..., hist[-(n+1)]=n个交易日前（含今天算第1天）
    earlier = hist[-(n + 1)][1]
    if earlier == 0:
        return None
    return round((realtime_close / earlier - 1) * 100, 2)


def emoji_for(ret: float) -> str:
    if ret >=  5: return "🔥🔥🔥"
    if ret >=  3: return "🔥🔥"
    if ret >=  1: return "📈"
    if ret >=  0: return "📊"
    if ret >= -1: return "📉"
    if ret >= -3: return "🔴"
    return "⚠️⚠️"


def send_bark(title: str, body: str):
    from urllib.parse import urlencode, quote
    server = BARK_SERVER.rstrip("/")
    key    = BARK_KEY
    if not key:
        print("BARK_KEY 未设置，跳过推送")
        return
    encoded_title = quote(title, safe="")
    params = urlencode({
        "body":  body[:2000],
        "level": "timeSensitive",
        "icon":  "https://img.icons8.com/ios-filled/100/26e07f/stocks.png",
        "copy":  body[:200],
    })
    url = f"{server}/{key}/{encoded_title}?{params}"
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=10) as r:
            resp = r.read().decode()
        print(f"  Bark 响应: {resp[:100]}")
    except Exception as e:
        print(f"  Bark 推送失败: {e}")


def main():
    print(f"指数动量信号推送  [{datetime.now().strftime('%Y-%m-%d %H:%M')}]")
    print("=" * 52)
    print(f"[DEBUG] BARK_KEY: {'已设置' if BARK_KEY else '未设置'}")

    print("[0/3] 检查是否为本周最后交易日...")
    try:
        is_last = is_last_trading_day()
    except Exception as e:
        print(f"[ERROR] {e}，继续执行")
        is_last = True
    if not is_last:
        sys.exit(0)

    realtime = fetch_realtime()

    print(f"[1/3] 实时: {len(realtime)} 只")
    print(f"[2/3] 计算{LOOKBACK}日动量...")

    results = []
    for bs_code, name in INDICES:
        hist = fetch_history_em(bs_code)
        rt   = realtime.get(bs_code, {})
        realtime_close = rt.get("close")
        today_chg = rt.get("today_chg")
        mom = calc_momentum(hist, LOOKBACK, realtime_close)

        if mom is not None:
            emoji = emoji_for(mom)
            chg_str = f"(今{today_chg:+.1f}%)" if today_chg is not None else ""
            base_date = hist[-(LOOKBACK + 1)][0] if len(hist) >= LOOKBACK + 1 else "?"
            print(f"  {emoji} {name:<5} {mom:+.2f}% {chg_str}  [基准={base_date}]")
            results.append({"name": name, "momentum": mom, "today_chg": today_chg})
        else:
            print(f"  数据不足: {name}")

    if len(results) < 2:
        print("有效数据不足")
        sys.exit(1)

    results.sort(key=lambda x: x["momentum"], reverse=True)

    title = "  ".join(
        f"{'★' if i==0 else ''}{r['name']}{r['momentum']:+.1f}%"
        for i, r in enumerate(results)
    )

    print()
    send_bark(title, "")
    print("完成")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FATAL: {e}")
        import traceback; traceback.print_exc()
        sys.exit(2)
