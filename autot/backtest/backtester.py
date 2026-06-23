import pandas as pd


def get_value(row, column_name: str) -> float:
    value = row[column_name]

    if isinstance(value, pd.Series):
        value = value.iloc[0]

    return float(value)


def calculate_max_drawdown(equity_curve: list[float]) -> float:
    peak = equity_curve[0]
    max_drawdown = 0.0

    for equity in equity_curve:
        if equity > peak:
            peak = equity

        drawdown = ((equity - peak) / peak) * 100

        if drawdown < max_drawdown:
            max_drawdown = drawdown

    return max_drawdown


def run_backtest(
    data: pd.DataFrame,
    initial_capital: float = 10000,
    trade_amount: float = 1000,
    transaction_cost_percent: float = 0.10,
) -> dict:

    in_position = False
    buy_price = 0.0
    buy_date = None
    trades = []
    capital = initial_capital
    equity_curve = [initial_capital]

    for i in range(1, len(data)):
        previous = data.iloc[i - 1]
        current = data.iloc[i]

        previous_ema20 = get_value(previous, "EMA_20")
        previous_ema50 = get_value(previous, "EMA_50")

        current_ema20 = get_value(current, "EMA_20")
        current_ema50 = get_value(current, "EMA_50")
        current_close = get_value(current, "Close")
        current_rsi = get_value(current, "RSI")

        buy_signal = (
            previous_ema20 <= previous_ema50
            and current_ema20 > current_ema50
            and current_rsi > 50
        )

        sell_signal = (
            previous_ema20 >= previous_ema50
            and current_ema20 < current_ema50
        ) or current_rsi < 45

        if not in_position and buy_signal:
            in_position = True
            buy_price = current_close
            buy_date = data.index[i]

        elif in_position and sell_signal:
            sell_price = current_close
            sell_date = data.index[i]

            gross_profit_percent = ((sell_price - buy_price) / buy_price) * 100
            net_profit_percent = gross_profit_percent - transaction_cost_percent
            profit_money = trade_amount * (net_profit_percent / 100)

            capital += profit_money
            equity_curve.append(capital)

            trades.append({
                "buy_date": buy_date,
                "sell_date": sell_date,
                "buy_price": buy_price,
                "sell_price": sell_price,
                "gross_profit_percent": gross_profit_percent,
                "net_profit_percent": net_profit_percent,
                "profit_money": profit_money,
            })

            in_position = False

    winning_trades = [trade for trade in trades if trade["profit_money"] > 0]
    losing_trades = [trade for trade in trades if trade["profit_money"] <= 0]

    win_rate = 0.0
    if trades:
        win_rate = (len(winning_trades) / len(trades)) * 100

    profit_loss = capital - initial_capital
    return_percent = (profit_loss / initial_capital) * 100
    max_drawdown = calculate_max_drawdown(equity_curve)

    return {
        "initial_capital": initial_capital,
        "final_capital": capital,
        "profit_loss": profit_loss,
        "return_percent": return_percent,
        "max_drawdown": max_drawdown,
        "transaction_cost_percent": transaction_cost_percent,
        "total_trades": len(trades),
        "winning_trades": len(winning_trades),
        "losing_trades": len(losing_trades),
        "win_rate": win_rate,
        "trades": trades,
    }