import argparse
import csv
import os
import re
from datetime import datetime, timedelta
from typing import Tuple, List, Dict

from utils import exchange_rate
from utils.parsing import parse_maybe_price

symbol_lookup = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP"
}

number_pattern = re.compile("^\d+$")


class Transaction:
    def __init__(self, settlement_date: str, transaction_date: str, symbol: str, sedol: str, isin: str, quantity: str,
                 price: str,
                 description: str, reference: str, debit: str, credit: str, running_balance: str):
        self._settlement_date = datetime.strptime(settlement_date, "%d/%m/%Y")
        self.transaction_date = datetime.strptime(transaction_date, "%d/%m/%Y")
        self.symbol = symbol
        self._sedol = sedol
        self._isin = isin
        self.quantity = int(quantity) if number_pattern.match(quantity) else None
        self.quantity_repurchased = int(quantity) if number_pattern.match(quantity) else None
        self._currency = symbol_lookup[running_balance[0]]
        self._price = parse_maybe_price(price)
        self._description = description
        self._reference = reference
        self._debit = parse_maybe_price(debit)
        self._credit = parse_maybe_price(credit)
        self._running_balance = parse_maybe_price(running_balance)
        self.gain_loss_gbp = 0
        self.gain_loss_explanation = ""

    @property
    def type(self):
        if self._description.startswith("Div "):
            return "DIV "
        if self.symbol and self._reference:
            if self._debit > 0:
                return "BUY "
            else:
                return "SELL"
        return "CASH"

    @property
    def balance_change(self) -> float:
        if self._credit > 0:
            return self._credit
        return -self._debit

    @property
    def exchange_rate(self) -> float:
        return exchange_rate.get_exchange_rate(self._currency, self.transaction_date)

    @property
    def balance_change_gbp(self) -> float:
        return self.balance_change / self.exchange_rate

    def __repr__(self):
        return self.__str__()

    def __str__(self) -> str:
        return "\t".join(self.to_csv_record().values())

    def to_csv_record(self) -> Dict[str, str]:
        return {
            "Transaction date": self.transaction_date.strftime("%Y-%m-%d"),
            "Type": self.type,
            "Symbol": self.symbol,
            "Price": self._price.__format__(".2f") if self._price else '',
            "Description": self._description,
            "Quantity": str(self.quantity) if self.quantity else '',
            "Balance Change": str(self.balance_change.__format__(".2f")),
            "Exchange rate": str(self.exchange_rate),
            "Balance Change (GBP)": self.balance_change_gbp.__format__(".2f"),
            "Gain/Loss (GBP)": self.gain_loss_gbp.__format__(".2f") if self.gain_loss_gbp else '',
            "Dividend (GBP)": "" if self.type != "DIV " else self.balance_change_gbp.__format__(".2f"),
            "Gain/Loss sourcing": self.gain_loss_explanation
        }

