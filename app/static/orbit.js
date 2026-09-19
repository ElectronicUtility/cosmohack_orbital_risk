// Canvas renders a schematic orthographic TEME scene, NOT an Earth-fixed map.
// Actual SGP4 positions / Earth radius share a scale. Marker size is exaggerated.
const R = 6378.137,
  TAU = Math.PI * 2;
export class OrbitScene {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.windows = [];
    this.selected = 0;
    this.sample = 0;
    this.yaw = 0.4;
    this.pitch = 0.35;
    this.observer = new ResizeObserver(() => this.draw());
    this.observer.observe(canvas.parentElement);
    let drag = null;
    canvas.addEventListener("pointerdown", (e) => {
      if (e.pointerType === "touch") return;
      drag = { x: e.clientX, y: e.clientY };
      canvas.setPointerCapture(e.pointerId);
    });
    canvas.addEventListener("pointermove", (e) => {
      if (!drag) return;
      this.yaw += (e.clientX - drag.x) * 0.007;
      this.pitch = Math.max(
        -1.3,
        Math.min(1.3, this.pitch + (e.clientY - drag.y) * 0.006),
      );
      drag = { x: e.clientX, y: e.clientY };
      this.draw();
    });
    for (const event of ["pointerup", "pointercancel", "lostpointercapture"])
      canvas.addEventListener(event, () => (drag = null));
  }
  setData(windows, selected, sample = 0) {
    this.windows = windows;
    this.selected = selected;
    this.sample = sample;
    this.draw();
  }
  reset() {
    const p = this.windows[this.selected]?.orbit[0]?.position_teme_km;
    if (p) {
      this.yaw = Math.atan2(p[0], p[1]);
      this.pitch = 0.3;
    } else {
      this.yaw = 0.4;
      this.pitch = 0.35;
    }
    this.draw();
  }
  rotate(delta) {
    this.yaw += delta;
    this.draw();
  }
  draw() {
    const { canvas, ctx: c } = this;
    if (!c) return;
    const box = canvas.parentElement.getBoundingClientRect(),
      w = box.width,
      h = box.height;
    if (!w || !h) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    c.setTransform(dpr, 0, 0, dpr, 0, 0);
    c.clearRect(0, 0, w, h);
    const r = Math.min(w * 0.265, h * 0.365),
      cx = w * 0.55,
      cy = h * 0.55,
      sy = Math.sin(this.yaw),
      co = Math.cos(this.yaw),
      sp = Math.sin(this.pitch),
      cp = Math.cos(this.pitch);
    const project = ([x, y, z]) => {
      const a = x * co - y * sy,
        b = x * sy + y * co;
      return {
        x: cx + (a * r) / R,
        y: cy - ((z * cp - b * sp) * r) / R,
        z: z * sp + b * cp,
      };
    };
    // Faint reticle conveys a coordinate frame rather than a geographical map.
    c.strokeStyle = "#26382e";
    c.lineWidth = 0.6;
    c.setLineDash([3, 8]);
    c.beginPath();
    c.moveTo(cx - r * 1.5, cy);
    c.lineTo(cx + r * 1.5, cy);
    c.moveTo(cx, cy - r * 1.35);
    c.lineTo(cx, cy + r * 1.35);
    c.stroke();
    c.setLineDash([]);
    c.strokeStyle = "#314735";
    c.beginPath();
    c.arc(cx, cy, r * 1.19, 0, TAU);
    c.stroke();
    for (let i = 0; i < 72; i++) {
      const a = (i * TAU) / 72;
      const l = i % 6 ? 3 : 7;
      c.beginPath();
      c.moveTo(
        cx + Math.cos(a) * (r * 1.19 - l),
        cy + Math.sin(a) * (r * 1.19 - l),
      );
      c.lineTo(cx + Math.cos(a) * r * 1.19, cy + Math.sin(a) * r * 1.19);
      c.stroke();
    }
    const paths = this.windows.map((w) =>
      w.orbit.map((s) => project(s.position_teme_km)),
    );
    const line = (ps, color, back = false) => {
      c.strokeStyle = color;
      c.lineWidth = back ? 1 : 1.6;
      c.setLineDash(back ? [3, 5] : []);
      c.beginPath();
      let down = false;
      for (const p of ps) {
        const visible = back ? p.z < 0 : p.z >= 0;
        if (visible) {
          if (down) c.lineTo(p.x, p.y);
          else c.moveTo(p.x, p.y);
          down = true;
        } else down = false;
      }
      c.stroke();
      c.setLineDash([]);
    };
    paths.forEach((p, i) =>
      line(p, i === this.selected ? "#82925c" : "#344439", true),
    );
    const sphere = c.createRadialGradient(
      cx - r * 0.4,
      cy - r * 0.45,
      r * 0.05,
      cx,
      cy,
      r,
    );
    sphere.addColorStop(0, "#345248");
    sphere.addColorStop(0.5, "#203c32");
    sphere.addColorStop(1, "#10251e");
    c.fillStyle = sphere;
    c.beginPath();
    c.arc(cx, cy, r, 0, TAU);
    c.fill();
    c.strokeStyle = "#5f8960";
    c.lineWidth = 1;
    c.stroke();
    const grid = (points) => {
      c.beginPath();
      let down = false;
      for (const p0 of points) {
        const p = project(p0);
        if (p.z >= 0) {
          if (down) c.lineTo(p.x, p.y);
          else c.moveTo(p.x, p.y);
          down = true;
        } else down = false;
      }
      c.stroke();
    };
    c.strokeStyle = "#65846855";
    c.lineWidth = 0.65;
    for (let lat = -75; lat <= 75; lat += 15) {
      const a = (lat * Math.PI) / 180;
      grid(
        Array.from({ length: 145 }, (_, i) => {
          const t = (i * TAU) / 144;
          return [
            R * Math.cos(a) * Math.cos(t),
            R * Math.cos(a) * Math.sin(t),
            R * Math.sin(a),
          ];
        }),
      );
    }
    for (let lng = 0; lng < 360; lng += 15) {
      const a = (lng * Math.PI) / 180;
      grid(
        Array.from({ length: 73 }, (_, i) => {
          const t = -Math.PI / 2 + (i * Math.PI) / 72;
          return [
            R * Math.cos(t) * Math.cos(a),
            R * Math.cos(t) * Math.sin(a),
            R * Math.sin(t),
          ];
        }),
      );
    }
    // Subtle stippling on the visible sphere, deterministic and schematic.
    c.fillStyle = "#b3cca529";
    for (let lat = -70; lat <= 70; lat += 5)
      for (let lon = 0; lon < 360; lon += 5) {
        const a = (lat * Math.PI) / 180,
          b = (lon * Math.PI) / 180,
          p = project([
            R * Math.cos(a) * Math.cos(b),
            R * Math.cos(a) * Math.sin(b),
            R * Math.sin(a),
          ]);
        if (p.z > 0) c.fillRect(p.x, p.y, 0.8, 0.8);
      }
    paths.forEach((p, i) =>
      line(p, i === this.selected ? "#d5f985" : "#729a6d66"),
    );
    const p = paths[this.selected]?.[this.sample];
    if (p) {
      const behind = p.z < 0 && Math.hypot(p.x - cx, p.y - cy) < r;
      c.setLineDash(behind ? [2, 3] : []);
      c.strokeStyle = "#d5f985";
      c.lineWidth = 1;
      c.beginPath();
      c.arc(p.x, p.y, 7, 0, TAU);
      c.stroke();
      c.setLineDash([]);
      if (!behind) {
        c.fillStyle = "#e5ffa5";
        c.beginPath();
        c.arc(p.x, p.y, 3, 0, TAU);
        c.fill();
      }
      c.font = "10px Consolas,monospace";
      c.fillStyle = "#e1eccb";
      const tx = p.x > w * 0.7 ? p.x - 110 : p.x + 16;
      c.fillText(
        behind
          ? "МКС · за Землёй"
          : "МКС / " + String.fromCharCode(65 + this.selected),
        tx,
        p.y - 12,
      );
    }
    c.fillStyle = "#8ba18c";
    c.font = "9px Consolas,monospace";
    c.fillText("TEME / СХЕМА", 20, h - 40);
    c.textAlign = "right";
    c.fillText("R⊕ 6 378 км", w - 20, 26);
    c.textAlign = "left";
  }
}
