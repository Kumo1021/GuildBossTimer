import discord
from discord.ext import commands, tasks
import json, os
from datetime import datetime, timedelta
from dotenv import load_dotenv

# 載入 .env
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
NOTIFY_CHANNEL = os.getenv('NOTIFY_CHANNEL', 'boss-notify')
PREFIX = ''  # 無前綴，直接以指令名稱呼叫

# 設定 Intents
intents = discord.Intents.default()
intents.message_content = True  # 允許讀取訊息內容以解析指令

# 建立 Bot
bot = commands.Bot(command_prefix=PREFIX, intents=intents)
DATA_FILE = 'bosses.json'

# 載入與儲存資料
def load_bosses():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump({'bosses': {}}, f, ensure_ascii=False, indent=2)
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    for info in data.get('bosses', {}).values():
        info.setdefault('aliases', [])
        info.setdefault('next_spawn', None)
        info.setdefault('notified', False)
    return data

def save_bosses(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

bosses = load_bosses()

# 輔助：名稱/別名對應
def resolve_boss(key: str):
    key_lower = key.lower()
    for name, info in bosses['bosses'].items():
        if name.lower() == key_lower or key_lower in [a.lower() for a in info['aliases']]:
            return name
    return None

# 解析時間字串：hhmm 或 MMddhhmm
def parse_time_str(ts: str):
    now = datetime.now()
    if len(ts) == 4 and ts.isdigit():
        hour, minute = int(ts[:2]), int(ts[2:])
        return now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    elif len(ts) == 8 and ts.isdigit():
        m, d = int(ts[:2]), int(ts[2:4])
        hh, mi = int(ts[4:6]), int(ts[6:])
        try:
            return datetime(now.year, m, d, hh, mi)
        except ValueError:
            return None
    return None

# 定期檢查重生前 5 分鐘推播
@tasks.loop(minutes=1)
async def check_respawns():
    now = datetime.now()
    for name, info in bosses['bosses'].items():
        ns = info.get('next_spawn')
        if ns and not info.get('notified'):
            spawn_time = datetime.fromisoformat(ns)
            delta = (spawn_time - now).total_seconds()
            if 0 < delta <= 300:
                channel = discord.utils.get(bot.get_all_channels(), name=NOTIFY_CHANNEL)
                if channel:
                    await channel.send(f"Boss **{name}** 即將在 5 分鐘後重生！")
                info['notified'] = True
    save_bosses(bosses)

@bot.event
async def on_ready():
    check_respawns.start()
    print(f'已登入：{bot.user}')

# 忽略未定義指令錯誤
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    raise error

# 列表指令：kb、kb all
@bot.command(name='kb')
async def list_bosses(ctx, opt: str = None):
    now = datetime.now()
    upcoming = []
    for n, info in bosses['bosses'].items():
        ns = info.get('next_spawn')
        if ns:
            dt = datetime.fromisoformat(ns)
            if dt > now:
                upcoming.append((n, dt))
    upcoming.sort(key=lambda x: x[1])
    data = upcoming if opt == 'all' else upcoming[:10]
    if not data:
        return await ctx.send("目前沒有任何即將重生的 Boss。")
    lines = [f"{n}：{dt.strftime('%m/%d %H:%M')}" for n, dt in data]
    await ctx.send("即將重生的 Boss：\n" + "\n".join(lines))

# 設定死亡時間 k [名稱] [hhmm/MMddhhmm]
@bot.command(name='k')
async def set_death(ctx, key: str, time_str: str = None):
    boss = resolve_boss(key)
    if not boss:
        return await ctx.send(f"查無 Boss **{key}**。")
    death = parse_time_str(time_str) if time_str else datetime.now()
    if time_str and not death:
        return await ctx.send("時間格式錯誤，請使用 hhmm 或 MMddhhmm。")
    info = bosses['bosses'][boss]
    spawn = death + timedelta(minutes=info['respawn_min'])
    info['next_spawn'] = spawn.isoformat()
    info['notified'] = False
    save_bosses(bosses)
    await ctx.send(f"已設定 **{boss}** 死亡於 {death.strftime('%m/%d %H:%M')}，下次重生：{spawn.strftime('%m/%d %H:%M')}。")

# 直接指定重生時間 kr [名稱] [hhmm/MMddhhmm]
@bot.command(name='kr')
async def set_respawn(ctx, key: str, time_str: str):
    boss = resolve_boss(key)
    if not boss:
        return await ctx.send(f"查無 Boss **{key}**。")
    dt = parse_time_str(time_str)
    if not dt:
        return await ctx.send("時間格式錯誤，請使用 hhmm 或 MMddhhmm。")
    info = bosses['bosses'][boss]
    info['next_spawn'] = dt.isoformat()
    info['notified'] = False
    save_bosses(bosses)
    await ctx.send(f"已設定 **{boss}** 下次重生於 {dt.strftime('%m/%d %H:%M')}。")

# 清除死亡時間 clear [all/lost/Boss]
@bot.command(name='clear')
async def clear_times(ctx, arg: str):
    now = datetime.now()
    data = bosses['bosses']
    if arg == 'all':
        for info in data.values(): info['next_spawn']=None; info['notified']=False
        save_bosses(bosses)
        return await ctx.send("已清除所有 Boss 的死亡時間。")
    if arg == 'lost':
        cnt = 0
        for info in data.values():
            ns = info.get('next_spawn')
            if ns and datetime.fromisoformat(ns) < now:
                info['next_spawn']=None; info['notified']=False; cnt+=1
        save_bosses(bosses)
        return await ctx.send(f"已清除 {cnt} 個已錯過的死亡時間。")
    boss = resolve_boss(arg)
    if not boss:
        return await ctx.send(f"查無 Boss **{arg}**。")
    data[boss]['next_spawn']=None; data[boss]['notified']=False
    save_bosses(bosses)
    await ctx.send(f"已清除 **{boss}** 的死亡時間。")

# 重設所有 Boss !restart [hhmm]
@bot.command(name='restart', aliases=['!restart'])
async def restart_all(ctx, time_str: str = None):
    now = datetime.now()
    data = bosses['bosses']
    if time_str:
        dt = parse_time_str(time_str)
        if not dt or len(time_str)!=4:
            return await ctx.send("時間格式錯誤，請使用 hhmm。")
        death = dt
    else:
        death = now
    for info in data.values():
        info['next_spawn'] = (death + timedelta(minutes=info['respawn_min'])).isoformat()
        info['notified'] = False
    save_bosses(bosses)
    await ctx.send(f"已將所有 Boss 的死亡時間設定為 {death.strftime('%m/%d %H:%M')}，並計算下次重生。")

# 新增/修改/移除 Boss 指令
@bot.command(name='add')
async def add_boss(ctx, name: str, respawn_min: int, *aliases):
    data = bosses['bosses']
    if name in data:
        return await ctx.send(f"Boss **{name}** 已存在。")
    data[name]={'respawn_min':respawn_min,'aliases':list(aliases),'next_spawn':None,'notified':False}
    save_bosses(bosses)
    await ctx.send(f"已新增 **{name}**，週期 {respawn_min} 分鐘，關鍵字：{', '.join(aliases) if aliases else '無'}。")

@bot.command(name='rename')
async def rename_boss(ctx, old: str, new: str):
    real=resolve_boss(old); data=bosses['bosses']
    if not real: return await ctx.send(f"查無 Boss **{old}**。")
    if new in data: return await ctx.send(f"Boss 名稱 **{new}** 已存在。")
    data[new]=data.pop(real); save_bosses(bosses)
    await ctx.send(f"已將 **{real}** 更名為 **{new}**。")

@bot.command(name='retime')
async def retime_boss(ctx,name:str,respawn_min:int):
    boss=resolve_boss(name)
    if not boss: return await ctx.send(f"查無 Boss **{name్**。")
    bosses['bosses'][boss]['respawn_min']=respawn_min; save_bosses(bosses)
    await ctx.send(f"已修改 **{boss}** 的重生週期為 {respawn_min} 分鐘。")

@bot.command(name='remove')
async def remove
