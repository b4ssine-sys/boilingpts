"""Keltner Channel model with Bollinger-squeeze detection.

Usage:
    pip install yfinance pandas numpy matplotlib lxml
    python keltner_model.py

Outputs one CSV and one PNG per ticker, plus a console readout.

Price data is split/dividend-adjusted at download (auto_adjust=True) so that
corporate actions do not enter ATR or the Bollinger standard deviation as
price shocks. All signal columns are computed causally: nothing on bar t is
derived from data after bar t.
"""

import argparse
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

PAIN_HORIZONS = (5, 10, 30)   # forward drawdown horizons for pain index
REGIME_FAST = 50              # fast EMA for bull/bear regime detection
REGIME_SLOW = 200             # slow EMA for regime detection

BREADTH_WASHOUT_LEVEL = 20.0  # breadth % below which the market is "washed out"

# Verdicts that constitute a valid entry signal.
ENTRY_VERDICTS = {"MOMENTUM OK", "BREADTH DIV OK"}

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


def regime(close: pd.Series) -> pd.Series:
    """BULL when fast EMA > slow EMA, BEAR otherwise."""
    fast = close.ewm(span=REGIME_FAST, adjust=False).mean()
    slow = close.ewm(span=REGIME_SLOW, adjust=False).mean()
    return pd.Series(np.where(fast >= slow, "BULL", "BEAR"), index=close.index)


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


def pain_index(close: pd.Series, open_price: pd.Series) -> pd.DataFrame:
    """Worst unrealized loss over the next N days, measured from next-day open."""
    entry = open_price.shift(-1)
    out = {}
    for h in PAIN_HORIZONS:
        shifts = pd.concat([close.shift(-k) for k in range(1, h + 1)], axis=1)
        out[f"pain_{h}d_pct"] = (shifts.min(axis=1) / entry - 1) * 100
    return pd.DataFrame(out, index=close.index)


def execution_discount(df: pd.DataFrame) -> pd.DataFrame:
    """How much buying at close beats open and typical price on down days."""
    typical = (df["High"] + df["Low"] + df["Close"]) / 3
    out = pd.DataFrame(index=df.index)
    out["exec_vs_open_pct"] = (df["Open"] - df["Close"]) / df["Open"] * 100
    out["exec_vs_typical_pct"] = (typical - df["Close"]) / typical * 100
    return out


# =============================================================================
# MARKET BREADTH
# =============================================================================
def get_sp500_tickers() -> list[str]:
    """Scrape the current S&P 500 tickers from Wikipedia."""
    table = pd.read_html(
        "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    )[0]
    return table["Symbol"].str.replace(".", "-", regex=False).tolist()


def calculate_sp500_breadth(period: str = "2y") -> pd.Series:
    """Daily Series: % of S&P 500 stocks trading above their 50-day SMA."""
    tickers = get_sp500_tickers()
    prices = yf.download(tickers, period=period, auto_adjust=True, progress=False)["Close"]
    if isinstance(prices, pd.Series):
        prices = prices.to_frame()
    ma50 = prices.rolling(window=50).mean()
    above_ma = prices > ma50
    count_above = above_ma.sum(axis=1)
    total_valid = prices.notna().sum(axis=1)
    breadth_pct = (count_above / total_valid) * 100
    return breadth_pct.rename("breadth_50ma")


def breadth_divergence(low: pd.Series, breadth: pd.Series,
                       pivot_bars: int = PIVOT_BARS,
                       lookback: int = DIV_LOOKBACK) -> np.ndarray:
    """True where price makes a lower swing low but breadth makes a higher low.

    Breadth often troughs 1-3 days before the final price low, so we compare
    a 3-bar rolling-min of breadth at each pivot, not the point value.
    """
    confirmed = confirmed_pivot_pos(low, pivot_bars)
    sparse = confirmed.dropna()

    last_pos = confirmed.ffill().to_numpy(dtype=float)
    prev_pos = sparse.shift(1).reindex(confirmed.index).ffill().to_numpy(dtype=float)

    bar = np.arange(len(low), dtype=float)
    valid = ~np.isnan(last_pos) & ~np.isnan(prev_pos) & (prev_pos >= bar - lookback)

    last_i = np.where(valid, last_pos, 0).astype(np.intp)
    prev_i = np.where(valid, prev_pos, 0).astype(np.intp)

    breadth_trough = breadth.rolling(window=3, min_periods=1).min()
    price_v = low.to_numpy(dtype=float)
    breadth_v = breadth_trough.to_numpy(dtype=float)

    lower_low = valid & (price_v[last_i] < price_v[prev_i])
    structural_div = lower_low & (breadth_v[last_i] > breadth_v[prev_i])
    return structural_div


# =============================================================================
# DIVERGENCE AND CLASSIFICATION
# =============================================================================
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
    "blk_breadth": f"breadth > {BREADTH_WASHOUT_LEVEL:.0f}% (not washed out)",
}


