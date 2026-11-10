(() => {
  const WORLD = 1;
  const SVG = "http://www.w3.org/2000/svg";
  const listeners = {};
  const state = { tokens: [], maps: [] };
  const toPoint = (c) => ({ x: ((c.longitude + 180) / 360) * WORLD, y: (0.5 - Math.log(Math.tan(Math.PI / 4 + (Math.max(-85, Math.min(85, c.latitude)) * Math.PI) / 360)) / (2 * Math.PI)) * WORLD });

  class Coordinate { constructor(latitude, longitude) { this.latitude = latitude; this.longitude = longitude; } }
  class MapRect {
    constructor(x, y, width, height) {
      for (const v of [x, y, width, height]) if (!(v >= 0 && v <= 1)) throw new RangeError("MapRect values are normalized to 0..1, got " + v);
      if (x + width > 1 || y + height > 1) throw new RangeError("MapRect reaches outside the world");
      this.x = x; this.y = y; this.width = width; this.height = height;
    }
  }
  class Style { constructor(options) { Object.assign(this, options); } }
  class Annotation {
    constructor(coordinate, factory, options = {}) { this.coordinate = coordinate; this.factory = factory; this.visible = options.visible !== false; }
  }
  class PolylineOverlay { constructor(points, options = {}) { this.points = points; this.style = options.style; } }

  class MapView {
    constructor(host, options) {
      this.options = options;
      this.annotations = new Set();
      this.overlays = new Set();
      this.nodes = new Map();
      this.rect = null;
      this.gone = false;
      host.style.position = "relative";
      host.style.overflow = "hidden";
      host.style.background = "#1c2230";
      this.host = host;
      this.grid = document.createElement("div");
      this.grid.style.cssText = "position:absolute;inset:0;background-image:linear-gradient(#262d3f 1px,transparent 1px),linear-gradient(90deg,#262d3f 1px,transparent 1px);background-size:64px 64px";
      this.lines = document.createElementNS(SVG, "svg");
      this.lines.style.cssText = "position:absolute;inset:0;width:100%;height:100%";
      this.marks = document.createElement("div");
      this.marks.style.cssText = "position:absolute;inset:0";
      this.tag = document.createElement("div");
      this.tag.textContent = "stand-in map";
      this.tag.style.cssText = "position:absolute;right:6px;bottom:4px;font:10px sans-serif;color:#5b6784";
      host.append(this.grid, this.lines, this.marks, this.tag);
      state.maps.push(this);
      this.frame = () => { if (this.gone) return; this.draw(); requestAnimationFrame(this.frame); };
      requestAnimationFrame(this.frame);
    }
    addAnnotation(a) { this.annotations.add(a); }
    removeAnnotation(a) { this.annotations.delete(a); const n = this.nodes.get(a); if (n) { n.remove(); this.nodes.delete(a); } }
    addOverlay(o) { this.overlays.add(o); }
    removeOverlay(o) { this.overlays.delete(o); const n = this.nodes.get(o); if (n) { n.remove(); this.nodes.delete(o); } }
    setVisibleMapRectAnimated(rect) { this.rect = rect; }
    destroy() { this.gone = true; this.host.replaceChildren(); }
    draw() {
      const rect = this.rect;
      const w = this.host.clientWidth, h = this.host.clientHeight;
      if (!rect || !w || !h) return;
      const scale = Math.min(w / rect.width, h / rect.height);
      const at = (c) => { const p = toPoint(c); return { x: (p.x - rect.x) * scale + (w - rect.width * scale) / 2, y: (p.y - rect.y) * scale + (h - rect.height * scale) / 2 }; };
      for (const o of this.overlays) {
        let n = this.nodes.get(o);
        if (!n) {
          n = document.createElementNS(SVG, "polyline");
          n.setAttribute("fill", "none");
          const s = o.style || {};
          n.setAttribute("stroke", s.strokeColor || "#fff");
          n.setAttribute("stroke-width", String(s.lineWidth || 1));
          n.setAttribute("stroke-linecap", s.lineCap || "butt");
          n.setAttribute("stroke-linejoin", s.lineJoin || "miter");
          if (s.lineDash) n.setAttribute("stroke-dasharray", s.lineDash.join(" "));
          if (s.strokeOpacity !== undefined) n.setAttribute("stroke-opacity", String(s.strokeOpacity));
          n.setAttribute("data-overlay", "");
          this.lines.append(n);
          this.nodes.set(o, n);
        }
        n.setAttribute("points", o.points.map((c) => { const p = at(c); return `${p.x.toFixed(1)},${p.y.toFixed(1)}`; }).join(" "));
      }
      for (const a of this.annotations) {
        let n = this.nodes.get(a);
        if (!n) {
          n = document.createElement("div");
          n.style.cssText = "position:absolute;left:0;top:0";
          n.append(a.factory());
          this.marks.append(n);
          this.nodes.set(a, n);
        }
        n.style.display = a.visible ? "" : "none";
        const p = at(a.coordinate);
        n.style.transform = `translate(${p.x.toFixed(1)}px, ${p.y.toFixed(1)}px)`;
      }
    }
  }

  window.mapkit = {
    Coordinate, MapRect, Style, Annotation, PolylineOverlay,
    Map: Object.assign(MapView, { ColorSchemes: { Dark: "dark", Light: "light" } }),
    FeatureVisibility: { Hidden: "hidden", Visible: "visible", Adaptive: "adaptive" },
    init(options) { options.authorizationCallback((token) => state.tokens.push(token)); },
    addEventListener(type, fn) { (listeners[type] = listeners[type] || new Set()).add(fn); },
    removeEventListener(type, fn) { if (listeners[type]) listeners[type].delete(fn); },
    __fail(status) { for (const fn of [...(listeners.error || [])]) fn({ type: "error", status }); },
    __state: state,
  };
})();
