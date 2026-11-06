// Geographic projection for frontend/assets/world-map.svg. Pure functions, no DOM access, so they can be
// tested in Node (see the spot checks in the build notes).
//
// The map is the upstream world-map-data outline set, Miller cylindrical (ESRI:54003 family), drawn in a
// 2400 x 1200 viewBox. Miller forward formula: y_m = 1.25 * ln(tan(pi/4 + 0.4 * phi)), x = lon in radians.
// The viewBox is an empirical linear fit of that projection, not the raw R * lambda extent:
// the constants below were fitted by least squares against the bounding boxes of reference countries
// (Iceland, South Africa, New Zealand, India, Chile). Fit residuals: x under 0.5 units, y under 9 units.
// The vertical fit is confirmed at both ends: the northernmost Canadian island (Ellesmere, about 83.1 N)
// lands at y about 8, and the South Sandwich Islands (about 59.4 S) land at y about 1198.
// The x axis wraps: longitudes are mapped into [X_LON_MIN, X_LON_MIN + 360), so the Pacific islands
// east of 180 degrees (for example, Hawaii's north-west chain) fall inside the viewBox.

export const WORLD_VIEWBOX = Object.freeze({ width: 2400, height: 1200 });

const X_PER_DEG = 6.601; // SVG units per degree of longitude
const X_AT_LON_ZERO = 1117.15; // SVG x of longitude 0
const Y_PER_MILLER = 380.64; // SVG units per unit of Miller y (y grows southward)
const Y_AT_MILLER_ZERO = 750.35; // SVG y where Miller y is 0 (the equator)
const LAT_LIMIT = 85; // Miller is undefined at the poles; the data never goes beyond this in practice.
export const X_LON_MIN = -X_AT_LON_ZERO / X_PER_DEG; // about -169.26 degrees

function wrapLon(lon) {
  const span = 360;
  return ((((lon - X_LON_MIN) % span) + span) % span) + X_LON_MIN;
}

// project(lat, lon) -> { x, y } in SVG viewBox units (0..2400 by 0..1200 for the drawn world).
// Returns null when lat or lon is not a finite number inside [-90, 90] and [-180, 180].
// Points outside the drawn world (for example, lat above 83 N) return coordinates outside the viewBox.
export function project(lat, lon) {
  if (typeof lat !== 'number' || typeof lon !== 'number') return null;
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return null;
  const phi = Math.max(-LAT_LIMIT, Math.min(LAT_LIMIT, lat)) * Math.PI / 180;
  const millerY = 1.25 * Math.log(Math.tan(Math.PI / 4 + 0.4 * phi));
  return {
    x: X_AT_LON_ZERO + X_PER_DEG * wrapLon(lon),
    y: Y_AT_MILLER_ZERO - Y_PER_MILLER * millerY,
  };
}

// True when a projected point lies inside the drawn viewBox (with a small margin for markers).
export function isInWorldView(point, margin = 0) {
  return !!point
    && point.x >= -margin && point.x <= WORLD_VIEWBOX.width + margin
    && point.y >= -margin && point.y <= WORLD_VIEWBOX.height + margin;
}
