// ============================================================
// route.js — van route on real streets (OSRM, OpenStreetMap data)
// OSRM: free open-source routing engine, no API key needed.
// Uses: depot, summary (map.js)
// ============================================================


// ===== 1. Settings and cache =====
const OSRM = 'https://router.project-osrm.org';
const cache = new Map();


// ===== 2. Points -> text for the OSRM address =====
function toOSRM(points){
    return points.map(p => p[1] + ',' + p[0]).join(';');
}


// ===== 3. Ask OSRM (with cache) =====
async function osrmGet(path) {
    if(cache.has(path)){
        return cache.get(path);
    }
    const res = await fetch(OSRM + path);
    const data = await res.json();
    if(data.code !== "Ok"){
        throw new Error(data.code);
    }
    cache.set(path, data);
    return data;
}


// ===== 4. Best round trip on streets =====
async function roadTrip(points) {
    const data = await osrmGet('/trip/v1/driving/' + toOSRM([depot, ...points]) + '?source=first&roundtrip=true&overview=full&geometries=geojson');
    const trip = data.trips[0];

    const order = [];
    data.waypoints.forEach((wp, i) => {
        if(i > 0){
            order[wp.waypoint_index - 1] = i - 1;
        }
    });

    return {
        order,
        line: trip.geometry.coordinates.map(c => [c[1], c[0]]),
        km: trip.distance / 1000,
        minutes: trip.duration / 60
    };
}


// ===== 5. Fixed order (for comparison "in order of appearance") =====
async function roadRoute(points) {
    const data = await osrmGet('/route/v1/driving/' + toOSRM([depot, ...points, depot]) + '?overview=false');
    return {
        km: data.routes[0].distance / 1000
    };
}


// ===== 6. Plan one run =====
function roughKm(a, b) {
  const r = Math.PI / 180;
  const h = Math.sin((b[0] - a[0]) * r / 2) ** 2 +
            Math.cos(a[0] * r) * Math.cos(b[0] * r) * Math.sin((b[1] - a[1]) * r / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(h)) * summary.detour;
}

function pick(points, scores, budgetMin) {
  const minutesOf = km => km / summary.speed_kmh * 60;
  let tour = [];
  let tourKm = 0;
  const left = new Set(points.keys());
  for (const i of left) if (scores[i] <= 0) left.delete(i);

  while (left.size && tour.length < summary.capacity) {
    let best = null;
    for (const i of left) {
      for (let k = 0; k <= tour.length; k++) {
        const a = k === 0 ? depot : points[tour[k - 1]];
        const b = k === tour.length ? depot : points[tour[k]];
        const extraKm = roughKm(a, points[i]) + roughKm(points[i], b) - roughKm(a, b);
        const value = scores[i] / (minutesOf(extraKm) + summary.stop_min);
        if (!best || value > best.value) best = { i, k, extraKm, value };
      }
    }
    left.delete(best.i);
    const total = minutesOf(tourKm + best.extraKm) + (tour.length + 1) * summary.stop_min;
    if (total > budgetMin) continue;
    tour.splice(best.k, 0, best.i);
    tourKm += best.extraKm;
  }
  return tour;
}

async function planRun(items, scores, budgetMin) {
  const points = items.map(d => [d.lat, d.lng]);
  let chosen = pick(points, scores, budgetMin);

  while (chosen.length) {
    const trip = await roadTrip(chosen.map(i => points[i]));
    const total = trip.minutes + chosen.length * summary.stop_min;
    if (total <= budgetMin) return { chosen, trip, total };
    const weakest = chosen.reduce((m, j) => scores[j] < scores[m] ? j : m);
    chosen = chosen.filter(i => i !== weakest);
  }
  return { chosen: [], trip: null, total: 0 };
}

function roughMinutes(points){
    const path = [depot, ...points, depot];
    let km = 0;
    for(let k = 1;k < path.length; k++){
        km += roughKm(path[k - 1], path[k]);
    }
    return km / summary.speed_kmh * 60 + points.length * summary.stop_min;
}

function quickDay(points, scores, w){
    const runs = [];
    const left = scores.slice();
    let budget = w.runHours * 60;
    while(true){
        const tour = pick(points, left, budget);
        if(!tour.length){
            break;
        }
        runs.push(tour);
        tour.forEach(i => left[i] = 0);
        budget -= roughMinutes(tour.map(i => points[i])) + summary.unload_min;
        if(w.mode === 'one'){
            break;
        }
    }
    return runs;
}

async function planDay(items, scores, w) {
  const runs = [];
  const left = scores.slice();
  let budget = w.runHours * 60;
  while (true) {
    const run = await planRun(items, left, budget);
    if (!run.chosen.length) break;
    runs.push(run);
    run.chosen.forEach(i => left[i] = 0);
    budget -= run.total + summary.unload_min;
    if (w.mode === 'one') break;
  }
  return runs;
}