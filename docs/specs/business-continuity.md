# Spec: Business Continuity

## Status

Draft

## Decision note

Current preferred direction:

- local-first
- single-user or single-custodian
- SQLite as the normal data store
- spreadsheet export as a first-class fallback
- no mandatory external hosting or public web dependency

The previous deployment model has been valuable as a learning exercise and as a proof that the app can run in production-style infrastructure. It is no longer the preferred operating model for the product itself.

## Problem

The system must remain usable by the lodge or chapter even if the current technical maintainer becomes unavailable, hosting payments stop, or the app can no longer be actively developed.

The risk is not only software failure. The larger risk is operational fragility:

- one person understands the system deeply
- hosting, deploy, and recovery depend on technical knowledge
- successors are more likely to understand a spreadsheet than a hosted web app
- external dependencies such as domains and credentials can break continuity even if the code is stable

Business continuity must therefore be treated as a primary design goal, not as a later hardening task.

## Principle

The app must never become the only form in which the lodge's working financial knowledge can survive.

If the hosted system disappears, the treasurer must be able to continue the core workflow using exported spreadsheet-friendly data and documented plain-English procedures.

## Scope

This spec covers:

- continuity planning for treasury operations
- exportability of operational data into spreadsheet-usable form
- fallback from hosted app to spreadsheet workflow
- backup and restore expectations
- reduction of technical dependency on one maintainer
- decisions about which features should remain in the app and which should stay in external tools

This spec does not require, at this stage:

- immediate implementation of every export or recovery tool
- a full disaster-recovery automation platform
- duplication of secretarial capabilities already covered by Hermes
- replacement of Microsoft Forms where continuity is better served by keeping it

## Core decision direction

This project should be willing to narrow its ambition if doing so improves continuity.

That means the preferred direction is now:

- a treasurer's aid rather than a multi-role administrative platform
- continued use of Hermes for secretary and membership management
- continued use of Microsoft Forms for public dining or meal booking
- the Treasurer app focusing on treasury-specific workflows that are not already well served elsewhere
- a local desktop-style workflow rather than a permanently hosted web service

## Users

Primary users under this continuity model:

- Current treasurer
- Future treasurer with limited technical skill
- chapter officer acting as system custodian
- A cautious non-developer who may need to recover data or continue work after a failure

## Goals

- Ensure the treasurer's records can be handed over without requiring software expertise
- Make the app optional rather than existential to the process
- Preserve data and business rules in forms that are understandable outside the codebase
- Reduce the blast radius of hosting, credential, or maintainer failure
- Favor boring, stable, documented workflows over ambitious platform growth

## Non-goals

- Building a general-purpose administrative suite for every Masonic role
- Replacing Hermes where Hermes already provides a supported workflow
- Forcing all lodge and chapter processes into one custom system
- Depending on continuous feature development to keep the records usable

## Continuity requirements

### 1. Spreadsheet fallback must be real

The system must be able to produce a working export pack that allows a successor to continue operations in spreadsheet form.

That export pack should be:

- understandable without database knowledge
- organized into workbook-like sheets or CSVs
- sufficient for the core treasurer workflow
- reproducible on demand

Minimum continuity exports should include:

- members and member balances
- payments
- meetings or reporting periods
- bank transactions and categorisations
- cash entries by meeting
- cash settlements linked to bank deposits
- statement totals and supporting category summaries

Stretch goal:

- export directly to a workbook structure close enough to the current spreadsheet model that a successor could continue there with minimal redesign

### 2. Operational knowledge must exist outside the code

The essential rules of the system must be documented in plain English.

That includes:

- what each category means
- how cash is entered
- how cash is settled to the bank
- how dues and dining balances are interpreted
- what must be checked at month-end or year-end
- how to continue manually if the app stops

The documentation must be good enough that a careful successor can understand the workflow even if they cannot read Python.

### 3. Hosting dependency must not destroy continuity

If hosting stops because of payment failure, access loss, or deliberate shutdown, the treasury workflow must still be recoverable.

The continuity plan should assume:

- a hosted copy may disappear suddenly
- the database may need to be restored elsewhere
- the fallback may be spreadsheet-first rather than app-first

Preferred mitigation:

- do not require hosting for normal use
- make the normal operating model local-first
- treat any non-local deployment as optional or temporary

Minimum requirements:

- regular database backups
- regular export pack generation
- a documented restore path
- a documented manual fallback path

### 4. Single-maintainer dependency must be reduced

The system should distinguish between:

- day-to-day operator
- data custodian
- technical maintainer

Even if there is only one technical maintainer, the other two roles should be teachable with low technical dependency.

Examples:

- a custodian should know where backups live
- a custodian should know what bills or renewals exist
- a custodian should know how to find the runbook and continuity guide
- an operator should not need to know how to deploy code

### 5. Feature choice must be filtered through continuity risk

New features should be accepted only if they improve the treasurer workflow without materially increasing continuity risk.

Features should be rejected, deferred, or kept in external services when they:

- duplicate supported third-party systems unnecessarily
- create new hosting or security obligations
- make the system harder to hand over
- depend on specialized technical knowledge to keep working

## Product implications

### Treasurer-first positioning

The app should be treated primarily as a treasurer's aid unless there is a strong continuity-safe reason to broaden it.

That implies prioritizing:

- cash workflow
- bank categorisation and reconciliation
- reporting
- member balance visibility
- export and handover
- local reliability over remote availability

### Secretary functions

Secretary and membership-management functions should not be expanded merely because they are possible.

If Hermes already covers the secretarial need well enough, then this app should avoid duplicating that responsibility unless there is a treasury-specific reason.

### Dining forms

Hosted dining forms inside this app are optional, not mandatory.

If Microsoft Forms provides a simpler and safer continuity story, then it may be the better long-term choice. The app can consume or record the results without owning the whole public booking workflow.

### Packaging

The preferred packaging direction is:

- keep the current application architecture
- run it locally by default
- consider Windows desktop packaging only as a wrapper around the existing app

This should not require a full native rewrite. The goal is easier use and handover, not a technically purer implementation.

## Acceptance criteria

This spec will be considered meaningfully addressed when:

- the project has a documented continuity model
- the preferred operating model is local-first rather than hosted-first
- the project can produce an export pack sufficient for spreadsheet fallback
- the app's critical workflows are documented in plain English
- hosting, backup, and restore dependencies are documented
- product scope decisions explicitly favor lower continuity risk
- it is possible to explain how the lodge would continue if the hosted app vanished

## Immediate follow-on work

The likely implementation work after agreeing this spec is:

1. Define the minimum continuity export pack
2. Define the minimum monthly backup routine
3. Write a plain-English continuity guide for a non-technical successor
4. Reassess whether dining forms should stay in Microsoft Forms
5. Reassess whether the app should remain treasurer-only rather than multi-role
6. Define the target form of a local packaged Windows app

## Open questions

- What is the minimum set of data a successor would need in spreadsheet form to continue confidently?
- Should the continuity export be CSV-based, workbook-based, or both?
- How often should the continuity export pack be produced?
- Should export generation be manual, scheduled, or part of month-end workflow?
- Which current features are genuinely treasury-essential, and which are convenience features?
- Should the project formally drop member-facing and multi-role ambitions now, or only defer them?
- Should any non-local recovery/demo environment exist at all, or should the project stay purely local?
