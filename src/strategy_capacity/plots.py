"""Dark figures with explicit separation between budget-fitting and extrapolated points."""
from __future__ import annotations
import json,os,tempfile
from pathlib import Path
os.environ.setdefault('MPLCONFIGDIR',str(Path(tempfile.gettempdir())/'strategy-capacity-mpl'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import numpy as np
import pandas as pd
from PIL import Image
from strategy_capacity.study import RESULTS

BG,PANEL,GRID='#080F1A','#101D2E','#24344A'
TEXT,MUTED='#F1F5FF','#A4B5CC'
MINT,CORAL,AMBER,BLUE='#2DDDC5','#FF617D','#F4C465','#76A9FF'


def money(x):
    if abs(x)>=1e9:return f'${x/1e9:g}bn'
    return f'${x/1e6:g}m'


def canvas(n,title,subtitle,footer):
    fig=plt.figure(figsize=(9,11.25),dpi=120,facecolor=BG)
    fig.text(.075,.949,f'STRATEGY CAPACITY LAB   /   {n:02d}',color=MINT,fontsize=11,weight='bold')
    fig.text(.075,.865,title,fontsize=30,weight='bold',linespacing=1.18)
    fig.text(.075,.793,subtitle,fontsize=12.5,color=MUTED,linespacing=1.5)
    fig.text(.075,.047,footer,fontsize=9.2,color=MUTED,linespacing=1.5)
    fig.text(.925,.022,'GN25  /  CAPITAL AND EXECUTION',ha='right',fontsize=8,color=MUTED)
    return fig


def style(ax):
    ax.set_facecolor(PANEL);ax.grid(color=GRID,linewidth=.7);ax.set_axisbelow(True)
    for spine in ax.spines.values():spine.set_visible(False)
    ax.tick_params(length=0,pad=7)


def save(fig,name):fig.savefig(RESULTS/'figures'/name,dpi=120,facecolor=BG)


def curves(s,f):
    f=f[(f.eta==s['base_eta'])&(f.capital_usd<=2e9)].sort_values('capital_usd')
    cap=s['participation_threshold_usd'];good=f.capital_usd<=cap*(1+1e-10)
    fig=canvas(1,'More dollars.\nLess room to trade.','Same weekly sector rotation  |  2011 to 2025\nFixed reference AUM, with modeled execution costs.','Solid: every reference order fits the 10% lagged-ADV budget.\nDashed: unchanged full-fill model exceeds the budget. Not executable outcomes.\nRates are arithmetic annualizations, not CAGRs. Cost assumptions are not calibrated.')
    ax=fig.add_axes([.15,.51,.75,.21]);style(ax)
    ax2=fig.add_axes([.15,.25,.75,.19]);style(ax2)
    for a,column,mult in [(ax,'net_annual_rate',100),(ax2,'annual_dollar_pnl',1e-6)]:
        a.set_xscale('log');a.axvline(cap,color=AMBER,linestyle=':',linewidth=1.7)
        a.plot(f.capital_usd,f[column]*mult,color=CORAL,linestyle='--',linewidth=2.1)
        a.plot(f.loc[good,'capital_usd'],f.loc[good,column]*mult,color=MINT,linewidth=3)
        a.set_xlim(1e6,2e9);a.set_xticks([1e6,1e7,1e8,1e9],["$1m","$10m","$100m","$1bn"],fontsize=11)
    ax.set_ylabel('Modeled net rate (%)',fontsize=12);ax.set_ylim(0,11)
    ax2.set_ylabel('Modeled annual P&L ($m)',fontsize=12);ax2.set_xlabel('Reference capital',fontsize=12)
    ax.text(cap*1.12,10,f'Budget threshold\n${cap/1e6:.1f}m',color=AMBER,fontsize=11,va='top')
    fig.text(.075,.174,'A POSITIVE CURVE DOES NOT SET CAPACITY',fontsize=11,color=MUTED,weight='bold')
    fig.text(.075,.12,f'At $1bn: 4.00% modeled net rate, but the largest order is\n{s["capital_cases"][3]["max_adv_fraction"]:.2f} times its trailing average daily dollar volume.',fontsize=12,color=TEXT,linespacing=1.5)
    save(fig,'01_capital_and_pnl.png');plt.close(fig)


def budget(s):
    rows=s['capital_cases'][:4];cap=s['participation_threshold_usd'];b=s['bottleneck']
    fig=canvas(2,'The bottleneck was\none rebalance.',f'{b["symbol"]}  |  {b["date"]}  |  {100*b["trade_weight"]:.2f}% of portfolio value\nTrailing 20-session dollar ADV: ${b["lagged_adv_usd"]/1e6:.1f}m','ADV uses only the previous 20 sessions. Budget fixed at 10% per asset/day order.\nThis is a planning threshold under fixed rules, not measured executable capacity.\nETF creation/redemption and underlying basket liquidity are outside this model.')
    ax=fig.add_axes([.19,.37,.69,.34]);style(ax)
    vals=np.array([x['max_adv_fraction']*100 for x in rows]);ys=np.arange(len(rows))
    ax.barh(ys,vals,color=[MINT if r['fits_participation_budget'] else CORAL for r in rows],height=.52)
    ax.set_xscale('log');ax.set_xlim(.1,500);ax.set_yticks(ys,[money(x['capital_usd']) for x in rows],fontsize=13);ax.invert_yaxis()
    ax.axvline(10,color=AMBER,linestyle='--',linewidth=1.5)
    ax.set_xticks([.1,1,10,100],["0.1%","1%","10%","100%"]);ax.set_xlabel('Largest order / lagged dollar ADV',fontsize=12,labelpad=12)
    for y,v in zip(ys,vals):ax.text(v*1.13,y,f'{v:.2f}%',va='center',fontsize=12,color=TEXT,weight='bold')
    fig.text(.075,.265,'CAPITAL THAT FITS EVERY ORDER',fontsize=11,color=MUTED,weight='bold')
    fig.text(.075,.208,f'${cap/1e6:.1f} million',fontsize=33,color=AMBER,weight='bold')
    fig.text(.075,.13,'5% ADV budget: $21.6m   |   20% budget: $86.6m\nA different order budget produces a different threshold.',fontsize=12,color=MUTED,linespacing=1.5)
    save(fig,'02_liquidity_budget.png');plt.close(fig)


def sensitivity(s,f):
    cap=s['participation_threshold_usd']
    fig=canvas(3,'How much does\nthe cost model matter?','One exposure path. Three assumed impact coefficients.\nDaily volatility and dollar ADV are lagged one session.','Average impact cost per dollar traded = eta x daily volatility x sqrt(order / ADV).\nThese coefficients are sensitivity assumptions, not confidence intervals or fitted values.\nAbove the participation threshold, full-fill returns are infeasible extrapolations.')
    ax=fig.add_axes([.15,.33,.75,.37]);style(ax)
    for eta,color in zip([.25,.5,1.],[BLUE,MINT,CORAL]):
        part=f[(f.eta==eta)&(f.capital_usd<=1e9)].sort_values('capital_usd');good=part.capital_usd<=cap*(1+1e-10)
        ax.plot(part.capital_usd,part.net_annual_rate*100,color=color,linestyle='--',alpha=.7)
        ax.plot(part.loc[good,'capital_usd'],part.loc[good,'net_annual_rate']*100,color=color,linewidth=2.8,label=f'eta = {eta:g}')
    ax.set_xscale('log');ax.set_xlim(1e6,1e9);ax.set_xticks([1e6,1e7,1e8,1e9],["$1m","$10m","$100m","$1bn"])
    ax.axvline(cap,color=AMBER,linestyle=':',linewidth=1.5);ax.axhline(0,color=MUTED,linewidth=.8)
    ax.set_xlabel('Reference capital');ax.set_ylabel('Modeled net annual rate (%)',fontsize=12)
    ax.legend(frameon=False,labelcolor=TEXT,fontsize=11,loc='lower left')
    fig.text(.075,.237,'THE PARTICIPATION THRESHOLD IS A SEPARATE TEST',fontsize=11,color=MUTED,weight='bold')
    fig.text(.075,.16,'Cheaper assumed impact can improve the return curve.\nIt does not make the same order a smaller fraction of ADV.',fontsize=13,color=TEXT,linespacing=1.5)
    save(fig,'03_cost_assumptions.png');plt.close(fig)


def animate(s,f):
    f=f[(f.eta==s['base_eta'])&(f.capital_usd<=1e9)].sort_values('capital_usd');cap=s['participation_threshold_usd']
    fig=canvas(4,'Same strategy.\nA growing order.', 'Historical reference-AUM sizing experiment  |  2011 to 2025\nThe animation changes capital, not the trading rules.','Modeled costs, arithmetic annual averages, no verified fills.\nOrders above the 10% lagged-ADV budget are marked as exceeding the rules.\nThis sensitivity study does not establish a live allocation recommendation.')
    ax=fig.add_axes([.15,.38,.75,.32]);style(ax);ax.set_xscale('log');ax.set_xlim(1e6,1e9);ax.set_ylim(0,11)
    ax.set_xticks([1e6,1e7,1e8,1e9],["$1m","$10m","$100m","$1bn"]);ax.set_ylabel('Modeled net annual rate (%)',fontsize=12);ax.set_xlabel('Reference capital',fontsize=12)
    ax.axvline(cap,color=AMBER,linestyle=':',linewidth=1.4)
    ax.plot(f.capital_usd,f.net_annual_rate*100,color=GRID,linewidth=2)
    line,=ax.plot([],[],color=MINT,linewidth=3);dot,=ax.plot([],[],'o',color=MINT,markersize=7)
    value=fig.text(.075,.26,'',fontsize=31,color=MINT,weight='bold');detail=fig.text(.075,.202,'',fontsize=14,color=MUTED);status=fig.text(.075,.135,'',fontsize=12,color=AMBER)
    frames=[];x=f.capital_usd.to_numpy();y=f.net_annual_rate.to_numpy()*100
    for j in np.linspace(0,len(f)-1,61).astype(int):
        line.set_data(x[:j+1],y[:j+1]);dot.set_data([x[j]],[y[j]])
        good=x[j]<=cap;line.set_color(MINT if good else CORAL);dot.set_color(MINT if good else CORAL)
        value.set_text(f'{money(x[j])}   |   {y[j]:.2f}%')
        part=float(f.iloc[j].max_adv_fraction)*100;detail.set_text(f'Largest reference order: {part:.2f}% of lagged ADV')
        status.set_text('WITHIN THE 10% PLANNING BUDGET' if good else 'EXCEEDS THE 10% PLANNING BUDGET')
        fig.canvas.draw();frames.append(Image.fromarray(np.asarray(fig.canvas.buffer_rgba())[:,:,:3].copy()))
    palette=frames[-1].quantize(colors=128,method=Image.Quantize.MEDIANCUT);ims=[x.quantize(palette=palette,dither=Image.Dither.NONE) for x in frames]
    ims[0].save(RESULTS/'figures/04_capacity_reveal.gif',save_all=True,append_images=ims[1:],duration=[900]+[160]*59+[3000],loop=0,disposal=2,optimize=False)
    import imageio_ffmpeg
    writer=imageio_ffmpeg.write_frames(str(RESULTS/'figures/04_capacity_reveal.mp4'),(1080,1350),fps=10,codec='libx264',quality=8,macro_block_size=2,output_params=['-movflags','+faststart']);writer.send(None)
    for frame in [frames[0]]*9+[z for im in frames[1:-1] for z in [im,im]]+[frames[-1]]*30:writer.send(np.asarray(frame).tobytes())
    writer.close();plt.close(fig)


def render():
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':14,'text.color':TEXT,'axes.labelcolor':MUTED,'xtick.color':MUTED,'ytick.color':MUTED,'text.parse_math':False})
    (RESULTS/'figures').mkdir(parents=True,exist_ok=True)
    s=json.loads((RESULTS/'summary.json').read_text());f=pd.read_csv(RESULTS/'capacity_grid.csv')
    curves(s,f);budget(s);sensitivity(s,f);animate(s,f)
    print('Created 3 dark PNG figures, GIF and MP4',flush=True)
