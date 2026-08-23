"""Keltner Channel model with Bollinger-squeeze detection.

Usage:
    pip install yfinance pandas numpy matplotlib
    python keltner_model.py

Outputs one CSV and one PNG per ticker, plus a console readout.

Price data is split/dividend-adjusted at download (auto_adjust=True) so that
corporate actions do not enter ATR or the Bollinger standard deviation as
price shocks. All signal columns are computed causally: nothing on bar t is
derived from data after bar t.
"""

import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt

TICKERS = ["VOO", "QQQ"]
WINDOW = 60          # trading days to report
EMA_LEN = 20         # Keltner midline
ATR_LEN = 10         # Keltner band volatility
KC_MULT = 2.0
BB_LEN = 20          # Bollinger, for squeeze detection
BB_MULT = 2.0
BB_DDOF = 1          # sample estimator; Bollinger's original spec uses 0
WARMUP = "9mo"       # extra history so EMA/ATR are seeded

RSI_LEN = 14
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
PIVOT_BARS = 3       # bars either side that define a swing low
DIV_LOOKBACK = 60    # max bars back when pairing swing lows
TOUCH_LEVEL = 0.15   # kc_pos at or below this counts as a lower-band touch
FWD_DAYS = 10        # forward return horizon for touch validation

# Optional volatility-regime scaling of the Keltner multiplier. Off by default:
# switching it on changes what kc_pos and TOUCH_LEVEL mean, so touch counts and
# any thresholds calibrated against them have to be re-tuned.
DYNAMIC_KC_MULT = False
VOL_BASELINE_LEN = 100   # bars in the long-run volatility baseline
VOL_DAMPING = 0.5        # 0 = static multiplier, 1 = full vol normalisation
KC_MULT_BOUNDS = (1.5, 3.0)

# Divergence verdict codes, kept as ints so the classifier stays vectorised.
DIV_NONE, DIV_BULLISH, DIV_DOWN = 0, 1, 2


def true_range(df: pd.DataFrame) -> pd.Series:
    """max(H-L, |H-C_prev|, |L-C_prev|), evaluated directly in numpy."""
    high = df["High"].to_numpy(dtype=float)
    low = df["Low"].to_numpy(dtype=float)
    close = df["Close"].to_numpy(dtype=float)
    if len(close) == 0:
        return pd.Series(dtype=float, index=df.index)

    prior_close = np.empty_like(close)
    prior_close[0] = np.nan
    prior_close[1:] = close[:-1]

    tr = np.maximum(
        high - low,
        np.maximum(np.abs(high - prior_close), np.abs(low - prior_close)),
    )
    # First bar has no prior close, so the high-low range is the whole story.
    tr[0] = high[0] - low[0]
    return pd.Series(tr, index=df.index)


def average_true_range(df: pd.DataFrame, length: int) -> pd.Series:
    return true_range(df).ewm(alpha=1 / length, adjust=False).mean()


