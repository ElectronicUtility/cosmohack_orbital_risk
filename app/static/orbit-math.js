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
