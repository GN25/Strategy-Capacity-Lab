import numpy as np
import pandas as pd
import pytest
from strategy_capacity.study import signal_weights,reference_path,liquidity_inputs,cost_components,capacity_threshold


def test_signal_excludes_recent_skipped_returns():
    dates=pd.bdate_range('2020-01-01',periods=15)
    p=pd.DataFrame({'A':np.arange(15)+100.,'B':np.arange(15)*.1+100},index=dates)
    before=signal_weights(p,3,2,1)
    p.iloc[-2:,0]*=100
    after=signal_weights(p,3,2,1)
    assert before.iloc[-1].equals(after.iloc[-1])


def test_future_data_cannot_change_earlier_signals():
    idx=pd.bdate_range('2020-01-01',periods=25)
    p=pd.DataFrame({'A':np.arange(25)+100.,'B':100-np.arange(25)*.1},index=idx)
    a=signal_weights(p,3,1,1)
    p.iloc[18:]=p.iloc[18:]*10
    b=signal_weights(p,3,1,1)
    pd.testing.assert_frame_equal(a.iloc[:18],b.iloc[:18])


def test_negative_momentum_leaves_cash_slots():
    p=pd.DataFrame({'A':[100,90,80,70,60],'B':[100,105,110,115,120]})
    w=signal_weights(p,2,0,2).iloc[-1]
    assert w['A']==0 and w['B']==.5 and w.sum()==.5


def test_trade_date_volume_and_volatility_not_used():
    idx=pd.bdate_range('2020-01-01',periods=8)
    f=pd.DataFrame({('A','adjusted'):np.arange(8)+100.,('A','close'):np.arange(8)+100.,('A','volume'):np.ones(8)*100},index=idx)
    c={'liquidity_window':3,'volatility_window':3}
    a,s=liquidity_inputs(f,c)
    f.iloc[-1]=[10000,10000,10000000]
    b,t=liquidity_inputs(f,c)
    assert a.iloc[-1,0]==b.iloc[-1,0] and s.iloc[-1,0]==t.iloc[-1,0]


def inputs():
    t=pd.DataFrame([[.2,0],[.1,.3]])
    adv=pd.DataFrame(np.full((2,2),1e7));v=pd.DataFrame(np.full((2,2),.02))
    return t,adv,v


def test_impact_scales_with_square_root_capital_and_linear_cost_does_not():
    t,a,v=inputs();l,i,p=cost_components(t,a,v,1e6,.5,5);ll,ii,pp=cost_components(t,a,v,4e6,.5,5)
    assert np.allclose(i*2,ii) and np.allclose(l,ll) and np.allclose(p*4,pp)


def test_zero_orders_have_zero_cost_and_participation():
    t,a,v=inputs();t[:]=0
    l,i,p=cost_components(t,a,v,1e10,.5,5)
    assert not l.any() and not i.any() and not p.any()


def test_capacity_threshold_is_exact_at_worst_order():
    t,a,v=inputs();t.index=pd.to_datetime(['2020-01-01','2020-01-02'])
    cap,event=capacity_threshold(t,a,.1)
    assert cap==pytest.approx(.1*1e7/.3)
    assert (cap*t.to_numpy()/a.to_numpy()).max()==pytest.approx(.1)
    assert (cap*1.01*t.to_numpy()/a.to_numpy()).max()>.1


def test_new_weights_do_not_earn_the_execution_day_return():
    idx=pd.bdate_range('2020-01-01',periods=20)
    prices=pd.DataFrame({'A':np.linspace(100,120,20),'B':np.linspace(100,110,20)},index=idx)
    c={'lookback_sessions':2,'skip_sessions':0,'top_n':1,'evaluation_start':str(idx[10].date()),'evaluation_end':str(idx[-1].date())}
    path,trades,w=reference_path(prices,c)
    assert path.gross_return.iloc[0]==0
    assert trades.iloc[0].sum()==1
    assert (w.sum(axis=1)<=1+1e-12).all()


def test_future_prices_do_not_change_past_holdings():
    idx=pd.bdate_range('2020-01-01',periods=35)
    prices=pd.DataFrame({'A':np.arange(35)+100.,'B':np.arange(35)*.5+100.},index=idx)
    c={'lookback_sessions':3,'skip_sessions':1,'top_n':1,'evaluation_start':str(idx[10].date()),'evaluation_end':str(idx[-1].date())}
    a,t,w=reference_path(prices,c);prices.iloc[25:,0]*=10;b,tt,ww=reference_path(prices,c)
    pd.testing.assert_frame_equal(w[w.index<idx[25]],ww[ww.index<idx[25]])
