# Status

Where the project stands.

League Table is an early version built on demo data.

- [x] FastAPI backend implementing the whole OpenAPI contract, on toy scores and a SQLAlchemy-backed store (SQLite by default, `DATABASE_URL`-configured)
- [x] Frontend wired to the real backend over HTTP (`httpApi.js`) instead of the in-browser mock
- [x] Table, podium, week, cumulative and rolling windows, weights, breakdowns
- [x] Commitments-based adjustment with a capped factor, the 100 ceiling and raw-score tie-breaks
- [x] Risk digest, risk records with evidence and history, instructor notes, student standing
- [x] Roles and privacy scoping enforced on the server
- [x] Student self-service for commitments (baseline submission, weekly updates) with instructor approval, effective-week choice and reversal
- [ ] Animated reveal, replay, streaks and badges
- [x] Postgres `AppStore` in production: the deployed dev and prod services run on Neon Postgres (see [Deployment](deployment.md))
- [x] Alert on failing commitment submissions, shown firing (see [`ops/alerts/`](../ops/alerts/README.md))
- [ ] Google Sheets adapter and a data check against a real sheet
- [ ] University sign-in (JWT issuance), privacy review, retention and backups before real students use it

The phasing in [`spec.md`](spec.md) holds the plan.
