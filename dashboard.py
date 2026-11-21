from load_holdings import ROOT
from portfolio_dashboard import show_dashboard


if __name__ == "__main__":
    show_dashboard(ROOT / "data" / "portfolio.db")
