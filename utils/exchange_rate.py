import os.path
from datetime import datetime

import requests
import xml.etree.ElementTree as ET

CACHE_LOCATION = "cache/"


def get_exchange_rate(currency: str, on: datetime) -> float:
    if currency == "GBP":
        return 1.0
    rates_on_date = _load_rates_on_date(on)
    return rates_on_date[currency]


def _load_rates_on_date(on: datetime):
    required_file = _rates_filename_for(on)
    if not os.path.exists(f"{CACHE_LOCATION}{required_file}"):
        if on < datetime(2023, 12, 1):
            _cache_rates_from_hmrc(required_file, f"http://www.hmrc.gov.uk/softwaredevelopers/rates/{required_file}")
        else:
            _cache_rates_from_hmrc(required_file, f"https://www.trade-tariff.service.gov.uk/api/v2/exchange_rates/files/{required_file}")
    tree = ET.parse(f"{CACHE_LOCATION}{required_file}")
    root = tree.getroot()
    lookup = {}
    for rate in root:
        lookup[rate.find("currencyCode").text] = float(rate.find("rateNew").text)
    return lookup


def _cache_rates_from_hmrc(filename: str, url: str):
    r = requests.get(url)
    r.raise_for_status()
    if not os.path.exists(CACHE_LOCATION):
        os.mkdir(CACHE_LOCATION)
    with open(f"{CACHE_LOCATION}{filename}", "wb") as f:
        f.write(r.content)


def _rates_filename_for(on: datetime) -> str:
    if on < datetime(2023, 12, 1):
        return f"exrates-monthly-{on.strftime('%m%y')}.XML"
    return f"monthly_xml_{on.year}-{on.month}.xml"
