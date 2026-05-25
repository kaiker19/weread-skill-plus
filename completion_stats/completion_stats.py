#!/usr/bin/env python3
"""
微信读书读完统计
- 今年读完几本 vs 历史读完几本
- 读完的书单
"""

import json, subprocess, os
from datetime import datetime, timezone, timedelta

CHINA_TZ = timezone(timedelta(hours=8))
SKILL_VERSION = "1.0.3"

def api(key, name, payload=None):
    payload = payload or {}
    payload["api_name"] = name
    payload["skill_version"] = SKILL_VERSION
    body = json.dumps(payload)
    r = subprocess.run(
        ["curl", "-s", "-X", "POST", "https://i.weread.qq.com/api/agent/gateway",
         "-H", f"Authorization: Bearer {key}",
         "-H", "Content-Type: application/json", "-d", body],
        capture_output=True, text=True
    )
    try:
        return json.loads(r.stdout)
    except:
        return {"errcode": -1, "errmsg": r.stdout[:200]}

def get_key():
    with open(os.path.expanduser("~/.openclaw/openclaw.json")) as f:
        return json.load(f)["skills"]["entries"]["weread-skills"]["env"]["WEREAD_API_KEY"]

def fmtDuration(seconds):
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h}小时{m}分钟" if h else f"{m}分钟"

def main():
    key = get_key()
    now = datetime.now(CHINA_TZ)
    year = now.year

    print(f"📚 微信读书读完统计 | {year}年")
    print("=" * 50)

    # 1. 书架里所有书，筛finishReading==1的（已读完）
    print("\n📖 书架中已读完的书...")
    shelf = api(key, "/shelf/sync")
    if shelf.get("errcode"):
        print(f"获取书架失败: {shelf}")
        return

    books = shelf.get("books", [])
    finished = [b for b in books if b.get("finishReading") == 1]
    reading = [b for b in books if b.get("finishReading") != 1]

    print(f"  书架总条目: {len(books)} 本")
    print(f"  其中已读完: {len(finished)} 本")
    print(f"  正在阅读: {len(reading)} 本")

    # 2. 今年读的（readUpdateTime 在今年）
    year_start = datetime(year, 1, 1, 0, 0, 0, tzinfo=CHINA_TZ).timestamp()
    finished_this_year = [
        b for b in finished
        if b.get("readUpdateTime", 0) >= year_start
    ]
    print(f"  今年新增读完: {len(finished_this_year)} 本")

    # 3. 阅读统计：今年 vs 总计
    print("\n📊 阅读时长统计...")

    # 今年
    stat_year = api(key, "/readdata/detail", {"mode": "annually"})
    if stat_year.get("errcode") == 0:
        total_year = stat_year.get("totalReadTime", 0)
        read_days_year = stat_year.get("readDays", 0)
        print(f"  {year}年总阅读时长: {fmtDuration(total_year)}")
        print(f"  有效阅读天数: {read_days_year} 天")
        if stat_year.get("compare") is not None:
            trend = "📈" if stat_year.get("compare", 0) > 0 else "📉"
            print(f"  相比去年: {trend} {abs(stat_year.get('compare', 0))*100:.0f}%")

    # 总计
    stat_all = api(key, "/readdata/detail", {"mode": "overall"})
    if stat_all.get("errcode") == 0:
        total_all = stat_all.get("totalReadTime", 0)
        read_days_all = stat_all.get("readDays", 0)
        print(f"  历史总阅读时长: {fmtDuration(total_all)}")
        print(f"  累计有效阅读天数: {read_days_all} 天")

    # 4. 输出今年读完的书单
    if finished_this_year:
        print(f"\n📗 {year}年读完的书单 ({len(finished_this_year)}本):")
        for b in sorted(finished_this_year, key=lambda x: x.get("readUpdateTime", 0), reverse=True):
            title = b.get("title", "?")
            author = b.get("author", "?")
            upd = b.get("readUpdateTime", 0)
            upd_str = datetime.fromtimestamp(upd, tz=CHINA_TZ).strftime("%Y-%m-%d") if upd else "?"
            print(f"  • {title}")
            print(f"    {author} | 读完于 {upd_str}")
    else:
        print(f"\n📗 {year}年暂无读完记录")

    # 5. 输出历史读完的书单
    if finished:
        print(f"\n📕 历史读完的书单 ({len(finished)}本，按读完时间排序）:")
        for b in sorted(finished, key=lambda x: x.get("readUpdateTime", 0), reverse=True)[:20]:
            title = b.get("title", "?")
            author = b.get("author", "?")
            upd = b.get("readUpdateTime", 0)
            upd_str = datetime.fromtimestamp(upd, tz=CHINA_TZ).strftime("%Y-%m-%d") if upd else "?"
            print(f"  • {title} — {author} | {upd_str}")
        if len(finished) > 20:
            print(f"  ... 还有 {len(finished) - 20} 本未展示")

    print("\n" + "=" * 50)

if __name__ == "__main__":
    main()