def keltner_multiplier(atr: pd.Series, close: pd.Series) -> pd.Series | float:
    """Static KC_MULT, or one scaled against a long-run volatility baseline.

    Bands already widen with ATR, so the multiplier only needs to absorb the
    *regime* component: ATR elevated against its own baseline pulls the
    multiplier down, a becalmed tape pushes it up, both damped and clamped.
    A GARCH conditional-variance baseline would be the rigorous version of
    this and needs the `arch` package; the ATR ratio is the cheap stand-in.
    """
    if not DYNAMIC_KC_MULT:
        return KC_MULT
    atr_pct = atr / close
    baseline = atr_pct.rolling(VOL_BASELINE_LEN, min_periods=VOL_BASELINE_LEN // 2).mean()
    ratio = (baseline / atr_pct).replace([np.inf, -np.inf], np.nan)
    mult = KC_MULT * np.power(ratio, VOL_DAMPING)
    return mult.clip(*KC_MULT_BOUNDS).fillna(KC_MULT)


def keltner(df: pd.DataFrame) -> pd.DataFrame:
    mid = df["Close"].ewm(span=EMA_LEN, adjust=False).mean()
    atr = average_true_range(df, ATR_LEN)
    mult = keltner_multiplier(atr, df["Close"])
    out = pd.DataFrame(index=df.index)
    out["close"] = df["Close"]
    out["kc_mid"] = mid
    out["kc_mult"] = mult
    out["kc_upper"] = mid + mult * atr
    out["kc_lower"] = mid - mult * atr
    out["kc_width_pct"] = (out["kc_upper"] - out["kc_lower"]) / mid * 100
    # Position in channel: 0 = at lower band, 1 = at upper band
    out["kc_pos"] = (out["close"] - out["kc_lower"]) / (out["kc_upper"] - out["kc_lower"])
    return out


def bollinger(df: pd.DataFrame) -> pd.DataFrame:
    mid = df["Close"].rolling(BB_LEN).mean()
    sd = df["Close"].rolling(BB_LEN).std(ddof=BB_DDOF)
    out = pd.DataFrame(index=df.index)
    out["bb_upper"] = mid + BB_MULT * sd
    out["bb_lower"] = mid - BB_MULT * sd
    return out


def rsi(close: pd.Series, length: int) -> pd.Series:
    delta = close.diff()
    avg_gain = delta.clip(lower=0).ewm(alpha=1 / length, adjust=False).mean()
    avg_loss = (-delta.clip(upper=0)).ewm(alpha=1 / length, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    return (100 - 100 / (1 + rs)).fillna(100)


def macd(close: pd.Series) -> pd.DataFrame:
    line = (close.ewm(span=MACD_FAST, adjust=False).mean()
            - close.ewm(span=MACD_SLOW, adjust=False).mean())
    signal = line.ewm(span=MACD_SIGNAL, adjust=False).mean()
    return pd.DataFrame({"macd": line, "macd_signal": signal, "macd_hist": line - signal})


def confirmed_pivot_pos(low: pd.Series, bars: int) -> pd.Series:
    """Position of the swing low *confirmed* on each bar, NaN where none is.

    A bar is a swing low when it is the lowest of the `bars` sessions either
    side of it, which cannot be known until `bars` sessions later. The centred
    comparison is therefore shifted forward by `bars` so the series is indexed
    by confirmation bar, not by pivot bar: reading it at bar t can only ever
    surface pivots already visible at t. Callers get the pivot's integer
    position, so no separate causality filter is needed downstream.
    """
    window = low.rolling(2 * bars + 1, center=True).min()
    is_pivot = (low == window) & low.notna()
    position = pd.Series(np.arange(len(low), dtype=float), index=low.index)
    return position.where(is_pivot).shift(bars)


def divergence(price: pd.Series, osc: pd.Series, low: pd.Series) -> np.ndarray:
    """Per-bar RSI-vs-price divergence code against the last two swing lows.

    Vectorised equivalent of walking each bar and pairing its two most recent
    confirmed pivots: forward-filling the confirmed-pivot positions gives the
    latest pivot per bar, and forward-filling those positions shifted by one
    within the sparse pivot series gives the one before it.
    """
    confirmed = confirmed_pivot_pos(low, PIVOT_BARS)
    sparse = confirmed.dropna()

    last_pos = confirmed.ffill().to_numpy(dtype=float)
    prev_pos = (
        sparse.shift(1).reindex(confirmed.index).ffill().to_numpy(dtype=float)
    )

    bar = np.arange(len(price), dtype=float)
    # Both pivots must sit inside the lookback; prev is the older of the two.
    valid = ~np.isnan(last_pos) & ~np.isnan(prev_pos) & (prev_pos >= bar - DIV_LOOKBACK)

    last_i = np.where(valid, last_pos, 0).astype(np.intp)
    prev_i = np.where(valid, prev_pos, 0).astype(np.intp)
    price_v = price.to_numpy(dtype=float)
    osc_v = osc.to_numpy(dtype=float)

    lower_low = valid & (price_v[last_i] < price_v[prev_i])
    # Price made a lower low. Did momentum follow it down, or hold up?
    bullish = lower_low & (osc_v[last_i] > osc_v[prev_i])

    return np.where(bullish, DIV_BULLISH, np.where(lower_low, DIV_DOWN, DIV_NONE))


BLOCK_LABELS = {
    "blk_div": "price and RSI both making lower lows",
    "blk_macd_hist": "MACD histogram negative and still falling",
    "blk_macd_signal": "MACD below its signal line",
}


def classify_touches(model: pd.DataFrame) -> pd.DataFrame:
    """Gate every lower-band touch on momentum, in one vectorised pass.

    Adds the individual blocking conditions as columns so the verdict can be
    audited bar by bar, then reduces them to a verdict with np.select.
    """
    div = model["divergence"].to_numpy()
    macd_hist = model["macd_hist"]
    rsi_now = model["rsi"]

    out = pd.DataFrame(index=model.index)
    out["blk_div"] = div == DIV_DOWN
    out["blk_macd_hist"] = (macd_hist < 0) & (macd_hist < macd_hist.shift(1))
    out["blk_macd_signal"] = model["macd"] < model["macd_signal"]
    out["blk_rsi"] = (rsi_now < 40) & (rsi_now < rsi_now.shift(1))
    blocks = out[list(BLOCK_LABELS) + ["blk_rsi"]].sum(axis=1).to_numpy()

    # The first bar has no prior bar to compare momentum against.
    scored = model["touch"].to_numpy() & (np.arange(len(model)) > 0)

    # A real divergent bottom almost always still has MACD under its signal
    # line, so divergence outranks one blocking condition but not two.
    verdict = np.select(
        [(div == DIV_BULLISH) & (blocks <= 1), blocks >= 2],
        ["MOMENTUM OK", "STAND ASIDE"],
        default="MARGINAL",
    )
    out["touch_verdict"] = np.where(scored, verdict, "")
    out["touch_notes"] = touch_notes(out, div, rsi_now.to_numpy(), scored)
    return out


def touch_notes(flags: pd.DataFrame, div: np.ndarray, rsi_v: np.ndarray,
                scored: np.ndarray) -> list[str]:
    """Human-readable reasons, built only for the handful of scored bars."""
    notes = [""] * len(flags)
    columns = {name: flags[name].to_numpy() for name in BLOCK_LABELS}
    blk_rsi = flags["blk_rsi"].to_numpy()

    for i in np.flatnonzero(scored):
        reasons = []
        if div[i] == DIV_BULLISH:
            reasons.append("bullish RSI divergence vs prior swing low")
        for name, label in BLOCK_LABELS.items():
            if columns[name][i]:
                reasons.append(label)
        if blk_rsi[i]:
            reasons.append(f"RSI {rsi_v[i]:.0f} and falling")
        notes[i] = "; ".join(reasons)
    return notes


def build(ticker: str) -> pd.DataFrame:
    # auto_adjust=True returns split/dividend-adjusted OHLC, so High, Low and
    # Close stay on one consistent basis. Adjusting Close alone would leave ATR
    # mixing adjusted and raw prices.
    df = yf.download(ticker, period=WARMUP, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if df.empty:
        raise RuntimeError(
            f"no price data returned for {ticker!r} — check the symbol and "
            f"network access to Yahoo Finance"
        )

    model = keltner(df).join(bollinger(df)).join(macd(df["Close"]))
    model["rsi"] = rsi(df["Close"], RSI_LEN)
    model["divergence"] = divergence(model["close"], model["rsi"], df["Low"])
    # Squeeze: Bollinger bands compressed inside the Keltner Channel
    model["squeeze"] = (model["bb_upper"] < model["kc_upper"]) & (
        model["bb_lower"] > model["kc_lower"]
    )
    model["touch"] = model["kc_pos"] <= TOUCH_LEVEL
    # Forward return is for validating the gate after the fact, never an input
    model["fwd_ret_pct"] = model["close"].shift(-FWD_DAYS) / model["close"] * 100 - 100

    # Classify on the full history so divergence has swing lows to pair with
    model = model.join(classify_touches(model))

    return model.tail(WINDOW).round(4)


def consecutive_true(series: pd.Series) -> int:
    values = series.to_numpy(dtype=bool)
    falses = np.flatnonzero(~values)
    return len(values) if falses.size == 0 else len(values) - falses[-1] - 1


def readout(ticker: str, model: pd.DataFrame) -> None:
    last = model.iloc[-1]
    width_pctile = (model["kc_width_pct"] < last["kc_width_pct"]).mean() * 100
    mid_slope = last["kc_mid"] - model["kc_mid"].iloc[-11]
    trend = "up" if mid_slope > 0 else "down"

    print(f"\n=== {ticker} — last {len(model)} sessions, through {model.index[-1].date()} ===")
    print(f"Close            {last['close']:.2f}")
    print(f"Upper / Mid / Lo {last['kc_upper']:.2f} / {last['kc_mid']:.2f} / {last['kc_lower']:.2f}")
    print(f"Channel position {last['kc_pos']:.2f}  (0 = lower band, 1 = upper band)")
    print(f"Channel width    {last['kc_width_pct']:.2f}%  ({width_pctile:.0f}th pctile of window)")
    if DYNAMIC_KC_MULT:
        print(f"KC multiplier    {last['kc_mult']:.2f}x  (vol-scaled, static base {KC_MULT}x)")
    print(f"EMA{EMA_LEN} slope (10d) {mid_slope:+.2f}  -> trend {trend}")
    print(f"Squeeze          {'ON' if last['squeeze'] else 'off'}"
          f"  ({consecutive_true(model['squeeze'])} consecutive days)")
    print(f"Closes above mid {int((model['close'] > model['kc_mid']).sum())} / {len(model)}")
    print(f"Upper-band tags  {int((model['close'] > model['kc_upper']).sum())}"
          f" | lower-band tags {int((model['close'] < model['kc_lower']).sum())}")

    hist_dir = "rising" if last["macd_hist"] > model["macd_hist"].iloc[-2] else "falling"
    print(f"RSI({RSI_LEN})          {last['rsi']:.1f}")
    print(f"MACD hist        {last['macd_hist']:+.3f} ({hist_dir}),"
          f" line {'above' if last['macd'] > last['macd_signal'] else 'below'} signal")

    touches = model[model["touch"]]
    if touches.empty:
        print("Lower-band touches: none in window")
        return
    print(f"\nLower-band touches (kc_pos <= {TOUCH_LEVEL}):")
    for date, pos, verdict, fwd, note in zip(
        touches.index,
        touches["kc_pos"].to_numpy(),
        touches["touch_verdict"].to_numpy(),
        touches["fwd_ret_pct"].to_numpy(),
        touches["touch_notes"].to_numpy(),
    ):
        fwd_txt = "n/a" if pd.isna(fwd) else f"{fwd:+.2f}%"
        print(f"  {date.date()}  pos {pos:.2f}  {verdict:<12}  fwd{FWD_DAYS}d {fwd_txt}")
        if note:
            print(f"                {note}")

    scored = touches.dropna(subset=["fwd_ret_pct"])
    if not scored.empty:
        print(f"\n  Avg fwd{FWD_DAYS}d by verdict:")
        for verdict, group in scored.groupby("touch_verdict"):
            print(f"    {verdict:<12} n={len(group):<3} {group['fwd_ret_pct'].mean():+.2f}%")


TOUCH_COLORS = {"MOMENTUM OK": "green", "MARGINAL": "goldenrod", "STAND ASIDE": "red"}


def plot(ticker: str, model: pd.DataFrame) -> None:
    fig, (ax, ax_rsi, ax_macd) = plt.subplots(
        3, 1, figsize=(11, 9), sharex=True, gridspec_kw={"height_ratios": [3, 1, 1]}
    )

    ax.plot(model.index, model["close"], color="black", lw=1.4, label="Close")
    ax.plot(model.index, model["kc_mid"], color="steelblue", lw=1, label=f"EMA{EMA_LEN}")
    ax.plot(model.index, model["kc_upper"], color="crimson", lw=1, ls="--")
    band_label = "Keltner (vol-scaled)" if DYNAMIC_KC_MULT else f"Keltner ±{KC_MULT:g} ATR"
    ax.plot(model.index, model["kc_lower"], color="crimson", lw=1, ls="--", label=band_label)
    ax.fill_between(model.index, model["kc_lower"], model["kc_upper"], color="crimson", alpha=0.06)
    squeeze_days = model.index[model["squeeze"]]
    ax.scatter(squeeze_days, model.loc[squeeze_days, "kc_lower"],
               marker="^", s=28, color="darkorange", label="Squeeze", zorder=5)
    for verdict, color in TOUCH_COLORS.items():
        days = model.index[model["touch_verdict"] == verdict]
        if len(days):
            ax.scatter(days, model.loc[days, "close"], marker="o", s=70,
                       facecolors="none", edgecolors=color, lw=2, label=verdict, zorder=6)
    ax.set_title(f"{ticker} — Keltner ({EMA_LEN} EMA, {ATR_LEN} ATR) with momentum gate")
    ax.legend(loc="upper left", fontsize=8, ncol=2)
    ax.grid(alpha=0.25)

    ax_rsi.plot(model.index, model["rsi"], color="purple", lw=1.1)
    ax_rsi.axhline(70, color="grey", ls=":", lw=0.8)
    ax_rsi.axhline(50, color="grey", ls="-", lw=0.6)
    ax_rsi.axhline(30, color="grey", ls=":", lw=0.8)
    ax_rsi.set_ylim(0, 100)
    ax_rsi.set_ylabel(f"RSI({RSI_LEN})", fontsize=8)
    ax_rsi.grid(alpha=0.25)

    hist = model["macd_hist"]
    ax_macd.bar(model.index, hist, color=["seagreen" if v >= 0 else "indianred" for v in hist])
    ax_macd.axhline(0, color="black", lw=0.7)
    ax_macd.set_ylabel("MACD hist", fontsize=8)
    ax_macd.grid(alpha=0.25)

    fig.tight_layout()
    fig.savefig(f"{ticker}_keltner.png", dpi=140)
    plt.close(fig)


def main() -> None:
    for ticker in TICKERS:
        model = build(ticker)
        model.to_csv(f"{ticker}_keltner.csv")
        readout(ticker, model)
        plot(ticker, model)
    print("\nSaved CSV and PNG per ticker in the working directory.")


if __name__ == "__main__":
    main()
