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
const ROUTE_COLOUR = '#0d366b';


// ===== 4. Draw vehicles =====
//   - clear vehLayer
//   - one circle per vehicle: coloured if in this run, grey otherwise
//   - tooltip: priority, hours standing, metres from station,
//              chance a rider takes it, "Bird serviced it and left it"
function drawVehicles(live, scores, chosenSet, t){
    vehLayer.clearLayers();
    live.forEach((d, i) => {
        const hours = (t - d.ts) / 3600000;
        const lines = [
            `<b>Priority ${fmt(scores[i].score, 2)}</b>`,
            `Standing ${fmt(hours, 1)} h · ${fmt(d.dist_to_station_m + 30)} m from a station`,
            `Chance a rider takes it: ${fmt((1 - scores[i].notSelf) * 100)}%`
        ];
        if(happened(d.serviced_at, t)){
            lines.push('<b>Bird serviced it on site and left it</b>');
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

function showStops(runs, t) {
    let html = '';
    let n = 0;
    runs.forEach((run, r) => {
        html += `<div class="loopname"><i class="dot" style="background:${runColour(r)}"></i>` +
                `Run ${r + 1} · ${run.stops.length} vehicles · ${fmt(run.km, 1)} km</div>` +
                `<ol class="stops" start="${n + 1}">`;
        run.stops.forEach(d => {
            n++;
            html += `<li><a target="_blank" href="https://www.google.com/maps/dir/?api=1&destination=${d.lat},${d.lng}">` +
                    `${fmt(d.dist_to_station_m + 30)} m from station · ${fmt((t - d.ts) / 3600000, 1)} h</a></li>`;
        });
        html += '</ol>';
    });
    el('stops').innerHTML = html;
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
    ['r-km', 'r-naive', 'r-save', 'r-time'].forEach(id => el(id).textContent = '–');
}


// ===== 6. Render everything for the slider moment =====
let renderId = 0;

async function render(withRoute) {
    const myId = ++renderId;
    const t = tMin + slider.value * STEP;
    const w = readWeights();
    const live = cases.filter(d => d.t0 <= t && d.t1 > t);

    el('count').textContent = live.length;
    el('when').textContent = new Date(t).toLocaleString('en-GB',
        { weekday: 'short', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
    ['w-time', 'w-dist', 'w-self', 'w-stop'].forEach(id => el(id + '-v').textContent = el(id).value);
    el('shift-v').textContent = w.runHours + ' h';

    const scores = live.map(d => priority(d, t, w));
    const points = live.map(d => [d.lat, d.lng]);

    // dragging / Play: instant preview, straight dashed lines
    if (!withRoute) {
        const quick = quickDay(points, scores.map(s => s.score), w);
        clearRoute();
        drawVehicles(live, scores, new Set(quick.flat()), t);
        drawPreview(quick.map(tour => tour.map(i => points[i])));
        el('picked').textContent =
            `Preview: ${quick.length} run(s), ${quick.flat().length} of ${live.length} vehicles. Release to build the street route.`;
        return;
    }

    // released: real street routes from OSRM
    drawVehicles(live, scores, new Set(), t);
    el('picked').textContent = 'Planning the route…';

    try {
        const plans = await planDay(live, scores.map(s => s.score), w);
        if (myId !== renderId) return;
        clearRoute();
        if (!plans.length) {
            el('picked').textContent = 'Nothing to collect in this time.';
            return;
        }

        const runs = [];
        let naiveKm = 0;
        for (const plan of plans) {
            const stops = plan.trip.order.map(k => live[plan.chosen[k]]);
            const firstCome = plan.chosen.map(i => live[i]).sort((a, b) => a.t0 - b.t0);
            const naive = await roadRoute(firstCome.map(d => [d.lat, d.lng]));
            naiveKm += naive.km;
            runs.push({ stops, line: plan.trip.line, km: plan.trip.km });
        }
        if (myId !== renderId) return;

        const chosen  = plans.flatMap(p => p.chosen);
        const km      = runs.reduce((sum, run) => sum + run.km, 0);
        const minutes = plans.reduce((sum, p) => sum + p.total, 0) + (plans.length - 1) * summary.unload_min;

        drawVehicles(live, scores, new Set(chosen), t);
        drawRoutes(runs);
        showStops(runs, t);
        showTiles(km, naiveKm, minutes);
        el('picked').textContent =
            `${plans.length} run(s) in ${w.runHours} h: the van collects ${chosen.length} of ${live.length}. Grey ones wait.`;
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
['w-time', 'w-dist', 'w-self', 'w-stop', 'shift'].forEach(id => {
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
// TODO: click on a tab -> highlight it and show its <section>
document.querySelectorAll('nav button').forEach(b => b.onclick = () => {
    document.querySelectorAll('nav button').forEach(x => x.classList.toggle('on', x === b));
    document.querySelectorAll('section').forEach(s => s.classList.toggle('on', s.id === b.dataset.tab));
});

// ===== 9. Start =====
// TODO: render(true)
render(true);