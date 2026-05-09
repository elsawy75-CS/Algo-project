/* network.js — canvas-based graph renderer for Cairo transport network */

const NodeColors = {
  Residential: '#2563eb',
  Mixed:       '#059669',
  Business:    '#059669',
  Industrial:  '#b45309',
  Government:  '#7c3aed',
  Medical:     '#dc2626',
  'Transit Hub':'#d97706',
  Airport:     '#d97706',
  Education:   '#d97706',
  Tourism:     '#d97706',
  Sports:      '#d97706',
  Commercial:  '#d97706',
  Facility:    '#d97706',
};

function getNodeColor(type) {
  return NodeColors[type] || '#6b7280';
}

function congestionColor(ratio) {
  if (ratio >= 0.90) return '#ef4444';
  if (ratio >= 0.70) return '#f59e0b';
  return '#22c55e';
}

/* Project (lon, lat) → canvas (x, y) */
function makeProjector(nodes, w, h, pad = 40) {
  const xs = nodes.map(n => n.x);
  const ys = nodes.map(n => n.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  return (lon, lat) => ({
    x: pad + (lon - minX) / (maxX - minX) * (w - 2 * pad),
    y: pad + (maxY - lat) / (maxY - minY) * (h - 2 * pad),
  });
}

/**
 * drawNetwork — render full network on a canvas element.
 * @param {HTMLCanvasElement} canvas
 * @param {Array} nodes  [{id,name,type,x,y,population,is_facility}]
 * @param {Array} edges  [{src,dst,congestion_ratio,capacity}]
 * @param {Object} opts  {highlightPath, highlightColor, mstEdges}
 */
function drawNetwork(canvas, nodes, edges, opts = {}) {
  if (!canvas) return;
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const W = rect.width  || canvas.offsetWidth  || 600;
  const H = rect.height || canvas.offsetHeight || 400;
  canvas.width  = W * dpr;
  canvas.height = H * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, W, H);

  const proj = makeProjector(nodes, W, H, 40);
  const posMap = {};
  nodes.forEach(n => { posMap[n.id] = proj(n.x, n.y); });

  const highlightSet = new Set(opts.highlightPath || []);
  const mstSet = opts.mstEdges ? new Set(opts.mstEdges.map(e => e.src + '-' + e.dst)) : null;

  /* ── Draw edges ── */
  edges.forEach(e => {
    const pa = posMap[e.src], pb = posMap[e.dst];
    if (!pa || !pb) return;

    if (mstSet !== null) {
      const inMST = mstSet.has(e.src + '-' + e.dst) || mstSet.has(e.dst + '-' + e.src);
      if (inMST) {
        ctx.strokeStyle = opts.highlightColor || '#22c55e';
        ctx.lineWidth = 2.5;
        ctx.globalAlpha = 0.9;
      } else {
        ctx.strokeStyle = 'rgba(255,255,255,0.08)';
        ctx.lineWidth = 0.7;
        ctx.globalAlpha = 0.5;
      }
    } else {
      const inPath = highlightSet.has(e.src) && highlightSet.has(e.dst);
      ctx.strokeStyle = inPath
        ? (opts.pathColor || '#60a5fa')
        : congestionColor(e.congestion_ratio || 0);
      ctx.lineWidth = inPath ? 3 : Math.max(0.8, (e.capacity || 2000) / 1600);
      ctx.globalAlpha = inPath ? 1 : 0.55;
    }

    ctx.beginPath();
    ctx.moveTo(pa.x, pa.y);
    ctx.lineTo(pb.x, pb.y);
    ctx.stroke();
    ctx.globalAlpha = 1;
  });

  /* ── Draw highlighted path ── */
  if (opts.highlightPath && opts.highlightPath.length > 1) {
    ctx.strokeStyle = opts.pathColor || '#60a5fa';
    ctx.lineWidth = 3.5;
    ctx.setLineDash([6, 3]);
    ctx.globalAlpha = 0.9;
    ctx.beginPath();
    const first = posMap[opts.highlightPath[0]];
    if (first) ctx.moveTo(first.x, first.y);
    opts.highlightPath.slice(1).forEach(nid => {
      const p = posMap[nid];
      if (p) ctx.lineTo(p.x, p.y);
    });
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.globalAlpha = 1;
  }

  /* ── Draw nodes ── */
  nodes.forEach(n => {
    const p = posMap[n.id];
    if (!p) return;
    const r = n.is_facility ? 5 : Math.max(5, Math.min(13, (n.population || 0) / 45000));
    ctx.beginPath();
    ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
    ctx.fillStyle = getNodeColor(n.type);
    ctx.fill();
    ctx.strokeStyle = 'rgba(255,255,255,0.25)';
    ctx.lineWidth = 1;
    ctx.stroke();

    /* Label */
    ctx.fillStyle = 'rgba(232,234,240,0.85)';
    ctx.font = '500 9.5px Inter,system-ui,sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(n.name.split(' ')[0], p.x, p.y - r - 3);
  });
}

