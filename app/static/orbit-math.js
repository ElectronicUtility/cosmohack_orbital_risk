const RAD = Math.PI / 180;
export const EARTH_RADIUS_KM = 6378.137;

// Display interpolation only: follow the orbital arc rather than a chord through Earth.
export function interpolateOrbit(orbit, index) {
  if (!orbit.length) return null;
  const value = Math.max(
    0,
    Math.min(orbit.length - 1, Number.isFinite(index) ? index : 0),
  );
  const lo = Math.floor(value),
    t = value - lo;
  const a = orbit[lo],
    b = orbit[Math.min(lo + 1, orbit.length - 1)];
  if (!t) return a;
  const ra = Math.hypot(...a.position_teme_km),
    rb = Math.hypot(...b.position_teme_km);
  const u = a.position_teme_km.map((x) => x / ra),
    v = b.position_teme_km.map((x) => x / rb);
  const dot = Math.max(
    -1,
    Math.min(
      1,
      u.reduce((sum, x, i) => sum + x * v[i], 0),
    ),
  );
  const angle = Math.acos(dot);
  let direction;
  if (dot < -0.999999) {
    const axis = Math.abs(u[0]) < 0.9 ? [1, 0, 0] : [0, 1, 0];
    const projection = axis.reduce((sum, x, i) => sum + x * u[i], 0);
    const tangent = axis.map((x, i) => x - projection * u[i]);
    const length = Math.hypot(...tangent);
    direction = u.map(
      (x, i) =>
        x * Math.cos(Math.PI * t) +
        (tangent[i] / length) * Math.sin(Math.PI * t),
    );
  } else {
    direction =
      angle < 1e-6
        ? u.map((x, i) => x * (1 - t) + v[i] * t)
        : u.map(
            (x, i) =>
              (x * Math.sin((1 - t) * angle) + v[i] * Math.sin(t * angle)) /
              Math.sin(angle),
          );
  }
  const scale = (ra + (rb - ra) * t) / Math.hypot(...direction);
  return {
    ...a,
    at: new Date(
      Date.parse(a.at) + (Date.parse(b.at) - Date.parse(a.at)) * t,
    ).toISOString(),
    position_teme_km: direction.map((x) => x * scale),
  };
}
const julian = (at) => Date.parse(at) / 86400000 + 2440587.5;

// Vallado GMST: UTC approximates UT1 for this visualization (no polar motion).
export function earthRotation(at) {
  const jd = julian(at),
    t = (jd - 2451545) / 36525;
  const degrees =
    280.46061837 +
    360.98564736629 * (jd - 2451545) +
    0.000387933 * t * t -
    (t * t * t) / 38710000;
  return (((degrees % 360) + 360) % 360) * RAD;
}

// Same low-precision solar ephemeris as app/orbit.py, in equatorial axes.
export function sunDirection(at) {
  const n = julian(at) - 2451545;
  const g = (357.528 + 0.9856003 * n) * RAD;
  const longitude =
    (280.46 + 0.9856474 * n + 1.915 * Math.sin(g) + 0.02 * Math.sin(2 * g)) *
    RAD;
  const obliquity = (23.439 - 0.0000004 * n) * RAD;
  return [
    Math.cos(longitude),
    Math.cos(obliquity) * Math.sin(longitude),
    Math.sin(obliquity) * Math.sin(longitude),
  ];
}

// Right-handed mapping: equatorial north becomes Three.js +Y.
export const sceneVector = ([x, y, z]) => [x, z, -y];
export const scenePosition = (position) =>
  sceneVector(position).map((value) => value / EARTH_RADIUS_KM);
