"""Capacity sensitivity with one frozen exposure path and lagged liquidity inputs."""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd
import requests

ROOT=Path(__file__).resolve().parents[2]
RAW=ROOT/"data/raw"
RESULTS=ROOT/"results"
PROTOCOL=ROOT/"config/protocol.json"


def sha(value):return hashlib.sha256(value if isinstance(value,bytes) else str(value).encode()).hexdigest()
def dump(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,allow_nan=False)+"\n")
def config():return json.loads(PROTOCOL.read_text())


def lock():
    path=RESULTS/"protocol_lock.json";digest=sha(PROTOCOL.read_bytes())
    if path.exists():
        if json.loads(path.read_text())["protocol_sha256"]!=digest:raise ValueError("Protocol changed after lock")
    else:dump(path,{"locked_at_utc":datetime.now(timezone.utc).isoformat(),"protocol_sha256":digest,"results_examined":False})


def fetch():
    lock();RAW.mkdir(parents=True,exist_ok=True);c=config();manifest=[]
    for symbol in c["symbols"]:
        path=RAW/f"{symbol}.json"
        params={"period1":int(pd.Timestamp(c['data_start'],tz="UTC").timestamp()),"period2":int(pd.Timestamp("2026-01-01",tz="UTC").timestamp()),"interval":"1d","events":"div,splits"}
        url=f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
        if not path.exists():
            for attempt in range(3):
                try:
                    r=requests.get(url,params=params,headers={"User-Agent":"Mozilla/5.0"},timeout=45);r.raise_for_status()
                    data=r.json()
                    if not data.get("chart",{}).get("result"):raise ValueError(f"Missing series: {symbol}")
                    dump(path,data);break
                except requests.RequestException:
                    if attempt==2:raise
                    time.sleep(1+attempt)
        manifest.append({"symbol":symbol,"url":url,"parameters":params,"sha256":sha(path.read_bytes())})
        print(f"Verified {symbol}",flush=True)
    dump(RESULTS/"source_manifest.json",{"retrieved_at_utc":datetime.now(timezone.utc).isoformat(),"source":"Yahoo Finance daily chart data","series":manifest})


def load():
    frames=[]
    for s in config()['symbols']:
        d=json.loads((RAW/f"{s}.json").read_text())["chart"]["result"][0]
        dates=pd.to_datetime(d['timestamp'],unit="s",utc=True).tz_convert("America/New_York").tz_localize(None).normalize()
        quote=d['indicators']['quote'][0]
        f=pd.DataFrame({"adjusted":d['indicators']['adjclose'][0]['adjclose'],"close":quote['close'],"volume":quote['volume']},index=dates)
        f=f[~f.index.duplicated()].sort_index()
        if f.isna().any().any() or (f[['adjusted','close','volume']]<=0).any().any():raise ValueError(f"Invalid price/volume rows: {s}")
        f.columns=pd.MultiIndex.from_product([[s],f.columns]);frames.append(f)
    data=pd.concat(frames,axis=1,join="inner").sort_index()
    counts={s:len(json.loads((RAW/f"{s}.json").read_text())["chart"]["result"][0]['timestamp']) for s in config()['symbols']}
    if len(set(counts.values()))!=1 or len(data)!=min(counts.values()):raise ValueError(f"Unaligned trading calendars: {counts}")
    return data


def signal_weights(prices,lookback=126,skip=21,top_n=3):
    momentum=prices.shift(skip)/prices.shift(skip+lookback)-1
    rank=momentum.rank(axis=1,ascending=False,method="first")
    selected=(rank<=top_n)&(momentum>0)
    return selected.astype(float)/top_n


