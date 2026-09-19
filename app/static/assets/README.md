# Scene assets and geometry

- `earth-blue-marble.png`: NASA/Goddard Space Flight Center Scientific Visualization Studio, Blue Marble, 2048 × 1024. Credit: NASA/GSFC, Reto Stockli and NASA Earth Observatory. https://svs.gsfc.nasa.gov/2915/
  Download (NASA asset mirror): https://assets.science.nasa.gov/content/dam/science/cds/svs/a000000/a002900/a002915/bluemarble-2048.png
- `earth-night.png`: NASA Earth at Night, 2048 × 1024. Data: Marc Imhoff (NASA/GSFC), Christopher Elvidge (NOAA/NGDC). Image: Craig Mayhew and Robert Simmon (NASA/GSFC). https://svs.gsfc.nasa.gov/2916/
- `iss.glb`: International Space Station (ISS) (A), NASA/Ames Research Center. Original NASA glTF model, unmodified. https://science.nasa.gov/3d-resources/international-space-station-iss-a/
- Renderer: Three.js 0.180.0, vendored under `../vendor/three/`, including its MIT license and Draco decoder. All runtime assets are served locally.

Earth texture longitude 0 maps to +X before GMST rotation. TEME positions and the equatorial Sun vector use the same right-handed mapping into the renderer: [x, y, z] → [x, z, -y]. Earth radius is 6378.137 km. Surface rotation uses Vallado GMST with UTC approximating UT1, without polar motion. Sun direction uses the same low-precision equatorial approximation as `app/orbit.py`; this is visualization accuracy, not a high-precision apparent solar ephemeris.

The selected orbit sample timestamp controls Earth rotation, Sun direction and ISS position. The texture is a static satellite composite, not live clouds. ISS size is exaggerated to stay visible, and its nadir-facing attitude is representative, not attitude telemetry. Intermediate orbit-line vertices use spherical interpolation for display only and do not feed back into analysis. WebGL depth testing hides the station and orbit behind Earth; Earth casts the station's night-side shadow.