def classify_touches(model: pd.DataFrame) -> pd.DataFrame:
    """Gate every lower-band touch on momentum and breadth, in one vectorised pass.

    Adds the individual blocking conditions as columns so the verdict can be
    audited bar by bar, then reduces them to a verdict with np.select.
    """
    div = model["divergence"].to_numpy()
    macd_hist = model["macd_hist"]
    rsi_now = model["rsi"]
    has_breadth = "breadth_50ma" in model.columns

    out = pd.DataFrame(index=model.index)
    out["blk_div"] = div == DIV_DOWN
    out["blk_macd_hist"] = (macd_hist < 0) & (macd_hist < macd_hist.shift(1))
    out["blk_macd_signal"] = model["macd"] < model["macd_signal"]

    if has_breadth:
        out["blk_breadth"] = model["breadth_50ma"] > BREADTH_WASHOUT_LEVEL
    else:
        out["blk_breadth"] = False

    out["blk_rsi"] = (rsi_now < 40) & (rsi_now < rsi_now.shift(1))
    blocks = out[list(BLOCK_LABELS) + ["blk_rsi"]].sum(axis=1).to_numpy()

    # The first bar has no prior bar to compare momentum against.
    scored = model["touch"].to_numpy() & (np.arange(len(model)) > 0)

    b_div = (model["breadth_div"].to_numpy()
             if "breadth_div" in model.columns
             else np.zeros(len(model), dtype=bool))

    verdict = np.select(
        [b_div, (div == DIV_BULLISH) & (blocks <= 1), blocks >= 2],
        ["BREADTH DIV OK", "MOMENTUM OK", "STAND ASIDE"],
        default="MARGINAL",
    )
    out["touch_verdict"] = np.where(scored, verdict, "")
    out["touch_notes"] = touch_notes(out, div, rsi_now.to_numpy(), b_div, scored)
    return out


def touch_notes(flags: pd.DataFrame, div: np.ndarray, rsi_v: np.ndarray,
                b_div: np.ndarray, scored: np.ndarray) -> list[str]:
    """Human-readable reasons, built only for the handful of scored bars."""
    notes = [""] * len(flags)
    columns = {name: flags[name].to_numpy() for name in BLOCK_LABELS}
    blk_rsi = flags["blk_rsi"].to_numpy()

    for i in np.flatnonzero(scored):
        reasons = []
        if b_div[i]:
            reasons.append("structural breadth divergence (constituent lows shrinking)")
        if div[i] == DIV_BULLISH:
            reasons.append("bullish RSI divergence vs prior swing low")
        for name, label in BLOCK_LABELS.items():
            if columns[name][i]:
                reasons.append(label)
        if blk_rsi[i]:
            reasons.append(f"RSI {rsi_v[i]:.0f} and falling")
        notes[i] = "; ".join(reasons)
    return notes


def _fetch_breadth(period: str = WARMUP) -> pd.Series | None:
    """Compute S&P 500 breadth, returning None on failure."""
    try:
        return calculate_sp500_breadth(period=period)
    except Exception as exc:
        print(f"  WARNING: breadth unavailable ({exc}), proceeding without it")
        return None


def build(ticker: str, breadth: pd.Series | None = None) -> pd.DataFrame:
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
    model["open"] = df["Open"]
    # Entry at next-day open; exit at close of t+FWD_DAYS
    model["fwd_ret_pct"] = model["close"].shift(-FWD_DAYS) / model["open"].shift(-1) * 100 - 100

    if breadth is not None:
        model["breadth_50ma"] = breadth
        model["breadth_div"] = breadth_divergence(df["Low"], model["breadth_50ma"])

    # Classify on the full history so divergence has swing lows to pair with
    model = model.join(classify_touches(model))
    model["regime"] = regime(df["Close"])
    model = model.join(pain_index(model["close"], df["Open"]))
    model = model.join(execution_discount(df))

    return model.tail(WINDOW).round(4)


