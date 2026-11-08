# W1 notes: earthquake and wildfire rule packs

Status: ILLUSTRATIVE. Every threshold below is a demonstration value, not validated against an authoritative standard (SDD 11.3). Not for operational use.

## Files

Created:
- backend/app/rules/generic.py: shared hash-checked loader and deterministic evaluator (PackSpec per hazard).
- backend/app/rules/earthquake.py and backend/app/rules/earthquake_v1.json: earthquake pack.
- backend/app/rules/wildfire.py and backend/app/rules/wildfire_v1.json: wildfire and smoke pack.
- datasets/samples/wildfire_sample.csv: 12 rows, expected counts in the test file.
- backend/tests/test_earthquake_wildfire_rules.py.
- docs/notes/w1-rules.md (this file).

Changed:
- backend/app/routes/hazards.py: Pack literal is flood | tsunami | earthquake | wildfire. Missing required columns return 422 VALIDATION_FAILED. The response `rule_pack` now carries `countries` for every pack (missing field means []).
- frontend/js/views/hazards.js: two new entries in PACKS (Earthquake, Wildfire and smoke).

Not touched: flood_v1.json, tsunami_v1.json, tsunami.py, engine.py. Their hashes are unchanged.

## Thresholds chosen (illustrative)

Earthquake (`magnitude` required; `coastal` optional, true/false/yes/no/1/0):
- EQ-R1: magnitude >= 5.0 gives at least LOW.
- EQ-R2: magnitude >= 6.0 gives MEDIUM.
- EQ-R3: magnitude >= 7.0 gives HIGH.
- EQ-R4: magnitude >= 7.0 and coastal = true gives flag `tsunami_check_candidate`. Not a tsunami warning.

Wildfire (`distance_km` required, distance from nearest settlement; `wind_kmh` optional):
- WF-R1: distance_km <= 5 gives MEDIUM.
- WF-R2: distance_km <= 2 gives HIGH.
- WF-R3: distance_km <= 10 and wind_kmh >= 20 gives flag `smoke_exposure_candidate`.

## Behaviour decisions

- Unknown is not zero. A missing or blank value that a severity rule needs gives UNKNOWN.
- An undecided flag rule never changes severity. For example, a fire 5.1 km away with unknown wind is LOW, not UNKNOWN. The flag is simply not set.
- Highest fired severity wins.
- Country: `countries` is an optional list of ISO 3166-1 alpha-2 codes. Missing means any country. Invalid codes are refused at load time.
- Output uses `tool` = earthquake_analyzer or wildfire_analyzer, `flag_counts` per flag, and `results` rows with district and the input columns.

## Test results

Command: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_earthquake_wildfire_rules.py tests/test_hazards_api.py tests/test_tsunami_rules.py -p no:warnings -o addopts="" -q`
Result: 64 passed.

## Requests for other files (owner)

1. backend/tests/test_hazards_api.py, `test_unknown_pack_is_refused`: it uses pack="wildfire" to mean an unknown pack. Wildfire is now a real pack, so this test passes only because the flood CSV lacks distance_km. Please change the pack name to something that is not a pack, for example "volcano", so the test checks what its name says.
2. backend/app/agent/tools.py and mock_script.py: optional. The agent tool list only describes flood and tsunami. If the agent should use the new packs, that needs a separate change and its own review.
3. frontend: the Rows table and candidate panels only show district and row fields. Flag counts (`flag_counts`) are not shown yet. Optional follow-up in hazards.js (outside the pack selector scope).
