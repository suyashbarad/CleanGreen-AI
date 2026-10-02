// ==========================================================================
// Clean and Green Tech — Admin Console & Live Route Operations
// Team Pixel Minds
// ==========================================================================

const STATE = {
  activeTab: "tab-map",
  osmBins: [],
  complaints: [],
  map: null,
  binLayer: null,
  complaintLayer: null,
  gapLinesLayer: null,
  truckMarker: null,
  routePolyline: null,
  routeCoords: [],
  truckAnimation: {
    isRunning: true,
    speed: 0.003, // Step increment
    currentSegmentIndex: 0,
    segmentProgress: 0,
    timerId: null
  },
  selectedComplaint: null
};

// Municipal Depot Coordinates (Near Pashan / Baner PMC Ward Office)
const DEPOT_COORDS = [18.5480, 73.7920];

// DOM Elements
const tabBtnMap = document.getElementById("tab-btn-map");
const tabBtnComplaints = document.getElementById("tab-btn-complaints");
const panelMap = document.getElementById("panel-map");
const panelComplaints = document.getElementById("panel-complaints");

const statOsmBins = document.getElementById("stat-osm-bins");
const statComplaints = document.getElementById("stat-complaints");
const badgeComplaintsCount = document.getElementById("badge-complaints-count");

const stripBinsVal = document.getElementById("strip-bins-val");
const stripComplaintsVal = document.getElementById("strip-complaints-val");
const stripGapsVal = document.getElementById("strip-gaps-val");
const stripRouteKm = document.getElementById("strip-route-km");

const btnToggleTruck = document.getElementById("btn-toggle-truck");
const truckPlayIcon = document.getElementById("truck-play-icon");
const btnResetMapView = document.getElementById("btn-reset-map-view");
const truckStatusText = document.getElementById("truck-status-text");

const swiggyTracker = document.getElementById("swiggy-tracker");
const trackerProgress = document.getElementById("tracker-progress");
const trackerStepDesc = document.getElementById("tracker-step-desc");
const trackerEta = document.getElementById("tracker-eta");

const complaintsContainer = document.getElementById("complaints-container");
const searchComplaints = document.getElementById("search-complaints");
const btnRefreshComplaints = document.getElementById("btn-refresh-complaints");

// Forensic Drawer Elements
const forensicDrawer = document.getElementById("forensic-drawer");
const btnDrawerClose = document.getElementById("btn-drawer-close");
const drawerComplaintId = document.getElementById("drawer-complaint-id");
const drawerTitle = document.getElementById("drawer-title");
const drawerContent = document.getElementById("drawer-content");
const drawerStatusSelect = document.getElementById("drawer-status-select");
const btnUpdateStatus = document.getElementById("btn-update-status");
const linkDownloadJson = document.getElementById("link-download-json");
const linkDownloadCsv = document.getElementById("link-download-csv");

// ==========================================================================
// 1. Initialization & Tab Switching
// ==========================================================================
document.addEventListener("DOMContentLoaded", async () => {
  setupTabs();
  initAdminMap();
  setupEventListeners();
  await loadData();
});

function setupTabs() {
  tabBtnMap.addEventListener("click", () => switchTab("tab-map"));
  tabBtnComplaints.addEventListener("click", () => switchTab("tab-complaints"));
}

function switchTab(tabId) {
  STATE.activeTab = tabId;

  if (tabId === "tab-map") {
    tabBtnMap.classList.add("active");
    tabBtnComplaints.classList.remove("active");
    panelMap.classList.add("active");
    panelComplaints.classList.remove("active");

    setTimeout(() => {
      if (STATE.map) {
        STATE.map.invalidateSize();
        fitAllPins();
      }
    }, 150);
  } else {
    tabBtnMap.classList.remove("active");
    tabBtnComplaints.classList.add("active");
    panelMap.classList.remove("active");
    panelComplaints.classList.add("active");
    renderComplaintsLedger(STATE.complaints);
  }
}

// ==========================================================================
// 2. Admin Map Setup
// ==========================================================================
function initAdminMap() {
  // Default centered around Baner/Pashan/Kothrud corridor where bins are located
  STATE.map = L.map("admin-map", {
    center: [18.5500, 73.8000],
    zoom: 13,
    zoomControl: true
  });

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 19
  }).addTo(STATE.map);

  STATE.binLayer = L.featureGroup().addTo(STATE.map);
  STATE.complaintLayer = L.featureGroup().addTo(STATE.map);
  STATE.gapLinesLayer = L.featureGroup().addTo(STATE.map);
}

