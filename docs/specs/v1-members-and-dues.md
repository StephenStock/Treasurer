# Spec: V1 Members and Dues

## Status

Planned

## Problem

The workbook shows that member records, subscription balances, and dining balances are the operational core of the treasurer process. The app needs a proper data model and UI flow for those records before more advanced features such as reconciliation and statement reporting can be built reliably.

## Scope

This spec covers:

- Member types and member status
- Member master records
- Annual reporting periods
- Combined yearly member balances for subscriptions and dining
- Individual subscription charges
- Recorded member payments
- The data model needed to support later member and dues screens

This spec does not yet cover:

- Authentication and route protection
- Bank import
- Cash-night entry
- Event attendance entry
- Full dining charge generation per meeting
- Online payments

## Users

- Treasurer
- Secretary

## Domain rules inferred from the workbook

- A member has both a membership status and a member type
- Member type influences expected subscription and dining treatment
- Subscription and dining balances must both be visible
- Dining balances should include the caterer outflows that relate to lodge meals
- One member may make one payment that covers several purposes
- A reporting year needs to be explicit, not implied
- Exceptional cases such as resignation, write-off, or exclusion must be recordable

## Data requirements

### Reporting periods

The system must store reporting periods such as `2025-26`.

Required fields:

- Label
- Start date
- End date
- Current-period flag

### Member types

The system must store configurable member types such as:

- `FULL`
- `ND`
- `PAYG`
- `SEC`
- `EXCLUDE`

Required fields:

- Code
- Description
- Subscription rule
- Dining rule
- Default subscription amount
- Default dining amount
- Active flag

### Members

Required fields:

- Membership number
- Full name
- Member type
- Email
- Phone
- Status
- Joined date
- Resigned date
- Notes

### Annual dues balance

The system must maintain one member-level annual balance row per reporting period showing:

- Subscription due
- Subscription paid
- Dining due
- Dining paid
- Overall status
- Notes

### Subscription charges

The system must store charge items separately from the annual summary balance.

Required fields:

- Member
- Reporting period
- Charge type
- Description
- Amount
- Due date
- Written-off flag
- Notes

### Payments

The system must store member payments with allocation amounts.

Required fields:

- Member
- Reporting period
- Payment date
- Payment method
- Reference
- Total amount
- Subscription amount
- Dining amount
- Initiation amount
- Donation amount
- Notes

## Acceptance criteria

- The database schema supports configurable member types
- The database schema supports reporting periods
- The database schema supports richer member records
- The database schema supports separate subscription charges and payments
- The app can still initialize with seed data after the schema update
- The dashboard can still render annual balances from the revised schema

## Deferred items

- Automatic balance rollups from payment rows
- Dining charges per event
- Write-off workflow UI
- CSV import from workbook
- Bank reconciliation links

## Implementation notes

- Keep the current `dues` table as a period summary table for now
- Use `subscription_charges` and `payments` to prepare for later reconciliation
- Avoid over-normalising until the treasurer workflows are clearer

## Follow-on feature work

After this data-model slice, the next likely implementation should be one of:

1. Authentication
2. Members list and member detail screens
3. Dues editing workflow
