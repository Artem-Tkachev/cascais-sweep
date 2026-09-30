// ============================================================
// collection.js — Collection tab: time slider, vehicles, route
// Uses: cases, fmt, vehLayer, routeLayer, summary (map.js),
//       priority, readWeights, happened (priority.js),
//       planRun, roadRoute (route.js)
// ============================================================


// ===== 1. Shortcut =====
const el = id => document.getElementById(id);


// ===== 2. Time slider =====
const STEP = 15*60*1000;
const tMin = Math.floor(Math.min(...cases.map(d => d.t0)) / STEP) * STEP;
const tMax = Math.max(...cases.map(d => d.t1));

const slider = el('t');
slider.min = 0;
slider.max = Math.floor((tMax - tMin) / STEP);
slider.value = Math.round((Date.parse('2026-08-27T15:00:00') - tMin) / STEP);

el('cap').textContent = summary.capacity;


// ===== 3. Colours =====
function colourByHours(h){
    if(h >= 8){
        return '#e34948';
    }
    if(h >= 4){
        return '#eb6834';
    }
    return '#eda100';
}
const WAIT_COLOUR = '#b9b8b3';
const SKIP_COLOUR = '#8a8984';        // skipped runs: grey dashed outline, white inside
const ROUTE_COLOUR = '#0d366b';


// ===== 4. Draw vehicles =====
//   - clear vehLayer
//   - one circle per vehicle: coloured if in this run, grey otherwise,
//     white with a dashed outline if its run was skipped (not worth it)
//   - tooltip: priority, hours standing, metres from station,
//              chance a rider takes it, "Bird serviced it and left it"
//   - skipped = Map: vehicle index -> rate of its skipped run
function drawVehicles(live, scores, chosenSet, t, skipped = new Map(), minRate = 0){
    vehLayer.clearLayers();
    live.forEach((d, i) => {
        const hours = (t - d.ts) / 3600000;
        const lines = [
            `<b>Priority ${fmt(scores[i].score, 2)}</b>`,
            `Standing ${fmt(hours, 1)} h (time level ${fmt(scores[i].time, 1)}) · ${fmt(d.dist_to_station_m + 30)} m from a station`,
            `Battery: ${d.battery == null ? '—' : fmt(d.battery * 100) + '%'}`,
            `Chance a rider takes it: ${fmt((1 - scores[i].notSelf) * 100)}%`
        ];
        if(happened(d.serviced_at, t)){
            lines.push('<b>Bird serviced it on site and left it</b>');
        }
        if(skipped.has(i)){
            lines.push(`<b>Skipped:</b> its run gives ${fmt(skipped.get(i), 2)} points/min (min ${fmt(minRate, 2)})`);
            L.circleMarker([d.lat, d.lng], {
                radius: 7, color: SKIP_COLOUR, weight: 2, dashArray: '3 2', fillColor: '#fff', fillOpacity: 1
            }).bindTooltip(lines.join('<br>')).addTo(vehLayer);
            return;
        }

        L.circleMarker([d.lat, d.lng], {
            radius: 7, color: '#fff', weight: 2, fillOpacity: 1,
            fillColor: chosenSet.has(i) ? colourByHours(hours): WAIT_COLOUR
        }).bindTooltip(lines.join('<br>')).addTo(vehLayer);
    });
}


// ===== 5. Draw route, stop list, tiles =====
const RUN_COLOURS = ['#0d366b', '#6b3fa0', '#0f7a55', '#9a4a00'];
const runColour = r => RUN_COLOURS[r % RUN_COLOURS.length];

function numberIcon(n, colour) {
    return L.divIcon({
        className: '',
        html: `<div class="stop-num" style="background:${colour}">${n}</div>`,
        iconSize: [18, 18], iconAnchor: [-4, 22]
    });
}

function drawRoutes(runs) {
    let n = 0;
    runs.forEach((run, r) => {
        L.polyline(run.line, { color: runColour(r), weight: 4, opacity: 0.85 }).addTo(routeLayer);
        run.stops.forEach(d => {
            n++;
            L.marker([d.lat, d.lng], { interactive: false, icon: numberIcon(n, runColour(r)) }).addTo(routeLayer);
        });
    });
}

