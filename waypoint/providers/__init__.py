"""Each outside service Waypoint reads from or sends to (Plaid, SimpleFIN, Carta, prices, Finnhub, Realie, push
notifications), plus the modules the bank providers share. Providers don't import each other (the import contracts in pyproject.toml).
"""
