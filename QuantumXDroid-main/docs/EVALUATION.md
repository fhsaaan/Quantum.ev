# Quantum.ev evaluation (2026-11-01)

**Verdict: before this work it was a strong hackathon prototype, not a deployable product. It is now a solid localhost demo, not a production fleet system.**

## What held up

- The QUBO, Ising and XY-mixer maths is correct and tested. The results are reproducible, and the code is small and readable.
- The XY-mixer result is real: 69-80% valid shots at 12 qubits, against 10-25% for the standard mixer.
- The experiment design is honest. It includes classical controls and a noise model.

## README claims that did not match the results

| Claim | Measured | Status |
| :--- | :--- | :--- |
| 15-25% energy cost reduction | 0-10.1% total cost saved | Removed |
| 20-33% peak shaving | Peak stayed the same or rose in all 12 runs, and peak is not in the objective | Removed |
| Sub-15 s re-optimisation | QAOA 37-81 s | Removed |
| Exact solvers time out | Proven optimum in about 2 s or less at 200 cars | Removed |
| ₹1,744 table, "0.00% gap", "100% wait elimination" | Figures appear in no results file | Removed |
| 100% feasibility | 69-80% valid; 51-79% under simulated noise | Corrected |
| KSEB tariff | Code calls the tariff illustrative | Corrected |
| OpenChargeMap live and connected | A saved snapshot file | Corrected |
| MIT licence badge | No licence file | Added MIT licence |

## Code problems fixed

- `debug=True` on `0.0.0.0` exposed the Werkzeug debugger, which allows remote code execution.
- If QAOA crashed, the app silently returned the baseline labelled as the quantum result.
- API input was not validated, so bad data caused 500 errors.
- There was no stable server option, health check, CI or pinned dependencies. Waitress, `/healthz`, a CI workflow and pinned versions were added. Docker was left out on purpose: the project runs on localhost.

## Still open

- Real data: the fleet is synthetic and there are no live ETAs or charger status.
- Late arrivals: the dispatcher assumes cars arrive on time, so gaps have no safety margin yet.
- Prices: dataset prices of ₹22-27/kWh are not used in the cost model.
- Time slots are 30 minutes, so shorter gaps go unused.
- Data checks: OpenChargeMap records were not verified against the live site, and some coordinates look rounded.
- Product: no login, rate limiting beyond the QAOA gate, database or persistent bookings. The live page is a simulator and does not accept real requests.
