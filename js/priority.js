// ============================================================
// priority.js — how important it is to collect a vehicle
// score = 3·time + 2·distance + 1.5·(not re-rented) + 1.5·bus stop
// Uses: analytics (map.js), sliders from index.html
// ============================================================


// ===== 1. Has an event already happened at moment t? =====
function happened(when, t){
    return when !== null && Date.parse(when) <= t;
}


// ===== 2. Chance that a rider takes the vehicle by themselves =====
const model = analytics.model;

function chanceSelf(d){
    const start = new Date(d.start);
    const hours = start.getHours() + start.getMinutes() / 60;

    const x = [
        d.battery ?? 0.5,
        d.dist_to_station_m,
        d.demand,
        Math.sin(hours / 24 * 2 * Math.PI),
        Math.cos(hours / 24 * 2 * Math.PI)
    ];

    let z = model.intercept;
    for(let i = 0; i < x.length; i++){
        z += model.coef[i] * (x[i] - model.mean[i]) / model.std[i];
    }
    return 1 / (1 + Math.exp(-z));
}


// ===== 3. Read the weight sliders =====
function readWeights(){
    const val = id => Number(document.getElementById(id).value);
    return{
        time: val('w-time'),
        dist: val('w-dist'),
        self: val('w-self'),
        stop: val('w-stop'),
        runHours: val('shift'),
        mode: document.getElementById('mode').value
    };
}


// ===== 4. Priority of one vehicle at moment t =====
function priority(d, t, w){
    if(happened(d.reserved_at, t)){
        return {score: 0, time: 0, dist: 0, notSelf: 0, stop: 0};
    }

    const hours = (t - d.ts) / 3600000;
    const time = Math.min(hours / 12, 1);
    const dist = Math.min(d.dist_to_station_m / 300, 1);
    const notSelf = 1 - chanceSelf(d);
    const stop = Math.max(0, Math.min(1, (40 - d.stop_dist_m) / 20));

    const score = w.time * time + w.dist * dist + w.self * notSelf + w.stop * stop;
    return {score, time, dist, notSelf, stop};
}
