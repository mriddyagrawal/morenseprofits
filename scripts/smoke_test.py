"""Phase-0 smoke test. Confirms jugaad-data works end-to-end on this machine.

Fetches one short spot window and one ATM option series for RELIANCE around
the Jan 2024 monthly expiry, prints shapes. Network required. Not a unit test.
"""
from datetime import date

from jugaad_data.nse import derivatives_df, expiry_dates, stock_df


def main() -> None:
    sym = "RELIANCE"

    spot = stock_df(symbol=sym, from_date=date(2024, 1, 2), to_date=date(2024, 1, 10), series="EQ")
    assert not spot.empty, "spot fetch returned empty"
    print(f"[spot] {sym} rows={len(spot)} cols={len(spot.columns)}")

    exps = expiry_dates(date(2024, 1, 1), instrument_type="OPTSTK", symbol=sym, contracts=1)
    assert exps, "no expiries returned"
    exp = exps[0]
    print(f"[expiry] first monthly expiry on/after 2024-01-01 for {sym}: {exp}")

    spot_at_first = float(spot.sort_values("DATE").iloc[0]["CLOSE"])
    atm_strike = round(spot_at_first / 20) * 20  # RELIANCE strikes step in ₹20 around this price
    print(f"[atm] spot≈{spot_at_first:.2f} -> guess ATM strike {atm_strike}")

    opt = derivatives_df(
        symbol=sym,
        from_date=date(2024, 1, 2),
        to_date=exp,
        expiry_date=exp,
        instrument_type="OPTSTK",
        strike_price=atm_strike,
        option_type="CE",
    )
    assert not opt.empty, "options fetch returned empty"
    print(f"[option] {sym} {exp} {atm_strike}CE rows={len(opt)} cols={len(opt.columns)}")
    print(f"[option] sample MARKET LOT values: {sorted(set(opt['MARKET LOT'].tolist()))[:3]}")

    print("OK")


if __name__ == "__main__":
    main()