// ==========================================================================
// 3. Load OSM Bins & Complaints Data
// ==========================================================================
async function loadData(isSilent = false) {
  try {
    if (!isSilent) {
      // 1. Fetch OSM Bins on initial load
      const binsRes = await fetch("/api/osm/bins");
      if (binsRes.ok) {
        const data = await binsRes.json();
        STATE.osmBins = data.bins || [];
        statOsmBins.textContent = STATE.osmBins.length;
        stripBinsVal.textContent = STATE.osmBins.length;
      }
    }

    // 2. Fetch Complaints
    const compRes = await fetch("/api/complaints");
    if (compRes.ok) {
      const data = await compRes.json();
      STATE.complaints = data.complaints || [];
      statComplaints.textContent = STATE.complaints.length;
      badgeComplaintsCount.textContent = STATE.complaints.length;
      stripComplaintsVal.textContent = STATE.complaints.length;
    }

    if (!isSilent) {
      renderMapData();
      buildCollectionRouteAndStartTruck();
    } else {
      updateComplaintPinsOnly();
    }

    renderComplaintsLedger(STATE.complaints);

  } catch (err) {
    if (!isSilent) console.error("Error loading admin data:", err);
  }
}

function updateComplaintPinsOnly() {
  if (!STATE.complaintLayer) return;
  STATE.complaintLayer.clearLayers();
  STATE.gapLinesLayer.clearLayers();
  let criticalGapCount = 0;

  STATE.complaints.forEach((c) => {
    const lat = c.coordinates ? c.coordinates.latitude : null;
    const lng = c.coordinates ? c.coordinates.longitude : null;
    if (!lat || !lng) return;

    const { nearestBin, minDistanceKm } = findNearestBin(lat, lng);
    const isBinGap = minDistanceKm > 0.6;
    if (isBinGap) criticalGapCount++;

    const isProcessing = c.analysis_status === "in_progress" || (!c.urls?.annotated_image && !c.report);
    const pinClass = isBinGap ? "custom-gap-pin" : "custom-complaint-pin";
    const pinIconSymbol = isProcessing ? "fa-spinner fa-spin" : (isBinGap ? "fa-circle-exclamation" : "fa-triangle-exclamation");

    const complaintPin = L.divIcon({
      className: "custom-complaint-pin-wrapper",
      html: `<div class="${pinClass}" title="${c.complaint_id}"><i class="fa-solid ${pinIconSymbol}"></i></div>`,
      iconSize: isBinGap ? [36, 36] : [32, 32],
      iconAnchor: [16, 32],
      popupAnchor: [0, -28]
    });

    const marker = L.marker([lat, lng], { icon: complaintPin }).addTo(STATE.complaintLayer);

    if (nearestBin) {
      const nLat = nearestBin.lat || nearestBin.center.lat;
      const nLon = nearestBin.lon || nearestBin.center.lon;
      L.polyline([[lat, lng], [nLat, nLon]], {
        color: isBinGap ? "#ef4444" : "#f59e0b",
        weight: 2,
        dashArray: "4, 6",
        opacity: 0.65
      }).addTo(STATE.gapLinesLayer);
    }
  });

  stripGapsVal.textContent = criticalGapCount;
}

