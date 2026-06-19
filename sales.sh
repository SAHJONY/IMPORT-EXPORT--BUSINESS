#!/usr/bin/env bash
set -euo pipefail

# Sales workflow: identify US buyers, generate outreach templates, and prepare pricing sheet.

REPORT_FILE=$(dirname "$(realpath "$0")")/reports/sales_report.md
mkdir -p "$(dirname "$REPORT_FILE")"

# 1. Target buyer list (placeholder) – use web search to find distributors
cat > buyer_search_query.txt <<'EOF'
US wholesale produce distributors for winter vegetables (garlic, onion, tomato, cucumber, pepper, lettuce, cabbage, beet) looking for Cuban imports
EOF

# 2. Outreach email template for US buyers
cat > us_buyer_email_template.txt <<'EOF'
Subject: Premium Cuban Winter Vegetables Available for US Distribution

Dear [Buyer Name],

We are pleased to introduce our line of high‑quality winter vegetables sourced directly from trusted farms in Cuba. Our portfolio includes:
- Garlic (fresh, 2‑3 lb heads)
- Onion (yellow, 1 lb bags)
- Tomato (Vine‑ripe, 1 lb crates)
- Cucumber (seedless, 2 lb packs)
- Sweet Pepper (red/green, 1 lb boxes)
- Lettuce (iceberg, 15 lb bags)
- Cabbage (green, 10 lb heads)
- Beet (red, 10 lb crates)

Key advantages:
- Seasonal price advantage (US winter demand, Cuban off‑season production)
- Consistent quality with HACCP‑compliant cold chain
- Flexible volume (5‑10 tons per season) and competitive FOB pricing

We hold an OFAC agricultural import license and USDA‑APHIS phytosanitary certification, ensuring smooth customs clearance.

Please let us know your interest, required volumes, and any specifications. We can provide a detailed quote and arrange a pilot shipment.

Best regards,
[Your Name]
[Your Title]
[Company]
[Phone]
[Email]
EOF

# 3. Pricing sheet template (CSV)
cat > pricing_template.csv <<'EOF'
Product,FOB Price (USD/lb),US Wholesale Price (USD/lb),Margin %
Garlic,0.25,0.80,68
Onion,0.25,0.75,66
Tomato,0.25,0.95,73
Cucumber,0.25,0.80,68
Pepper,0.25,1.10,77
Lettuce,0.25,0.55,55
Cabbage,0.25,0.45,55
Beet,0.25,0.60,58
EOF

# 4. Summarize sales steps
cat > "$REPORT_FILE" <<'EOR'
# Sales Report

## Target Buyers
- Created `buyer_search_query.txt` with search terms to locate US wholesale distributors.
- A sub‑agent should perform a web search, compile a list of 5–6 potential buyers with contact info, and save as `buyers.xlsx`.

## Outreach Email
- Template `us_buyer_email_template.txt` ready for personalization.

## Pricing Sheet
- `pricing_template.csv` provides baseline FOB and wholesale pricing with margin calculations.

## Next Steps
1. Execute the buyer search (via a sub‑agent or manually) and populate a spreadsheet.
2. Personalize and send outreach emails to identified buyers.
3. Adjust pricing if needed based on buyer feedback and volume commitments.
4. Once agreements are in place, coordinate with the logistics sub‑agent for shipment scheduling.
EOR

echo "Sales report written to $REPORT_FILE"
