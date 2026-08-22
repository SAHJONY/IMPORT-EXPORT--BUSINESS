# SAHJONY Global Trade OS

Production-oriented import/export operating system with governed sourcing, market intelligence, compliance, document movement, communications, shipment tracking, treasury and owner controls.

## Role workspaces

- Owner: `/owner`
- Employee: `/employee`
- Customer / participant: `/customer`
- Messages: `/owner/messages`, `/employee/messages`, `/customer/messages`
- Documents: `/owner/documents`, `/employee/documents`, `/customer/documents`
- Shipping: `/owner/shipping`, `/employee/shipping`, `/customer/shipping`

## Seamless business communications

Messages, document movements, shipment milestones, exceptions, approvals, payment/compliance events and other operational events are designed to flow into one case-linked business timeline with role-scoped visibility. Customer-facing events can create portal notification records; external channels stay fail-closed until an approved provider and participant consent are configured.

## End-to-end shipment tracking

Shipment tracking covers the operational lifecycle from booking/pickup through origin handling, export customs, main carriage, transshipment, import customs, destination handling and final delivery. The model supports ocean, air, ground, LCL, parcel and multimodal movements.

Tracking data is persisted in InsForge using:

- `shipments`
- `shipment_milestones`
- `shipment_sync_events`

Every customer-visible milestone or exception can publish into the unified business communications timeline. Exception events are marked action-required and can generate portal notifications.

The backend already includes a server-side Maersk OAuth adapter. Production tracking sync requires approved Maersk credentials plus a contracted API path supplied through `MAERSK_TRACKING_PATH_TEMPLATE`; the application intentionally does not guess a carrier endpoint.

## Production data schemas

Apply before enabling the respective features:

- `insforge/communications.sql`
- `insforge/business_communications.sql`
- `insforge/documents.sql`
- `insforge/shipments.sql`

## Security and release policy

- Owner-only controls remain fail-closed.
- Employee operations are separate from executive treasury/configuration authority.
- Customer/participant visibility must remain tenant-scoped.
- Customer documents and shipment milestones must use authenticated RLS/storage authorization before sensitive live records are exposed.
- Consequential compliance, payment, treasury and trade release decisions are not performed through chat or tracking updates.