/**
 * animateRace — animate node exploration for race visualisation.
 * Returns a Promise that resolves when animation ends.
 */
function animateRace(canvas, nodes, edges, path, exploredCount, color, label) {
  return new Promise(resolve => {
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    const W = rect.width  || 400;
    const H = rect.height || 280;
    canvas.width  = W * dpr;
    canvas.height = H * dpr;
    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);

    const proj = makeProjector(nodes, W, H, 35);
    const posMap = {};
    nodes.forEach(n => { posMap[n.id] = proj(n.x, n.y); });

    // Animate "explored" nodes flashing one by one
    const pathSet = new Set(path);
    const nonPath = nodes.filter(n => !pathSet.has(n.id));
    const toExplore = nonPath.slice(0, Math.min(exploredCount, nonPath.length));

    let frame = 0;
    const totalFrames = toExplore.length + 20;

    function renderFrame() {
      ctx.clearRect(0, 0, W, H);

      // Edges
      edges.forEach(e => {
        const pa = posMap[e.src], pb = posMap[e.dst];
        if (!pa || !pb) return;
        ctx.strokeStyle = 'rgba(255,255,255,0.07)';
        ctx.lineWidth = 0.8;
        ctx.beginPath();
        ctx.moveTo(pa.x, pa.y);
        ctx.lineTo(pb.x, pb.y);
        ctx.stroke();
      });

      // Explored nodes so far
      toExplore.slice(0, frame).forEach(n => {
        const p = posMap[n.id];
        if (!p) return;
        ctx.beginPath();
        ctx.arc(p.x, p.y, 5, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(107,114,128,0.4)';
        ctx.fill();
      });

      // Path
      if (frame > toExplore.length) {
        ctx.strokeStyle = color;
        ctx.lineWidth = 3;
        ctx.setLineDash([6, 3]);
        ctx.beginPath();
        const first = posMap[path[0]];
        if (first) ctx.moveTo(first.x, first.y);
        path.slice(1).forEach(nid => {
          const p = posMap[nid];
          if (p) ctx.lineTo(p.x, p.y);
        });
        ctx.stroke();
        ctx.setLineDash([]);
      }

      // Path nodes
      nodes.forEach(n => {
        const p = posMap[n.id];
        if (!p) return;
        if (!pathSet.has(n.id)) return;
        const r = n.is_facility ? 5 : Math.max(5, Math.min(12, (n.population || 0) / 45000));
        ctx.beginPath();
        ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();
        ctx.font = '9px Inter,system-ui,sans-serif';
        ctx.fillStyle = '#fff';
        ctx.textAlign = 'center';
        ctx.fillText(n.name.split(' ')[0], p.x, p.y - r - 3);
      });

      frame++;
      if (frame <= totalFrames) {
        setTimeout(renderFrame, 40);
      } else {
        resolve();
      }
    }
    renderFrame();
  });
}
