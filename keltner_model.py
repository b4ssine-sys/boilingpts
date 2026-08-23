"""Keltner Channel model with Bollinger-squeeze detection.

Usage:
    pip install yfinance pandas matplotlib
    python keltner_model.py

Outputs one CSV and one PNG per ticker, plus a console readout.
"""

import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt

TICKERS = ["VOO", "QQQM"]
WINDOW = 60          # trading days to report
EMA_LEN = 20         # Keltner midline
ATR_LEN = 10         # Keltner band volatility
KC_MULT = 2.0
BB_LEN = 20          # Bollinger, for squeeze detection
BB_MULT = 2.0
WARMUP = "9mo"       # extra history so EMA/ATR are seeded

RSI_LEN = 14
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
PIVOT_BARS = 3       # bars either side that define a swing low
DIV_LOOKBACK = 60    # max bars back when pairing swing lows
TOUCH_LEVEL = 0.15   # kc_pos at or below this counts as a lower-band touch
FWD_DAYS = 10        # forward return horizon for touch validation


def average_true_range(df: pd.DataFrame, length: int) -> pd.Series:
    prior_close = df["Close"].shift(1)
    true_range = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - prior_close).abs(),
            (df["Low"] - prior_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(alpha=1 / length, adjust=False).mean()


def keltner(df: pd.DataFrame) -> pd.DataFrame:
    mid = df["Close"].ewm(span=EMA_LEN, adjust=False).mean()
    atr = average_true_range(df, ATR_LEN)
    out = pd.DataFrame(index=df.index)
    out["close"] = df["Close"]
    out["kc_mid"] = mid
    out["kc_upper"] = mid + KC_MULT * atr
    out["kc_lower"] = mid - KC_MULT * atr
    out["kc_width_pct"] = (out["kc_upper"] - out["kc_lower"]) / mid * 100
    # Position in channel: 0 = at lower band, 1 = at upper band
    out["kc_pos"] = (out["close"] - out["kc_lower"]) / (out["kc_upper"] - out["kc_lower"])
    return out


def bollinger(df: pd.DataFrame) -> pd.DataFrame:
    mid = df["Close"].rolling(BB_LEN).mean()
    sd = df["Close"].rolling(BB_LEN).std(ddof=0)
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


def pivot_lows(low: pd.Series, bars: int) -> pd.Series:
    """True where a bar is the lowest of the `bars` sessions either side of it."""
    window = low.rolling(2 * bars + 1, center=True).min()
    return (low == window) & low.notna()


def divergence_at(price: pd.Series, osc: pd.Series, pivots: pd.Series, end: int) -> str:
    """Compare the two most recent swing lows confirmed on or before bar `end`.

    A pivot at bar p is only knowable at p + PIVOT_BARS, so pivots that would
    still be unconfirmed at `end` are excluded to keep the signal causal.
    """
    confirmed = [
        p for p in range(max(0, end - DIV_LOOKBACK), end + 1)
        if pivots.iloc[p] and p + PIVOT_BARS <= end
    ]
    if len(confirmed) < 2:
        return "none"
    prev, last = confirmed[-2], confirmed[-1]
    if price.iloc[last] >= price.iloc[prev]:
        return "none"
    # Price made a lower low. Did momentum follow it down, or hold up?
    return "bullish" if osc.iloc[last] > osc.iloc[prev] else "confirmed_down"


def classify_touch(model: pd.DataFrame, end: int) -> tuple[str, list[str]]:
    """Gate a lower-band touch on momentum. Returns (verdict, reasons)."""
    row, prior = model.iloc[end], model.iloc[end - 1]
    reasons: list[str] = []
    blocks = 0

    div = divergence_at(model["close"], model["rsi"], model["pivot_low"], end)
    if div == "bullish":
        reasons.append("bullish RSI divergence vs prior swing low")
    elif div == "confirmed_down":
        reasons.append("price and RSI both making lower lows")
        blocks += 1

    if row["macd_hist"] < 0 and row["macd_hist"] < prior["macd_hist"]:
        reasons.append("MACD histogram negative and still falling")
        blocks += 1
    if row["macd"] < row["macd_signal"]:
        reasons.append("MACD below its signal line")
        blocks += 1
    if row["rsi"] < 40 and row["rsi"] < prior["rsi"]:
        reasons.append(f"RSI {row['rsi']:.0f} and falling")
        blocks += 1

    # A real divergent bottom almost always still has MACD under its signal line,
    # so divergence is allowed to outrank one blocking condition but not two.
    if div == "bullish" and blocks <= 1:
        return "MOMENTUM OK", reasons
    if blocks >= 2:
        return "STAND ASIDE", reasons
    return "MARGINAL", reasons


def build(ticker: str) -> pd.DataFrame:
    df = yf.download(ticker, period=WARMUP, auto_adjust=False, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    model = keltner(df).join(bollinger(df)).join(macd(df["Close"]))
    model["rsi"] = rsi(df["Close"], RSI_LEN)
    model["pivot_low"] = pivot_lows(df["Low"], PIVOT_BARS)
    # Squeeze: Bollinger bands compressed inside the Keltner Channel
    model["squeeze"] = (model["bb_upper"] < model["kc_upper"]) & (
        model["bb_lower"] > model["kc_lower"]
    )
    model["touch"] = model["kc_pos"] <= TOUCH_LEVEL
    # Forward return is for validating the gate after the fact, never an input
    model["fwd_ret_pct"] = model["close"].shift(-FWD_DAYS) / model["close"] * 100 - 100

    # Classify on the full history so divergence has swing lows to pair with
    verdicts, notes = [], []
    for i in range(len(model)):
        if i > 0 and model["touch"].iloc[i]:
            verdict, reasons = classify_touch(model, i)
        else:
            verdict, reasons = "", []
        verdicts.append(verdict)
        notes.append("; ".join(reasons))
    model["touch_verdict"] = verdicts
    model["touch_notes"] = notes

    return model.tail(WINDOW).round(4)


def consecutive_true(series: pd.Series) -> int:
    count = 0
    for value in reversed(series.tolist()):
        if not value:
            break
        count += 1
    return count


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
    for date, row in touches.iterrows():
        fwd = row["fwd_ret_pct"]
        fwd_txt = "n/a" if pd.isna(fwd) else f"{fwd:+.2f}%"
        print(f"  {date.date()}  pos {row['kc_pos']:.2f}  {row['touch_verdict']:<12}"
              f"  fwd{FWD_DAYS}d {fwd_txt}")
        if row["touch_notes"]:
            print(f"                {row['touch_notes']}")

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
    ax.plot(model.index, model["kc_lower"], color="crimson", lw=1, ls="--", label="Keltner ±2 ATR")
    ax.fill_between(model.index, model["kc_lower"], model["kc_upper"], color="crimson", alpha=0.06)
    squeeze_days = model.index[model["squeeze"]]
    ax.scatter(squeeze_days, model.loc[squeeze_days, "kc_lower"],
               marker="^", s=28, color="darkorange", label="Squeeze", zorder=5)
    for verdict, color in TOUCH_COLORS.items():
        days = model.index[model["touch_verdict"] == verdict]
        if len(days):
            ax.scatter(days, model.loc[days, "close"], marker="o", s=70,
                       facecolors="none", edgecolors=color, lw=2, label=verdict, zorder=6)
    ax.set_title(f"{ticker} — Keltner ({EMA_LEN} EMA, {ATR_LEN} ATR, {KC_MULT}x) with momentum gate")
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
