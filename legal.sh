#!/usr/bin/env bash
set -euo pipefail

# Legal workflow: obtain OFAC license and USDA-APHIS phytosanitary certificate.
# This script is intended to be run by a Hermes sub‑agent; it writes a concise report.

REPORT_FILE=$(dirname "$(realpath "$0")")/reports/legal_report.md
mkdir -p "$(dirname "$REPORT_FILE")"

# 1. OFAC license request (placeholder steps)
cat > ofac_request.txt <<'EOF'
--- OFAC Agricultural License Request ---
Applicant: <Your Company Name>
Purpose: Import winter vegetables from Cuba to the United States.
Products: Garlic, Onion, Tomato, Cucumber, Pepper, Lettuce, Cabbage, Beet.
Estimated annual import volume: 5,000 lbs.
--- End ---
EOF

# 2. USDA-APHIS phytosanitary info (placeholder)
cat > phyes_certificate_template.txt <<'EOF'
--- Phytosanitary Certificate Request ---
Exporter: <Cuban Producer Name>
Commodity: Fresh vegetables (list above)
Origin: Cuba
Destination: United States
Requested inspection date: <date>
--- End ---
EOF

# 3. Summarize actions performed
cat > "$REPORT_FILE" <<'EOR'
# Legal & Compliance Report

## OFAC License
- Prepared `ofac_request.txt` with required details.
- User must submit this file via the Treasury OFAC portal (https://sanctionssearch.ofac.treas.gov).

## USDA‑APHIS Phytosanitary Certificate
- Generated `phyes_certificate_template.txt` for the Cuban NPPO.
- Exporter should obtain a signed certificate and provide a digital copy.

## Next Steps
1. Submit the OFAC request and await approval (typically 30‑60 days).
2. Have the Cuban producer secure the phytosanitary certificate.
3. Store the approved documents securely before any shipment.
EOR

echo "Legal report written to $REPORT_FILE"
