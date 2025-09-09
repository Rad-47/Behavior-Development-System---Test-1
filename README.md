
# BCAT Zero‑Touch (AUTO Pattern)

**No Pattern ID to enter.** The system will either:
1) Use your **Team/Scenario → Pattern** map (if a match exists), or
2) Compute **alignment against all 24 patterns** and automatically pick the best match.

## Use (no coding)
1) Install Docker Desktop.
2) Unzip this folder.
3) Run: `docker compose up --build -d`
4) Visit **http://localhost:8090/setup** and enter Spiky API URL, email, password.
5) (Optional) Visit **/map** to add explicit mappings like:
   ```json
   {"team":{"sales-east":15,"cs-apac":21}, "scenario":{"demo":7,"discovery":11}}
   ```
6) Drop videos into `./data/in/`. Results appear in `./data/out/` and at **http://localhost:8090**.

## Outputs
- `<video>.spiky.json` — raw Spiky metrics
- `<video>.bcat.json` — includes the **chosen pattern** (mapped or auto-best) and the **BCAT scores**

## API
The scorer runs at `http://localhost:8080/score`:
- If you send **no pattern**, it returns `{ "best": ..., "all": {...} }` with the best of 24.
- If you send a pattern (id/name/order), it scores that one.

## Notes
- The Team/Scenario mapping looks for `team_id` / `scenario_id` under either `ml.meta` or `ml.session`.
- For production, switch to token-based auth or a secrets vault.
