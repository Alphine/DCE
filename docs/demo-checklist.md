# Demo checklist (submission day)

Use this order. Each step says what the juror should see. Run the full path once before going on stage.

## 0. Before the demo (10 minutes)

- [ ] Open https://commander.basyid.dev in a clean browser window. Check the sign-in page loads.
- [ ] Sign in as `analyst` and check the Command Center shows numbers (not all zeros).
- [ ] Check these datasets are APPROVED: flood incidents, wildfire, earthquake, logistics.
- [ ] Check at least one simulation run, one verified report, one approved mission, two shelters, one published warning.
- [ ] Check the public warnings page `https://commander.basyid.dev/#/public` opens without login.
- [ ] Have the offline video and the screenshots ready in case the venue network fails.

## 1. Story (1 minute)

Say: a flood and a wildfire hit two countries at once. Field reports come in, an analyst checks them, a rule pack gives the impact, a simulation shows the next 24 hours, and an approver decides the response. Every number says whether it is observed, verified, simulated, or a decision.

## 2. Command Center (2 minutes)

- Status bar: critical and high alerts, decisions waiting for you, UTC and local clock.
- Decision queue on the left: oldest first, with who must decide.
- Map in the centre: point layers and country outlines (Natural Earth, public domain).
- Say the one-liner about data classes.

## 3. Situation (1 minute)

- Filter by country (ID, GR, JP).
- Click a point: its details and data class.

## 4. Datasets (1 minute)

- Open a dataset: column profile, five-row preview, SHA-256, who uploaded it.
- Point out that the uploader cannot approve their own dataset.

## 5. Hazard Intelligence (2 minutes)

- The newest flood dataset is analysed on opening.
- Show severity chips, road-blocked candidates, the rule pack version and hash.
- Say: thresholds are illustrative and not validated. This is said on screen.
- Switch to the wildfire pack for the smoke candidates.

## 6. Simulation and Planning (2 minutes)

- The newest run opens: timeline, peak hour, peak by district.
- Say: the run is reproducible. Same inputs, same output hash.
- Open Planning: per-district allocation in priority order. Point out "not estimated" (medical, rescue, transport).

## 7. Logistics (1 minute)

- Shelters, stock, teams, vehicles. Show a coverage gap.

## 8. Missions and the human gate (2 minutes)

- Open the approved mission. Show the decision history and the content hash.
- Say: an approver who did not propose it must decide. Sign in as `approver` to show the approve button only for approvers.

## 9. Alerts and public warnings (2 minutes)

- Alerts list and the summary numbers.
- Open `#/public` in a new window with no login. Say: only published warnings are public, in English or Indonesian.

## 10. AI agent (optional, 1 minute)

- Show the agent task list. Say: the model only plans. The plan is checked against a schema and a tool list before anything runs, and a human approves it at gate A.
- Do not promise a live run. If the planner fails, say so and show the reason code. That is the safety check working.

## 11. Installers and offline (1 minute)

- Show the Windows installer (NSIS). Say: it is not yet code-signed, and the first start needs the network.
- Say: offline reading works for data already seen on the device. Offline sign-in is planned, not built.

## 12. Honest limits (say these every time)

- Rule thresholds are illustrative.
- Simulations are not observations.
- Not for operational use without validation by an authoritative source.
- Map data: Natural Earth (public domain) and Leaflet (BSD 2-Clause). No online tiles.

## If something fails on stage

| Problem | What to do |
| --- | --- |
| Site does not load | Switch to the video. Say the server is being checked. |
| Login fails | Use the screenshots of the signed-in screens. |
| Agent task fails | Show the reason code. Explain the schema gate. Move on. |
| Map is empty | Use the Situation table; the points are the same data. |
