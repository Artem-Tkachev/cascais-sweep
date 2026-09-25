# Cascais Sweep

**Find abandoned scooters. Plan the van. Clear the streets.**

Hack the City 2026 · Challenge #9 — *Plan collection of abandoned micromobility vehicles (Cascais)*

Two different organisations share Cascais's streets. **Bird** is a private operator: it earns money from rides and must keep its scooters at stations. **Cascais Próxima** is the municipal company that manages mobility for the city. If a scooter stays more than 30 m outside a station area for more than 2 hours, it is *abandoned*: Cascais Próxima removes it with its own van and Bird pays a €4.5 fine for each one. Cascais Sweep detects these vehicles — from historical data and from the operator's live feed — ranks them by priority and plans the municipal van's route on real streets.

---

## What we found (3 weeks of Bird data)

| | |
|---|---|
| Trips / vehicles / stations | 16,888 trips · 1,388 vehicles · 157 stations |
| Abandonment cases | **920** — about **44 new every day**, 49 standing at any moment (max 76) |
| Time on the street after the 2 h limit | median **13.6 h**, 24,791 vehicle-hours in total |
| When Bird picks vehicles up | **94%** of pickups between 06:00 and 14:00 — vehicles left in the afternoon wait until morning |
| Serviced and left | **109** cases where a Bird technician serviced an already abandoned vehicle on the spot and left it (6,652 more hours) |
| Blocking bus stops | 30 cases within 20 m of a stop, 657 h |
| New stations? | the 8 best new sites would remove only **6–14%** of cases — abandonment is spread across the city |

## Impact (simulation on the same 3 weeks)

One municipal van, weekdays 09:00–18:00, 18 vehicles per run:

| Scenario | Vehicle-hours abandoned | Collected / day | km / day |
|---|---|---|---|
| Bird only (no municipal van) | 24,791 | — | — |
| Our tool, one 2 h run a day | 18,840 (−24%) | 12.7 (~10 in our data) | 21 |
| Full shift, first-come order | 11,642 (−53%) | 27.5 | 134 |
| **Full shift, our route** | **10,246 (−59%)** | **30.7** | **94** |

Fines: about €45/day in our data period (~10 vehicles) → €138/day with a full shift (≈ +€2,000 a month).

---

## The website

Open `index.html` through a local server (see *Run it*) or on GitHub Pages.

**Collection**
- Move through 3 weeks of real data (15-minute steps) or switch to **Live** — Bird's public feed, refreshed every minute.
- Every abandoned vehicle gets a priority score:
  `score = 3·time + 2·distance + 1.5·(1 − chance a rider takes it) + 1.5·bus stop`
  (time: hours / 12, max 1 · distance: metres beyond the zone / 300, max 1 · bus stop: 1 within 20 m, 0 beyond 40 m · reserved vehicles: 0). Weights are sliders.
- The planner picks the vehicles worth the most per minute of detour, within the van capacity (18) and the time available — **one run** or **as many runs as fit**.
- The order and the path come from **OSRM** (open-source routing on OpenStreetMap), compared with visiting the same vehicles in first-come order. Numbered stop list with a navigation link for the driver.
- While dragging a slider or playing the timeline, a dashed straight-line preview is shown; the street route is requested when you release.

**Demand** — supply/demand KPIs per H3 hexagon (~170 m): trips started (demand), trips ended (supply), imbalance, abandonments per day, share of trip ends abandoned.

**Impact** — the simulation results above, fines, accessibility, and why more stations would not solve the problem.

`charts.html` — the earlier analysis page with hourly charts and suggested new station sites.

---

## How it works

```
data/copy_viagens.xlsx (events) ─┐
data/copy_cartoes.xlsx (trips)  ─┼─ detect.py ──▶ abandoned cases ─┐
data/station_information.json  ─┘                                  ├─ analytics.py ──▶ data/data.js ─┐
data/stops.csv (TML bus stops) ────────────────────────────────────┘                                  │
                                                                                                        ├─▶ index.html + js/
Bird GBFS feed ─▶ live.py (snapshot every minute) ─▶ live_map.py (every minute) ─▶ data/live.js ─────────┘
```

**`detect.py`** — builds the allowed zone (station polygons + 30 m, in metres, EPSG:3763), cuts each vehicle's events into parking episodes (from `trip_end` / `provider_drop_off` to `trip_start` / real pickup), and keeps those outside the zone for more than 120 min. A `maintenance_pick_up` followed by a drop-off at the same place (< 50 m) is an on-site service, not a pickup. Timestamps are UTC → Lisbon time.

**`analytics.py`** — H3 KPIs, hourly profiles, DBSCAN clusters for new-station sites, a logistic-regression model *"will a rider take this vehicle by themselves?"* (battery, distance, local demand, hour of day; accuracy 64.9% vs 56.9% baseline), distance to bus stops, and the 3-week van simulation.

**`live.py`** — saves Bird's GBFS `free_bike_status` every minute to `data/snapshots/` (read-only files).

**`live_map.py`** — Bird changes `bike_id` on every request, so vehicles are matched between snapshots by position: exact coordinates first (~95%), then the nearest one within 5 m of the same type (only if snapshots are ≤ 5 min apart). This keeps how long each vehicle has been standing and flags on-site battery swaps (charge +30 points). Every minute it writes the abandoned ones to `data/live.js`.

**Website (`js/`)**

| File | Role |
|---|---|
| `map.js` | data, map, stations, depot |
| `priority.js` | the priority score and the model |
| `route.js` | vehicle selection, runs, OSRM requests |
| `collection.js` | Collection tab: time slider, live mode, drawing |
| `demand.js` | Demand tab: H3 hexagons |
| `impact.js` | Impact tab |

Only open tools: Python (pandas, geopandas, shapely, h3, scikit-learn), Leaflet, OpenStreetMap tiles, OSRM. No API keys.

---

## Run it

```bash
pip install pandas openpyxl geopandas shapely h3 scikit-learn requests

# historical analysis (needs the challenge data files in data/)
python detect.py
python analytics.py        # -> data/data.js

# live mode (three terminals)
python live.py             # snapshot of the Bird feed every minute
python live_map.py         # -> data/live.js every minute
python -m http.server 8000 # open http://localhost:8000
```

The challenge data files are not in this repository.

---

## Assumptions and limits

- Simulation: straight-line distance × 1.35, 20 km/h, 3 min per pickup, 10 min unloading, lunch 13–14, weekdays only.
- Several runs are planned greedily one after another; a VRP solver would balance them better.
- GPS accuracy: ~4% of cases lie within 5 m of the 30 m border; they get a low priority.
- Live mode shows the time Bird publishes (`last_updated`), usually 1–2 minutes behind.

## Next

- Pilot with Cascais Próxima on a small server; store events instead of full snapshots.
- VROOM (VRP solver on OSRM) for multi-run plans.
- GBFS is an open standard, so the tool works for other operators and cities.
- Use scooter trips that start at bus stops to find where and when people need bus connections that do not exist yet.

---

Built by Artem Tkachev (NOVA IMS). Rules and parameters (depot, van capacity, current workflow, fine, time zone) confirmed with João Silva, Cascais Próxima.