def load_csv(path: str) -> pd.DataFrame:
    """Load OHLCV data from a local CSV file.

    Accepts common column naming conventions (case-insensitive):
    Date, Open, High, Low, Close, Volume.
    """
    df = pd.read_csv(path)
    df.columns = df.columns.str.strip()
    col_map = {}
    for col in df.columns:
        lc = col.lower()
        if lc in ("date", "datetime", "timestamp"):
            col_map[col] = "Date"
        elif lc == "open":
            col_map[col] = "Open"
        elif lc == "high":
            col_map[col] = "High"
        elif lc == "low":
            col_map[col] = "Low"
        elif lc in ("close", "close/last", "adj close", "adj_close", "adjusted close"):
            col_map[col] = "Close"
        elif lc == "volume":
            col_map[col] = "Volume"
    df = df.rename(columns=col_map)
    for required in ("Date", "Open", "High", "Low", "Close"):
        if required not in df.columns:
            raise ValueError(
                f"CSV missing required column '{required}'. "
                f"Found: {list(df.columns)}"
            )
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.set_index("Date").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    for col in ("Open", "High", "Low", "Close", "Volume"):
        if col in df.columns and df[col].dtype == object:
            df[col] = df[col].str.replace(r"[\$,\s]", "", regex=True)
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def build_from_csv(path: str, ticker: str = "CSV",
                   breadth: pd.Series | None = None) -> pd.DataFrame:
    """Build the full model from a local CSV file instead of Yahoo Finance."""
    df = load_csv(path)
    return _build_from_frame(ticker, df, breadth=breadth)


def _format_ratio(v: float) -> str:
    return "inf" if np.isinf(v) else f"{v:.2f}"


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
    if "regime" in model.columns:
        print(f"Regime           {last['regime']}  ({REGIME_FAST}/{REGIME_SLOW} EMA cross)")
    if "breadth_50ma" in model.columns and pd.notna(last.get("breadth_50ma")):
        print(f"S&P 500 breadth  {last['breadth_50ma']:.1f}%  (above 50-day MA)")

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
        print(f"  {date.date()}  pos {pos:.2f}  {verdict:<14}  fwd{FWD_DAYS}d {fwd_txt}")
        if note:
            print(f"                {note}")

    scored = touches.dropna(subset=["fwd_ret_pct"])
    if not scored.empty:
        print(f"\n  Avg fwd{FWD_DAYS}d by verdict:")
        for verdict, group in scored.groupby("touch_verdict"):
            print(f"    {verdict:<14} n={len(group):<3} {group['fwd_ret_pct'].mean():+.2f}%")


TOUCH_COLORS = {
    "BREADTH DIV OK": "dodgerblue",
    "MOMENTUM OK": "green",
    "MARGINAL": "goldenrod",
    "STAND ASIDE": "red",
}


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


def main(csv_path: str | None = None, ticker_override: str | None = None) -> None:
    print("Fetching S&P 500 breadth data...")
    breadth = _fetch_breadth()

    if csv_path:
        ticker = ticker_override or csv_path.rsplit("/", 1)[-1].split(".")[0].upper()
        print(f"Loading data from {csv_path} (ticker: {ticker})...")
        model = build_from_csv(csv_path, ticker=ticker, breadth=breadth)
        model.to_csv(f"{ticker}_keltner.csv")
        readout(ticker, model)
        plot(ticker, model)
        performance_report(model)
    else:
        for ticker in TICKERS:
            model = build(ticker, breadth=breadth)
            model.to_csv(f"{ticker}_keltner.csv")
            readout(ticker, model)
            plot(ticker, model)
    print("\nSaved CSV and PNG per ticker in the working directory.")