def reference_path(adjusted,c):
    r=adjusted.pct_change(fill_method=None)
    signals=signal_weights(adjusted,c['lookback_sessions'],c['skip_sessions'],c['top_n'])
    week=adjusted.index.to_period("W-SUN")
    signal_dates=adjusted.groupby(week).tail(1).index
    signal_set=set(signal_dates)
    dates=adjusted.index[(adjusted.index>=c['evaluation_start'])&(adjusted.index<=c['evaluation_end'])]
    post=np.zeros(adjusted.shape[1]);records=[];trades=[];weights=[]
    full_index=adjusted.index
    for n,t in enumerate(dates):
        j=full_index.get_loc(t);prev=full_index[j-1]
        today=r.loc[t].to_numpy(float)
        gross=float(np.dot(post,today))
        drift=post*(1+today)/(1+gross)
        rebalance=prev in signal_set or n==0
        if rebalance:
            prior_signals=signal_dates[signal_dates<t]
            if not len(prior_signals):raise ValueError("No signal available before entry")
            target=signals.loc[prior_signals[-1]].to_numpy(float)
        else:target=drift
        delta=np.abs(target-drift)
        records.append({"date":t,"gross_return":gross,"one_way_turnover":float(delta.sum()),"rebalance":rebalance,"signal_date":str(prior_signals[-1].date()) if rebalance else None})
        trades.append(delta);weights.append(target);post=target
    frame=pd.DataFrame(records).set_index('date')
    return frame,pd.DataFrame(trades,index=dates,columns=adjusted.columns),pd.DataFrame(weights,index=dates,columns=adjusted.columns)


def liquidity_inputs(data,c):
    adjusted=data.xs('adjusted',axis=1,level=1)
    dollar_volume=data.xs('close',axis=1,level=1)*data.xs('volume',axis=1,level=1)
    adv=dollar_volume.rolling(c['liquidity_window'],min_periods=c['liquidity_window']).mean().shift(1)
    sigma=adjusted.pct_change(fill_method=None).rolling(c['volatility_window'],min_periods=c['volatility_window']).std(ddof=1).shift(1)
    return adv,sigma


def capacity_threshold(trades,adv,budget):
    with np.errstate(divide='ignore',invalid='ignore'):
        limits=np.where(trades.to_numpy()>1e-12,budget*adv.to_numpy()/trades.to_numpy(),np.inf)
    i,j=np.unravel_index(np.argmin(limits),limits.shape)
    return float(limits[i,j]),{"date":str(trades.index[i].date()),"symbol":str(trades.columns[j]),"trade_weight":float(trades.iloc[i,j]),"lagged_adv_usd":float(adv.iloc[i,j])}


def cost_components(trades,adv,sigma,capital,eta,linear_bps):
    delta=trades.to_numpy();liquidity=adv.to_numpy();vol=sigma.to_numpy()
    participation=capital*delta/liquidity
    impact=(delta*eta*vol*np.sqrt(participation)).sum(axis=1)
    linear=delta.sum(axis=1)*linear_bps/10000
    return linear,impact,participation


