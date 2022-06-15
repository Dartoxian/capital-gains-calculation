import re


def parse_maybe_price(price_raw: str) -> float:
    if price_raw.strip() == "":
        return 0
    without_symbol = re.sub(r"[^\d.]", "", price_raw)
    return float(without_symbol)