# =============================================================================
# BACKTEST EXECUTION
# =============================================================================
def _build_from_frame(ticker: str, df: pd.DataFrame,
                      breadth: pd.Series | None = None) -> pd.DataFrame:
    """Same pipeline as build(), but takes an already-downloaded single-ticker frame."""
    if df.empty:
        raise RuntimeError(f"no price data for {ticker!r}")
    model = keltner(df).join(bollinger(df)).join(macd(df["Close"]))
    model["rsi"] = rsi(df["Close"], RSI_LEN)
    model["divergence"] = divergence(model["close"], model["rsi"], df["Low"])
    model["squeeze"] = (model["bb_upper"] < model["kc_upper"]) & (
        model["bb_lower"] > model["kc_lower"]
    )
    model["touch"] = model["kc_pos"] <= TOUCH_LEVEL
    model["open"] = df["Open"]
    model["fwd_ret_pct"] = model["close"].shift(-FWD_DAYS) / model["open"].shift(-1) * 100 - 100

    if breadth is not None:
        model["breadth_50ma"] = breadth
        model["breadth_div"] = breadth_divergence(df["Low"], model["breadth_50ma"])

    model = model.join(classify_touches(model))
    model["regime"] = regime(df["Close"])
    model = model.join(pain_index(model["close"], df["Open"]))
    model = model.join(execution_discount(df))
    return model


# =============================================================================
# PORTFOLIO ANALYTICS
# =============================================================================
def _strategy_returns(model: pd.DataFrame) -> np.ndarray:
    """Daily return series: open-entry on signal+1, close-to-close thereafter, 0 when idle."""
    close = model["close"].to_numpy()
    open_p = model["open"].to_numpy()
    n = len(model)

    cc_ret = np.zeros(n)
    cc_ret[1:] = close[1:] / close[:-1] - 1

    oc_ret = np.zeros(n)
    oc_ret[1:] = (close[1:] - open_p[1:]) / open_p[1:]

    signals = model["touch_verdict"].isin(ENTRY_VERDICTS).to_numpy()
    active = np.zeros(n, dtype=bool)
    first_day = np.zeros(n, dtype=bool)
    for i in np.flatnonzero(signals):
        entry = i + 1
        end = min(i + FWD_DAYS + 1, n)
        if entry < n and not active[entry]:
            first_day[entry] = True
        active[entry:end] = True

    ret = np.where(first_day, oc_ret, cc_ret)
    return ret * active


def _max_drawdown(equity: np.ndarray) -> float:
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak * 100
    return float(np.nanmin(dd))


def _sharpe(returns: np.ndarray) -> float:
    s = np.std(returns)
    if s == 0:
        return 0.0
    return float(np.mean(returns) / s * np.sqrt(252))


def _sortino(returns: np.ndarray) -> float:
    downside = returns[returns < 0]
    if len(downside) == 0:
        return float("inf") if np.mean(returns) > 0 else 0.0
    ds = np.std(downside)
    if ds == 0:
        return float("inf") if np.mean(returns) > 0 else 0.0
    return float(np.mean(returns) / ds * np.sqrt(252))


def _recovery_factor(equity: np.ndarray) -> float:
    total_ret = (equity[-1] / equity[0] - 1) * 100
    mdd = abs(_max_drawdown(equity))
    return total_ret / mdd if mdd > 0 else float("inf")


def _max_idle_streak(t_model: pd.DataFrame) -> int:
    """Max consecutive sessions in BULL regime without an entry signal."""
    bull = (t_model["regime"] == "BULL").to_numpy()
    sig = t_model["touch_verdict"].isin(ENTRY_VERDICTS).to_numpy()
    idle = bull & ~sig
    if not idle.any():
        return 0
    groups = np.cumsum(~idle)
    return int(pd.Series(idle).groupby(groups).sum().max())


