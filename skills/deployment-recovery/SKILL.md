---
name: deployment-recovery
description: Recover SAHJONY production releases when automatic Vercel builds are rate-limited by using the repository's guarded prebuilt deployment workflow.
---

# Deployment Recovery

Recover SAHJONY Global Trade production deployment when Git-triggered Vercel builds are rate-limited or the external deployment connector cannot submit a valid deployment request.

## Policy
- Do not evade Vercel account, billing, security, abuse, or quota controls.
- Use `.github/workflows/vercel-recovery-deploy.yml`; do not reproduce its commands ad hoc.
- Keep automatic Git deployments restricted to `main` until the recovery workflow has a tested `VERCEL_TOKEN`.
- Run the prebuilt workflow manually during a build-rate incident; do not create repeated trigger commits.
- Never commit Vercel credentials. Use the GitHub Actions secret `VERCEL_TOKEN`.
- Production project is `prj_XmlR9SuaYKEE9siBC7lrsjLzYjb9` under team `team_Me3fB0D0J6He10CgJlJ44Xaq`.
- Canonical production URL is `https://www.sahjony.com`.
- Fail closed: deployment is not successful until immutable and canonical URLs pass smoke tests.

## Recovery sequence
1. Confirm `main` is the intended release SHA and the repository doctors pass.
2. Run the `Vercel Prebuilt Production` GitHub Action manually.
3. The action pulls production environment configuration, builds `.vercel/output` in GitHub Actions, and sends one prebuilt immutable artifact to Vercel.
4. Verify `/`, `/supabase-login.html`, and `/health` on the immutable URL before promoting it; then repeat the checks on the canonical production URL.
5. For voice releases, verify inbound status and perform an authorized outbound test from Owner OS before declaring the phone system operational.
6. If Vercel rejects the prebuilt deployment because the account itself is rate-limited, stop after one attempt and report the reset window; do not create duplicate projects or accounts to evade it.

## Credential bootstrap
If the workflow reports `Missing GitHub Actions secret VERCEL_TOKEN`, create a scoped Vercel token with deployment access for the existing team/project and store it as the repository Actions secret `VERCEL_TOKEN`. Do not paste it into source code or logs.
