import discord
import json, re, os, asyncio, datetime as dt
import pytz
from discord.ext import commands, tasks
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from dotenv import load_dotenv

load_dotenv()                 # 本機 .env 讀取
TOKEN = os.getenv("DISCORD_TOKEN")
TIMEZONE = pytz.timezone("Asia/Taipei")

# ──載入王清單──────────────────────────
def load_bosses():
    with open("bosses.json", encoding="utf-8") as f:
        return json.load(f)

def save_bosses(data):
    with open("bosses.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

bosses = load_bosses()

# ──Bot 初始化──────────────────────────
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
scheduler = AsyncIOScheduler(timezone=TIMEZONE)
scheduler.start()

# ──輔助函式───────────────────────────
def schedule_alert(ctx, boss, spawn_time):
    # 5 分鐘前推播
    alert_time = spawn_time - dt.timedelta(minutes=5)
    if alert_time < dt.datetime.now(TIMEZONE):
        return
    scheduler.add_job(
        func=lambda: asyncio.run_coroutine_threadsafe(
            ctx.send(f"⏰ **{boss}** 5 分鐘後重生！"), bot.loop),
        trigger=DateTrigger(run_date=alert_time),
        name=f"alert_{boss}"
    )

def parse_hhmm(s):
    m = re.fullmatch(r"([01]\d|2[0-3])([0-5]\d)", s)
    return f"{m.group(1)}:{m.group(2)}" if m else None

# ──指令：k <王> [HHMM]──────────────────
@bot.command(name="k")
async def killed(ctx, boss: str, time: str = None):
    if boss not in bosses:
        return await ctx.send("查無此王，請確認名稱。")
    base = dt.datetime.now(TIMEZONE)
    if time:
        hhmm = parse_hhmm(time)
        if not hhmm:
            return await ctx.send("時間格式錯誤，請用 4 位數 24 小時制 (例如 2125)。")
        base = TIMEZONE.localize(
            dt.datetime.combine(base.date(), dt.datetime.strptime(hhmm, "%H:%M").time()))
        # 若玩家輸入已是過去時間，代表昨天殺的
        if base > dt.datetime.now(TIMEZONE):
            base -= dt.timedelta(days=1)
    respawn = base + dt.timedelta(minutes=bosses[boss]["respawn_min"])
    bosses[boss]["next_spawn"] = respawn.isoformat()
    save_bosses(bosses)
    schedule_alert(ctx, boss, respawn)
    await ctx.send(f"已記錄 **{boss}**！預計 {respawn:%m/%d %H:%M} 重生。")

# ──指令：!next─────────────────────────
@bot.command(name="next")
async def next_ten(ctx):
    upcoming = []
    for name, data in bosses.items():
        if data["next_spawn"]:
            upcoming.append((name,
                             dt.datetime.fromisoformat(data["next_spawn"])))
    if not upcoming:
        return await ctx.send("尚未記錄任何王的重生時間。")
    upcoming.sort(key=lambda x: x[1])
    msg_lines = [f"**接下來 10 隻王重生表**"]
    for name, t in upcoming[:10]:
        delta = int((t - dt.datetime.now(TIMEZONE)).total_seconds()//60)
        msg_lines.append(f"• {t:%m/%d %H:%M} ➜ **{name}**（剩 {delta} 分）")
    await ctx.send("\n".join(msg_lines))

# ──啟動 Bot────────────────────────────
bot.run(TOKEN)
