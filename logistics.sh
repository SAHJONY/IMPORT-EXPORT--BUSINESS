#!/usr/bin/env bash
set -euo pipefail

# Logistics workflow: freight, cold chain, customs broker, and ngrok tunnel for monitoring.

REPORT_FILE=$(dirname "$(realpath "$0")")/reports/logistics_report.md
mkdir -p "$(dirname "$REPORT_FILE")"

# 1. Freight options (placeholder)
cat > freight_options.txt <<'EOF'
--- Freight Options for Cuban Veg Export ---
1. Sea freight (container) from Havana Port to Miami Port
   - Estimated transit: 7-10 days
   - Cost: $0.04 per lb (including refrigerated container)
2. Air freight (cargo) from Havana Intl Airport to Miami Intl Airport
   - Estimated transit: 1-2 days
   - Cost: $0.20 per lb (high priority, perishable)
3. Hybrid: Sea freight to Port Everglades, then truck refrigerated to final warehouse.
--- End ---
EOF

# 2. Cold‑chain checklist
cat > cold_chain_checklist.txt <<'EOF'
--- Cold‑Chain Checklist ---
- Use ISO 22C refrigerated reefers for sea freight.
- Install temperature data loggers (range 0°C to 5°C).
- Verify carrier's HACCP compliance.
- Ensure US customs broker provides on‑site temperature monitoring.
--- End ---
EOF

# 3. Customs broker engagement (placeholder contact)
cat > broker_contact.txt <<'EOF'
Customs Broker: XYZ Logistics Co.
Phone: +1-305-555-0123
Email: logistics@xyzco.com
Website: https://xyzco.com
Service: Import clearance for perishable agricultural goods, HTS 07 49 xx xx.
EOF

# 4. Ngrok tunnel for monitoring (if user wants a live endpoint for tracking)
# Assume user already has ngrok installed and authtoken configured.
NGROK_TUNNEL_NAME="my_fastapi_50001"
NGROK_PORT=50001
# Stop any existing tunnel with the same name
ngrok tunnel stop "$NGROK_TUNNEL_NAME" || true
# Start a new tunnel (background) and capture the public URL
NGROK_URL=$(ngrok http "$NGROK_PORT" --name "$NGROK_TUNNEL_NAME" --log=stdout | grep -Eo "https://[a-z0-9]+\.ngrok\.free\.dev")

echo "Ngrok tunnel started: $NGROK_URL" > ngrok_url.txt

# 5. Summarize logistics steps
cat > "$REPORT_FILE" <<'EOR'
# Logistics Report

## Freight Options
See `freight_options.txt` for evaluated sea and air freight alternatives.

## Cold‑Chain Management
`cold_chain_checklist.txt` outlines temperature monitoring requirements.

## Customs Broker
Contact details in `broker_contact.txt`. Provide them with OFAC license and phytosanitary certificates.

## Ngrok Tunnel
- Stopped any existing tunnel named `my_fastapi_50001`.
- Started a new tunnel on local port 50001.
- Public URL saved to `ngrok_url.txt` (e.g., https://abcd1234.ngrok.free.dev).
- Use this URL to monitor incoming shipments via a simple FastAPI endpoint you host.

## Next Steps
1. Choose freight method and book with carrier.
2. Ensure temperature loggers are installed on the container.
3. Share the broker with the OFAC license and phytosanitary docs.
4. Deploy your FastAPI server on port 50001 (if not already running) and verify the ngrok URL is reachable.
EOR

echo "Logistics report written to $REPORT_FILE"