def performance_report(model: pd.DataFrame) -> None:
    """Print execution, risk, and regime analytics for the full backtest."""
    entries = model[model["touch_verdict"].isin(ENTRY_VERDICTS)]
    scored = entries.dropna(subset=["fwd_ret_pct"])

    if scored.empty:
        print("\nNo scored entry signals for analytics.")
        return

    tickers = model.index.get_level_values("Ticker").unique()

    print("\n========================================================")
    print("            PERFORMANCE ANALYTICS")
    print("========================================================")

    # --- Signal Frequency & Distribution ---
    dates = model.index.get_level_values("Date")
    date_range_days = (dates.max() - dates.min()).days
    years = max(date_range_days / 365.25, 0.01)
    n_signals = len(entries)
    signal_dates = entries.index.get_level_values("Date").unique().sort_values()
    avg_gap = float("nan")
    if len(signal_dates) > 1:
        avg_gap = signal_dates.to_series().diff().dt.days.mean()

    print(f"\n--- Signal Frequency & Distribution ---")
    print(f"  Total entry signals:        {n_signals}")
    print(f"  Approx signals/year:        {n_signals / years:.1f}")
    if not np.isnan(avg_gap):
        print(f"  Avg gap between signals:    {avg_gap:.0f} days")
    print(f"  Per-ticker:")
    for ticker in tickers:
        t_entries = entries.xs(ticker, level="Ticker")
        n = len(t_entries)
        by_verdict = t_entries["touch_verdict"].value_counts()
        parts = ", ".join(f"{v}: {c}" for v, c in by_verdict.items())
        print(f"    {ticker}: {n} signals ({n / years:.1f}/yr)  [{parts}]")

    # --- Execution Quality ---
    if "exec_vs_open_pct" in entries.columns:
        avg_vs_open = entries["exec_vs_open_pct"].mean()
        avg_vs_typ = entries["exec_vs_typical_pct"].mean()
        print(f"\n--- Execution Quality (signal days only) ---")
        print(f"  Avg discount vs Open:    {avg_vs_open:+.2f}%  (positive = bought cheaper)")
        print(f"  Avg discount vs Typical: {avg_vs_typ:+.2f}%")

    # --- Consecutive Idle in Bull ---
    print(f"\n--- Consecutive Idle Days (BULL regime, no entry signal) ---")
    for ticker in tickers:
        t_model = model.xs(ticker, level="Ticker")
        streak = _max_idle_streak(t_model)
        print(f"  {ticker}: {streak} consecutive days")

    # --- Risk-Adjusted Returns ---
    print(f"\n--- Risk-Adjusted Returns ({FWD_DAYS}d hold vs buy-and-hold) ---")
    header = (f"  {'Ticker':<7} {'Sharpe':>7} {'Sortino':>8} {'MaxDD':>8} {'Recovery':>9}"
              f"  |  {'BH Shrp':>8} {'BH Sort':>8} {'BH MDD':>8} {'BH Rec':>7}")
    print(header)
    for ticker in tickers:
        t_model = model.xs(ticker, level="Ticker")
        daily_ret = t_model["close"].pct_change().to_numpy()
        daily_ret = np.nan_to_num(daily_ret, nan=0.0)
        strat_ret = _strategy_returns(t_model)

        strat_eq = np.cumprod(1 + strat_ret)
        bh_eq = np.cumprod(1 + daily_ret)

        s_sh = _sharpe(strat_ret)
        s_so = _sortino(strat_ret)
        s_mdd = _max_drawdown(strat_eq)
        s_rec = _recovery_factor(strat_eq)

        b_sh = _sharpe(daily_ret)
        b_so = _sortino(daily_ret)
        b_mdd = _max_drawdown(bh_eq)
        b_rec = _recovery_factor(bh_eq)

        print(f"  {ticker:<7} {_format_ratio(s_sh):>7} {_format_ratio(s_so):>8} {s_mdd:>7.2f}%"
              f" {_format_ratio(s_rec):>9}"
              f"  |  {_format_ratio(b_sh):>8} {_format_ratio(b_so):>8} {b_mdd:>7.2f}%"
              f" {_format_ratio(b_rec):>7}")

    # --- Post-Entry Drawdown (Pain Index) ---
    pain_cols = [f"pain_{h}d_pct" for h in PAIN_HORIZONS if f"pain_{h}d_pct" in scored.columns]
    if pain_cols:
        print(f"\n--- Post-Entry Drawdown / Pain Index (entry signals) ---")
        for col in pain_cols:
            vals = scored[col].dropna()
            if not vals.empty:
                horizon = col.split("_")[1]
                print(f"  Worst {horizon:>3}:  avg {vals.mean():+.2f}%  "
                      f"worst {vals.min():+.2f}%  "
                      f"median {vals.median():+.2f}%")

    # --- Hit Rate by Regime ---
    if "regime" in scored.columns:
        print(f"\n--- Hit Rate by Regime ({REGIME_FAST}/{REGIME_SLOW} EMA cross) ---")
        print(f"  {'Regime':<7} {'Trades':>7} {'Win Rate':>10} {'Avg Ret':>9} {'Avg Pain5d':>11}")
        for reg in ("BULL", "BEAR"):
            group = scored[scored["regime"] == reg]
            if group.empty:
                continue
            wr = (group["fwd_ret_pct"] > 0).mean() * 100
            ar = group["fwd_ret_pct"].mean()
            pain = group["pain_5d_pct"].mean() if "pain_5d_pct" in group.columns else float("nan")
            pain_s = f"{pain:+.2f}%" if not np.isnan(pain) else "n/a"
            print(f"  {reg:<7} {len(group):>7} {wr:>9.1f}% {ar:>+8.2f}% {pain_s:>11}")

    # --- Hit Rate by Verdict ---
    print(f"\n--- Hit Rate by Verdict ---")
    print(f"  {'Verdict':<14} {'Trades':>7} {'Win Rate':>10} {'Avg Ret':>9}")
    for v in sorted(ENTRY_VERDICTS):
        group = scored[scored["touch_verdict"] == v]
        if group.empty:
            continue
        wr = (group["fwd_ret_pct"] > 0).mean() * 100
        ar = group["fwd_ret_pct"].mean()
        print(f"  {v:<14} {len(group):>7} {wr:>9.1f}% {ar:>+8.2f}%")


