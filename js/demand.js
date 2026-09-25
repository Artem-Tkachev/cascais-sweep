// ============================================================
// demand.js — Demand tab: supply / demand KPIs per H3 hexagon
// Numbers come from analytics.py (analytics.hex), averaged per day.
// Uses: analytics, summary, fmt, map, hexLayer (map.js), el (collection.js)
// ============================================================


// ===== 1. Colours =====
// Sequential blues for "how much"; blue-to-red for the imbalance
const SEQ = ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95', '#0d366b'];
const DIV = ['#1c5cab', '#6da7ec', '#cde2fb', '#f0efec', '#f6c3c2', '#ea8584', '#b92f2f'];

const hexes = analytics.hex.features;

function colourFor(metric, values) {
    if (metric === 'net') {
        const lim = Math.max(...values.map(Math.abs)) * 0.5 || 1;
        const stops = [-lim, -lim * 0.5, -lim * 0.15, lim * 0.15, lim * 0.5, lim];
        return v => DIV[stops.filter(s => v > s).length];
    }
    const sorted = values.filter(v => v > 0).sort((a, b) => a - b);
    const stops = [1, 2, 3, 4, 5, 6].map(k => sorted[Math.floor(sorted.length * k / 7)] ?? 0);
    return v => v <= 0 ? null : SEQ[stops.filter(s => v > s).length];
}


// ===== 2. Text for one value =====
function valueText(metric, v) {
    if (metric === 'abandon_rate') return fmt(v * 100) + '% of trip ends';
    if (metric === 'abandoned') return fmt(v, 1) + ' cases/day';
    return fmt(v, 1) + ' trips/day';
}


// ===== 3. Draw hexagons + legend =====
function drawHex() {
    const metric = el('metric').value;
    const colour = colourFor(metric, hexes.map(f => f.properties[metric]));

    hexLayer.clearLayers();
    hexes.forEach(f => {
        const p = f.properties;
        const c = colour(p[metric]);
        if (!c) return;
        L.geoJSON(f, { style: { color: '#fff', weight: 1, fillColor: c, fillOpacity: 0.78 } })
            .bindTooltip(`<b>${valueText(metric, p[metric])}</b><br>` +
                         `Started ${fmt(p.starts, 1)}/day · ended ${fmt(p.ends, 1)}/day<br>` +
                         `Abandoned ${fmt(p.abandoned * summary.days)} times in 3 weeks`)
            .addTo(hexLayer);
    });

    el('hexlegend').innerHTML = metric === 'net'
        ? `<span><i class="dot" style="background:${DIV[0]}"></i>vehicles missing</span>` +
          `<span><i class="dot" style="background:${DIV[3]}"></i>balanced</span>` +
          `<span><i class="dot" style="background:${DIV[6]}"></i>vehicles pile up</span>`
        : `<span>less</span>` + SEQ.map(c => `<i class="dot" style="background:${c};margin:0"></i>`).join('') + `<span>more</span>`;
}

el('metric').onchange = drawHex;
drawHex();


// ===== 4. KPI tiles for the whole city =====
el('kpitiles').innerHTML =
    `<div class="tile"><b>${fmt(summary.trips_per_day)}</b><small>real trips per day</small></div>` +
    `<div class="tile"><b>${fmt(summary.trips_fake_share * 100)}%</b><small>failed "ghost" trips removed</small></div>` +
    `<div class="tile"><b>${fmt(summary.abandoned_per_day)}</b><small>new abandonments per day</small></div>` +
    `<div class="tile"><b>${fmt(summary.median_hours, 1)} h</b><small>median time abandoned</small></div>`;