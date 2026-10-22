# Alerts

Alert rules for the deployed demo, exported from Grafana Cloud (Alerting, More, Export, YAML).

## Commitment submissions failing (dev)

[`commitment-submissions-failing-dev.yaml`](commitment-submissions-failing-dev.yaml)

Fires when **3 or more** `PUT /me/commitments/weeks/{weekNumber}` requests on the dev service return a 5xx within 5 minutes, and stays that way for 2 minutes. It uses the journey metric `league_table_requests_total` (see the Observability section of the main README).

| Setting | Value |
|---|---|
| Query | `sum(increase(league_table_requests_total{http_route="/me/commitments/weeks/{weekNumber}", http_status_class="5xx", deployment_environment="dev"}[5m]))` |
| Condition | above 2 |
| Evaluation | every 1m, pending for 2m |
| No data | OK (a healthy service has no 5xx series) |
| Notification | email contact point |

The rule carries no student data: it counts requests by route template and status class only.

### Evidence

On 2026-10-22 the rule was shown firing and resolving on the dev service by turning on the demo fault switch (`FAULT_COMMITMENT_ERRORS=1`, see the main README) and submitting weekly commitments, which each returned 500.

- Grafana Alert activity showed the rule in the `league-table` folder go from Pending to Firing.
- Notification emails received, in order: `[FIRING:1] Commitment submissions failing (dev) league-table`, and after the switch was turned off, `[RESOLVED] Commitment submissions failing (dev) league-table`.

### Importing the rule

In Grafana: Alerting, Alert rules, New alert rule, Import (or provision the YAML through the Grafana provisioning API). The data source UID `grafanacloud-prom` and the contact point name in the file belong to the original stack; change them if you import into another one.

### Reproducing the test

1. In Render, set `FAULT_COMMITMENT_ERRORS=1` on `league-table-dev`, save and restart the service.
2. Send a few valid `PUT /me/commitments/weeks/{n}` requests as a student. Each returns 500.
3. Within about 5 minutes the rule goes Pending, then Firing, and an email is sent.
4. Remove the variable and restart. The rule returns to Normal and a resolved email is sent.
