import discord
from discord.ext import commands, tasks
import json
from datetime import datetime, timedelta

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# 載入王資料
def load_bosses():
    try:
        with open("bosses.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

# 儲存王資料
def save_bosses(data):
    with open("bosses.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

bosses = load_bosses()

# 根據名稱或關鍵字查找王
def resolve_boss(key):
    if key in bosses:
        return key
    for name, info in bosses.items():
        if key in info.get("aliases", []):
            return name
    return None

# 推播任務，每分鐘檢查是否有王要重生
@tasks.loop(minutes=1)
async def boss_notifier():
    now = datetime.now()
    for name, info in bosses.items():
        ns = info.get("next_spawn")
        if ns:
            ns_time = datetime.strptime(ns, "%Y-%m-%d %H:%M")
            if now + timedelta(minutes=5) >= ns_time > now:
                channel = discord.utils.get(bot.get_all_channels(), name="王通知")
                if channel:
                    await channel.send(f"⚔️ **{name}** 將在5分鐘內重生！")

@bot.event
async def on_ready():
    boss_notifier.start()
    print(f"登入為 {bot.user}")

# k [王] [時間] 或 k [王]
@bot.command(name="k")
async def k(ctx, name: str, time: str = None):
    boss_name = resolve_boss(name)
    if not boss_name:
        return await ctx.send("查無此王/關鍵字")

    now = datetime.now()
    if time:
        try:
            dt = datetime.strptime(time, "%H%M")
            death_time = now.replace(hour=dt.hour, minute=dt.minute, second=0, microsecond=0)
            if death_time > now:
                death_time -= timedelta(days=1)
        except ValueError:
            return await ctx.send("時間格式錯誤，請使用 HHMM 格式")
    else:
        death_time = now

    respawn_time = death_time + timedelta(minutes=bosses[boss_name]["respawn_min"])
    bosses[boss_name]["next_spawn"] = respawn_time.strftime("%Y-%m-%d %H:%M")
    save_bosses(bosses)
    await ctx.send(f"已設定 **{boss_name}** 重生時間為 {respawn_time.strftime('%m/%d %H:%M')}")

# kr [王] [重生時間] (HHMM 或 MMddHHMM)
@bot.command(name="kr")
async def kr(ctx, name: str, time: str):
    boss_name = resolve_boss(name)
    if not boss_name:
        return await ctx.send("查無此王/關鍵字")

    try:
        if len(time) == 4:
            dt = datetime.strptime(time, "%H%M")
            next_spawn = datetime.now().replace(hour=dt.hour, minute=dt.minute, second=0, microsecond=0)
            if next_spawn < datetime.now():
                next_spawn += timedelta(days=1)
        elif len(time) == 8:
            next_spawn = datetime.strptime(time, "%m%d%H%M")
            next_spawn = next_spawn.replace(year=datetime.now().year)
        else:
            return await ctx.send("時間格式錯誤，請使用 HHMM 或 MMddHHMM")

        bosses[boss_name]["next_spawn"] = next_spawn.strftime("%Y-%m-%d %H:%M")
        save_bosses(bosses)
        await ctx.send(f"**{boss_name}** 已設定重生時間為 {next_spawn.strftime('%m/%d %H:%M')}")
    except ValueError:
        await ctx.send("時間格式錯誤，請使用 HHMM 或 MMddHHMM")

# kb：列出近10筆重生，kb all：列出全部
@bot.command(name="kb")
async def kb(ctx, mode: str = None):
    now = datetime.now()
    result = []
    for name, info in bosses.items():
        if info.get("next_spawn"):
            ns_time = datetime.strptime(info["next_spawn"], "%Y-%m-%d %H:%M")
            result.append((ns_time, name))
    result.sort()
    if mode != "all":
        result = result[:10]
    if not result:
        return await ctx.send("目前沒有重生資料")
    text = "\n".join([f"{name}：{dt.strftime('%m/%d %H:%M')}" for dt, name in result])
    await ctx.send("📜 重生時間如下：\n" + text)

# add [王] [週期] [關鍵字...]
@bot.command(name="add")
async def add(ctx, name: str, cycle: int, *tags):
    if name in bosses:
        return await ctx.send("已存在同名王")
    bosses[name] = {"respawn_min": int(cycle), "aliases": list(tags), "next_spawn": None}
    save_bosses(bosses)
    await ctx.send(f"已新增 **{name}**，週期 {cycle} 分，關鍵字 {', '.join(tags) if tags else '無'}")

# rename [舊王名] [新王名]
@bot.command(name="rename")
async def rename(ctx, old: str, new: str):
    if new in bosses:
        return await ctx.send("新名稱已存在")
    name = resolve_boss(old)
    if not name:
        return await ctx.send("查無此王/關鍵字")
    bosses[new] = bosses.pop(name)
    save_bosses(bosses)
    await ctx.send(f"已將 **{name}** 更名為 **{new}**")

# retime [王] [新週期]
@bot.command(name="retime")
async def retime(ctx, name: str, cycle: int):
    boss_name = resolve_boss(name)
    if not boss_name:
        return await ctx.send("查無此王/關鍵字")
    bosses[boss_name]["respawn_min"] = int(cycle)
    save_bosses(bosses)
    await ctx.send(f"**{boss_name}** 的重生週期已改為 {cycle} 分鐘")

# remove [王]
@bot.command(name="remove")
async def remove(ctx, name: str):
    boss_name = resolve_boss(name)
    if not boss_name:
        return await ctx.send("查無此王/關鍵字")
    del bosses[boss_name]
    save_bosses(bosses)
    await ctx.send(f"已刪除 **{boss_name}**")

# tags add/remove [王] [關鍵字]
@bot.group(name="tags")
async def tags(ctx):
    if ctx.invoked_subcommand is None:
        await ctx.send("請使用 tags add/remove")

@tags.command(name="add")
async def tags_add(ctx, name: str, tag: str):
    boss_name = resolve_boss(name)
    if not boss_name:
        return await ctx.send("查無此王/關鍵字")
    if tag not in bosses[boss_name]["aliases"]:
        bosses[boss_name]["aliases"].append(tag)
    save_bosses(bosses)
    await ctx.send(f"已為 **{boss_name}** 新增關鍵字：{tag}")

@tags.command(name="remove")
async def tags_remove(ctx, name: str, tag: str):
    boss_name = resolve_boss(name)
    if not boss_name:
        return await ctx.send("查無此王/關鍵字")
    if tag in bosses[boss_name]["aliases"]:
        bosses[boss_name]["aliases"].remove(tag)
    save_bosses(bosses)
    await ctx.send(f"已為 **{boss_name}** 移除關鍵字：{tag}")

# info [王]
@bot.command(name="info")
async def info(ctx, name: str = None):
    if name:
        boss_name = resolve_boss(name)
        if not boss_name:
            return await ctx.send("查無此王/關鍵字")
        info = bosses[boss_name]
        await ctx.send(f"📌 **{boss_name}**：週期 {info['respawn_min']} 分，關鍵字 {', '.join(info['aliases']) if info['aliases'] else '無'}")
    else:
        text = "\n".join([f"{n}：{d['respawn_min']} 分，關鍵字 {', '.join(d['aliases']) if d['aliases'] else '無'}" for n, d in bosses.items()])
        await ctx.send("📌 所有王設定如下：\n" + text)
# clear [王] / clear all / clear lost
@bot.command(name="clear")
async def clear(ctx, target: str):
    if target == "all":
        for name in bosses:
            bosses[name]["next_spawn"] = None
        save_bosses(bosses)
        await ctx.send("已清除所有王的重生時間")
    elif target == "lost":
        now = datetime.now()
        count = 0
        for name, info in bosses.items():
            ns = info.get("next_spawn")
            if ns:
                ns_time = datetime.strptime(ns, "%Y-%m-%d %H:%M")
                if ns_time < now:
                    bosses[name]["next_spawn"] = None
                    count += 1
        save_bosses(bosses)
        await ctx.send(f"已清除 {count} 筆已過期的重生時間")
    else:
        boss_name = resolve_boss(target)
        if not boss_name:
            return await ctx.send("查無此王/關鍵字")
        bosses[boss_name]["next_spawn"] = None
        save_bosses(bosses)
        await ctx.send(f"已清除 **{boss_name}** 的重生時間")

# !restart [時間]
@bot.command(name="restart")
async def restart(ctx, time: str = None):
    now = datetime.now()
    if time:
        try:
            dt = datetime.strptime(time, "%H%M")
            base_time = now.replace(hour=dt.hour, minute=dt.minute, second=0, microsecond=0)
            if base_time > now:
                base_time -= timedelta(days=1)
        except ValueError:
            return await ctx.send("時間格式錯誤，請使用 HHMM")
    else:
        base_time = now

    for name, info in bosses.items():
        respawn = base_time + timedelta(minutes=info["respawn_min"])
        info["next_spawn"] = respawn.strftime("%Y-%m-%d %H:%M")

    save_bosses(bosses)
    await ctx.send(f"所有王已重設為 {base_time.strftime('%H:%M')} 為死亡時間後重新計算")

bot.run('YOUR_BOT_TOKEN')
