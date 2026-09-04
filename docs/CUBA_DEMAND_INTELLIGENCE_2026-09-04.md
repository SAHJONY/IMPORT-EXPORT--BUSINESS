# Cuba Demand Intelligence — SAHJONY Global Trade

## Objective
Turn customer-reported operating data into structured, evidence-based reorder demand without turning SAHJONY into a POS or accounting system.

## Minimum operating data
- product / SKU / category
- current stock
- monthly consumption
- reorder point
- preferred packaging
- last purchase price (benchmark only)
- destination
- required date

## Decision engine
The service calculates days of cover and labels inventory HEALTHY, WATCH, REORDER_DUE, or CRITICAL. Only CRITICAL and REORDER_DUE are automatic reorder candidates.

## RFQ boundary
The system may generate a non-binding RFQ draft. It does not contact suppliers, promote a draft to a firm quote, sign a contract, authorize payment, or create SAHJONY capital exposure.

## Canonical operator
All actionable demand is assigned to Sofia Smith (`sofia-smith`).

## Commercial objective
Inventory signal -> RFQ draft -> qualified RFQ -> supplier comparison -> protected quote -> compliant deal room -> delivery -> repeat order.

## Success metrics
7-day pilot: at least 10 businesses observed, 5 usable reorder signals, and 3 RFQ-ready demand records. 30-day target: demonstrate at least one complete signal-to-RFQ workflow while maintaining $0 SAHJONY capital at risk.
