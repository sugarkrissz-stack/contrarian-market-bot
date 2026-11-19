import sys, os, tempfile, sqlite3, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import yaml, db, backtest
from signals import signal_engine as se
from signals.signal_engine import *

cfg = yaml.safe_load(open("config.yaml"))
res = []
def check(name, ok, extra=""):
    res.append(ok); print(("PASS " if ok else "FAIL ") + name + (" — " + str(extra) if extra else ""))

# ---------- shock rules ----------
base = {"price_chg_1h_pct":-1.0,"price_chg_4h_pct":-2.0,"price_chg_24h_pct":-3.0,
        "oi_chg_1h_pct":0.3,"oi_chg_4h_pct":0.5,"oi_usd_chg_1h_pct":-0.7,"oi_usd_chg_4h_pct":-5.2}
s = evaluate_market_shock("BTCUSDT", base, {}, {}, {"value":12}, cfg)
check("USD-OI drop caused only by price is NOT a liquidation flush", s is None, s and s.direction)
d = dict(base, oi_chg_4h_pct=-6.0)
s = evaluate_market_shock("BTCUSDT", d, {}, {}, {"value":50}, cfg)
check("real OI-contract drop -6% => LIQUIDATION FLUSH, longs flushed", s and s.direction=="LIQUIDATION FLUSH" and "longs flushed" in s.reason, s and s.reason)
d = dict(base, price_chg_24h_pct=-4.6)
s = evaluate_market_shock("BTCUSDT", d, {}, {}, {"value":12}, cfg)
check("F&G 12 + 24h -4.6% but OI flat is NOT capitulation (only price shock <5% -> none)", s is None, s and s.direction)
d = dict(base, price_chg_24h_pct=-4.6, oi_chg_4h_pct=-3.5)
s = evaluate_market_shock("BTCUSDT", d, {}, {}, {"value":12}, cfg)
check("F&G 12 + 24h -4.6% + OI -3.5% => PANIC CAPITULATION", s and s.direction=="PANIC CAPITULATION", s and s.direction)
d = dict(base, price_chg_1h_pct=4.0, oi_chg_4h_pct=0.2)
s = evaluate_market_shock("BTCUSDT", d, {}, {}, {"value":50}, cfg)
check("pure +4% pump => SHOCK PUMP", s and s.direction=="SHOCK PUMP")

# ---------- crowding label / retail baseline ----------
check("label without baseline stays neutral", crowding_label(2.9)=="Balanced")
check("label long crowd vs baseline", crowding_label(3.1, 2.76)=="Longs Crowded / Squeeze Risk")
check("label short crowd vs baseline", crowding_label(2.4, 2.76)=="Shorts Crowded / Bounce Setup")
check("label normal", crowding_label(2.8, 2.76)=="Balanced")

fund0 = {"funding_rate":0.0,"annualized_apr":0.0,"basis_pct":-0.05,"mark_price":100}
oi0 = {"oi_delta_4h_pct":0.0}
# retail 2.9 vs median 2.76 => not crowded. The old absolute rule (>2.6) + F&G extreme-greed would fire short.
r = score_crypto("ETHUSDT", fund0, oi0, {"retail_ratio":2.9,"whale_ratio":2.8}, {"value":85}, cfg, basis_baseline=-0.05, retail_baseline=2.76)
check("retail 2.9 vs median 2.76 does not count as B (no short on greed alone)", r is None, r and r.conditions_met)
r = score_crypto("ETHUSDT", fund0, oi0, {"retail_ratio":3.15,"whale_ratio":2.8}, {"value":85}, cfg, basis_baseline=-0.05, retail_baseline=2.76)
check("retail 3.15 vs median 2.76 (+0.39) + greed => SHORT", r and r.direction=="SHORT", r and r.conditions_met)
r = score_crypto("ETHUSDT", fund0, oi0, {"retail_ratio":3.15,"whale_ratio":2.8}, {"value":85}, cfg, basis_baseline=-0.05, retail_baseline=None)
check("no retail baseline => retail arm skipped, greed alone no signal", r is None)
fl = dict(fund0, funding_rate=-0.00006, annualized_apr=-6.57)
r = score_crypto("ETHUSDT", fl, oi0, {"retail_ratio":2.7,"whale_ratio":2.7}, {"value":15}, cfg, basis_baseline=-0.05, retail_baseline=2.7)
check("funding -6.6% APR no longer counts as A (threshold back at -8%) => F&G alone => no signal", r is None, r and r.conditions_met)
fl = dict(fund0, funding_rate=-0.0001, annualized_apr=-10.95)
r = score_crypto("ETHUSDT", fl, oi0, {"retail_ratio":2.7,"whale_ratio":2.7}, {"value":15}, cfg, basis_baseline=-0.05, retail_baseline=2.7)
check("funding -10.95% + fear => LONG", r and r.direction=="LONG")

