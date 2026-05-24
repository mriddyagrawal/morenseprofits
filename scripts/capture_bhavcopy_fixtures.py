"""Capture byte-for-byte F&O bhavcopy fixtures for one pre-Jul-8-2024 date
and one ≥Jul-8-2024 date. Saves to tests/fixtures/.

The capture-phase findings (recorded as a comment so future readers don't
re-derive them):

  - **Pre-Jul-8-2024**: `jugaad_data.nse.archives.NSEArchives.bhavcopy_fo_raw`
    works — it fetches the legacy ZIP at
    /content/historical/DERIVATIVES/{yyyy}/{MMM}/fo{dd}{MMM}{yyyy}bhav.csv.zip
    and returns the unwrapped CSV. Schema:
        INSTRUMENT,SYMBOL,EXPIRY_DT,STRIKE_PR,OPTION_TYP,OPEN,HIGH,LOW,
        CLOSE,SETTLE_PR,CONTRACTS,VAL_INLAKH,OPEN_INT,CHG_IN_OI,TIMESTAMP

  - **Post-Jul-8-2024**: legacy endpoint returns HTML (jugaad raises
    BadZipFile). The new UDiff F&O bhavcopy lives at
    https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{YYYYMMDD}_F_0000.csv.zip
    — verified by direct GET on 2024-07-08, 2024-07-25, 2024-08-29, 2024-10-25
    (all 200 OK with valid ZIP). The `NSEDailyReports` API exposes this as
    `FO-UDIFF-BHAVCOPY-CSV` BUT only for CurrentDay/PreviousDay; historical
    dates must use direct URL construction. UDiff schema is completely
    different from legacy:
        TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,
        XpryDt,FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,
        HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,
        OpnIntrst,ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,
        SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4
    FinInstrmTp values: STO (stock option), IDO (index option),
    STF (stock future), IDF (index future).

Run once; outputs are committed to git for the test suite to use offline.
"""
from __future__ import annotations

import io
import sys
import zipfile
from datetime import date
from pathlib import Path

import requests

from jugaad_data.nse.archives import NSEArchives

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "tests" / "fixtures"
OUT.mkdir(parents=True, exist_ok=True)

# Pre-Jul-8 candidate: 2024-01-25 (RELIANCE Jan monthly expiry; active F&O day)
# Post-Jul-8 candidate: 2024-08-29 (RELIANCE Aug monthly expiry; active F&O day)
PRE_CUTOVER = date(2024, 1, 25)
POST_CUTOVER = date(2024, 8, 29)
UDIFF_URL_TPL = "https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{ymd}_F_0000.csv.zip"
NSE_HEADERS = {
    "user-agent": "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/134.0.6998.166 Safari/537.36",
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def report(label: str, fn) -> str | None:
    sys.stderr.write(f"\n=== {label} ===\n")
    try:
        content = fn()
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"FAIL: {type(e).__name__}: {e}\n")
        return None
    if not content:
        sys.stderr.write("FAIL: empty content\n")
        return None
    text = content if isinstance(content, str) else content.decode("utf-8", errors="replace")
    sys.stderr.write(f"OK: {len(text)} bytes\n")
    sys.stderr.write(f"--- first 300 chars ---\n{text[:300]}\n")
    sys.stderr.write(f"--- last 200 chars ---\n{text[-200:]}\n")
    return text


def fetch_legacy(arc: NSEArchives, dt: date) -> str:
    return arc.bhavcopy_fo_raw(dt)


def fetch_udiff_direct(dt: date) -> str:
    """Construct the UDiff archive URL directly and pull the inner CSV.
    The NSEDailyReports API only exposes today/yesterday — for historical
    dates we have to hit the archive ourselves."""
    url = UDIFF_URL_TPL.format(ymd=dt.strftime("%Y%m%d"))
    r = requests.get(url, headers=NSE_HEADERS, timeout=60)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        name = zf.namelist()[0]
        with zf.open(name) as fp:
            return fp.read().decode("utf-8")


def main() -> int:
    arc = NSEArchives()
    sys.stderr.write(f"udiff_start_date = {arc.udiff_start_date}\n")

    pre = report(
        f"LEGACY bhavcopy_fo_raw({PRE_CUTOVER})",
        lambda: fetch_legacy(arc, PRE_CUTOVER),
    )
    if pre:
        (OUT / f"bhavcopy_fo_legacy_{PRE_CUTOVER.strftime('%Y%m%d')}.csv").write_text(pre)
        sys.stderr.write("saved\n")

    post = report(
        f"UDIFF direct-URL fetch ({POST_CUTOVER})",
        lambda: fetch_udiff_direct(POST_CUTOVER),
    )
    if post:
        (OUT / f"bhavcopy_fo_udiff_{POST_CUTOVER.strftime('%Y%m%d')}.csv").write_text(post)
        sys.stderr.write("saved\n")

    sys.stderr.write("\n=== SUMMARY ===\n")
    sys.stderr.write(f"legacy pre-cutover  ({PRE_CUTOVER}):  {'OK' if pre else 'FAIL'}\n")
    sys.stderr.write(f"udiff post-cutover  ({POST_CUTOVER}): {'OK' if post else 'FAIL'}\n")
    return 0 if (pre and post) else 1


if __name__ == "__main__":
    raise SystemExit(main())
