import { shadowAt } from "./model.js?v=20260919-7";
import * as THREE from "./vendor/three/three.module.min.js";
import { GLTFLoader } from "./vendor/three/GLTFLoader.js";
import { DRACOLoader } from "./vendor/three/DRACOLoader.js";
import {
  earthRotation,
  sunDirection,
  scenePosition,
  sceneVector,
} from "./orbit-math.js";

export class OrbitScene {
  constructor(canvas) {
    this.canvas = canvas;
    this.windows = [];
    this.selected = 0;
    this.sample = 0;
    this.yaw = 0.4;
    this.pitch = 0.35;
    this.zoom = 1;
    this.note = document.getElementById("orbit-render-status");
    this.stationLabel = document.getElementById("station-label");
    try {
      this.renderer = new THREE.WebGLRenderer({
        canvas,
        antialias: true,
        alpha: true,
      });
    } catch {
      this.message("Для 3D нужен WebGL. Расчёты доступны ниже.");
      return;
    }
    this.renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.scene = new THREE.Scene();
    this.camera = new THREE.OrthographicCamera(-2, 2, 1.65, -1.65, 0.1, 20);
    this.scene.add(new THREE.AmbientLight(0xffffff, 0.12));
    this.sun = new THREE.DirectionalLight(0xffffff, 2.8);
    this.sun.castShadow = true;
    Object.assign(this.sun.shadow.camera, {
      left: -1.5,
      right: 1.5,
      top: 1.5,
      bottom: -1.5,
      near: 0.1,
      far: 10,
    });
    this.sun.shadow.mapSize.set(1024, 1024);
    this.sun.shadow.bias = -0.0002;
    this.scene.add(this.sun);
    this.earth = new THREE.Mesh(
      new THREE.SphereGeometry(1, 96, 64),
      new THREE.MeshPhongMaterial({
        color: 0xffffff,
        shininess: 6,
        specular: 0x182432,
      }),
    );
    this.solarDirection = { value: new THREE.Vector3(1, 0, 0) };
    this.earth.material.onBeforeCompile = (shader) => {
      shader.uniforms.solarDirection = this.solarDirection;
      shader.vertexShader =
        "uniform vec3 solarDirection; varying float solarAltitude;\n" +
        shader.vertexShader;
      shader.vertexShader = shader.vertexShader.replace(
        "#include <begin_vertex>",
        "#include <begin_vertex>\nsolarAltitude = dot(normalize(mat3(modelMatrix) * normal), solarDirection);",
      );
      shader.fragmentShader =
        "varying float solarAltitude;\n" + shader.fragmentShader;
      shader.fragmentShader = shader.fragmentShader.replace(
        "#include <emissivemap_fragment>",
        "#include <emissivemap_fragment>\ntotalEmissiveRadiance *= 1.0 - smoothstep(-0.08, 0.08, solarAltitude);",
      );
    };
    this.earth.castShadow = true;
    this.scene.add(this.earth);
    this.paths = new THREE.Group();
    this.station = new THREE.Group();
    this.scene.add(this.paths, this.station);
    this.message("Загрузка Земли и МКС…");
    this.loadAssets();
    this.observer = new ResizeObserver(() => this.draw());
    this.observer.observe(canvas.parentElement);
    let drag = null;
    canvas.addEventListener("pointerdown", (e) => {
      drag = { x: e.clientX, y: e.clientY };
      canvas.setPointerCapture(e.pointerId);
    });
    canvas.addEventListener("pointermove", (e) => {
      if (!drag) return;
      this.yaw -= (e.clientX - drag.x) * 0.007;
      this.pitch = Math.max(
        -1.3,
        Math.min(1.3, this.pitch + (e.clientY - drag.y) * 0.006),
      );
      drag = { x: e.clientX, y: e.clientY };
      this.draw();
    });
    for (const event of ["pointerup", "pointercancel", "lostpointercapture"])
      canvas.addEventListener(event, () => (drag = null));
    canvas.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        this.zoom = Math.max(
          0.8,
          Math.min(2, this.zoom * Math.exp(-e.deltaY * 0.001)),
        );
        this.draw();
      },
      { passive: false },
    );
    canvas.addEventListener("webglcontextlost", (e) => {
      e.preventDefault();
      this.message("3D приостановлено. Обновите страницу.");
    });
  }
  message(text) {
    this.note.textContent = text;
    this.note.hidden = !text;
  }
  async loadAssets() {
    const draco = new DRACOLoader();
    draco.setDecoderPath(new URL("./vendor/three/draco/", import.meta.url).href);
    const loader = new GLTFLoader().setDRACOLoader(draco);
    const results = await Promise.allSettled([
      new THREE.TextureLoader().loadAsync(
        new URL("./assets/earth-blue-marble.png", import.meta.url).href,
      ),
      loader.loadAsync(new URL("./assets/iss.glb", import.meta.url).href),
      new THREE.TextureLoader().loadAsync(new URL("./assets/earth-night.png", import.meta.url).href),
    ]);
    if (results[0].status === "fulfilled") {
      const texture = results[0].value;
      texture.colorSpace = THREE.SRGBColorSpace;
      texture.anisotropy = Math.min(
        8,
        this.renderer.capabilities.getMaxAnisotropy(),
      );
      this.earth.material.map = texture;
      this.earth.material.needsUpdate = true;
    }
    if (results[2].status === "fulfilled") {
      const texture = results[2].value;
      texture.colorSpace = THREE.SRGBColorSpace;
      this.earth.material.emissiveMap = texture;
      this.earth.material.emissive.set(0xffffff);
      this.earth.material.emissiveIntensity = 0.8;
      this.earth.material.needsUpdate = true;
    }
    if (results[1].status === "fulfilled") {
      const model = results[1].value.scene;
      const box = new THREE.Box3().setFromObject(model);
      const size = box.getSize(new THREE.Vector3());
      const center = box.getCenter(new THREE.Vector3());
      // Exaggerated size for visibility; position remains on the measured orbit.
      const scale = 0.3 / Math.max(size.x, size.y, size.z);
      model.scale.setScalar(scale);
      model.position.copy(center).multiplyScalar(-scale);
      model.traverse((node) => {
        if (!node.isMesh) return;
        node.castShadow = true;
        node.receiveShadow = true;
      });
      this.station.add(model);
    }
    draco.dispose();
    this.canvas.dataset.assets = results.every((r) => r.status === "fulfilled")
      ? "ready"
      : "error";
    this.message(
      results.some((r) => r.status === "rejected")
        ? "Не удалось загрузить 3D-ресурсы. Обновите страницу."
        : "",
    );
    this.draw();
  }
  setData(windows, selected, sample = 0) {
    const changed = this.windows !== windows || this.selected !== selected;
    this.windows = windows;
    this.selected = selected;
    this.sample = sample;
    if (!this.renderer) return;
    if (changed) {
      for (const child of [...this.paths.children]) {
        child.geometry.dispose();
        child.material.dispose();
        this.paths.remove(child);
      }
      windows.forEach((window, index) => {
        const points = window.orbit.map(
          (state) =>
            new THREE.Vector3(...scenePosition(state.position_teme_km)),
        );
        if (points.length < 2) return;
        // Spherical interpolation avoids chords cutting through Earth between 5-min samples.
        const vertices = [];
        points.forEach((p, i) => {
          if (i === points.length - 1) return;
          const next = points[i + 1],
            a = p.clone().normalize(),
            b = next.clone().normalize();
          const angle = a.angleTo(b);
          for (let j = 0; j < 12; j++) {
            const t = j / 12;
            const direction =
              angle < 1e-6
                ? a.clone()
                : a
                    .clone()
                    .multiplyScalar(Math.sin((1 - t) * angle))
                    .addScaledVector(b, Math.sin(t * angle))
                    .divideScalar(Math.sin(angle));
            vertices.push(
              direction.multiplyScalar(
                THREE.MathUtils.lerp(p.length(), next.length(), t),
              ),
            );
          }
        });
        vertices.push(points.at(-1));
        const positions = [],
          colors = [];
        const lighting = window.factors.find((f) => f.mechanism === "lighting");
        for (let j = 0; j < vertices.length - 1; j++) {
          const segment = Math.floor(j / 12),
            fraction = ((j % 12) + 0.5) / 12;
          const a = window.orbit[segment],
            b = window.orbit[Math.min(segment + 1, window.orbit.length - 1)];
          const time =
            Date.parse(a.at) + (Date.parse(b.at) - Date.parse(a.at)) * fraction;
          const color = new THREE.Color(
            index !== selected
              ? 0x9daec4
              : shadowAt(lighting, time)
                ? 0xa36416
                : 0x245ac5,
          );
          for (const v of [vertices[j], vertices[j + 1]]) {
            positions.push(v.x, v.y, v.z);
            colors.push(color.r, color.g, color.b);
          }
        }
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute(
          "position",
          new THREE.Float32BufferAttribute(positions, 3),
        );
        geometry.setAttribute(
          "color",
          new THREE.Float32BufferAttribute(colors, 3),
        );
        const line = new THREE.LineSegments(
          geometry,
          new THREE.LineBasicMaterial({
            vertexColors: true,
            transparent: true,
            opacity: index === selected ? 1 : 0.16,
          }),
        );
        this.paths.add(line);
      });
    }
    this.draw();
  }
  reset() {
    const state = this.windows[this.selected]?.orbit[this.sample];
    if (state) {
      const radial = new THREE.Vector3(
        ...scenePosition(state.position_teme_km),
      ).normalize();
      const sun = new THREE.Vector3(...sceneVector(sunDirection(state.at)));
      const tangent = sun.clone().addScaledVector(radial, -sun.dot(radial));
      if (tangent.lengthSq() < 1e-6)
        tangent.crossVectors(radial, new THREE.Vector3(0, 1, 0));
      const view = radial
        .multiplyScalar(0.48)
        .addScaledVector(tangent.normalize(), 0.88)
        .normalize();
      this.yaw = Math.atan2(view.x, view.z);
      this.pitch = Math.asin(view.y);
    } else {
      this.yaw = 0.4;
      this.pitch = 0.35;
    }
    this.zoom = 1;
    this.draw();
  }
  rotate(delta) {
    this.yaw += delta;
    this.draw();
  }
  draw() {
    if (!this.renderer) return;
    const { width, height } = this.canvas.parentElement.getBoundingClientRect();
    if (!width || !height) return;
    this.renderer.setSize(width, height, false);
    const halfHeight = Math.max(1.6, (1.4 * height) / width) / this.zoom;
    this.camera.left = (-halfHeight * width) / height;
    this.camera.right = (halfHeight * width) / height;
    this.camera.top = halfHeight;
    this.camera.bottom = -halfHeight;
    this.camera.position.set(
      5 * Math.cos(this.pitch) * Math.sin(this.yaw),
      5 * Math.sin(this.pitch),
      5 * Math.cos(this.pitch) * Math.cos(this.yaw),
    );
    this.camera.lookAt(0, 0, 0);
    this.camera.updateProjectionMatrix();
    const orbit = this.windows[this.selected]?.orbit || [];
    const state = orbit[this.sample];
    this.station.visible = !!state;
    this.stationLabel.hidden = !state;
    if (state) {
      this.earth.rotation.y = earthRotation(state.at);
      this.solarDirection.value.set(...sceneVector(sunDirection(state.at)));
      this.sun.position.copy(this.solarDirection.value).multiplyScalar(5);
      this.station.position.set(...scenePosition(state.position_teme_km));
      // Representative nadir-facing attitude, not live ISS attitude telemetry.
      const radial = this.station.position.clone().normalize();
      this.station.quaternion.setFromUnitVectors(
        new THREE.Vector3(0, 1, 0),
        radial,
      );
      this.canvas.dataset.time = state.at;
      this.canvas.dataset.earthRotation = this.earth.rotation.y;
    }
    this.renderer.render(this.scene, this.camera);
    if (state) {
      const projected = this.station.position.clone().project(this.camera);
      const towardsCamera = this.camera.position.clone().normalize();
      const depth = this.station.position.dot(towardsCamera);
      const distanceFromAxis = this.station.position
        .clone()
        .addScaledVector(towardsCamera, -depth)
        .length();
      const behind = depth < 0 && distanceFromAxis < 1;
      this.stationLabel.hidden =
        Math.abs(projected.x) > 0.9 || Math.abs(projected.y) > 0.9;
      this.stationLabel.textContent = behind ? "МКС за Землёй" : "МКС";
      this.stationLabel.style.left = `${((projected.x + 1) * width) / 2}px`;
      this.stationLabel.style.top = `${((1 - projected.y) * height) / 2}px`;
    }
  }
}