// ==========================================================================
// 4. Render Pins: Green (Bins), Orange (Complaints), Red (New Bin Needed)
// ==========================================================================
function renderMapData() {
  STATE.binLayer.clearLayers();
  STATE.complaintLayer.clearLayers();
  STATE.gapLinesLayer.clearLayers();

  let criticalGapCount = 0;

  // 1. Render Green Bins (Existing OSM Bins)
  STATE.osmBins.forEach((b, idx) => {
    const lat = b.lat || (b.center && b.center.lat);
    const lon = b.lon || (b.center && b.center.lon);
    if (!lat || !lon) return;

    const amenity = b.tags ? b.tags.amenity : "waste_basket";
    const name = (b.tags && b.tags.name) ? b.tags.name : "Municipal Dustbin";

    const greenPin = L.divIcon({
      className: "custom-bin-pin-wrapper",
      html: `<div class="custom-bin-pin" title="${name} (${amenity})"><i class="fa-solid fa-trash-can"></i></div>`,
      iconSize: [28, 28],
      iconAnchor: [14, 14],
      popupAnchor: [0, -14]
    });

    const marker = L.marker([lat, lon], { icon: greenPin }).addTo(STATE.binLayer);
    marker.bindPopup(`
      <div style="font-size: 0.85rem;">
        <span style="background: #ecfdf5; color: #047857; padding: 2px 6px; border-radius: 4px; font-weight: 700; font-size: 10px;">
          <i class="fa-solid fa-check"></i> OSM EXISTING BIN
        </span>
        <h4 style="margin: 5px 0 2px; font-size: 0.95rem;">${name}</h4>
        <div style="color: #64748b; font-size: 0.78rem;">Type: <code>${amenity}</code></div>
        <div style="font-family: monospace; font-size: 0.75rem; color: #334155; margin-top: 4px;">(${lat.toFixed(5)}, ${lon.toFixed(5)})</div>
      </div>
    `);
  });

  // 2. Render Complaints with Proximity Calculation
  STATE.complaints.forEach((c) => {
    const lat = c.coordinates ? c.coordinates.latitude : null;
    const lng = c.coordinates ? c.coordinates.longitude : null;
    if (!lat || !lng) return;

    // Calculate nearest bin distance
    const { nearestBin, minDistanceKm } = findNearestBin(lat, lng);

    // If nearest bin is > 0.6 km (600m), flag as RED GAP (New bin needed!)
    const isBinGap = minDistanceKm > 0.6;
    if (isBinGap) criticalGapCount++;

    const pinClass = isBinGap ? "custom-gap-pin" : "custom-complaint-pin";
    const pinIconSymbol = isBinGap ? "fa-circle-exclamation" : "fa-triangle-exclamation";

    const complaintPin = L.divIcon({
      className: "custom-complaint-pin-wrapper",
      html: `<div class="${pinClass}" title="${c.complaint_id}"><i class="fa-solid ${pinIconSymbol}"></i></div>`,
      iconSize: isBinGap ? [36, 36] : [32, 32],
      iconAnchor: [16, 32],
      popupAnchor: [0, -28]
    });

    const marker = L.marker([lat, lng], { icon: complaintPin }).addTo(STATE.complaintLayer);

    // Draw connecting line to nearest bin
    if (nearestBin) {
      const nLat = nearestBin.lat || nearestBin.center.lat;
      const nLon = nearestBin.lon || nearestBin.center.lon;

      L.polyline([[lat, lng], [nLat, nLon]], {
        color: isBinGap ? "#ef4444" : "#f59e0b",
        weight: 2,
        dashArray: "4, 6",
        opacity: 0.65
      }).addTo(STATE.gapLinesLayer);
    }

    const itemCount = c.stats ? c.stats.item_count : (c.report && c.report.items ? c.report.items.length : "N/A");
    const thumbUrl = c.urls && c.urls.annotated_image ? c.urls.annotated_image : (c.urls ? c.urls.original_image : "");

    marker.bindPopup(`
      <div style="max-width: 240px; font-size: 0.82rem;">
        ${isBinGap ? `
          <div style="background: #fef2f2; color: #dc2626; border: 1px solid #fecaca; padding: 2px 6px; border-radius: 4px; font-weight: 700; font-size: 10px; margin-bottom: 4px;">
            <i class="fa-solid fa-circle-exclamation"></i> NEW BIN REQUIRED (LACK OF BINS)
          </div>
        ` : `
          <div style="background: #fffbeb; color: #b45309; border: 1px solid #fde68a; padding: 2px 6px; border-radius: 4px; font-weight: 700; font-size: 10px; margin-bottom: 4px;">
            <i class="fa-solid fa-triangle-exclamation"></i> REPORTED WASTE
          </div>
        `}
        ${thumbUrl ? `<img src="${thumbUrl}" style="width: 100%; height: 90px; object-fit: cover; border-radius: 4px; margin-bottom: 4px;" />` : ""}
        <strong style="color: #0f172a;">${c.complaint_id}</strong>
        <div style="color: #475569; font-size: 0.75rem; margin: 2px 0;">${c.address || "Pune Area"}</div>
        <div style="font-size: 0.75rem; margin-top: 4px;">
          <strong>Nearest Bin:</strong> <span style="color: ${isBinGap ? '#dc2626' : '#047857'}; font-weight: 700;">${minDistanceKm.toFixed(2)} km</span>
        </div>
        <div style="font-size: 0.75rem;"><strong>Items Found:</strong> ${itemCount}</div>
        <button onclick="openForensicDrawerById('${c.complaint_id}')" style="margin-top: 6px; width: 100%; background: #0f172a; color: white; border: none; padding: 4px; border-radius: 4px; font-size: 11px; font-weight: 600; cursor: pointer;">
          Inspect AI Forensics
        </button>
      </div>
    `);
  });

  stripGapsVal.textContent = criticalGapCount;
  fitAllPins();
}

function fitAllPins() {
  if (!STATE.map) return;
  const allLayers = L.featureGroup([STATE.binLayer, STATE.complaintLayer]);
  if (allLayers.getLayers().length > 0) {
    STATE.map.fitBounds(allLayers.getBounds(), { padding: [40, 40], maxZoom: 15 });
  }
}

// Distance Calculation (Haversine formula in km)
function findNearestBin(lat, lng) {
  let nearestBin = null;
  let minDistanceKm = 9999;

  STATE.osmBins.forEach((b) => {
    const bLat = b.lat || (b.center && b.center.lat);
    const bLon = b.lon || (b.center && b.center.lon);
    if (!bLat || !bLon) return;

    const d = haversineDistance(lat, lng, bLat, bLon);
    if (d < minDistanceKm) {
      minDistanceKm = d;
      nearestBin = b;
    }
  });

  return { nearestBin, minDistanceKm };
}

