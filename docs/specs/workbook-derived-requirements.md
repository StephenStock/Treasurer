# Requirements Derived From `Accounts 2025-26.xlsx`

## Status

Living reference

## Purpose

Translate the current spreadsheet workflow into a clear set of software requirements for the Lodge Treasurer web application.

## Source workbook reviewed

- `Accounts 2025-26.xlsx`

## Sheets reviewed

- `Statement`
- `Cash`
- `Bank`
- `Members`
- `Dining Check`

## Overall conclusion

The spreadsheet is doing much more than simple bookkeeping. It is acting as:

- An annual statement generator
- A member subscriptions ledger
- A dining charges tracker
- A cash collection log for meetings
- A bank transaction categorisation tool
- A reconciliation and cross-check workbook

The web app should therefore be designed as a small lodge operations system, not just a generic accounts register.

## Business goals

- Maintain a complete annual picture of lodge income and expenditure
- Track what each member owes and has paid for subscriptions and dining
- Record cash collected at meetings by category
- Reconcile cash activity against banked income
- Produce year-end statement figures with less manual spreadsheet work
- Preserve process knowledge so the next treasurer can take over smoothly

## Primary user roles inferred from the workbook

### Treasurer

- Maintains members, dues, dining balances, cash collections, and bank transactions
- Produces statement figures and year-end summaries
- Reconciles totals across cash, bank, and member records

### Secretary

- May need read or update access to member status and communications
- May need visibility into meeting attendance and dining numbers

### Dining or events lead

- May need access to meal bookings, dining counts, and dietary notes

### Member

- May later need access to own dues position, dining bookings, and payment history

## Functional requirements

### 1. Member management

The system must store a member record with enough data to support subscriptions, dining, and status decisions.

Required member fields inferred from `Members`:

- Full name
- Member type
- Subscription amount due
- Subscription amount paid
- Subscription balance outstanding
- Dining amount due
- Dining amount paid
- Dining balance outstanding
- Comments or notes

The system should also support:

- Membership status values such as `FULL`, `ND`, `PAYG`, `SEC`, `RESIGNED`, `EXCLUDE`
- Special handling for visitors and non-standard attendees
- Notes for exceptional cases such as illness, resignation, or debt write-off

### 2. Subscription and dues tracking

The system must track annual subscription charges and payments at member level.

Requirements inferred from `Members`, `Statement`, and `Bank`:

- Store annual subscription amount expected per member
- Record payments received against subscriptions
- Show outstanding balance per member
- Support partial payments and arrears
- Distinguish current-year dues from arrears from prior years
- Support exempt or excluded members where collection is not expected

### 3. Dining charge tracking

The system must track meal-related charges and payments by member and by meeting.

Requirements inferred from `Members`, `Dining Check`, `Cash`, and `Bank`:

- Record whether a member dined at each meeting
- Calculate dining amount due based on attendance and member type
- Record dining payments received
- Show unpaid dining balances
- Support different charging models such as:
  - fixed annual dining expectations for some member types
  - pay-as-you-go dining for others
- Support visitors paying for meals separately

### 4. Event and meeting management

The app should treat each meeting or dining occasion as a real event.

Requirements inferred from `Cash` and `Dining Check`:

- Create meetings or events such as September, November, January, March, May
- Record attendance or dining participation per member per event
- Track event-specific income categories
- Support visitor attendance
- Later support meal booking before the event, not just post-event reconciliation

### 5. Cash collection recording

The system must support cash-night entry similar to the `Cash` sheet.

Cash categories inferred from the workbook:

- Subscriptions
- Dining
- Gavel
- Raffle
- Copper Pot
- Donations
- Almoner
- Tyler

Requirements:

- Record cash lines per meeting and per person or collection type
- Support entry types such as `Member`, `Visitor`, `Tyler`, `Collection`
- Calculate total cash in and total cash out
- Record net retained amount where relevant
- Keep meeting-level summaries
- Allow the net cash from a meeting to be settled into the bank later without re-categorising the original cash entries
- Link each cash settlement back to the bank deposit row so the bank ledger stays complete while the cash categorisation stays single-source

### 6. Bank transaction import and categorisation

The system must support a bank ledger similar to the `Bank` sheet.

Required bank fields inferred from the sheet:

- Date
- Details
- Transaction type
- Money in
- Money out
- Running balance

Required categorisation capabilities:

- Cash
- Pre-subscriptions
- Pre-dining
- Subscriptions
- Dining
- Visitor
- Initiation
- SumUp
- Gavel
- Donations
- Chapter LOI
- LOI
- Relief
- UGLE
- PGLE
- Orsett
- Woolmarket
- Caterer
- Bank Charges
- Widows

