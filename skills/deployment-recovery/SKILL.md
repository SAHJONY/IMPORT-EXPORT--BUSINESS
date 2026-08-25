# Deployment Recovery Skill

Purpose: recover SAHJONY Global Trade production deployment when Git-triggered Vercel builds are rate-limited or the external deployment connector cannot submit a valid deployment request.

## Policy
- Do not evade Vercel account, billing, security, abuse, or quota controls.
- Prefer prebuilt deployment: `vercel pull --environment=production`, `vercel build --prod`, then `vercel deploy --prebuilt --prod`.
- Never commit Vercel credentials. Use the GitHub Actions secret `VERCEL_TOKEN`.
- Production project is `prj_XmlR9SuaYKEE9siBC7lrsjLzYjb9` under team `team_Me3fB0D0J6He10CgJlJ44Xaq`.
- Canonical production URL is `https://import-export-business.vercel.app`.
- Fail closed: deployment is not successful until immutable and canonical URLs pass smoke tests.

## Recovery sequence
1. Confirm `main` is the intended release SHA and CI passed.
2. Run the `Vercel Recovery Deploy` GitHub Action.
3. The action pulls production environment configuration, builds `.vercel/output` in GitHub Actions, and sends the prebuilt artifact to Vercel.
4. Verify `/`, `/client`, `/owner`, `/health`, and `/voice/health` on both the immutable deployment URL and canonical production URL.
5. For voice releases, verify inbound status and perform an authorized outbound test from Owner OS before declaring the phone system operational.
6. If Vercel rejects the deployment because the account itself is rate-limited, stop and report the external platform limit; do not create duplicate projects or accounts to evade it.

## Credential bootstrap
If the workflow reports `Missing GitHub Actions secret VERCEL_TOKEN`, create a scoped Vercel token with deployment access for the existing team/project and store it as the repository Actions secret `VERCEL_TOKEN`. Do not paste it into source code or logs.
