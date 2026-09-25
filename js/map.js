// ============================================================
// map.js — shared data, number formatting, map, stations, depot
// Loaded first: the other js files use what is defined here.
// ============================================================


// ===== 1. Data from data/data.js =====
const analytics = window.ANALYTICS;     // everything analytics.py computed
const summary   = analytics.summary;    // depot, van capacity, speed, fine...

// Abandoned cases. Times come as text ("2026-08-29T04:48:02"),
// we add them as numbers (ms since 1970) so they are easy to compare.
const cases = window.ABANDONED.map(d => ({
  ...d,                                 // keep all original fields
  ts: Date.parse(d.start),              // vehicle was parked
  t0: Date.parse(d.abandoned_from),     // counts as abandoned (start + 2 h)
  t1: Date.parse(d.end)                 // picked up or rented again
}));

let liveFeed = window.LIVE || null;
let liveCases = liveFeed ? liveFeed.bikes.map(d => ({...d, ts:Date.parse(d.start) })) : [];


// ===== 2. Number formatting =====
// fmt(1234.567, 1) -> "1,234.6"
function fmt(x, digits = 0) {
  return x.toLocaleString('en-GB', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  });
}


// ===== 3. Map =====
const map = L.map('map', { preferCanvas: true })   // draw inside <div id="map">
  .setView([38.700, -9.40], 13);                   // centre of Cascais, zoom 13

L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap contributors',
  maxZoom: 19
}).addTo(map);

// ===== 4. Bird stations =====
// Station areas as blue polygons
L.geoJSON(window.STATIONS, {
  style: { color: '#2a78d6', weight: 1, fillOpacity: 0.3 }
}).addTo(map);

// A small dot in the centre of every station, name on hover
for (const f of window.STATIONS.features) {
  L.circleMarker([f.properties.lat, f.properties.lon], {
    radius: 3, color: '#2a78d6', weight: 1, fillOpacity: 0.9
  }).bindTooltip(f.properties.name).addTo(map);
}


// ===== 5. Layers =====
// A layer is a box of map objects we can clear and redraw in one call.
const vehLayer   = L.layerGroup().addTo(map);   // abandoned vehicles
const routeLayer = L.layerGroup().addTo(map);   // van route
const hexLayer = L.layerGroup();


// ===== 6. Depot =====
const depot = summary.depot;                    // [38.736065, -9.386573]

// Warehouse icon drawn as SVG: roof, walls and a door (white lines)
const DEPOT_SVG = `
  <svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2"
       stroke-linecap="round" stroke-linejoin="round">
    <path d="M3 10 L12 4 L21 10"/>
    <path d="M5 9 V20 H19 V9"/>
    <path d="M9 20 V14 H15 V20"/>
  </svg>`;

L.marker(depot, {
  icon: L.divIcon({ className: 'depot-icon', html: DEPOT_SVG, iconSize: [26, 26] }),
  zIndexOffset: 1000                            // always on top of vehicles
}).bindTooltip('Depot').addTo(map);