function drawPreview(runs) {
    runs.forEach((points, r) => {
        L.polyline([depot, ...points, depot], {
            color: runColour(r), weight: 2, opacity: 0.7, dashArray: '6 6'
        }).addTo(routeLayer);
    });
}

// skipped runs: thin grey dashed line, so you can see where the van does NOT go
function drawSkipped(lines) {
    lines.forEach(line => {
        L.polyline(line, { color: SKIP_COLOUR, weight: 2, opacity: 0.6, dashArray: '2 6' }).addTo(routeLayer);
    });
}

// Map: vehicle index -> rate of its skipped run (for drawVehicles)
function skippedMap(runs, key) {
    const m = new Map();
    runs.forEach(run => run[key].forEach(i => m.set(i, run.rate)));
    return m;
}

function showStops(runs, skippedRuns, t, minRate) {
    let html = '';
    let n = 0;
    runs.forEach((run, r) => {
        const tag = run.worth ? '' : ' · <span class="warn">not worth it</span>';
        html += `<div class="loopname"><i class="dot" style="background:${runColour(r)}"></i>` +
                `Run ${r + 1} · ${run.stops.length} vehicles · ${fmt(run.km, 1)} km · ${fmt(run.rate, 2)} pts/min${tag}</div>` +
                `<ol class="stops" start="${n + 1}">`;
        run.stops.forEach(d => {
            n++;
            html += `<li><a target="_blank" href="https://www.google.com/maps/dir/?api=1&destination=${d.lat},${d.lng}">` +
                    `${fmt(d.dist_to_station_m + 30)} m from station · ${fmt((t - d.ts) / 3600000, 1)} h · ${d.battery == null ? '—' : fmt(d.battery * 100) + '%'}</a></li>`;
        });
        html += '</ol>';
    });
    skippedRuns.forEach((run, r) => {
        html += `<div class="loopname skipped"><i class="dot skip-dot"></i>` +
                `Skipped run ${runs.length + r + 1} · ${run.chosen.length} vehicles · ${fmt(run.trip.km, 1)} km · ` +
                `${fmt(run.rate, 2)} pts/min &lt; ${fmt(minRate, 2)}</div>`;
    });
    el('stops').innerHTML = html;
}

// "Collect all" vs "Skip unprofitable": runs, vehicles, km, time, km per vehicle
function planStats(plans) {
    const vehicles = plans.reduce((sum, p) => sum + p.chosen.length, 0);
    const km = plans.reduce((sum, p) => sum + p.trip.km, 0);
    const minutes = plans.reduce((sum, p) => sum + p.total, 0) + Math.max(0, plans.length - 1) * summary.unload_min;
    return { runs: plans.length, vehicles, km, minutes };
}

const hm = minutes => `${Math.floor(minutes / 60)} h ${String(Math.round(minutes % 60)).padStart(2, '0')}`;

function showCompare(plans, w) {
    const all = planStats(plans);
    const skip = planStats(plans.filter(p => p.inSkipPlan));
    const row = (name, s, on) =>
        `<tr class="${on ? 'pick' : ''}"><td>${name}</td><td>${s.runs}</td><td>${s.vehicles}</td>` +
        `<td>${fmt(s.km, 1)}</td><td>${hm(s.minutes)}</td><td>${s.vehicles ? fmt(s.km / s.vehicles, 2) : '–'}</td></tr>`;
    const diff = (a, b, f) => (b - a === 0 ? '0' : (b - a > 0 ? '+' : '−') + f(Math.abs(b - a)));
    let html = '<h2>Collect all vs skip unprofitable</h2><table>' +
        '<tr><th></th><th>Runs</th><th>Vehicles</th><th>km</th><th>Time</th><th>km/veh</th></tr>' +
        row('Collect all', all, !w.skip) +
        row(`Skip &lt; ${fmt(w.minRate, 2)} pts/min`, skip, w.skip) +
        `<tr class="diff"><td>Difference</td><td>${diff(all.runs, skip.runs, x => x)}</td>` +
        `<td>${diff(all.vehicles, skip.vehicles, x => x)}</td><td>${diff(all.km, skip.km, x => fmt(x, 1))}</td>` +
        `<td>${diff(all.minutes, skip.minutes, hm)}</td><td></td></tr></table>`;
    if (all.runs === skip.runs) {
        html += '<p class="muted">Every run is worth driving: nothing to skip.</p>';
    } else {
        html += `<p class="muted">Skipping saves ${fmt(all.km - skip.km, 1)} km and ${hm(all.minutes - skip.minutes)} of van time ` +
                `for ${all.vehicles - skip.vehicles} vehicle(s). They wait until more vehicles gather nearby or until they have stood long enough to be worth the trip.</p>`;
    }
    el('compare').innerHTML = html;
}

