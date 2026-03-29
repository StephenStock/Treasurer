# Workbook Review

## Fixed in code

- The statement page was summing raw `bank_transaction_allocations` only, so it missed workbook cash rows entirely and could not match the `Statement` tab.
- The statement page was showing raw ledger categories instead of the workbook statement lines. It now groups values to match the workbook layout:
  - General Fund
  - Charity Account
  - Benevolent Fund
  - Lodge of Instruction
- The cash workbook import mapped column `I` (`Donations` on the cash `OUT` side) to `DONATIONS_IN`. That was backwards. It now maps to `DONATIONS_OUT`.
- Fresh database setup now imports the `Cash` tab from the workbook as well as the `Bank` tab.
- The statement queries now respect the current reporting period instead of summing every period.
- The virtual account category map was not being seeded on a fresh database because `consolidate_virtual_accounts()` returned early before writing `virtual_account_category_map`. That is now fixed.
- The virtual account map was out of line with the workbook in a few places. It has been corrected so:
  - `GAVEL`, `RAFFLE`, `DONATIONS_IN`, `DONATIONS_OUT`, and `RELIEF` feed `CHARITY`
  - `LOI` alone feeds `LOI`
  - `CHAPTER_LOI` feeds `MAIN`
  - `WIDOWS` and `ALMONER` feed `BENEVOLENT`

## Why the numbers differed

- The workbook `Statement` tab mixes `Bank` and `Cash` totals. The app statement was only using bank allocations.
- The workbook treats some categories as transfers or balance-sheet movements rather than statement income:
  - `CASH`
  - `PRE_SUBS`
  - `PRE_DINING`
- The workbook combines some categories into one visible line:
  - `Dining Fees` = `DINING` + `VISITOR` + cash dining
  - `Subscriptions` = `SUBS` + cash subs
  - `Gavels` and `Raffles` include cash collections
- The local workspace database at `instance/Treasurer.db` is older than the current import logic. It still contains only 22 payment-generated bank rows and no imported cashbook rows, so even with the code fixes it will not match the workbook until it is backfilled.

## Confirmed comparison on a fresh temp database

Using a fresh temporary database created from the current code and workbook:

- General Fund income: `8123.70`
- General Fund expenditure: `8888.20`
- Charity income: `998.15`
- Charity expenditure: `620.00`
- Benevolent expenditure: `167.00`
- LOI income: `177.30`

These match the workbook statement lines.

## Still unresolved / needs your decision

- Existing database backfill: resolved
  - Decision taken: automatic only when the target tables are empty.
  - Startup now seeds/imports bank and cash workbook data for the current reporting period when those tables are empty.
  - Existing non-empty data is left alone on startup.
  - Your current working database may still need a one-time manual backfill if it already contains partial older data.
  - Safe manual commands remain:
    - `python -m flask --app app import-bank-statements`
    - `python -m flask --app app import-cashbook`

- Balance sheet parity with the workbook: resolved
  - Added first-class `member_prepayments` data so `Members!C` / `Members!D` are modeled instead of being hidden workbook-only values.
  - Added first-class `virtual_account_transfers` data for workbook transfers such as `Glasgow/Frank -> Centenary`.
  - Updated the Statement page balance sheet to use workbook-style account rows with `Xfr In` / `Xfr Out`.
  - Verified on a fresh sandbox database that the statement balance rows now match the workbook, including the final closing total `20732.67`.

- Members / Dining Check logic:
  - The workbook uses `Members` and `Dining Check` tabs to drive some member-level values.
  - `PP Subs` / `PP Dining` are now stored as first-class prepayment data.
  - `Dining Check` is intentionally out of scope and can be ignored for the app.

- Workbook formulas that look odd and need confirmation:
  - `Statement!C24` is `=F47`
  - `Statement!H29` is `=Bank!AH104`
  - Both currently evaluate to `0`, but they do not read like intentional business rules.
  - Decision needed: are those formulas correct, or accidental sheet references?

## Recommendation

- First backfill the existing database so the current project is using the workbook-derived bank and cash data.
- Then decide whether we want full workbook balance-sheet parity.
- If the answer is yes, the cleanest next step is to add an explicit transfer model plus stored pre-paid fields rather than trying to keep inferring those values indirectly.
