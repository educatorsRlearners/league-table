# Observability and the demo fault switch

Telemetry export and the switch that demonstrates the alert. The alert rule lives in [`ops/alerts/`](../ops/alerts/README.md).

## Observability

The backend can export OpenTelemetry traces, metrics, and logs over OTLP/HTTP to Grafana Cloud. It is off unless `OTEL_EXPORTER_OTLP_ENDPOINT` is set; with it unset the app configures and exports nothing.

| Variable | Meaning |
| --- | --- |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP base URL, e.g. `https://otlp-gateway-prod-eu-west-2.grafana.net/otlp`. Setting it turns telemetry on. |
| `GRAFANA_OTLP_INSTANCE_ID` | Grafana Cloud instance ID (the basic-auth username; not secret). |
| `GRAFANA_OTLP_TOKEN` | Grafana Cloud access token (the password). **Secret.** Set it in the Render dashboard (service > Environment); `render.yaml` declares it with `sync: false` and never holds a value. The `Authorization: Basic` header is built in code, so no base64 step is needed. |
| `OTEL_SERVICE_NAME` | Resource `service.name`; default `league-table`. `render.yaml` sets `league-table-dev` and `league-table-prod`. |
| `DEPLOYMENT_ENV` | Resource `deployment.environment` (`dev` or `prod`). |

What is emitted for the commitment journey (`PUT /me/commitments/weeks/{weekNumber}` and the `GET /me/commitments` page load):

- **Traces**: one server span per request (named by route template) with child spans for the database queries. `/login/options` health checks are not traced.
- **Logs**: one JSON line per request on stdout (also sent over OTLP) with `trace_id` and `span_id` matching the trace.
- **Metrics** for routes under `/me/commitments`, labelled only by `http.route` and `http.status_class` (`2xx`/`4xx`/`5xx`): `league_table.requests`, `league_table.request.errors` (4xx and 5xx), and `league_table.request.duration` (seconds histogram).

No student names or ids, note text, hours values, tokens, or request bodies are recorded: query strings are dropped, URLs are replaced by the route template, and SQL is recorded as the parameterised statement without values. `backend/tests/test_telemetry.py` asserts this with sentinel values.

Finding it in Grafana Cloud (Explore, pick the data source for each signal, and filter `service_name` = `league-table-dev` or `league-table-prod`; `deployment_environment` tells dev from prod):

- **Traces**: Explore > Tempo (`grafanacloud-<stack>-traces`) > Search, service name as above, span name `PUT /me/commitments/weeks/{weekNumber}`. Open a trace to see the database spans.
- **Logs**: Explore > Loki (`grafanacloud-<stack>-logs`), query `{service_name="league-table-prod"} | json`; the `trace_id` field links to the trace.
- **Metrics**: Explore > Prometheus (`grafanacloud-<stack>-prom`), e.g. `sum by (http_route, http_status_class) (rate(league_table_requests_total[5m]))`, `league_table_request_errors_total`, and `histogram_quantile(0.95, sum by (le) (rate(league_table_request_duration_seconds_bucket[5m])))`. Metrics are pushed about once a minute.

Free-tier note: the free Render services sleep when idle, so telemetry from a sleeping service only appears after it wakes.

## Demo fault switch

`FAULT_COMMITMENT_ERRORS` is a **demo-only** switch that produces a real, repeatable fault to show the alerting. It is off by default. Set to `1` or `true` (case-insensitive), `PUT /me/commitments/weeks/{weekNumber}` raises an unhandled error before anything is written and answers HTTP 500; the span is marked as an error, the `league_table.request` log line has `http_status_class` `5xx`, and `league_table_requests_total` counts it under `5xx`. Unset, empty, `0`, `false`, or anything else leaves behaviour unchanged, and no other route is affected. It is read from the environment on every request and cannot be toggled through the API. Never leave it on in production outside a demo. The alert rule that this fault triggers is documented in [`ops/alerts/README.md`](../ops/alerts/README.md).

To turn it on or off in Render: open the service > Environment, set `FAULT_COMMITMENT_ERRORS` to `1` (or delete it / set it to `0`), save, then restart the service so the new value takes effect.
