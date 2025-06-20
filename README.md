# Swipe Expenses Tool

This repo contains a simple tool to help categorize bank transactions using a swipe-like interface.

## Requirements
- Python 3.12+
- A web browser

## Usage
1. Export your transactions from HSBC, Wells Fargo or Citibank as a CSV file with columns including `Date`, `Description`, and `Amount`.
2. Convert the CSV to a JSON file using the parser:
   ```bash
   python3 swipe_expenses/parse_transactions.py yourfile.csv -b HSBC -o swipe_expenses/transactions.json
   ```
3. Open `swipe_expenses/index.html` in a browser. Use the buttons or arrow keys to categorize each transaction. Results are displayed at the end of the session.

A sample `transactions.json` is provided for demonstration.
