import csv
import json
import argparse
from datetime import datetime


def parse_csv(file_path, bank=None):
    # Basic parser that expects header fields: Date, Description, Amount
    transactions = []
    with open(file_path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            date = row.get('Date') or row.get('Transaction Date') or row.get('Posting Date')
            description = row.get('Description') or row.get('Details')
            amount = row.get('Amount') or row.get('Debit') or row.get('Credit')
            try:
                amount = float(amount.replace(',', '')) if amount else 0.0
            except ValueError:
                amount = 0.0
            transactions.append({
                'date': date,
                'description': description,
                'amount': amount,
                'bank': bank,
            })
    return transactions


def main():
    parser = argparse.ArgumentParser(description='Convert bank CSV to transactions JSON')
    parser.add_argument('csv', help='CSV file exported from bank')
    parser.add_argument('-b', '--bank', default='Unknown', help='Bank name')
    parser.add_argument('-o', '--output', default='transactions.json', help='Output JSON file')
    args = parser.parse_args()

    data = parse_csv(args.csv, args.bank)
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

    print(f'Wrote {len(data)} transactions to {args.output}')


if __name__ == '__main__':
    main()