class Holding:
    def __init__(self, symbol: str):
        self._symbol = symbol
        self.pool_quantity = 0
        self.pool_average_price_gbp = 0
        self.transactions: List[Transaction] = []

    def add_transaction(self, new_transaction: Transaction):
        existing_same_day_transactions = [t for t in self.transactions if t.transaction_date == new_transaction.transaction_date and t.type not in ['DIV ', 'CASH'] and t.type == new_transaction.type]
        if existing_same_day_transactions:
            print(existing_same_day_transactions)
            raise NotImplementedError("I don't do same day trading")

        if new_transaction.type == "BUY ":
            sale_in_last_30_days = [t for t in self.transactions if t.transaction_date >= new_transaction.transaction_date - timedelta(days=30) and t.type == "SELL"]
            if sale_in_last_30_days:
                self.pool_quantity += new_transaction.quantity
                quantity_not_b_and_b = new_transaction.quantity
                i = 0
                while quantity_not_b_and_b > 0 and i < len(sale_in_last_30_days):
                    sale = sale_in_last_30_days[i]
                    b_and_b_shares = min(sale.quantity_repurchased, quantity_not_b_and_b)
                    sale.quantity_repurchased -= b_and_b_shares
                    sale_price = (b_and_b_shares * sale.balance_change_gbp / sale.quantity)
                    repurchase_price = (b_and_b_shares * new_transaction.balance_change_gbp / new_transaction.quantity) # Negative
                    new_transaction.gain_loss_gbp += sale_price + repurchase_price
                    new_transaction.gain_loss_explanation += f"Bought back {b_and_b_shares} for {repurchase_price.__format__('.2f')} that were sold on {sale.transaction_date.strftime('%Y-%m-%d')} for {sale_price.__format__('.2f')}. "
                    if b_and_b_shares == sale.quantity:
                        i += 1
                    quantity_not_b_and_b -= b_and_b_shares
                if quantity_not_b_and_b > 0:
                    self.pool_average_price_gbp = ((self.pool_quantity * self.pool_average_price_gbp) + (-quantity_not_b_and_b * new_transaction.balance_change_gbp / new_transaction.quantity)) / (self.pool_quantity + quantity_not_b_and_b)
                    new_transaction.gain_loss_explanation += f"Added {quantity_not_b_and_b} to the S104 Pool, making the average price {self.pool_average_price_gbp.__format__('.2f')}"
            else:
                self.pool_average_price_gbp = ((self.pool_quantity * self.pool_average_price_gbp) + (-new_transaction.balance_change_gbp)) / (self.pool_quantity + new_transaction.quantity)
                self.pool_quantity += new_transaction.quantity
                new_transaction.gain_loss_explanation += f"Added {new_transaction.quantity} to the S104 Pool, making the average price {self.pool_average_price_gbp.__format__('.2f')}"
        if new_transaction.type == "SELL":
            new_transaction.gain_loss_gbp = new_transaction.balance_change_gbp - (new_transaction.quantity * self.pool_average_price_gbp)
            self.pool_quantity -= new_transaction.quantity
            new_transaction.gain_loss_explanation += f"Sold {new_transaction.quantity} from S104 pool (which now contains {self.pool_quantity})"

        self.transactions.append(new_transaction)

    def print_history(self):
        print()
        for t in self.transactions:
            print("\t".join(t.to_csv_record().values()))



def parse_price(price: str) -> Tuple[float, str]:
    symbol = price[0]
    amount = float(price[1:])
    return amount, symbol_lookup[symbol]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=str, help="Filename to be imported")
    args = parser.parse_args()
    if not os.path.exists(args.path):
        parser.error(f"{args.path} does nto exist")

    with open(args.path) as f:
        reader = csv.reader(f)
        transactions = [Transaction(*r) for r in reader if "Settlement Date" not in r]
        transactions = sorted(transactions, key=lambda x: x.transaction_date)

        holdings = {}

        for t in transactions:
            if t.symbol:
                if t.symbol not in holdings:
                    holdings[t.symbol] = Holding(t.symbol)
                holdings[t.symbol].add_transaction(t)

        for h in holdings.values():
            h.print_history()

        output = args.path.replace(".csv", "-processed.csv")
        print(f"Writing output to {output}")
        with open(output, "w") as out_f:
            writer = csv.DictWriter(out_f, list(holdings.values())[0].transactions[0].to_csv_record().keys())
            for h in holdings.values():
                writer.writeheader()
                for t in h.transactions:
                    writer.writerow(t.to_csv_record())
                writer.writerow({})

        output = args.path.replace(".csv", "-processed-23-24.csv")
        print(f"Writing output to {output}")
        with open(output, "w") as out_f:
            writer = csv.DictWriter(out_f, list(holdings.values())[0].transactions[0].to_csv_record().keys())
            for h in holdings.values():
                relevant_transactions = [
                    t for t in h.transactions
                    if datetime(2023, 4, 6) <= t.transaction_date <= datetime(2024, 4, 5)
                ]
                if not relevant_transactions:
                    continue
                writer.writerow({"Transaction date": f"{h._symbol} has S104 pool of {h.pool_quantity} at {h.pool_average_price_gbp.__format__('.2f')} on {datetime.now().strftime('%Y-%m-%d')}"})
                writer.writeheader()
                for t in relevant_transactions:
                    writer.writerow(t.to_csv_record())
                writer.writerow({})
