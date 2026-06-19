## Multi‑Business Collaboration (Collaboración Multi‑Negocio)

Each subsidiary or partner can **add data** (orders, inventory, paperwork, financial records) via a secure personal API token. The token grants **write‑only** access to its own business scope; it cannot read data belonging to other participants. Only the owner (you) holds the **owner token** and can view or control every business.

### How to add a participant (owner only) / Cómo añadir un participante (solo propietario)
1. Call the admin endpoint with your owner token (replace `<YOUR_OWNER_TOKEN>`):
   ```bash
   curl -X POST "https://<ngrok_url>/admin/add_participant" \
        -H "Authorization: Bearer <YOUR_OWNER_TOKEN>" \
        -d "business_id=business_01" -d "participant_id=user_a"
   ```
   The response returns a unique **token** for that participant.
2. Share that token securely with the participant. They will use it in the `Authorization: Bearer <token>` header for all subsequent calls.

### Participant data submission (write‑only) / Envío de datos del participante (solo escritura)
```bash
curl -X POST "https://<ngrok_url>/submit" \
     -H "Authorization: Bearer <PARTICIPANT_TOKEN>" \
     -H "Content-Type: application/json" \
     -d '{"data_type":"invoice","payload":{"invoice_id":"INV001","amount":1200,"currency":"USD"}}'
```
- `data_type` can be **order**, **inventory**, **invoice**, **payment**, etc.
- The payload is stored as JSON and can be processed later by automated scripts.

### Owner view of all submissions / Vista del propietario de todos los envíos
```bash
curl -X GET "https://<ngrok_url>/admin/submissions" \
     -H "Authorization: Bearer <YOUR_OWNER_TOKEN>"
```
The response contains every record submitted by all participants, ordered by timestamp.

### Automated paperwork & payments (24/7/365) / Documentación y pagos automáticos (24/7/365)
You can schedule a **cron job** that reads the `submissions` table, generates the required paperwork (PDF invoices, customs forms) and triggers bank transfers via your preferred API. The job runs under the owner token, so it has full visibility but participants never see each other’s data.

```bash
cronjob action=create name="process_submissions" schedule="*/5 * * * *" prompt="Read new rows from submissions, create PDFs, and initiate payments via your banking API."```

---
All configuration files (`.env`, `ngrok.yml`, `run_fastapi_ngrok.bat`) remain unchanged; just add the owner token value to `.env` and keep it secret.