function showTiles(km, naiveKm, minutes) {
    el('r-km').textContent    = fmt(km, 1);
    el('r-naive').textContent = fmt(naiveKm, 1);
    el('r-save').textContent  = '−' + fmt(Math.max(0, 1 - km / naiveKm) * 100) + '%';
    el('r-time').textContent  = `${Math.floor(minutes / 60)} h ${Math.round(minutes % 60)} min`;
}

function clearRoute() {
    routeLayer.clearLayers();
    el('stops').innerHTML = '';
    el('compare').innerHTML = '';
    ['r-km', 'r-naive', 'r-save', 'r-time'].forEach(id => el(id).textContent = '–');
}


// ===== 6. Render everything for the slider moment =====
let renderId = 0;

async function render(withRoute) {
    const myId = ++renderId;
    const isLive = el('source').value === 'live';
    const t = isLive ? liveFeed.updated * 1000 : tMin + slider.value * STEP;
    const w = readWeights();
    const live = isLive ? liveCases : cases.filter(d => d.t0 <= t && d.t1 > t);
    slider.disabled = isLive;
    el('play').disabled = isLive;

    el('count').textContent = live.length;
    el('when').textContent = new Date(t).toLocaleString('en-GB',
        { weekday: 'short', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
    ['w-time', 'w-dist', 'w-self', 'w-stop'].forEach(id => el(id + '-v').textContent = el(id).value);
    el('shift-v').textContent = w.runHours + ' h';
    el('min-rate-v').textContent = fmt(w.minRate, 2);

    const scores = live.map(d => priority(d, t, w));
    const points = live.map(d => [d.lat, d.lng]);
    const ages = live.map(d => (t - d.ts) / 3600000);

    // dragging / Play: instant preview, straight dashed lines
    if (!withRoute) {
        const quick = quickDay(points, scores.map(s => s.score), w, ages);
        const kept = quick.filter(r => !r.skipped);
        const skipped = quick.filter(r => r.skipped);
        clearRoute();
        drawVehicles(live, scores, new Set(kept.flatMap(r => r.tour)), t, skippedMap(skipped, 'tour'), w.minRate);
        drawPreview(kept.map(r => r.tour.map(i => points[i])));
        drawSkipped(skipped.map(r => [depot, ...r.tour.map(i => points[i]), depot]));
        const skipText = skipped.length ? ` ${skipped.length} run(s) skipped: not worth it.` : '';
        el('picked').textContent =
            `Preview: ${kept.length} run(s), ${kept.flatMap(r => r.tour).length} of ${live.length} vehicles.${skipText} Release to build the street route.`;
        return;
    }

    // released: real street routes from OSRM
    drawVehicles(live, scores, new Set(), t);
    el('picked').textContent = 'Planning the route…';

    try {
        const all = await planDay(live, scores.map(s => s.score), w, t);
        if (myId !== renderId) return;
        clearRoute();
        if (!all.length) {
            el('picked').textContent = 'Nothing to collect in this time.';
            return;
        }
        const plans = all.filter(p => !p.skipped);       // runs the van really drives
        const skipped = all.filter(p => p.skipped);      // not worth it: the van waits
        showCompare(all, w);
        drawSkipped(skipped.map(p => p.trip.line));
        if (!plans.length) {
            drawVehicles(live, scores, new Set(), t, skippedMap(skipped, 'chosen'), w.minRate);
            showStops([], skipped, t, w.minRate);
            el('picked').textContent =
                `Not worth driving now: the best run gives ${fmt(all[0].rate, 2)} points/min (min ${fmt(w.minRate, 2)}). ` +
                `The van waits for more vehicles.`;
            return;
        }

        const runs = [];
        let naiveKm = 0;
        for (const plan of plans) {
            const stops = plan.trip.order.map(k => live[plan.chosen[k]]);
            const firstCome = plan.chosen.map(i => live[i]).sort((a, b) => a.t0 - b.t0);
            const naive = await roadRoute(firstCome.map(d => [d.lat, d.lng]));
            naiveKm += naive.km;
            runs.push({ stops, line: plan.trip.line, km: plan.trip.km, rate: plan.rate, worth: plan.worth,
                        oldestH: plan.oldestH });
        }
        if (myId !== renderId) return;

        const chosen  = plans.flatMap(p => p.chosen);
        const km      = runs.reduce((sum, run) => sum + run.km, 0);
        const minutes = plans.reduce((sum, p) => sum + p.total, 0) + (plans.length - 1) * summary.unload_min;

        drawVehicles(live, scores, new Set(chosen), t, skippedMap(skipped, 'chosen'), w.minRate);
        drawRoutes(runs);
        showStops(runs, skipped, t, w.minRate);
        showTiles(km, naiveKm, minutes);
        const skipText = skipped.length ? ` ${skipped.length} run(s) skipped: not worth it.` : '';
        el('picked').textContent =
            `${plans.length} run(s) in ${w.runHours} h: the van collects ${chosen.length} of ${live.length}.${skipText} Grey ones wait.`;
    } catch (err) {
        if (myId !== renderId) return;
        clearRoute();
        el('picked').textContent = 'Route service unavailable: ' + err.message;
    }
}

// ===== 7. Controls =====
slider.oninput = () => render(false);
slider.onchange = () => render(true);
el('mode').onchange = () => render(true);
el('skip').onchange = () => render(true);
el('source').onchange = () => { if (timer) stop(); render(true); };
if (!liveFeed) el('source').querySelector('[value=live]').disabled = true;
['w-time', 'w-dist', 'w-self', 'w-stop', 'shift', 'min-rate'].forEach(id => {
    el(id).oninput = () => render(false);
    el(id).onchange = () => render(true);
});

let timer = null;
const playBtn = el('play');

function stop(){
    clearInterval(timer);
    timer = null;
    playBtn.textContent = 'Play';
    render(true);
}

playBtn.onclick = () => {
    if (timer) return stop();
    playBtn.textContent = 'Pause';
    timer = setInterval(() => {
        slider.value = (Number(slider.value) + 1) % (Number(slider.max) + 1);
        render(false);
    }, Number(el('speed').value));
};

el('speed').onchange = () => {
    if(timer){
        clearInterval(timer);
        timer = null;
        playBtn.click();
    }
};

// ===== 8. Tabs =====
document.querySelectorAll('nav button').forEach(b => b.onclick = () => {
    document.querySelectorAll('nav button').forEach(x => x.classList.toggle('on', x === b));
    document.querySelectorAll('section').forEach(s => s.classList.toggle('on', s.id === b.dataset.tab));
    const onDemand = b.dataset.tab === 'kpi';
    [vehLayer, routeLayer].forEach(l => onDemand ? map.removeLayer(l) : l.addTo(map));
    onDemand ? hexLayer.addTo(map) : map.removeLayer(hexLayer);
    if (onDemand && timer) stop();
});

// ===== 9. Start =====
render(true);


// ===== 10. Live: reload data/live.js every minute =====
function refreshLive(){
    const s = document.createElement('script');
    s.src = 'data/live.js?v=' + Date.now();
    s.onload = () => {
        s.remove();
        liveFeed = window.LIVE;
        liveCases = liveFeed.bikes.map(d => ({...d, ts: Date.parse(d.start) }));
        el('source').querySelector('[value=live]').disabled = false;
        if(el('source').value === 'live'){
            render(true);
        }
    };
    s.onerror = () => s.remove();
    document.body.appendChild(s);
}
setInterval(refreshLive, 60 * 1000);