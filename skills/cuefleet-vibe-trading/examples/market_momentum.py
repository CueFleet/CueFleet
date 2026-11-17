"""Small example of a CueFleet signal based on two completed candles."""

from decimal import Decimal


def predict(request):
    candles = request["market"]["candles"]
    if len(candles) < 2:
        return "NO_SIGNAL"

    previous, latest = (Decimal(str(candle["close"])) for candle in candles[-2:])
    if previous <= 0 or latest <= 0 or latest == previous:
        return "NO_SIGNAL"
    return "LONG" if latest > previous else "SHORT"
