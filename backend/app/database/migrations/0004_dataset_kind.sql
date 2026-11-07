-- Dataset kind: CSV (default for existing rows) or GEOJSON (docs/api.md section 3, SDD 17.2).
ALTER TABLE datasets ADD COLUMN kind TEXT NOT NULL DEFAULT 'CSV' CHECK (kind IN ('CSV', 'GEOJSON'));
