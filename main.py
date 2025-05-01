# -*- coding: utf-8 -*-
"""
Discord Guild Boss Timer Bot – 完整版
(2025-05-01)
"""
import json, os, re, asyncio, datetime as dt
from typing import Optional, Tuple, Dict, List

import discord
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
import pytz
from dotenv import load_dotenv

# ─────────────────────────────────── 基本設定
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
TIMEZONE = pytz.timezone("Asia/Taipei")
DATA_FILE = "bosses.json"
DATE_FMT = "%m/%d %H:%M"

# ─────────────────────────────────── 資料存取

def load_bosses() -> Dict[str, dict]:
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, ensure_ascii=False, indent=2)
    with open(DATA_FILE, encoding="utf-8") as f:
        return json.load(f)

def save_bosses(data: Dict[str, dict]):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

bosses = load_bosses()

# ─────────────────────────────────── 工具函式

def parse_time(s: str, now: dt.datetime) -> Optional[dt.datetime]:
    """支援 hhmm 或 MMddhhmm，回傳 tz-aware datetime。"""
    if not s:
        return None
    if re.fullmatch(r"\d{4}", s):
        hh, mm = int(s[:2]), int(s[2:])
        t = TIMEZONE.localize(dt.datetime.combine(now.date(), dt.time(hh, mm)))
        if t < now:
            t += dt.timedelta(days=1)
        return t
    if re.fullmatch(r"\d{8}", s):
        M, d, hh, mm = map(int, (s[:2], s[2:4], s[4:6], s[6:]))
        year = now.year + ((M, d) < (now.month, now.day))
        return TIMEZONE.localize(dt.datetime(year, M, d, hh, mm))
    return None


def resolve_boss(key: str) -> Optional[str]:
    k = key.lower()
    for name, d in bosses.items():
        if k == name.lower() or k in [t.lower() for t in d.get("aliases", [])]:
            return name
    return None


def advance_to_future(name: str, now: dt.datetime) -> Tuple[Optional[dt.datetime], int]:
    data = bosses[name]
    nxt_iso = data.get("next_spawn")
    if not nxt_iso:
        return None, 0
    nxt = dt.datetime.fromisoformat(nxt_iso)
    if nxt > now:
        return nxt, 0
    cycle = dt.timedelta(minutes=data["respawn_min"])
    missed = int((now - nxt) // cycle) + 1
    nxt += cycle * missed
    data["next_spawn"] = nxt.isoformat()
    return nxt, missed

# ─────────────────────────────────── Bot 初始化
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="", intents=intents)

aio_sched = AsyncIOScheduler(timezone=TIMEZONE)
aio_sched.start()

# ─────────────────────────────────── 排程提示

def schedule_alert(ch, boss: str, when: dt.datetime):
    alert = when - dt.timedelta(minutes=5)
    if alert < dt.datetime.now(TIMEZONE):
        return
    aio_sched.add_job(
        lambda: asyncio.run_coroutine_threadsafe(ch.send(f"⏰ **{boss}** 5 分鐘後重生！"), bot.loop),
        trigger=DateTrigger(run_date=alert),
        name=f"alert_{boss}_{int(when.timestamp())}"
    )

# ─────────────────────────────────── 事件攔截
@bot.event
aasync def on_message(msg):
    if msg.author.bot:
        return
    await bot.process_commands(msg)

# ─────────────────────────────────── kb
@bot.command(name="kb")
async def kb(ctx, sub: str = None):
    now = dt.datetime.now(TIMEZONE)
    rows: List[Tuple[str, dt.datetime, int]] = []
    changed = False
    for n in bosses:
        nxt, missed = advance_to_future(n, now)
        if nxt:
            rows.append((n, nxt, missed))
            if missed:
                changed = True
    if changed:
        save_bosses(bosses)
    if not rows:
        return await ctx.send("尚未有紀錄")
    rows.sort(key=lambda x: x[1])
    if sub != "all":
        rows = rows[:10]
    lines = ["**接下來重生表**"]
    for n, t, m in rows:
        left = int((t - now).total_seconds() // 60)
        miss_txt = f"（已過 {m} 次）" if m else ""
        lines.append(f"• {t:{DATE_FMT}} ➜ **{n}**（剩 {left} 分）{miss_txt}")
    await ctx.send("\n".join(lines))

# ─────────────────────────────────── k
@bot.command(name="k")
async def k(ctx, key: str, when: str = None):
    name = resolve_boss(key)
    if not name:
        return await ctx.send("查無此王/關鍵字")
    now = dt.datetime.now(TIMEZONE)
    death = parse_time(when, now) if when else now
    if death is None:
        return await ctx.send("時間格式錯誤 hhmm 或 MMddhhmm")
    nxt = death + dt.timedelta(minutes=bosses[name]["respawn_min"])
    bosses[name]["next_spawn"] = nxt.isoformat()
    save_bosses(bosses)
    schedule_alert(ctx.channel, name, nxt)
    await ctx.send(f"已記錄 **{name}**，下次 {nxt:{DATE_FMT}} 重生")

# ─────────────────────────────────── kr
@bot.command(name="kr")
async def kr(ctx, key: str, ts: str):
    name = resolve_boss(key)
    if not name:
        return await ctx.send("查無此王/關鍵字")
    now = dt.datetime.now(TIMEZONE)
    nxt = parse_time(ts, now)
    if nxt is None:
        return await ctx.send("時間格式錯誤 hhmm 或 MMddhhmm")
    bosses[name]["next_spawn"] = nxt.isoformat()
    save_bosses(bosses)
    schedule_alert(ctx.channel, name, nxt)
    await ctx.send(f"已設定 **{name}** 下一次 {nxt:{DATE_FMT}} 重生")

# ─────────────────────────────────── clear
@bot.command(name="clear")
async def clear(ctx, target: str):
    now = dt.datetime.now(TIMEZONE)
    if target == "all":
        for b in bosses.values():
            b["next_spawn"] = None
        save_bosses(bosses)
        return await ctx.send("已清除所有紀錄")
    if target == "lost":
        for b in bosses.values():
            if b.get("next_spawn") and dt.datetime.fromisoformat(b["next_spawn"]) < now:
                b["next_spawn"] = None
        save_bosses(bosses)
        return await ctx.send("已清除過期紀錄")
    name = resolve_boss(target)
    if not name:
        return await ctx.send("查無此王/關鍵字")
    bosses[name]["next_spawn"] = None
    save_bosses(bosses)
    await ctx.send(f"已清除 **{name}** 紀錄")

# ─────────────────────────────────── restart
@bot.command(name="restart", aliases=["!restart"])
async def restart(ctx, ts: str = None):
    now = dt.datetime.now(TIMEZONE)
    base = parse_time(ts, now) if ts else now
    if ts and base is None:
        return await ctx.send("時間格式錯誤 hhmm")
    for n, d in bosses.items():
        nxt = base + dt.timedelta(minutes=d["respawn_min"])
        d["next_spawn"] = nxt.isoformat()
        schedule_alert(ctx.channel, n, nxt)
    save_bosses(bosses)
    await ctx.send("已重設全部王死亡時間")

# ─────────────────────────────────── 管理指令 add / rename / retime / remove / tags
@bot.command(name="add")
async def add(ctx, name: str, cycle: int, *t):