def run():
    lock();c=config();data=load();adjusted=data.xs('adjusted',axis=1,level=1)
    path,trades,weights=reference_path(adjusted,c)
    adv,sigma=liquidity_inputs(data,c);adv=adv.loc[path.index];sigma=sigma.loc[path.index]
    if adv.isna().any().any() or sigma.isna().any().any():raise ValueError("Missing lagged risk or liquidity input")
    if (weights.sum(axis=1)>1+1e-10).any() or (weights<0).any().any():raise ValueError("Leverage or short weights in reference path")
    limit,bottleneck=capacity_threshold(trades,adv,c['participation_budget'])
    capital_grid=np.unique(np.r_[np.geomspace(c['capital_min_usd'],c['capital_max_usd'],c['capital_points']),limit])
    rows=[]
    gross_ann=float(path.gross_return.mean()*252)
    for eta in c['impact_eta_sensitivity']:
        for capital in capital_grid:
            linear,impact,part=cost_components(trades,adv,sigma,capital,eta,c['linear_cost_bps_one_way'])
            net=path.gross_return.to_numpy()-linear-impact
            active=part[trades.to_numpy()>1e-12]
            value=float(net.mean()*252)
            rows.append({"capital_usd":float(capital),"eta":eta,"gross_annual_rate":gross_ann,"linear_cost_annual_rate":float(linear.mean()*252),"impact_cost_annual_rate":float(impact.mean()*252),"net_annual_rate":value,"annual_dollar_pnl":float(capital*value),"max_adv_fraction":float(part.max()),"p95_active_order_adv_fraction":float(np.quantile(active,.95)),"orders_over_budget":int((part>c['participation_budget']+1e-12).sum()),"fits_participation_budget":bool(capital<=limit*(1+1e-10))})
    grid=pd.DataFrame(rows);grid.to_csv(RESULTS/"capacity_grid.csv",index=False)
    daily=path.copy()
    for capital in [1e6,1e7,1e8,1e9,1e10]:
        linear,impact,_=cost_components(trades,adv,sigma,capital,c['impact_eta'],c['linear_cost_bps_one_way'])
        daily[f"net_at_{int(capital)}"]=path.gross_return.to_numpy()-linear-impact
    daily.to_csv(RESULTS/"daily_reference.csv")
    trades.to_csv(RESULTS/"order_weights.csv");weights.to_csv(RESULTS/"reference_weights.csv")
    adv.to_csv(RESULTS/"lagged_adv.csv");sigma.to_csv(RESULTS/"lagged_volatility.csv")
    budgets=[]
    for b in c['participation_sensitivity']:
        v,event=capacity_threshold(trades,adv,b)
        budgets.append({"adv_budget":b,"capital_threshold_usd":v,"bottleneck":event})
    sample=[]
    for capital in [1e6,1e7,1e8,1e9,1e10]:
        row=grid[(grid.eta==c['impact_eta'])&np.isclose(grid.capital_usd,capital)].iloc[0].to_dict()
        sample.append({k:(bool(v) if isinstance(v,np.bool_) else int(v) if isinstance(v,np.integer) else float(v) if isinstance(v,np.floating) else v) for k,v in row.items()})
    mean_linear=float(path.one_way_turnover.mean()*c['linear_cost_bps_one_way']/10000*252)
    impact_coefficient=float((trades.to_numpy()*sigma.to_numpy()*np.sqrt(trades.to_numpy()/adv.to_numpy())).sum(axis=1).mean()*252*c['impact_eta'])
    a=gross_ann-mean_linear
    mathematical_zero=(a/impact_coefficient)**2 if a>0 else None
    mathematical_peak=(2*a/(3*impact_coefficient))**2 if a>0 else None
    years=[]
    for year,g in daily.groupby(daily.index.year):
        years.append({"year":int(year),"gross_arithmetic_sum":float(g.gross_return.sum()),"net_at_1m_arithmetic_sum":float(g.net_at_1000000.sum()),"net_at_100m_arithmetic_sum":float(g.net_at_100000000.sum())})
    pd.DataFrame(years).to_csv(RESULTS/"calendar_years.csv",index=False)
    summary={"start":str(path.index.min().date()),"end":str(path.index.max().date()),"sessions":len(path),"rebalance_sessions":int(path.rebalance.sum()),"active_asset_orders":int((trades>1e-12).sum().sum()),"gross_annual_arithmetic_rate":gross_ann,"annual_one_way_turnover":float(path.one_way_turnover.mean()*252),"linear_cost_annual_rate":mean_linear,"base_eta":c['impact_eta'],"adv_budget":c['participation_budget'],"participation_threshold_usd":limit,"bottleneck":bottleneck,"budget_sensitivity":budgets,"capital_cases":sample,"uncapped_model_zero_return_capital_usd":mathematical_zero,"uncapped_model_dollar_pnl_peak_capital_usd":mathematical_peak,"uncapped_peak_fits_budget":bool(mathematical_peak is not None and mathematical_peak<=limit),"interpretation":"Reference-AUM cost sensitivity, arithmetic annualization, not CAGR or a compounded wealth simulation. All curves assume full reference-price rebalances. Points above the participation budget are infeasible extrapolations, not investable outcomes.","limitations":c['limitations'],"protocol_sha256":sha(PROTOCOL.read_bytes())}
    dump(RESULTS/"summary.json",summary)
    print(json.dumps(summary,indent=2),flush=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['fetch','run','plot']);a=p.parse_args();RESULTS.mkdir(parents=True,exist_ok=True)
    if a.command=='fetch':fetch()
    elif a.command=='run':run()
    else:
        from strategy_capacity.plots import render
        render()


if __name__=='__main__':main()