# ---------- shock context + dedupe ----------
long_sig = Signal("crypto","BTCUSDC","LONG",65,["A","C"],{},"[BTC]","Contrarian LONG")
sh = Signal("shock","BTCUSDT","LIQUIDATION FLUSH",90,[],{}, "[BTC]","OI -6%", trigger_type="SHOCK")
n = attach_shock_context([long_sig], [sh])
check("shock context appended to same-asset contrarian alert", n==1 and "Shock context: LIQUIDATION FLUSH" in long_sig.reason)
eth = Signal("crypto","ETHUSDT","LONG",55,["A","C"],{},"[ETH]","x")
check("no context for a different asset", attach_shock_context([eth],[sh])==0 and "Shock" not in eth.reason)
check("mode default is context", shock_mode(cfg)=="context" and shock_mode({"market_shock":{"mode":"bogus"}})=="context")

# ---------- cooldown / caps / flip-flop (temp DB) ----------
tmp = tempfile.mkdtemp(); dbp = os.path.join(tmp,"t.db"); db.init(dbp)
c2 = dict(cfg)
check("empty db: LONG passes", passes_cooldown(Signal("crypto","BTCUSDT","LONG",60,[],{},"b","r"), c2))
db.record_alert("crypto","BTCUSDT","SHORT",55)
check("flip-flop: LONG on BTCUSDC blocked right after SHORT on BTCUSDT", not passes_cooldown(Signal("crypto","BTCUSDC","LONG",60,[],{},"b","r"), c2))
check("other asset unaffected by flip-flop", passes_cooldown(Signal("crypto","ETHUSDT","LONG",60,[],{},"e","r"), c2))
db.record_alert("shock","BTCUSDT","SHOCK DUMP",80)
db.record_alert("crypto","ETHUSDT","LONG",55)   # now 3 alerts in 24h > cap 2
check("global cap (2) shared across sources blocks next alert", not passes_cooldown(Signal("shock","SOLUSDT","SHOCK DUMP",80,[],{},"s","r",trigger_type="SHOCK"), c2))
tmp2 = tempfile.mkdtemp(); db.init(os.path.join(tmp2,"t2.db"))
c3 = dict(cfg, max_alerts_per_day=5)
db.record_alert("shock","BTCUSDT","SHOCK DUMP",80)
check("shock sub-cap (1/24h) blocks a second shock alert on another asset", not passes_cooldown(Signal("shock","ETHUSDT","SHOCK DUMP",80,[],{},"e","r",trigger_type="SHOCK"), c3))
check("shock cooldown blocks sibling BTCUSDC", not passes_cooldown(Signal("shock","BTCUSDC","SHOCK PUMP",80,[],{},"b","r",trigger_type="SHOCK"), dict(c3, market_shock=dict(cfg["market_shock"], max_alerts_per_day=9))))

# ---------- db baselines ----------
tmp3 = tempfile.mkdtemp(); db.init(os.path.join(tmp3,"t3.db"))
from datetime import datetime, timezone, timedelta
now = datetime.now(timezone.utc)
for k in range(30):
    db.insert_ratios({"ts": (now - timedelta(hours=k)).isoformat(timespec="seconds"), "symbol":"ETHUSDT","retail_ratio":2.5+0.01*k,"whale_ratio":2.0})
rb = db.retail_baseline("ETHUSDT", 7, 24)
check("retail baseline median", rb is not None and abs(rb-2.645)<0.01, rb)
check("retail baseline None when thin", db.retail_baseline("ETHUSDT",7,500) is None and db.retail_baseline("NOPE",7,24) is None)

# ---------- backtest maths ----------
def mk(closes, spread=0.5):
    return [(i*3600000, c, c+spread, c-spread, c) for i, c in enumerate(closes)]
