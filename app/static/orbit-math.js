const RAD = Math.PI / 180;
export const EARTH_RADIUS_KM = 6378.137;
const julian = (at) => Date.parse(at) / 86400000 + 2440587.5;

// Vallado GMST: UTC approximates UT1 for this visualization (no polar motion).
export function earthRotation(at) {
  const jd = julian(at), t = (jd - 2451545) / 36525;
  const degrees = 280.46061837 + 360.98564736629 * (jd - 2451545)
    + 0.000387933 * t * t - t * t * t / 38710000;
  return ((degrees % 360 + 360) % 360) * RAD;
}

// Same low-precision solar ephemeris as app/orbit.py, in equatorial axes.
export function sunDirection(at) {
  const n = julian(at) - 2451545;
  const g = (357.528 + 0.9856003 * n) * RAD;
  const longitude = (280.460 + 0.9856474 * n
    + 1.915 * Math.sin(g) + 0.020 * Math.sin(2 * g)) * RAD;
  const obliquity = (23.439 - 0.0000004 * n) * RAD;
  return [Math.cos(longitude), Math.cos(obliquity) * Math.sin(longitude),
    Math.sin(obliquity) * Math.sin(longitude)];
}

// Right-handed mapping: equatorial north becomes Three.js +Y.
export const sceneVector = ([x, y, z]) => [x, z, -y];
export const scenePosition = (position) =>
  sceneVector(position).map((value) => value / EARTH_RADIUS_KM);

// Interpolate the short orbital arc, keeping the sampled radius rather than
// cutting a straight chord through the Earth. This affects display only.
export function orbitSample(orbit, position) {
  if (!orbit.length) return null;
  const index = Math.max(0, Math.min(orbit.length - 1, position));
  const i = Math.floor(index), t = index - i, a = orbit[i], b = orbit[i + 1];
  if (!b || t === 0) return a;
  const ra = Math.hypot(...a.position_teme_km), rb = Math.hypot(...b.position_teme_km);
  const u = a.position_teme_km.map(v => v / ra), v = b.position_teme_km.map(v => v / rb);
  const angle = Math.acos(Math.max(-1, Math.min(1, u.reduce((s, x, j) => s + x * v[j], 0))));
  const sa = angle < 1e-8 ? 1 - t : Math.sin((1 - t) * angle) / Math.sin(angle);
  const sb = angle < 1e-8 ? t : Math.sin(t * angle) / Math.sin(angle);
  const radius = ra + (rb - ra) * t;
  return {...a, at: new Date(Date.parse(a.at) + (Date.parse(b.at) - Date.parse(a.at)) * t).toISOString(),
    position_teme_km: u.map((x, j) => radius * (sa * x + sb * v[j]))};
}

export function sampleAtTime(orbit, at) {
  if (!orbit.length || at <= Date.parse(orbit[0].at)) return 0;
  const next = orbit.findIndex(s => Date.parse(s.at) > at);
  if (next < 0) return orbit.length - 1;
  const start = Date.parse(orbit[next - 1].at);
  return next - 1 + (at - start) / (Date.parse(orbit[next].at) - start);
}
