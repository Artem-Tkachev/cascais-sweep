// ============================================================
// impact.js — Impact tab: simulation results from analytics.py
// Nothing is computed here: we only show numbers from data.js.
// Uses: analytics, summary, fmt (map.js)
// ============================================================


// ===== 1. Scenarios =====
// analytics.scenarios = 4 simulated ways of working over 3 weeks:
//   now (Bird only), opt_2h (our tool, one 2 h run),
//   naive (full shift, first-come order), opt (full shift, our route)
const scenarios = analytics.scenarios;
const base  = scenarios[0].abandoned_hours;
const opt   = scenarios.find(s => s.name === 'opt');
const naive = scenarios.find(s => s.name === 'naive');
const two   = scenarios.find(s => s.name === 'opt_2h');

const NAMES = {
  now:    'Today: Bird only',
  opt_2h: 'Our tool, one 2 h run',
  naive:  'Full shift, first-come order',
  opt:    'Full shift, our route'
};

// ===== 2. Table =====
let rows = '<tr><th>Scenario</th><th>Hours abandoned</th><th>Average</th><th>Collected/day</th><th>km/day</th></tr>';

scenarios.forEach((s, i) => {
  const cut = i === 0 ? '' : ` <small class="muted">(−${fmt((1 - s.abandoned_hours / base) * 100)}%)</small>`;
  rows += `<tr class="${s.name === 'opt' ? 'pick' : ''}">` +
    `<td>${NAMES[s.name]}</td>` +
    `<td>${fmt(s.abandoned_hours)}${cut}</td>` +
    `<td>${fmt(s.mean_h, 1)} h</td>` +
    `<td>${i === 0 ? '—' : fmt(s.collected_per_day, 1)}</td>` +
    `<td>${i === 0 ? '—' : fmt(s.km_per_day)}</td></tr>`;
});

document.getElementById('scentable').innerHTML = rows;


// ===== 3. Notes under the table =====
const fine = summary.fine_eur, today = summary.today_per_day;

let notes =
  `<b>Today</b> the municipal team makes one ~2 h run a day and collects about <b>${today} vehicles</b>. ` +
  `In the <b>same 2 hours</b> our tool collects <b>${fmt(two.collected_per_day, 1)}</b>. ` +
  `Over the <b>full 09:00–18:00 shift</b> one van collects <b>${fmt(opt.collected_per_day, 1)} a day</b> ` +
  `and cuts the time vehicles stand abandoned by <b>${fmt((1 - opt.abandoned_hours / base) * 100)}%</b>. ` +
  `It drives ${fmt(opt.km_per_day)} km a day instead of ${fmt(naive.km_per_day)} km in first-come order.` +
  `<br><br><b>Fines.</b> Bird pays ${fmt(fine, 1)} € per collected vehicle: ${fmt(today * fine)} € a day today → ` +
  `<b>${fmt(opt.collected_per_day * fine)} € a day</b>, about <b>+${fmt((opt.collected_per_day - today) * fine * 21.7)} € a month</b>.` +
  `<br><br><b>Bird was there and left it.</b> In ${summary.serviced_left_cases} cases a Bird technician serviced an already abandoned vehicle on the spot and left it. ` +
  `Together they stood another <b>${fmt(summary.serviced_left_hours)} h</b>. Each case has a place and time: evidence for fines.`;

if (analytics.stop_stats) {
  const st = analytics.stop_stats;
  notes += `<br><br><b>Accessibility.</b> ${st.cases_near_stop} abandoned vehicles stood within 20 m of a bus stop, ` +
           `<b>${fmt(st.stop_hours_total)} h</b> in total. They block wheelchairs, prams and visually impaired people.`;
}

// "Why not just build more stations?" — checked in analytics.py (DBSCAN clusters, 60 m)
const sites = analytics.stations_suggested;
const covered = sites.reduce((sum, c) => sum + c.covered, 0);
notes += `<br><br><b>Why not more stations?</b> The ${sites.length} best new station sites would cover only ` +
         `${covered} of ${summary.abandoned_cases} cases (${fmt(covered / summary.abandoned_cases * 100, 1)}%). ` +
         `Abandoned vehicles are spread across the city (median ${summary.median_dist_m} m from a station), ` +
         `so regular collection works better than new stations. Each station also has an installation and maintenance cost (Cascais Próxima), ` +
         `so a station in a low-demand area would not pay off.`;

document.getElementById('scennote').innerHTML = notes;


// ===== 4. Assumptions =====
document.getElementById('assump').textContent =
  `Simulation on 3 weeks of real data. Depot ${summary.depot.join(', ')}, 1 van, ${summary.capacity} vehicles per run, ` +
  `shift ${summary.shift[0]}:00–${summary.shift[1]}:00, lunch ${summary.lunch[0]}–${summary.lunch[1]}, weekdays only. ` +
  `Road = straight line × ${summary.detour}, ${summary.speed_kmh} km/h, ${summary.stop_min} min per pickup.`;