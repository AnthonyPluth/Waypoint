(() => {
  const WORLD = 1;
  const SVG = "http://www.w3.org/2000/svg";
  const listeners = {};
  const state = { tokens: [], maps: [], directions: [], shape: "nested" };
  const toPoint = (c) => ({ x: ((c.longitude + 180) / 360) * WORLD, y: (0.5 - Math.log(Math.tan(Math.PI / 4 + (Math.max(-85, Math.min(85, c.latitude)) * Math.PI) / 360)) / (2 * Math.PI)) * WORLD });

  class Coordinate { constructor(latitude, longitude) { this.latitude = latitude; this.longitude = longitude; } }
  class MapRect {
    constructor(x, y, width, height) {
      for (const v of [x, y, width, height]) if (!(v >= 0 && v <= 1)) throw new RangeError("MapRect values are normalized to 0..1, got " + v);
      if (y + height > 1) throw new RangeError("MapRect reaches outside the world");
      this.x = x; this.y = y; this.width = width; this.height = height;
    }
  }
  class Style { constructor(options) { Object.assign(this, options); } }
  class Annotation {
    constructor(coordinate, factory, options = {}) { this.coordinate = coordinate; this.factory = factory; this.visible = options.visible !== false; this.data = options.data; }
  }
  class PolylineOverlay { constructor(points, options = {}) { this.points = points; this.style = options.style; this.data = options.data; this.enabled = options.enabled; } }
  class PolygonOverlay { constructor(points, options = {}) { this.points = points; this.style = options.style; this.data = options.data; this.enabled = options.enabled; } }

  class MapView {
    constructor(host, options) {
      this.options = options;
      this.annotations = new Set();
      this.overlays = new Set();
      this.nodes = new Map();
      this.rect = null;
      this.gone = false;
      this.heard = {};
      this.isScrollEnabled = options.isScrollEnabled !== false;
      this.selectedAnnotation = null;
      this.selectedOverlay = null;
      host.style.position = "relative";
      host.style.overflow = "hidden";
      host.style.background = "#1c2230";
      this.host = host;
      this.grid = document.createElement("div");
      this.grid.style.cssText = "position:absolute;inset:0;background-image:linear-gradient(#262d3f 1px,transparent 1px),linear-gradient(90deg,#262d3f 1px,transparent 1px);background-size:64px 64px";
      this.lines = document.createElementNS(SVG, "svg");
      this.lines.style.cssText = "position:absolute;inset:0;width:100%;height:100%";
      this.marks = document.createElement("div");
      this.marks.style.cssText = "position:absolute;inset:0;pointer-events:none";
      this.tag = document.createElement("div");
      this.tag.textContent = "stand-in map";
      this.tag.style.cssText = "position:absolute;right:6px;bottom:4px;font:10px sans-serif;color:#5b6784";
      host.append(this.grid, this.lines, this.marks, this.tag);
      if (options.showsZoomControl) {
        const control = document.createElement("div");
        control.setAttribute("aria-hidden", "true");
        control.style.cssText = "position:absolute;right:10px;top:10px;display:flex;flex-direction:column;border-radius:8px;overflow:hidden;border:1px solid #3a4560;background:#10141d;color:#c9d2e6;font:600 18px sans-serif";
        for (const [name, factor, glyph] of [["in", 0.5, "+"], ["out", 2, "\u2212"]]) {
          const part = document.createElement("div");
          part.textContent = glyph;
          part.setAttribute("data-zoom", name);
          part.style.cssText = "width:34px;height:34px;display:grid;place-items:center;cursor:pointer;user-select:none";
          part.addEventListener("click", (event) => { event.stopPropagation(); this.zoomBy(factor); });
          control.append(part);
        }
        host.append(control);
      }
      host.addEventListener("click", (event) => { if (!event.defaultPrevented && event.target === host || event.target === this.grid || event.target === this.lines) this.deselect(); });
      host.addEventListener("pointerdown", (event) => this.dragStart(event));
      state.maps.push(this);
      this.frame = () => { if (this.gone) return; this.draw(); requestAnimationFrame(this.frame); };
      requestAnimationFrame(this.frame);
    }
    addAnnotation(a) { this.annotations.add(a); }
    removeAnnotation(a) { this.annotations.delete(a); const n = this.nodes.get(a); if (n) { n.remove(); this.nodes.delete(a); } }
    addOverlay(o) { this.overlays.add(o); }
    removeOverlay(o) {
      this.overlays.delete(o);
      const n = this.nodes.get(o);
      if (n) { const hit = this.nodes.get(n); if (hit) hit.remove(); n.remove(); this.nodes.delete(n); this.nodes.delete(o); }
    }
    setVisibleMapRectAnimated(rect) { this.rect = rect; setTimeout(() => this.emit("region-change-end"), 0); }
    get region() {
      const r = this.rect || { width: 1, height: 1 };
      return { span: { latitudeDelta: r.height * 360, longitudeDelta: r.width * 360 } };
    }
    addEventListener(type, fn) { (this.heard[type] = this.heard[type] || new Set()).add(fn); }
    removeEventListener(type, fn) { if (this.heard[type]) this.heard[type].delete(fn); }
    emit(type, event = {}) { for (const fn of [...(this.heard[type] || [])]) fn(event); }
    zoomBy(factor) {
      const r = this.rect;
      if (!r) return;
      const width = Math.min(1, r.width * factor), height = Math.min(1, r.height * factor);
      const focus = this.selectedAnnotation ? toPoint(this.selectedAnnotation.coordinate) : null;
      const cx = focus ? focus.x : r.x + r.width / 2, cy = focus ? focus.y : r.y + r.height / 2;
      const x = cx - width / 2, y = Math.max(0, Math.min(1 - height, cy - height / 2));
      this.rect = new MapRect(((x % 1) + 1) % 1, y, width, height);
      setTimeout(() => this.emit("region-change-end"), 0);
    }
    dragStart(event) {
      if (!this.isScrollEnabled || !this.rect || event.target.closest("[data-zoom]")) return;
      let last = { x: event.clientX, y: event.clientY };
      let moved = false;
      const move = (e) => {
        if (!moved && Math.hypot(e.clientX - last.x, e.clientY - last.y) < 3) return;
        moved = true;
        const scale = Math.min(this.host.clientWidth / this.rect.width, this.host.clientHeight / this.rect.height);
        const dx = (last.x - e.clientX) / scale, dy = (last.y - e.clientY) / scale;
        last = { x: e.clientX, y: e.clientY };
        this.rect = new MapRect((((this.rect.x + dx) % 1) + 1) % 1, Math.max(0, Math.min(1 - this.rect.height, this.rect.y + dy)), this.rect.width, this.rect.height);
      };
      const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); if (moved) this.emit("region-change-end"); };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
    }
    select(item) {
      this.selectedAnnotation = "coordinate" in item ? item : null;
      this.selectedOverlay = "coordinate" in item ? null : item;
      this.emit("select", "coordinate" in item ? { annotation: item } : { overlay: item });
    }
    deselect() {
      if (!this.selectedAnnotation && !this.selectedOverlay) return;
      this.selectedAnnotation = null;
      this.selectedOverlay = null;
      this.emit("deselect");
    }
    destroy() { this.gone = true; this.host.replaceChildren(); }
    draw() {
      const rect = this.rect;
      const w = this.host.clientWidth, h = this.host.clientHeight;
      if (!rect || !w || !h) return;
      const scale = Math.min(w / rect.width, h / rect.height);
      const at = (c) => { const p = toPoint(c); if (p.x < rect.x && rect.x + rect.width > 1) p.x += 1; return { x: (p.x - rect.x) * scale + (w - rect.width * scale) / 2, y: (p.y - rect.y) * scale + (h - rect.height * scale) / 2 }; };
      const ringOf = (ring) => ring.map((c) => { const p = at(c); return `${p.x.toFixed(1)},${p.y.toFixed(1)}`; });
      for (const o of this.overlays) {
        const polygon = Array.isArray(o.points[0]);
        let n = this.nodes.get(o);
        if (!n) {
          n = document.createElementNS(SVG, polygon ? "path" : "polyline");
          n.setAttribute("data-overlay", "");
          n.setAttribute("data-kind", polygon ? "polygon" : "polyline");
          if (o.enabled) {
            n.style.pointerEvents = polygon ? "visiblePainted" : "stroke";
            n.addEventListener("click", (event) => { event.stopPropagation(); this.select(o); });
          }
          this.lines.append(n);
          this.nodes.set(o, n);
        }
        const s = o.style || {};
        if (n.__style !== s) {
          n.__style = s;
          n.setAttribute("fill", polygon ? (s.fillColor || "#fff") : "none");
          if (polygon && s.fillOpacity !== undefined) n.setAttribute("fill-opacity", String(s.fillOpacity));
          n.setAttribute("fill-rule", "evenodd");
          n.setAttribute("stroke", s.strokeColor || "#fff");
          n.setAttribute("stroke-width", String(s.lineWidth || 1));
          n.setAttribute("stroke-linecap", s.lineCap || "butt");
          n.setAttribute("stroke-linejoin", s.lineJoin || "miter");
          if (s.lineDash) n.setAttribute("stroke-dasharray", s.lineDash.join(" "));
          if (s.strokeOpacity !== undefined) n.setAttribute("stroke-opacity", String(s.strokeOpacity));
        }
        if (polygon) n.setAttribute("d", o.points.map((ring) => "M" + ringOf(ring).join("L") + "Z").join(" "));
        else n.setAttribute("points", ringOf(o.points).join(" "));
        if (o.enabled) {
          let hit = this.nodes.get(n);
          if (!hit) {
            hit = document.createElementNS(SVG, "circle");
            hit.setAttribute("r", polygon ? "6" : "10");
            hit.setAttribute("fill", "transparent");
            hit.setAttribute("data-hit", "");
            hit.setAttribute("data-kind", polygon ? "polygon" : "polyline");
            hit.style.pointerEvents = "all";
            hit.addEventListener("click", (event) => { event.stopPropagation(); this.select(o); });
            this.lines.append(hit);
            this.nodes.set(n, hit);
          }
          if (!o.__hit) o.__hit = polygon ? interior(o.points) : o.points[Math.floor(o.points.length / 2)];
          const mid = at(o.__hit);
          hit.setAttribute("cx", mid.x.toFixed(1));
          hit.setAttribute("cy", mid.y.toFixed(1));
          hit.style.display = mid.x >= 0 && mid.x <= w && mid.y >= 0 && mid.y <= h ? "" : "none";
        }
      }
      for (const a of this.annotations) {
        let n = this.nodes.get(a);
        if (!n) {
          n = document.createElement("div");
          n.style.cssText = "position:absolute;left:0;top:0;pointer-events:auto;cursor:pointer";
          n.append(a.factory());
          n.addEventListener("click", (event) => { event.stopPropagation(); this.select(a); });
          this.marks.append(n);
          this.nodes.set(a, n);
        }
        n.style.display = a.visible ? "" : "none";
        const p = at(a.coordinate);
        n.style.transform = `translate(${p.x.toFixed(1)}px, ${p.y.toFixed(1)}px)`;
      }
    }
  }

  const inside = (ring, x, y) => {
    let on = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      if ((ring[i].y > y) !== (ring[j].y > y) && x < ((ring[j].x - ring[i].x) * (y - ring[i].y)) / (ring[j].y - ring[i].y) + ring[i].x) on = !on;
    }
    return on;
  };
  const interior = (rings) => {
    const ring = rings.reduce((a, b) => (b.length > a.length ? b : a)).map(toPoint);
    const xs = ring.map((p) => p.x), ys = ring.map((p) => p.y);
    const cx = (Math.min(...xs) + Math.max(...xs)) / 2, cy = (Math.min(...ys) + Math.max(...ys)) / 2;
    let best = null;
    for (let i = 0; i <= 24; i++) {
      for (let j = 0; j <= 24; j++) {
        const x = Math.min(...xs) + ((Math.max(...xs) - Math.min(...xs)) * i) / 24, y = Math.min(...ys) + ((Math.max(...ys) - Math.min(...ys)) * j) / 24;
        const d = Math.hypot(x - cx, y - cy);
        if ((!best || d < best.d) && inside(ring, x, y)) best = { x, y, d };
      }
    }
    return best ? { latitude: (Math.atan(Math.sinh(Math.PI * (1 - 2 * best.y))) * 180) / Math.PI, longitude: best.x * 360 - 180 } : rings[0][0];
  };

  class Directions {
    route(request, callback) {
      const a = request.origin, b = request.destination;
      const part = [];
      for (let i = 0; i <= 12; i++) {
        const t = i / 12;
        const wave = Math.sin(t * Math.PI * 3) * 0.05 * Math.min(1, Math.hypot(b.latitude - a.latitude, b.longitude - a.longitude));
        part.push(new Coordinate(a.latitude + (b.latitude - a.latitude) * t + wave, a.longitude + (b.longitude - a.longitude) * t - wave));
      }
      state.directions.push({ origin: a, destination: b, transportType: request.transportType });
      const parts = [part.slice(0, 7), part.slice(7)];
      const route = state.shape === "flat" ? { path: part } : state.shape === "steps" ? { steps: parts.map((path) => ({ path })) } : { path: parts };
      setTimeout(() => callback(null, { routes: [route] }), 0);
      return state.directions.length;
    }
    cancel() {}
  }
  Directions.Transport = { Automobile: "automobile", Walking: "walking" };

  window.mapkit = {
    Coordinate, Directions, MapRect, Style, Annotation, PolylineOverlay, PolygonOverlay,
    Map: Object.assign(MapView, { ColorSchemes: { Dark: "dark", Light: "light" } }),
    FeatureVisibility: { Hidden: "hidden", Visible: "visible", Adaptive: "adaptive" },
    init(options) { options.authorizationCallback((token) => state.tokens.push(token)); },
    addEventListener(type, fn) { (listeners[type] = listeners[type] || new Set()).add(fn); },
    removeEventListener(type, fn) { if (listeners[type]) listeners[type].delete(fn); },
    __fail(status) { for (const fn of [...(listeners.error || [])]) fn({ type: "error", status }); },
    __state: state,
  };
})();
