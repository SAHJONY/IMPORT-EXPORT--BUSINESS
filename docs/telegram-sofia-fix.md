# Telegram + Sofia integrity fix

- `/telegram/health` is explicitly read-only and does not access persistence or Telegram provider APIs.
- Backend imports are lazy and limited to webhook persistence and Sofia inbox reads.
- Telegram inbound is stored as engagement evidence and conservatively triaged for Sofia.
- Concrete commercial messages may be marked `trade_requirement_candidate`, but are never auto-qualified and never create an RFQ or trade intake.
- `/telegram/sofia/inbox` gives the owner/application a read-only Sofia queue for Telegram events.
- Binding commitments, capital deployment, payments, banking changes, and contracts remain outside Telegram automation authority.
