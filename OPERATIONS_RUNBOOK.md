# OPERATIONS RUNBOOK

## Global release principle
No trade is released because a dashboard says READY. Release requires the applicable live evidence, role authority and transaction gates.

## Cuba Authorized Trade Desk

### Owner setup
1. Activate the real `CU` current-law jurisdiction.
2. Apply `insforge/cuba_authorized_trade.sql`.
3. Onboard each employee with a unique employee ID.
4. Register the actual government authorization basis and attach its evidence document.
5. Verify the authorization record only after confirming the authority, scope, dates and conditions.

### Employee workflow
1. Sign in with the employee's own identity/session.
2. Open `/employee/cuba-desk`.
3. Create a U.S. → Cuba case assigned to that employee.
4. Identify the product and ECCN/EAR99 basis.
5. Identify consignee, end user and end use.
6. Link the verified government authorization record.
7. Assemble supporting documents and evidence.
8. Escalate for compliance/owner review.

### Required transaction gates
- product classification
- government authorization / license-exception scope
- end-user/end-use eligibility
- restricted-party and sanctions screening
- banking/payment-path compliance
- required commercial/export/customs documents
- logistics/carrier/forwarder route compliance
- recordkeeping evidence

### Release rule
Employees cannot self-release Cuba transactions. A case remains unreleasable until a verified authorization exists, every required gate is PASS or formally NOT_APPLICABLE, and the owner authorizes release.

### Immediate HOLD triggers
Put the case on HOLD when authorization scope is unclear, a screening candidate match exists, banking changes, end user/end use changes, product classification changes, authorization expires/revokes, required documentation is incomplete, or a carrier/forwarder refuses the route.

### Current-law caveat
OFAC/BIS and other applicable rules can change. Before each release, use current authoritative regulatory information and the exact transaction facts. The OS must never treat a license exception or general license as broader than its actual terms.