def run_backtest() -> pd.DataFrame:
    print(f"Downloading data for {len(TICKERS)} tickers...")
    raw_df = yf.download(TICKERS, period=WARMUP, auto_adjust=True, progress=False)

    print("Fetching S&P 500 breadth data...")
    breadth = _fetch_breadth()

    if isinstance(raw_df.columns, pd.MultiIndex):
        ticker_level = raw_df.columns.names.index("Ticker") if "Ticker" in raw_df.columns.names else 1
    else:
        ticker_level = None

    pieces = []
    for ticker in TICKERS:
        if ticker_level is not None:
            df = raw_df.xs(ticker, level=ticker_level, axis=1).dropna(how="all")
        else:
            df = raw_df.copy()
        if df.empty:
            print(f"  WARNING: no data for {ticker}, skipping")
            continue
        model = _build_from_frame(ticker, df, breadth=breadth)
        model["Ticker"] = ticker
        pieces.append(model)

    if not pieces:
        raise RuntimeError("no data returned for any ticker")

    model = pd.concat(pieces)
    model = model.set_index("Ticker", append=True).reorder_levels(["Date", "Ticker"]).sort_index()

    print("\n========================================================")
    print("                 BACKTEST RESULTS")
    print("========================================================")

    entries = model[model["touch_verdict"].isin(ENTRY_VERDICTS)].dropna(subset=["fwd_ret_pct"])

    if len(entries) == 0:
        print("No valid entry signals found in the dataset.")
        return model

    win_rate = (entries["fwd_ret_pct"] > 0).mean() * 100
    avg_return = entries["fwd_ret_pct"].mean()

    print(f"Total Valid Signals:    {len(entries)}")
    print(f"Forward Return Horizon: {FWD_DAYS} days")
    print(f"Overall Win Rate:       {win_rate:.2f}%")
    print(f"Average Expected Return:{avg_return:+.2f}%\n")

    print("--- Breakdown by Ticker ---")
    ticker_stats = entries.groupby("Ticker")["fwd_ret_pct"].agg(
        Trades="count",
        Win_Rate_Pct=lambda x: (x > 0).mean() * 100,
        Avg_Return_Pct="mean",
    )
    print(ticker_stats.round(2))

    performance_report(model)

    return model


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Keltner Channel model")
    parser.add_argument("csv_file", nargs="?", default=None,
                        help="path to a local OHLCV CSV file (bypasses Yahoo Finance)")
    parser.add_argument("--ticker", metavar="NAME",
                        help="ticker label for the CSV data (default: derived from filename)")
    parser.add_argument("--backtest", action="store_true",
                        help="run multi-ticker backtest (uses Yahoo Finance)")
    args = parser.parse_args()

    if args.backtest:
        run_backtest()
    else:
        main(csv_path=args.csv_file, ticker_override=args.ticker)