Requirements:

- Import or enter bank transactions
- Support workbook-derived import and statement-file upload import
- Allocate a transaction across one or more categories
- Support inbound and outbound transactions
- Keep cross-check totals
- Record transaction descriptions exactly as received from the bank
- Allow later reconciliation against members, events, and cash records

### 7. Reconciliation and cross-checking

The workbook clearly relies on validation columns and comparison totals. The system must preserve that capability.

Requirements inferred from `Bank`, `Cash`, `Members`, and `Dining Check`:

- Compare expected subscriptions against payments received
- Compare expected dining totals against dining attendance
- Compare cash meeting totals against banked amounts
- Compare annual income and expenditure totals against statement output
- Flag unexplained differences
- Provide a treasurer-friendly reconciliation screen

### 8. Annual statement and reporting

The `Statement` sheet shows year-end reporting as a core output, not a side effect.

Requirements:

- Produce annual income totals by category
- Produce annual expenditure totals by category
- Calculate surplus or deficit
- Show comparative or reference figures for prior year where available
- Support planning assumptions for next year such as:
  - projected membership count
  - initiation count
  - dues rate changes
  - unit-price assumptions
- Export a statement summary for presentation or committee review

Income categories inferred from `Statement`:

- Dining Fees
- Subscriptions
- Initiation Fees
- Chapter C of I Rent
- SumUp

Expenditure categories inferred from `Statement`:

- Catering
- UGLE
- PGLE
- Orsett Masonic Hall rent
- Lodge of Instruction rent at Woolmarket
- Tyler fee
- Bank charges

### 9. Special cases and exception handling

The workbook contains free-text notes and edge cases that matter operationally.

Requirements:

- Allow notes against members, dues items, and transactions
- Allow debts to be marked as unrecoverable or written off
- Allow resigned members to remain in the historical record
- Support visitors who are not full lodge members
- Support one-off payments such as initiations

### 10. Data export and handover

Because this system will eventually be handed to another treasurer, portability matters.

Requirements:

- Export members data to CSV
- Export annual transactions to CSV
- Export statement summaries
- Support database backup
- Preserve an audit-friendly record of who changed what, if feasible

## Non-functional requirements

### Usability

- The system should be simpler to operate than the current workbook
- Core tasks should be possible without accounting software knowledge
- Totals and balances should be visible without manual formula work

### Maintainability

- The system should be understandable by a future treasurer or helper
- Business rules should be documented, especially around member types and dining charges
- Categories should be configurable rather than buried in code where practical

### Data integrity

- Financial totals must be reproducible from underlying records
- Reconciliation differences must be visible
- Deleting historical financial records should be restricted or avoided

### Security

- Treasurer and secretary areas should require login
- Member-facing access should be limited to each member's own information
- Sensitive financial screens should not be public

## Proposed application modules

Based on the workbook, the app should eventually include:

1. Members
2. Dues and arrears
3. Events and dining
4. Cash collections
5. Bank ledger
6. Reconciliation
7. Statement and reporting
8. Admin and handover tools

## Suggested implementation order

To keep scope controlled, build in this order:

1. Authentication and roles
2. Members and member types
3. Dues tracking
4. Events and dining attendance
5. Cash entry by meeting
6. Bank transaction ledger and categorisation
7. Reconciliation dashboard
8. Annual statement reporting
9. Member-facing self-service

## Immediate database implications

The current starter schema is too small for the spreadsheet workflow. We will likely need additional tables such as:

- `member_types`
- `meetings`
- `meeting_attendance`
- `cash_entries`
- `cash_batches`
- `bank_transactions`
- `transaction_allocations`
- `subscription_charges`
- `dining_charges`
- `write_offs`
- `reporting_periods`

## Assumptions and open questions

These points are inferred from the workbook and should be confirmed before implementation:

- Whether `FULL`, `ND`, `PAYG`, `SEC`, and `EXCLUDE` should be configurable codes
- Whether dining charges are per meeting, per package, or manually overridden
- Whether subscriptions and dining should be billed separately or as a combined incoming payment
- Whether UGLE, PGLE, Orsett, and Woolmarket are always fixed category outputs
- Whether `LOI`, `Chapter LOI`, `Relief`, `Widows`, and `Donations` need separate reporting treatment
- Whether the statement should be printable in a formal year-end format

## Implementation notes

Parts of this requirements set are now live in the app, including:

- internal-user authentication
- members and dues records
- bank import and categorisation
- cash entry by meeting
- linked cash-to-bank settlement flow

This document should stay focused on workbook intent and business rules. Delivery status should be tracked in the roadmap and the runbook.