cs = mk([100,100,100,95,100,110,110,110])
o = backtest.trade_outcome(cs, 2, 3, "long")   # entry 100, window bars 3..5: lows 94.5.., exit 110
check("long outcome ret +10, adverse 5.5", abs(o["ret"]-10)<1e-9 and abs(o["adverse"]-5.5)<1e-9, o)
o = backtest.trade_outcome(cs, 2, 3, "short")
check("short outcome ret -10, adverse = max high 110.5 => 10.5", abs(o["ret"]+10)<1e-9 and abs(o["adverse"]-10.5)<1e-9, o)
check("horizon beyond data => None", backtest.trade_outcome(cs, 6, 5, "long") is None)
sm = backtest.summarize(cs, [2], 3, "long", [3.0, 6.0])
check("stop 3% hit, 6% not", sm["stop_hit"][3.0]==100 and sm["stop_hit"][6.0]==0 and sm["clean_win"][6.0]==100, sm)
check("dedupe episodes", backtest.dedupe_events([1,2,3,10,11,30],5)==[1,10,30])
dumps, pumps = backtest.shock_events(mk([100]*30+[95]+[95]*3+[101]))
check("shock events detect -5% dump (4h window keeps firing; episodes collapse to one) and later pump", backtest.dedupe_events(dumps,6)==[30] and 34 in pumps, (dumps,pumps))
fe = backtest.setup_then_trigger(mk([10,9,8,9.5,10]), [1,2], 5)
check("setup->trigger: close above prior high after fear", fe==[3,4] or 3 in fe, fe)
# funding mapping: settlement at ft closes bar ft-1h
cs = mk([100]*10); fe_l, fe_s = backtest.funding_events(cs, [(5*3600000, -0.0002), (7*3600000, 0.0004), (8*3600000, 0.0)])
check("funding events map to the bar closing at settlement", fe_l==[4] and fe_s==[6], (fe_l,fe_s))
st = backtest.structure_stop_stats(mk([100,101,103,104,105,106,107,108,109,110]), [1], 5, "long")
check("structure stop stats computed", st and st["n"]==1 and st["stop_hit_pct"]==0, st)

# ---------- fetch pagination with a fake OKX ----------
random.seed(1)
N = 250
allc = [[str((N-1-k)*86400000), "100","101","99","100","1","1","1","1"] for k in range(N)]  # newest first
calls = []
def fake_get(ep, params):
    calls.append(params.get("after"))
    rows = allc
    if params.get("after"):
        rows = [r for r in allc if int(r[0]) < int(params["after"])]
    return {"data": rows[:100]}
got = backtest.fetch_candles("X", "1Dutc", 230, fake_get, sleep=0)
check("candle pagination returns 230 oldest-first, no dups", len(got)==230 and got==sorted(got) and len({c[0] for c in got})==230, (len(got), calls))
fr = [{"fundingTime": str((300-k)*28800000), "fundingRate":"0.0001","realizedRate":"0.0001"} for k in range(150)]
def fake_fund(ep, params):
    rows = fr if not params.get("after") else [r for r in fr if int(r["fundingTime"])<int(params["after"])]
    return {"data": rows[:100]}
fh = backtest.fetch_funding_history("X", 400, fake_fund, sleep=0)
check("funding pagination collects 150", len(fh)==150 and fh==sorted(fh))
def boom(ep, params): raise RuntimeError("nope")
check("OI history failure is swallowed", backtest.fetch_oi_history("X", 100, boom)=={})

# ---------- full report on synthetic random walk ----------
class FakeNet:
    pass
random.seed(7)
px=100; hist=[]
for k in range(2300):
    px*=1+random.gauss(0,0.01); hist.append(px)
def fake_candles(ep, params):
    bar=params["bar"]; step = 86400000 if bar.startswith("1D") else 3600000
    n=len(hist)
    rows=[[str(k*step), str(hist[k]), str(hist[k]*1.004), str(hist[k]*0.996), str(hist[k]), "1","1","1","1"] for k in range(n)][::-1]
    if params.get("after"): rows=[r for r in rows if int(r[0])<int(params["after"])]
    return {"data": rows[:100]}
def fake_all(ep, params):
    if "history-candles" in ep: return fake_candles(ep, params)
    if "funding-rate-history" in ep:
        rows=[{"fundingTime":str(k*8*3600000),"fundingRate":str(random.gauss(-0.00005,0.0001)),"realizedRate":str(random.gauss(-0.00005,0.0001))} for k in range(700,0,-1)]
        if params.get("after"): rows=[r for r in rows if int(r["fundingTime"])<int(params["after"])]
        return {"data": rows[:100]}
    return {"data": []}
fng = {}
for k in range(2300):
    day = datetime.fromtimestamp(k*86400, timezone.utc).strftime("%Y-%m-%d")
    fng[day] = random.choice([10,15,25,50,60,85,90])
parts = backtest.run_daily_fng(fake_all, fng) + backtest.run_hourly(fake_all) + backtest.run_funding(fake_all)
rep = backtest.build_report(parts)
check("report builds with all three sections", "## A." in rep and "## B." in rep and "## C." in rep and "random-day baseline" in rep and "Structure stop" in rep, len(rep))
open(os.environ.get("SP","/tmp")+"/sample_report.md","w").write(rep)
print(f"\n{sum(res)}/{len(res)} passed")
sys.exit(0 if all(res) else 1)
