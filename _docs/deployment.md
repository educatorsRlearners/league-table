# Deployment

How the dev and prod demo services run and deploy.

Two Render services (Docker, free plan, Frankfurt) run the app against Neon Postgres:

| Environment | URL |
| --- | --- |
| Dev | <https://league-table-dev.onrender.com> |
| Prod | <https://league-table-prod.onrender.com> |

Demo logins (pick them on the login screen, or send the token as a Bearer token):

- `demo-instructor` — the instructor
- `demo-amara` — a student in `c1` (also `demo-rosa`)
- `demo-camila` — a student in `c2`

The data is demo data only. The seed adds any missing demo rows at startup and never overwrites existing ones, so changes made in the app persist across restarts and deploys until the database is cleared. The free services sleep after about 15 minutes idle, so the first request can take up to a minute to answer.

How deploys work (auto-deploy on Render is off; GitHub Actions calls Render deploy hooks):

- **Dev** deploys automatically after the CI workflow passes on `main` (`.github/workflows/deploy-dev.yml`).
- **Prod** deploys manually: Actions > Deploy to production > Run workflow (`.github/workflows/deploy-prod.yml`). It uses the `production` environment, where required reviewers can be added.
- Both wait for `/login/options` to return 200 (up to 10 minutes) and fail if the service is unhealthy.
- The hook URLs live in the repository secrets `RENDER_DEPLOY_HOOK_DEV` and `RENDER_DEPLOY_HOOK_PROD`.
