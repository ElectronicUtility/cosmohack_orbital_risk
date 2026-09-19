import test from "node:test";
import assert from "node:assert/strict";
import { earthRotation, sunDirection, scenePosition, sceneVector, EARTH_RADIUS_KM } from "../app/static/orbit-math.js";
import { SphereGeometry, Vector3, Matrix4 } from "../app/static/vendor/three/three.module.min.js";

const close = (actual, expected, tolerance = 1e-8) =>
  assert.ok(Math.abs(actual - expected) < tolerance, `${actual} != ${expected}`);

test("GMST matches the J2000 reference and advances one turn per sidereal day", () => {
  const at = "2000-01-01T12:00:00Z";
  close(earthRotation(at), 280.46061837 * Math.PI / 180);
  const later = new Date(Date.parse(at) + 86164091).toISOString();
  close(earthRotation(later), earthRotation(at), 1e-6);
});

test("solar direction agrees with Python analysis at equinox, solstice and sample time", () => {
  const references = [
    ["2024-03-20T03:06:00Z", [0.9999999977468909, 0.00006159086187618263, 0.00002669801713386445]],
    ["2024-06-20T20:51:00Z", [-0.0000306281251763259, 0.917508899743521, 0.3977152473231966]],
    ["2024-05-05T01:00:00Z", [0.706618291697189, 0.6492245571541684, 0.2814215063333296]],
  ];
  for (const [at, expected] of references) {
    const actual = sunDirection(at);
    actual.forEach((value, index) => close(value, expected[index]));
    close(Math.hypot(...actual), 1);
  }
});

test("Greenwich is on the day side at equinox noon and night side twelve hours later", () => {
  for (const [at, sign] of [["2024-03-20T12:00:00Z", 1], ["2024-03-21T00:00:00Z", -1]]) {
    const sun = new Vector3(...sceneVector(sunDirection(at)));
    const greenwich = new Vector3(1, 0, 0).applyAxisAngle(new Vector3(0, 1, 0), earthRotation(at));
    assert.ok(sign * sun.dot(greenwich) > 0.99);
  }
});

test("texture Greenwich and east longitude match orbital coordinates after Earth rotation", () => {
  const sphere = new SphereGeometry(1, 8, 4);
  const uv = sphere.attributes.uv, position = sphere.attributes.position;
  const rotation = earthRotation("2024-05-05T01:00:00Z");
  for (const [u, longitude] of [[0.5, 0], [0.75, Math.PI / 2]]) {
    let index = -1;
    for (let i = 0; i < uv.count; i++)
      if (uv.getX(i) === u && uv.getY(i) === 0.5) index = i;
    assert.notEqual(index, -1);
    const rendered = new Vector3().fromBufferAttribute(position, index)
      .applyMatrix4(new Matrix4().makeRotationY(rotation));
    const inertial = scenePosition([
      EARTH_RADIUS_KM * Math.cos(longitude + rotation),
      EARTH_RADIUS_KM * Math.sin(longitude + rotation), 0,
    ]);
    rendered.toArray().forEach((value, i) => close(value, inertial[i], 1e-7));
  }
  sphere.dispose();
});

test("coordinate mapping preserves altitude and north pole orientation", () => {
  close(Math.hypot(...scenePosition([EARTH_RADIUS_KM + 410, 0, 0])), 1 + 410 / EARTH_RADIUS_KM);
  assert.deepEqual(scenePosition([0, 0, EARTH_RADIUS_KM]), [0, 1, -0]);
});

test('playback interpolates an orbital arc without losing altitude and keeps UTC continuous', async () => {
  const { orbitSample } = await import('../app/static/orbit-math.js');
  const radius = 6800, angle = Math.PI / 6;
  const orbit = [
    {at: '2024-05-05T01:00:00Z', position_teme_km: [radius, 0, 0]},
    {at: '2024-05-05T01:05:00Z', position_teme_km: [radius * Math.cos(angle), radius * Math.sin(angle), 0]},
  ];
  for (const t of [.01, .25, .5, .75, .99]) {
    const sample = orbitSample(orbit, t);
    assert.ok(Math.abs(Math.hypot(...sample.position_teme_km) - radius) < 1e-8);
    assert.ok(Math.abs(Math.atan2(sample.position_teme_km[1], sample.position_teme_km[0]) - angle*t) < 1e-12);
    assert.equal(Date.parse(sample.at), Date.parse(orbit[0].at) + 300000*t);
  }
  assert.equal(orbitSample(orbit, -1), orbit[0]);
  assert.equal(orbitSample(orbit, 5), orbit[1]);
  assert.equal(orbitSample([], 0), null);
});

test('playback time advances evenly across a shorter final sample interval', async () => {
  const { sampleAtTime, orbitSample } = await import('../app/static/orbit-math.js');
  const orbit = ['01:00:00', '01:05:00', '01:06:00'].map(time => ({
    at: `2024-05-05T${time}Z`, position_teme_km: [6800, 0, 0],
  }));
  for (const seconds of [30, 150, 300, 315, 330, 359]) {
    const at = Date.parse(orbit[0].at) + seconds * 1000;
    assert.equal(Date.parse(orbitSample(orbit, sampleAtTime(orbit, at)).at), at);
  }
  assert.equal(sampleAtTime(orbit, Date.parse(orbit[2].at) + 1000), 2);
});