function haversineDistance(lat1, lon1, lat2, lon2) {
  const R = 6371; // Earth radius in km
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
            Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
            Math.sin(dLon / 2) * Math.sin(dLon / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return R * c;
}

// ==========================================================================
// 5. Swiggy / Zomato Animated Garbage Truck Engine
// ==========================================================================
// 5. Swiggy / Zomato Animated Garbage Truck Engine (Real Street Roads via OSRM)
// ==========================================================================
async function buildCollectionRouteAndStartTruck() {
  const stops = [DEPOT_COORDS];

  // Pick representative bins for collection
  const nearbyBins = STATE.osmBins.slice(0, 4);
  nearbyBins.forEach(b => {
    const bLat = b.lat || (b.center && b.center.lat);
    const bLon = b.lon || (b.center && b.center.lon);
    if (bLat && bLon) stops.push([bLat, bLon]);
  });

  // Add complaints
  STATE.complaints.forEach(c => {
    if (c.coordinates && c.coordinates.latitude && c.coordinates.longitude) {
      stops.push([c.coordinates.latitude, c.coordinates.longitude]);
    }
  });

  if (stops.length < 3) {
    stops.push([18.5178, 73.8151]); // MIT-WPU Kothrud
    stops.push([18.5300, 73.8300]);
  }

  // Return to depot
  stops.push(DEPOT_COORDS);

  // Fetch real turn-by-turn road geometry from OpenStreetMap OSRM
  trackerStepDesc.textContent = "Calculating turn-by-turn street route...";
  const roadResult = await fetchStreetRoadRoute(stops);
  STATE.routeCoords = roadResult.coords;

  if (roadResult.distanceKm) {
    stripRouteKm.textContent = `${roadResult.distanceKm} km (Roads)`;
  } else {
    let totalKm = 0;
    for (let i = 0; i < STATE.routeCoords.length - 1; i++) {
      totalKm += haversineDistance(
        STATE.routeCoords[i][0], STATE.routeCoords[i][1],
        STATE.routeCoords[i + 1][0], STATE.routeCoords[i + 1][1]
      );
    }
    stripRouteKm.textContent = `${totalKm.toFixed(1)} km`;
  }

  // Draw collection route polyline along street roads
  if (STATE.routePolyline) STATE.map.removeLayer(STATE.routePolyline);

  STATE.routePolyline = L.polyline(STATE.routeCoords, {
    color: "#059669",
    weight: 5,
    opacity: 0.9,
    dashArray: "8, 6",
    lineCap: "round",
    lineJoin: "round"
  }).addTo(STATE.map);

  // Create Animated Vehicle Marker (Top-down navigation vehicle)
  const truckIcon = L.divIcon({
    className: "truck-marker-wrapper",
    html: `
      <div class="nav-vehicle-marker" id="truck-icon-el">
        <div class="vehicle-pulse-ring"></div>
        <svg class="vehicle-svg" viewBox="0 0 36 50" fill="none" xmlns="http://www.w3.org/2000/svg">
          <rect x="5" y="8" width="26" height="38" rx="5" fill="rgba(0,0,0,0.3)"/>
          <rect x="2" y="11" width="4" height="9" rx="1.5" fill="#0f172a"/>
          <rect x="30" y="11" width="4" height="9" rx="1.5" fill="#0f172a"/>
          <rect x="2" y="32" width="4" height="9" rx="1.5" fill="#0f172a"/>
          <rect x="30" y="32" width="4" height="9" rx="1.5" fill="#0f172a"/>
          <rect x="5" y="6" width="26" height="38" rx="5" fill="#059669" stroke="#ffffff" stroke-width="2"/>
          <path d="M8 8C8 6.89543 8.89543 6 10 6H26C27.1046 6 28 6.89543 28 8V18H8V8Z" fill="#047857"/>
          <rect x="10" y="10" width="16" height="7" rx="2" fill="#38bdf8"/>
          <circle cx="10" cy="7" r="2" fill="#fef08a"/>
          <circle cx="26" cy="7" r="2" fill="#fef08a"/>
          <rect x="7" y="21" width="22" height="21" rx="3" fill="#065f46" stroke="#10b981" stroke-width="1.5"/>
          <rect x="11" y="24" width="14" height="4" rx="1" fill="#10b981" opacity="0.6"/>
          <rect x="11" y="30" width="14" height="4" rx="1" fill="#10b981" opacity="0.6"/>
          <circle cx="18" cy="19" r="2.5" fill="#f59e0b" stroke="#ffffff" stroke-width="1"/>
        </svg>
      </div>
    `,
    iconSize: [46, 46],
    iconAnchor: [23, 23]
  });

  if (STATE.truckMarker) STATE.map.removeLayer(STATE.truckMarker);
  STATE.truckMarker = L.marker(STATE.routeCoords[0], { icon: truckIcon }).addTo(STATE.map);

  // Start Swiggy/Zomato live street navigation loop
  startTruckAnimation();
}

async function fetchStreetRoadRoute(stops) {
  try {
    // Up to 8 key stops to ensure fast OSRM query
    const keyStops = stops.length > 8 
      ? [stops[0], stops[1], stops[2], ...stops.slice(stops.length - 3)] 
      : stops;

    const coordsParam = keyStops.map(s => `${s[1].toFixed(5)},${s[0].toFixed(5)}`).join(";");
    const url = `https://router.project-osrm.org/route/v1/driving/${coordsParam}?overview=full&geometries=geojson`;

    const resp = await fetch(url);
    if (!resp.ok) throw new Error("OSRM routing service unavailable");
    const data = await resp.json();

    if (data && data.routes && data.routes.length > 0) {
      const roadGeoJson = data.routes[0].geometry.coordinates; // [[lon, lat], ...]
      const roadDistanceKm = (data.routes[0].distance / 1000).toFixed(1);
      
      // Convert to [lat, lon]
      const roadLatLons = roadGeoJson.map(pt => [pt[1], pt[0]]);
      
      // Micro-interpolate between street coordinates for butter-smooth steering
      const denseRoadCoords = interpolateDenseStreetWaypoints(roadLatLons, 3);
      return { coords: denseRoadCoords, distanceKm: roadDistanceKm };
    }
  } catch (err) {
    console.warn("OSRM street routing notice (using fallback):", err);
  }

  // Graceful fallback if offline
  return { coords: generateInterpolatedRoute(stops), distanceKm: null };
}

function interpolateDenseStreetWaypoints(points, steps = 3) {
  const dense = [];
  for (let i = 0; i < points.length - 1; i++) {
    const p1 = points[i];
    const p2 = points[i + 1];
    for (let s = 0; s < steps; s++) {
      const frac = s / steps;
      dense.push([
        p1[0] + (p2[0] - p1[0]) * frac,
        p1[1] + (p2[1] - p1[1]) * frac
      ]);
    }
  }
  dense.push(points[points.length - 1]);
  return dense;
}

function generateInterpolatedRoute(stops) {
  const interpolated = [];
  for (let i = 0; i < stops.length - 1; i++) {
    const start = stops[i];
    const end = stops[i + 1];
    const steps = 25;
    for (let s = 0; s <= steps; s++) {
      const frac = s / steps;
      const lat = start[0] + (end[0] - start[0]) * frac;
      const lng = start[1] + (end[1] - start[1]) * frac;
      interpolated.push([lat, lng]);
    }
  }
  return interpolated;
}

function startTruckAnimation() {
  if (STATE.truckAnimation.timerId) clearInterval(STATE.truckAnimation.timerId);

  let stepIdx = 0;
  const totalSteps = STATE.routeCoords.length;

  STATE.truckAnimation.timerId = setInterval(() => {
    if (!STATE.truckAnimation.isRunning || totalSteps === 0) return;

    stepIdx = (stepIdx + 1) % totalSteps;
    const currentPos = STATE.routeCoords[stepIdx];
    const nextPos = STATE.routeCoords[(stepIdx + 1) % totalSteps];

    STATE.truckMarker.setLatLng(currentPos);

    // Rotate vehicle towards street heading
    const angle = calculateHeadingAngle(currentPos, nextPos);
    const truckIconEl = document.getElementById("truck-icon-el");
    if (truckIconEl) {
      truckIconEl.style.transform = `rotate(${angle}deg)`;
    }

    // Update floating Swiggy tracker card
    const progressPercent = Math.round((stepIdx / totalSteps) * 100);
    trackerProgress.style.width = `${progressPercent}%`;

    const remainingKm = ((1 - (stepIdx / totalSteps)) * 11.2).toFixed(1);
    const etaMins = Math.max(1, Math.round(remainingKm * 2.2));
    trackerEta.textContent = `ETA: ${etaMins} Mins • ${remainingKm} km left`;

    if (progressPercent < 35) {
      trackerStepDesc.textContent = "Clearing Baner & Pashan municipal street bins...";
    } else if (progressPercent < 75) {
      trackerStepDesc.textContent = "Arriving at reported waste blackspot for clearance...";
    } else {
      trackerStepDesc.textContent = "Returning via arterial road to Municipal Depot...";
    }

  }, 80); // 80ms tick for fluid street driving
}

function calculateHeadingAngle(pos1, pos2) {
  const dLat = pos2[0] - pos1[0];
  const dLng = pos2[1] - pos1[1];
  const rad = Math.atan2(dLng, dLat);
  return (rad * 180 / Math.PI);
}

// ==========================================
// 6. Complaints Ledger & Forensic Drawer
// ==========================================
function renderComplaintsLedger(list) {
  if (!complaintsContainer) return;

  if (list.length === 0) {
    complaintsContainer.innerHTML = `
      <div style="grid-column: 1/-1; background: white; padding: 2.5rem; text-align: center; border-radius: 8px; border: 1px dashed #cbd5e1;">
        <i class="fa-solid fa-folder-open" style="font-size: 2.5rem; color: #94a3b8; margin-bottom: 0.75rem;"></i>
        <h3 style="color: #1e293b;">No Complaints Filed Yet</h3>
        <p style="color: #64748b; font-size: 0.85rem; margin-top: 0.25rem;">
          Go to the <a href="index.html" style="color: #059669; font-weight: 700;">Citizen Reporter</a> to upload a photo and file a waste spot.
        </p>
      </div>
    `;
    return;
  }

  complaintsContainer.innerHTML = list.map((c) => {
    const urls = c.urls || {};
    const stats = c.stats || {};
    const isProcessing = c.analysis_status === "in_progress" || (!urls.annotated_image && !c.report);
    const isFailed = c.analysis_status === "failed";
    const imgUrl = urls.annotated_image || urls.original_image || "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='100' height='100'><rect fill='%23e2e8f0' width='100' height='100'/></svg>";
    const statusClass = isProcessing ? "status-processing" : (c.status === "Resolved" ? "status-resolved" : (c.status === "Truck Dispatched" ? "status-dispatched" : "status-pending"));

    return `
      <div class="complaint-card ${isProcessing ? 'processing' : ''}" onclick="openForensicDrawerById('${c.complaint_id}')">
        <div style="position: relative;">
          <img src="${imgUrl}" class="complaint-card-image" alt="Waste Image" />
          ${isProcessing ? `
            <span class="complaint-badge-overlay" style="background: rgba(2,132,199,0.92);">
              <i class="fa-solid fa-spinner fa-spin"></i> AI SCANNING
            </span>
          ` : (isFailed ? `
            <span class="complaint-badge-overlay" style="background: rgba(220,38,38,0.92);">
              <i class="fa-solid fa-triangle-exclamation"></i> TIMEOUT
            </span>
          ` : (urls.annotated_image ? `
            <span class="complaint-badge-overlay">
              <i class="fa-solid fa-draw-polygon"></i> ANNOTATED
            </span>
          ` : ""))}
        </div>
        <div class="complaint-card-body">
          <div class="complaint-top-row">
            <span class="complaint-cid">${c.complaint_id}</span>
            <span class="status-pill ${statusClass}">${isProcessing ? "AI Scanning..." : (c.status || "Pending")}</span>
          </div>
          <div class="complaint-address">
            <i class="fa-solid fa-location-dot" style="color: #059669;"></i> ${c.address || "Pune Blackspot"}
          </div>
          <div style="font-size: 0.72rem; color: #64748b;">
            <i class="fa-regular fa-clock"></i> ${c.local_time || c.timestamp || "Recent"}
          </div>
          <div class="complaint-metrics-row">
            ${isProcessing ? `
              <div class="card-progress-screen">
                <div class="card-progress-header">
                  <span><i class="fa-solid fa-microchip fa-spin"></i> AI ANALYZING</span>
                  <button type="button" class="btn-card-retry" onclick="event.stopPropagation(); retryComplaintAnalysis('${c.complaint_id}')" title="Re-run AI">
                    <i class="fa-solid fa-rotate-right"></i> Retry
                  </button>
                </div>
                <div class="card-progress-track">
                  <div class="card-progress-fill"></div>
                </div>
                <div class="card-progress-subtext">
                  <span>Detecting items & bounding boxes...</span>
                </div>
              </div>
            ` : (isFailed ? `
              <div class="card-progress-screen" style="background: #fef2f2; border-color: #fecaca;">
                <div class="card-progress-header" style="color: #b91c1c;">
                  <span><i class="fa-solid fa-triangle-exclamation"></i> ANALYSIS TIMEOUT</span>
                  <button type="button" class="btn-card-retry" style="border-color: #fca5a5; color: #b91c1c;" onclick="event.stopPropagation(); retryComplaintAnalysis('${c.complaint_id}')">
                    <i class="fa-solid fa-rotate-right"></i> Retry
                  </button>
                </div>
                <div class="card-progress-subtext" style="color: #b91c1c;">
                  <span>Click Retry to run with fast model</span>
                </div>
              </div>
            ` : `
              <div class="c-metric">Items: <strong>${stats.item_count || 0}</strong></div>
              <div class="c-metric">SUP Violations: <strong style="color: ${stats.sup_violations > 0 ? '#dc2626' : '#059669'}">${stats.sup_violations || 0}</strong></div>
            `)}
          </div>
        </div>
      </div>
    `;
  }).join("");
}

// Open Forensic Drawer by Complaint ID
window.openForensicDrawerById = function (cid) {
  const complaint = STATE.complaints.find(c => c.complaint_id === cid);
  if (!complaint) return;
  STATE.selectedComplaint = complaint;

  drawerComplaintId.textContent = complaint.complaint_id;
  drawerTitle.textContent = `Forensic Waste Audit — ${complaint.address || "Pune"}`;
  drawerStatusSelect.value = complaint.status || "Pending";

  const urls = complaint.urls || {};
  const report = complaint.report || {};
  const items = report.items || [];
  const stats = complaint.stats || {};
  const isProcessing = complaint.analysis_status === "in_progress" || (!urls.annotated_image && !complaint.report);

  linkDownloadJson.href = urls.json_report || "#";
  linkDownloadCsv.href = urls.csv_report || "#";

  if (isProcessing) {
    drawerContent.innerHTML = `
      <!-- Live Progress Diagnostics Screen -->
      <div class="drawer-progress-monitor">
        <div class="drawer-progress-header">
          <div class="drawer-progress-title">
            <span class="progress-pulsar"></span>
            <span>Live Model Diagnostics & Forensic Ingestion Monitor</span>
          </div>
          <button type="button" class="btn-drawer-retry" onclick="retryComplaintAnalysis('${complaint.complaint_id}')">
            <i class="fa-solid fa-rotate-right"></i> Force Re-Analyze
          </button>
        </div>

        <div class="drawer-progress-bar-track">
          <div class="drawer-progress-bar-fill"></div>
        </div>

        <div class="progress-steps-list">
          <div class="progress-step-item completed">
            <i class="fa-solid fa-circle-check"></i>
            <span><strong>Step 1:</strong> Full-Resolution Raw Photo & GPS Geolocation Ingestion Complete</span>
          </div>
          <div class="progress-step-item active">
            <i class="fa-solid fa-spinner fa-spin"></i>
            <span><strong>Step 2:</strong> Gemini Multimodal Spatial Scan (Detecting individual garbage items & coordinates)</span>
          </div>
          <div class="progress-step-item queued">
            <i class="fa-regular fa-circle"></i>
            <span><strong>Step 3:</strong> 4-Quadrant 2D Bounding Box Extraction & Pillow Annotator</span>
          </div>
          <div class="progress-step-item queued">
            <i class="fa-regular fa-circle"></i>
            <span><strong>Step 4:</strong> Plastic Resin Classification (1-7) & CPCB EPR Brand Verification</span>
          </div>
        </div>
      </div>

      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.85rem; margin-bottom: 1.25rem;">
        <div>
          <div style="font-size: 0.75rem; font-weight: 700; color: #475569; margin-bottom: 0.35rem;">
            CITIZEN RAW CAPTURE (ACTIVE RADAR SCAN)
          </div>
          <div class="photo-scanning-container">
            <div class="radar-scan-line"></div>
            <img src="${urls.original_image || ''}" style="width: 100%; height: 210px; object-fit: cover; display: block;" />
          </div>
        </div>
        <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 210px; background: #f0f9ff; border: 1.5px dashed #0284c7; border-radius: 6px; color: #0369a1; padding: 1.25rem; text-align: center;">
          <i class="fa-solid fa-brain fa-bounce" style="font-size: 2.2rem; margin-bottom: 0.75rem; color: #0284c7;"></i>
          <strong style="font-size: 0.95rem; color: #0c4a6e;">Multimodal Model Running</strong>
          <p style="font-size: 0.75rem; color: #0284c7; margin-top: 0.35rem; line-height: 1.4;">
            The Vision AI model is scanning this photo in a background thread.
          </p>
          <span style="margin-top: 0.65rem; font-size: 0.68rem; background: #e0f2fe; color: #0369a1; padding: 2px 8px; border-radius: 999px; font-weight: 700;">
            <i class="fa-solid fa-arrows-rotate fa-spin"></i> Auto-refreshing every 4s
          </span>
        </div>
      </div>
    `;
    forensicDrawer.classList.remove("hidden");
    return;
  }

  drawerContent.innerHTML = `
    <!-- Image Comparison Section -->
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.85rem; margin-bottom: 1.25rem;">
      <div>
        <div style="font-size: 0.75rem; font-weight: 700; color: #475569; margin-bottom: 0.35rem;">
          ORIGINAL CITIZEN PHOTO
        </div>
        <img src="${urls.original_image || ''}" style="width: 100%; height: 210px; object-fit: cover; border-radius: 6px; border: 1px solid #cbd5e1;" />
      </div>
      <div>
        <div style="font-size: 0.75rem; font-weight: 700; color: #047857; margin-bottom: 0.35rem;">
          ANNOTATED (GARBAGE-VISION v2.0)
        </div>
        <img src="${urls.annotated_image || urls.original_image || ''}" style="width: 100%; height: 210px; object-fit: cover; border-radius: 6px; border: 1px solid #059669;" />
      </div>
    </div>

    <!-- Forensic Summary Stats -->
    <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.65rem; margin-bottom: 1.25rem;">
      <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 0.6rem; text-align: center;">
        <div style="font-size: 0.65rem; color: #64748b; font-weight: 700;">TOTAL ITEMS</div>
        <div style="font-size: 1.25rem; font-weight: 800; color: #0f172a;">${stats.item_count || items.length}</div>
      </div>
      <div style="background: ${stats.sup_violations > 0 ? '#fef2f2' : '#f8fafc'}; border: 1px solid ${stats.sup_violations > 0 ? '#fecaca' : '#e2e8f0'}; border-radius: 6px; padding: 0.6rem; text-align: center;">
        <div style="font-size: 0.65rem; color: ${stats.sup_violations > 0 ? '#dc2626' : '#64748b'}; font-weight: 700;">SUP INFRACTIONS</div>
        <div style="font-size: 1.25rem; font-weight: 800; color: ${stats.sup_violations > 0 ? '#dc2626' : '#059669'};">${stats.sup_violations || 0}</div>
      </div>
      <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 0.6rem; text-align: center;">
        <div style="font-size: 0.65rem; color: #64748b; font-weight: 700;">SEGREGATION</div>
        <div style="font-size: 0.95rem; font-weight: 800; color: #0f172a; text-transform: uppercase;">${stats.segregation_verdict || 'MIXED'}</div>
      </div>
    </div>

    <!-- Multi-Item Enumeration Table -->
    <div style="border: 1px solid #e2e8f0; border-radius: 6px; overflow: hidden;">
      <div style="background: #f8fafc; padding: 0.5rem 0.75rem; font-weight: 700; font-size: 0.75rem; color: #334155; border-bottom: 1px solid #e2e8f0;">
        <i class="fa-solid fa-list-check"></i> ITEMIZED FORENSIC INVENTORY (${items.length} Artifacts Identified)
      </div>
      <div style="max-height: 220px; overflow-y: auto;">
        <table style="width: 100%; border-collapse: collapse; font-size: 0.75rem;">
          <thead style="background: #f1f5f9; text-align: left; color: #475569;">
            <tr>
              <th style="padding: 6px 10px;">Item Name</th>
              <th style="padding: 6px 10px;">Stream</th>
              <th style="padding: 6px 10px;">Material / Resin</th>
              <th style="padding: 6px 10px;">SUP Violation</th>
              <th style="padding: 6px 10px;">Brand (EPR)</th>
            </tr>
          </thead>
          <tbody>
            ${items.length > 0 ? items.map((it, idx) => `
              <tr style="border-bottom: 1px solid #f1f5f9;">
                <td style="padding: 6px 10px; font-weight: 600;">${it.item_name || 'Item'} ${it.count > 1 ? `(x${it.count})` : ''}</td>
                <td style="padding: 6px 10px;"><span style="background: #eff6ff; color: #1d4ed8; padding: 1px 4px; border-radius: 3px; font-size: 10px;">${it.stream || 'GENERIC'}</span></td>
                <td style="padding: 6px 10px; font-family: monospace;">${it.resin_code || it.material || 'N/A'}</td>
                <td style="padding: 6px 10px; color: ${it.sup_violation ? '#dc2626' : '#64748b'}; font-weight: ${it.sup_violation ? '700' : 'normal'}">
                  ${it.sup_violation ? '<i class="fa-solid fa-xmark"></i> YES' : '<i class="fa-solid fa-check"></i> NO'}
                </td>
                <td style="padding: 6px 10px; font-weight: 600; color: #047857;">${it.brand || 'Unidentified'}</td>
              </tr>
            `).join("") : `
              <tr><td colspan="5" style="padding: 12px; text-align: center; color: #94a3b8;">Detailed item enumeration available in report.json</td></tr>
            `}
          </tbody>
        </table>
      </div>
    </div>
  `;

  forensicDrawer.classList.remove("hidden");
};

// ==========================================
// 7. Event Listeners
// ==========================================
function setupEventListeners() {
  btnToggleTruck.addEventListener("click", () => {
    STATE.truckAnimation.isRunning = !STATE.truckAnimation.isRunning;
    if (STATE.truckAnimation.isRunning) {
      btnToggleTruck.innerHTML = `<i class="fa-solid fa-pause"></i> Pause Route`;
      truckStatusText.textContent = `🚚 PMC Truck #04 in Transit • Speed: 26 km/h`;
    } else {
      btnToggleTruck.innerHTML = `<i class="fa-solid fa-play"></i> Resume Route`;
      truckStatusText.textContent = `⏸️ Truck Route Paused at Checkpoint`;
    }
  });

  btnResetMapView.addEventListener("click", () => fitAllPins());

  btnRefreshComplaints.addEventListener("click", () => loadData());

  searchComplaints.addEventListener("input", (e) => {
    const q = e.target.value.toLowerCase().trim();
    if (!q) {
      renderComplaintsLedger(STATE.complaints);
      return;
    }
    const filtered = STATE.complaints.filter(c =>
      (c.complaint_id && c.complaint_id.toLowerCase().includes(q)) ||
      (c.address && c.address.toLowerCase().includes(q)) ||
      (c.notes && c.notes.toLowerCase().includes(q))
    );
    renderComplaintsLedger(filtered);
  });

  btnDrawerClose.addEventListener("click", () => {
    forensicDrawer.classList.add("hidden");
  });

  btnUpdateStatus.addEventListener("click", async () => {
    if (!STATE.selectedComplaint) return;
    const newStatus = drawerStatusSelect.value;
    try {
      const res = await fetch(`/api/complaints/${STATE.selectedComplaint.complaint_id}/status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: newStatus })
      });
      if (res.ok) {
        STATE.selectedComplaint.status = newStatus;
        renderComplaintsLedger(STATE.complaints);
        alert(`Status updated to: ${newStatus}`);
      }
    } catch (err) {
      alert("Error updating status: " + err.message);
    }
  });

  // Live Auto-Poll every 4 seconds to reflect background Vision AI completions seamlessly
  setInterval(() => {
    loadData(true);
  }, 4000);
}

// 1-Click AI Analysis Retry Handler
window.retryComplaintAnalysis = async function (cid) {
  try {
    const res = await fetch(`/api/complaints/${cid}/retry`, { method: "POST" });
    const data = await res.json();
    if (res.ok && data.success) {
      // Immediate silent refresh
      await loadData(true);
      // If drawer is currently open on this complaint, re-render drawer with progress screen
      if (STATE.selectedComplaint && STATE.selectedComplaint.complaint_id === cid) {
        openForensicDrawerById(cid);
      }
    } else {
      alert(`Could not start retry: ${data.error || "Unknown error"}`);
    }
  } catch (err) {
    alert(`Error retrying AI analysis: ${err.message}`);
  }
};

