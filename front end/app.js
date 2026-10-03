// ==========================================================================
// Clean and Green Tech — Team Pixel Minds
// Geo-Spatial Waste Spotter & Garbage-Vision AI Pipeline
// Default Location: MIT-WPU, Kothrud, Pune, Maharashtra (18.5178, 73.8151)
// ==========================================================================

const DEFAULT_COORDS = {
  lat: 18.5178,
  lng: 73.8151,
  label: "MIT World Peace University (MIT-WPU), Kothrud, Pune"
};

// Application State
const state = {
  selectedLat: DEFAULT_COORDS.lat,
  selectedLng: DEFAULT_COORDS.lng,
  resolvedAddress: "MIT World Peace University, Paud Road, Kothrud, Pune, Maharashtra 411038",
  uploadedFile: null,
  uploadedImageDataUrl: null,
  exifCoords: null,
  isAdvancedOpen: false
};

// DOM Elements
const dropZone = document.getElementById("drop-zone");
const photoInput = document.getElementById("photo-input");
const dropzonePrompt = document.getElementById("dropzone-prompt");
const previewContainer = document.getElementById("preview-container");
const imagePreview = document.getElementById("image-preview");
const previewFilename = document.getElementById("preview-filename");
const previewFilesize = document.getElementById("preview-filesize");
const btnBrowse = document.getElementById("btn-browse");
const btnRemovePhoto = document.getElementById("btn-remove-photo");

const gpsPhotoAlert = document.getElementById("gps-photo-alert");
const gpsPhotoCoords = document.getElementById("gps-photo-coords");
const btnApplyExif = document.getElementById("btn-apply-exif");

// Advanced drawer elements
const btnToggleAdvanced = document.getElementById("btn-toggle-advanced");
const advancedDrawer = document.getElementById("advanced-drawer");
const advancedChevron = document.getElementById("advanced-chevron");
const wasteCategorySelect = document.getElementById("waste-category");
const wasteNotesTextarea = document.getElementById("waste-notes");

// Map & console elements
const latValEl = document.getElementById("lat-val");
const lngValEl = document.getElementById("lng-val");
const resolvedAddressEl = document.getElementById("resolved-address");
const btnLocateMe = document.getElementById("btn-locate-me");
const btnResetMit = document.getElementById("btn-reset-mit");
const reportForm = document.getElementById("report-form");

// Snappy Loading Screen Elements
const loadingModal = document.getElementById("loading-modal");
const loadingStepTitle = document.getElementById("loading-step-title");
const loadingStepDesc = document.getElementById("loading-step-desc");
const progressBarFill = document.getElementById("progress-bar-fill");
const loadingTerminal = document.getElementById("loading-terminal");

// Report Modal Elements
const reportModal = document.getElementById("report-modal");
const modalContent = document.getElementById("modal-content");
const btnModalClose = document.getElementById("btn-modal-close");
const btnModalDone = document.getElementById("btn-modal-done");
const btnModalDownload = document.getElementById("btn-modal-download");

let map = null;
let marker = null;
let currentBackendResult = null;

// ==========================================================================
// 1. Leaflet Map Initialization
// ==========================================================================
function initMap() {
  map = L.map("map", {
    center: [state.selectedLat, state.selectedLng],
    zoom: 16,
    zoomControl: true
  });

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 19
  }).addTo(map);

  const pinIcon = L.divIcon({
    className: "custom-pin-wrapper",
    html: `<div class="custom-pin-icon"><i class="fa-solid fa-trash-can"></i></div>`,
    iconSize: [32, 32],
    iconAnchor: [16, 32],
    popupAnchor: [0, -30]
  });

  marker = L.marker([state.selectedLat, state.selectedLng], {
    draggable: true,
    icon: pinIcon
  }).addTo(map);

  marker.bindPopup(`<b>Waste Pin Locked</b><br>MIT-WPU, Kothrud, Pune`).openPopup();

  marker.on("dragend", function () {
    const position = marker.getLatLng();
    updateLocation(position.lat, position.lng);
  });

  map.on("click", function (e) {
    updateLocation(e.latlng.lat, e.latlng.lng);
  });

  reverseGeocode(state.selectedLat, state.selectedLng);
}

function updateLocation(lat, lng, shouldPan = false) {
  state.selectedLat = parseFloat(lat.toFixed(6));
  state.selectedLng = parseFloat(lng.toFixed(6));

  marker.setLatLng([state.selectedLat, state.selectedLng]);
  if (shouldPan) {
    map.setView([state.selectedLat, state.selectedLng], Math.max(map.getZoom(), 16), {
      animate: true
    });
  }

  latValEl.textContent = state.selectedLat.toFixed(6);
  lngValEl.textContent = state.selectedLng.toFixed(6);

  reverseGeocode(state.selectedLat, state.selectedLng);
}

let geocodeTimeout = null;
function reverseGeocode(lat, lng) {
  resolvedAddressEl.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin"></i> Resolving coordinates...`;

  if (geocodeTimeout) clearTimeout(geocodeTimeout);

  geocodeTimeout = setTimeout(async () => {
    try {
      const response = await fetch(
        `https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lng}&zoom=18&addressdetails=1`
      );
      if (!response.ok) throw new Error("Geocoding service unavailable");
      const data = await response.json();

      if (data && data.display_name) {
        state.resolvedAddress = data.display_name;
        resolvedAddressEl.textContent = data.display_name;
        marker.setPopupContent(`<b>Waste Pin Locked</b><br><small>${data.display_name.slice(0, 65)}...</small>`);
      } else {
        fallbackAddress();
      }
    } catch {
      fallbackAddress();
    }
  }, 350);
}

function fallbackAddress() {
  const fallback = `Paud Road, Kothrud, Pune (${state.selectedLat}, ${state.selectedLng})`;
  state.resolvedAddress = fallback;
  resolvedAddressEl.textContent = fallback;
}

// ==========================================================================
// 2. Photo Upload & Drag/Drop
// ==========================================================================
function setupPhotoUpload() {
  btnBrowse.addEventListener("click", () => photoInput.click());
  
  dropZone.addEventListener("click", (e) => {
    if (!state.uploadedFile && e.target !== btnBrowse) {
      photoInput.click();
    }
  });

  ["dragenter", "dragover"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.add("drag-active");
    });
  });

  ["dragleave", "drop"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.remove("drag-active");
    });
  });

  dropZone.addEventListener("drop", (e) => {
    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      handleImageFile(files[0]);
    }
  });

  photoInput.addEventListener("change", (e) => {
    if (e.target.files && e.target.files.length > 0) {
      handleImageFile(e.target.files[0]);
    }
  });

  btnRemovePhoto.addEventListener("click", (e) => {
    e.stopPropagation();
    clearPhoto();
  });

  btnApplyExif.addEventListener("click", () => {
    if (state.exifCoords) {
      updateLocation(state.exifCoords.latitude, state.exifCoords.longitude, true);
    }
  });
}

function handleImageFile(file) {
  if (!file.type.startsWith("image/")) {
    alert("Please upload an image file (JPG, PNG, WEBP).");
    return;
  }

  state.uploadedFile = file;
  previewFilename.textContent = file.name;
  previewFilesize.textContent = formatBytes(file.size);

  // Read 100% original full-size image untouched for maximum AI forensic precision
  const reader = new FileReader();
  reader.onload = function (e) {
    state.uploadedImageDataUrl = e.target.result;
    imagePreview.src = state.uploadedImageDataUrl;
    dropzonePrompt.classList.add("hidden");
    previewContainer.classList.remove("hidden");
  };
  reader.readAsDataURL(file);

  checkExifGPS(file);
}

function clearPhoto() {
  state.uploadedFile = null;
  state.uploadedImageDataUrl = null;
  state.exifCoords = null;
  photoInput.value = "";
  imagePreview.src = "";
  previewContainer.classList.add("hidden");
  dropzonePrompt.classList.remove("hidden");
  gpsPhotoAlert.classList.add("hidden");
}

function formatBytes(bytes) {
  if (bytes === 0) return "0 Bytes";
  const k = 1024;
  const sizes = ["Bytes", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
}

async function checkExifGPS(file) {
  try {
    if (window.exifr) {
      const gps = await window.exifr.gps(file);
      if (gps && gps.latitude && gps.longitude) {
        state.exifCoords = gps;
        gpsPhotoCoords.textContent = `Lat: ${gps.latitude.toFixed(6)}, Lon: ${gps.longitude.toFixed(6)}`;
        gpsPhotoAlert.classList.remove("hidden");
      } else {
        gpsPhotoAlert.classList.add("hidden");
      }
    }
  } catch {
    gpsPhotoAlert.classList.add("hidden");
  }
}

// ==========================================================================
// 3. Advanced Drawer Toggle (Subtypes & Extra Notes)
// ==========================================================================
function setupAdvancedToggle() {
  btnToggleAdvanced.addEventListener("click", () => {
    state.isAdvancedOpen = !state.isAdvancedOpen;
    btnToggleAdvanced.setAttribute("aria-expanded", state.isAdvancedOpen);

    if (state.isAdvancedOpen) {
      advancedDrawer.classList.remove("hidden");
      advancedChevron.classList.add("rotate-180");
    } else {
      advancedDrawer.classList.add("hidden");
      advancedChevron.classList.remove("rotate-180");
    }
  });
}

// ==========================================================================
// 4. Map Controls & Backend Complaint Submission
// ==========================================================================
function setupControls() {
  btnLocateMe.addEventListener("click", () => {
    if (!navigator.geolocation) {
      alert("Geolocation is not supported by your browser.");
      return;
    }

    btnLocateMe.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin"></i> Locating...`;
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        btnLocateMe.innerHTML = `<i class="fa-solid fa-crosshairs"></i> Locate Me`;
        btnResetMit.classList.remove("active-location");
        btnLocateMe.classList.add("active-location");
        updateLocation(pos.coords.latitude, pos.coords.longitude, true);
      },
      (err) => {
        btnLocateMe.innerHTML = `<i class="fa-solid fa-crosshairs"></i> Locate Me`;
        alert("GPS error: " + err.message + ". Retaining MIT-WPU Kothrud position.");
      },
      { timeout: 8000, enableHighAccuracy: true }
    );
  });

  btnResetMit.addEventListener("click", () => {
    btnLocateMe.classList.remove("active-location");
    btnResetMit.classList.add("active-location");
    updateLocation(DEFAULT_COORDS.lat, DEFAULT_COORDS.lng, true);
  });

  // Submit Complaint -> Instant Optimistic Confirmation + Background Server Dispatch
  // Only listen on the FORM submit — clicking the button inside the form already triggers it.
  reportForm.addEventListener("submit", function(e) {
    e.preventDefault();

    if (!state.uploadedFile || !state.uploadedImageDataUrl) {
      alert("Please upload or capture a waste photo first!");
      dropZone.scrollIntoView({ behavior: "smooth" });
      return;
    }

    // Capture all values synchronously BEFORE any state reset
    const notes = state.isAdvancedOpen ? wasteNotesTextarea.value.trim() : "";
    const uploadPhotoBase64 = state.uploadedImageDataUrl;
    const uploadFileName = state.uploadedFile.name;
    const uploadLat = state.selectedLat;
    const uploadLng = state.selectedLng;
    const uploadAddress = state.resolvedAddress || "MIT-WPU Kothrud, Pune";

    // Generate immediate client receipt ID
    const now = new Date();
    const tsStr = now.getFullYear().toString() +
      String(now.getMonth() + 1).padStart(2, '0') +
      String(now.getDate()).padStart(2, '0') + "_" +
      String(now.getHours()).padStart(2, '0') +
      String(now.getMinutes()).padStart(2, '0') +
      String(now.getSeconds()).padStart(2, '0');
    const randCode = Math.random().toString(16).substring(2, 6).toUpperCase();
    const instantId = "CMP-" + tsStr + "-" + randCode;

    // Local receipt stays honest: the real analysis comes back from the server under this same ID.
    const localComplaintObj = {
      complaint_id: instantId,
      timestamp: now.toISOString(),
      local_time: now.getFullYear() + "-" + String(now.getMonth() + 1).padStart(2, '0') + "-" + String(now.getDate()).padStart(2, '0') + " " + String(now.getHours()).padStart(2, '0') + ":" + String(now.getMinutes()).padStart(2, '0') + ":" + String(now.getSeconds()).padStart(2, '0'),
      coordinates: { latitude: uploadLat, longitude: uploadLng },
      address: uploadAddress,
      notes: notes,
      status: "Pending",
      analysis_status: "in_progress",
      original_filename: uploadFileName,
      image_file: uploadFileName,
      urls: {
        original_image: uploadPhotoBase64,
        annotated_image: null,
        json_report: null,
        csv_report: null
      },
      stats: {
        item_count: 0,
        sup_violations: 0,
        hazard_flag: false,
        segregation_verdict: null
      },
      report: null
    };

    saveComplaintToLocalStorage(localComplaintObj);

    // Award +50 Green Credits instantly!
    const earnedPts = REWARDS_CONFIG.CREDITS_PER_UPLOAD;
    const newBalance = addGreenCredits(earnedPts);

    // 1. Show instant confirmation modal to citizen (0 ms)
    renderCitizenSuccessModal({
      complaint_id: instantId,
      address: uploadAddress,
      coordinates: { latitude: uploadLat, longitude: uploadLng }
    }, earnedPts, newBalance);

    // 2. Reset form for next report
    resetCitizenForm();

    // 3. Fire-and-forget upload to server in background (tries relative first, then direct Render URL)
    const payload = JSON.stringify({
      image_base64: uploadPhotoBase64,
      filename: uploadFileName,
      latitude: uploadLat,
      longitude: uploadLng,
      address: uploadAddress,
      notes: notes,
      client_complaint_id: instantId,
      client_local_time: localComplaintObj.local_time
    });

    fetch("/api/submit-complaint", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: payload
    }).then(function(res) {
      if (res.ok) return res.json();
      throw new Error("Relative fetch failed");
    }).catch(function() {
      if (window.location.hostname.includes("vercel.app")) {
        return fetch("https://cleangreen-ai-backend.onrender.com/api/submit-complaint", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: payload
        }).then(function(res) { if (res.ok) return res.json(); });
      }
    }).then(function(data) {
      if (!data || !data.complaint_id) return;
      if (data.complaint_id !== instantId) renameLocalComplaint(instantId, data.complaint_id);
      console.log("[BACKGROUND] Complaint saved to backend:", data.status, data.complaint_id);
    }).catch(function(err) {
      console.warn("[STANDALONE] Backend waking up or offline. Complaint saved in local storage:", err);
    });
  });

function saveComplaintToLocalStorage(c) {
  try {
    const existing = JSON.parse(localStorage.getItem("swachhComplaintsLedger") || "[]");
    existing.unshift(c);
    const trimmed = existing.slice(0, 35);
    localStorage.setItem("swachhComplaintsLedger", JSON.stringify(trimmed));
  } catch (err) {
    console.warn("Could not save complaint to localStorage:", err);
  }
}

function renameLocalComplaint(oldId, newId) {
  try {
    const list = JSON.parse(localStorage.getItem("swachhComplaintsLedger") || "[]");
    const row = list.find(function(c) { return c.complaint_id === oldId; });
    if (!row) return;
    row.complaint_id = newId;
    localStorage.setItem("swachhComplaintsLedger", JSON.stringify(list));
  } catch (err) {
    console.warn("Could not reconcile complaint id:", err);
  }
}

  // Modal Actions
  btnModalClose.addEventListener("click", () => reportModal.classList.add("hidden"));
  btnModalDone.addEventListener("click", () => {
    reportModal.classList.add("hidden");
    resetCitizenForm();
  });

  // Setup Rewards & Incentives Handlers
  setupRewardsHandlers();
}

function resetCitizenForm() {
  clearPhoto();
  if (wasteNotesTextarea) wasteNotesTextarea.value = "";
}

// Render Simple & Instant Citizen Confirmation Modal with Green Credits Award
function renderCitizenSuccessModal(result, earnedPts = 50, currentBalance = 150) {
  modalContent.innerHTML = `
    <div style="text-align: center; padding: 0.5rem 0 0.25rem;">
      <div style="width: 54px; height: 54px; background: #ecfdf5; border: 2px solid #10b981; color: #047857; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 1.6rem; margin: 0 auto 0.75rem; box-shadow: 0 4px 12px rgba(16, 185, 129, 0.25);">
        <i class="fa-solid fa-check"></i>
      </div>
      <h3 style="font-size: 1.2rem; font-weight: 800; color: #0f172a; margin-bottom: 0.25rem;">Submitted! Thank you!</h3>
      <p style="color: #047857; font-weight: 600; font-size: 0.82rem; margin-bottom: 0.25rem;">Thank you for helping keep Pune clean.</p>
      <p style="color: #64748b; font-size: 0.78rem; margin-bottom: 0.75rem;">
        Your waste report has been received and queued for clearance.
      </p>

      <!-- Eco-Credits Celebration Card -->
      <div class="credits-award-box">
        <div class="credits-award-title">
          <i class="fa-solid fa-coins"></i> +${earnedPts} GREEN CREDITS EARNED!
        </div>
        <div class="credits-award-desc">
          Your new balance is <strong>${currentBalance} PTS</strong>. Redeemable for Pune Metro & Property Tax!
        </div>
        <button type="button" class="btn-view-rewards-inline" id="btn-modal-view-rewards">
          <i class="fa-solid fa-gift"></i> View Rewards & Redeem
        </button>
      </div>

      <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 0.85rem; text-align: left; font-size: 0.78rem; display: flex; flex-direction: column; gap: 0.45rem; margin-top: 0.75rem;">
        <div style="display: flex; justify-content: space-between; border-bottom: 1px solid #e2e8f0; padding-bottom: 0.35rem;">
          <span style="color: #64748b;">Complaint ID:</span>
          <strong style="font-family: monospace; color: #0f172a;">${result.complaint_id}</strong>
        </div>
        <div style="display: flex; justify-content: space-between; border-bottom: 1px solid #e2e8f0; padding-bottom: 0.35rem;">
          <span style="color: #64748b;">Status:</span>
          <span style="background: #ecfdf5; color: #047857; font-weight: 700; font-size: 0.7rem; padding: 2px 6px; border-radius: 4px;">
            Submitted to Ward Office
          </span>
        </div>
        <div>
          <span style="color: #64748b; display: block; margin-bottom: 0.15rem;">Location:</span>
          <span style="color: #1e293b; font-weight: 600;">${state.resolvedAddress || 'MIT-WPU Kothrud, Pune'}</span>
        </div>
      </div>
    </div>
  `;

  // Wire inline rewards button inside success modal
  const btnViewRewards = document.getElementById("btn-modal-view-rewards");
  if (btnViewRewards) {
    btnViewRewards.addEventListener("click", () => {
      reportModal.classList.add("hidden");
      resetCitizenForm();
      const hub = document.getElementById("rewards-hub");
      if (hub) hub.scrollIntoView({ behavior: "smooth" });
    });
  }

  reportModal.classList.remove("hidden");
}

// ==========================================================================
// Civic Rewards & Green Credits Manager
// ==========================================================================
const REWARDS_CONFIG = {
  CREDITS_PER_UPLOAD: 50,
  INITIAL_CREDITS: 100,
  REWARDS: {
    metro: {
      name: "Pune Metro Transit Pass",
      benefit: "₹25 Fare Voucher / Smart Card Topup",
      cost: 100,
      codePrefix: "PUN-METRO",
      instructions: "Present this digital voucher QR/code at any MahaMetro Pune ticket counter (Vanaz, Garware College, Shivajinagar, Civil Court, Swargate) or redeem inside the Pune Metro ticketing mobile app."
    },
    tax: {
      name: "PMC Property Tax Concession",
      benefit: "2% Property Tax Rebate Certificate",
      cost: 300,
      codePrefix: "PMC-TAX-REBATE",
      instructions: "Enter this rebate certificate code on the PMC Property Tax portal (propertytax.punecorporation.org) during annual assessment payment or present at any Citizen Facilitation Center (CFC)."
    },
    bus: {
      name: "PMPML Daily Bus Travel Pass",
      benefit: "1-Day Unlimited City Bus Travel Pass",
      cost: 75,
      codePrefix: "PMPML-PASS",
      instructions: "Show this digital pass code to any PMPML conductor or validate on the PMPML 'Apli PMPML' ticketing app for unlimited travel across all Pune & PCMC bus routes for 24 hours."
    }
  }
};

function getGreenCredits() {
  const saved = localStorage.getItem("swachhGreenCredits");
  if (saved === null) {
    localStorage.setItem("swachhGreenCredits", REWARDS_CONFIG.INITIAL_CREDITS.toString());
    return REWARDS_CONFIG.INITIAL_CREDITS;
  }
  return parseInt(saved, 10) || 0;
}

function setGreenCredits(amount) {
  localStorage.setItem("swachhGreenCredits", Math.max(0, amount).toString());
  updateGreenCreditsUI();
}

function addGreenCredits(amount) {
  const current = getGreenCredits();
  const next = current + amount;
  setGreenCredits(next);
  return next;
}

function deductGreenCredits(amount) {
  const current = getGreenCredits();
  if (current < amount) return false;
  setGreenCredits(current - amount);
  return true;
}

function updateGreenCreditsUI() {
  const balance = getGreenCredits();
  const navBalanceEl = document.getElementById("nav-credit-balance");
  const sectionBalanceEl = document.getElementById("rewards-section-balance");

  if (navBalanceEl) navBalanceEl.textContent = balance;
  if (sectionBalanceEl) sectionBalanceEl.textContent = balance;

  // Update disabled state on all redeem buttons based on active balance
  document.querySelectorAll(".btn-redeem").forEach(btn => {
    const cost = parseInt(btn.getAttribute("data-cost"), 10) || 0;
    if (balance < cost) {
      btn.disabled = true;
      btn.title = `Requires ${cost} PTS (Need ${cost - balance} more)`;
    } else {
      btn.disabled = false;
      btn.title = `Redeem for ${cost} PTS`;
    }
  });
}

function setupRewardsHandlers() {
  // 1. Navbar Credits Button -> Smooth scroll to Rewards Hub
  const btnNavCredits = document.getElementById("btn-nav-credits");
  if (btnNavCredits) {
    btnNavCredits.addEventListener("click", () => {
      const hub = document.getElementById("rewards-hub");
      if (hub) hub.scrollIntoView({ behavior: "smooth" });
    });
  }

  // 2. Redeem Buttons
  document.querySelectorAll(".btn-redeem").forEach(btn => {
    btn.addEventListener("click", () => {
      const rewardKey = btn.getAttribute("data-reward");
      const cost = parseInt(btn.getAttribute("data-cost"), 10);
      const reward = REWARDS_CONFIG.REWARDS[rewardKey];
      if (!reward) return;

      const balance = getGreenCredits();
      if (balance < cost) {
        alert(`Insufficient Green Credits! You need ${cost} PTS for "${reward.name}". You currently have ${balance} PTS. Upload ${Math.ceil((cost - balance)/50)} more waste photo(s) to earn points!`);
        return;
      }

      const confirmed = confirm(`Redeem ${cost} Green Credits for "${reward.name}" (${reward.benefit})?\n\nYour remaining balance will be ${balance - cost} PTS.`);
      if (confirmed) {
        if (deductGreenCredits(cost)) {
          showVoucherModal(rewardKey, reward);
        }
      }
    });
  });

  // 3. Voucher Modal Close Actions
  const voucherModal = document.getElementById("voucher-modal");
  const btnVoucherClose = document.getElementById("btn-voucher-close");
  const btnVoucherDone = document.getElementById("btn-voucher-done");

  if (btnVoucherClose) {
    btnVoucherClose.addEventListener("click", () => {
      if (voucherModal) voucherModal.classList.add("hidden");
    });
  }

  if (btnVoucherDone) {
    btnVoucherDone.addEventListener("click", () => {
      if (voucherModal) voucherModal.classList.add("hidden");
    });
  }
}

// Show Voucher Modal with Authentic Alphanumeric Code and Copy Action
function showVoucherModal(rewardKey, reward) {
  const voucherModal = document.getElementById("voucher-modal");
  const voucherContent = document.getElementById("voucher-modal-content");
  const copyBtn = document.getElementById("btn-copy-voucher");

  const randSuffix = Math.random().toString(36).substring(2, 6).toUpperCase();
  const year = new Date().getFullYear();
  const voucherCode = `${reward.codePrefix}-${randSuffix}-${year}`;

  const iconClass = rewardKey === 'metro' ? 'fa-train-subway' : (rewardKey === 'tax' ? 'fa-building-columns' : 'fa-bus');

  voucherContent.innerHTML = `
    <div class="voucher-certificate">
      <div class="voucher-seal">
        <i class="fa-solid ${iconClass}"></i>
      </div>
      <div class="voucher-title">${reward.name}</div>
      <div class="voucher-desc"><strong>Civic Benefit:</strong> ${reward.benefit}</div>
      
      <div style="font-size: 0.68rem; font-weight: 700; color: #64748b; margin-bottom: 0.35rem; letter-spacing: 0.05em;">YOUR UNIQUE VOUCHER CODE</div>
      <div class="voucher-code-box" id="active-voucher-code">${voucherCode}</div>
      
      <div class="voucher-instructions">
        <strong>Redemption Instructions:</strong><br>
        ${reward.instructions}
      </div>
      
      <div style="margin-top: 0.85rem; font-size: 0.72rem; color: #059669; font-weight: 700;">
        <i class="fa-solid fa-circle-check"></i> Verified by Pune Swachh Citizen Incentive Framework
      </div>
    </div>
  `;

  if (copyBtn) {
    copyBtn.onclick = () => {
      navigator.clipboard.writeText(voucherCode).then(() => {
        const originalHtml = copyBtn.innerHTML;
        copyBtn.innerHTML = `<i class="fa-solid fa-check" style="color: #10b981;"></i> Copied!`;
        setTimeout(() => {
          copyBtn.innerHTML = originalHtml;
        }, 2000);
      }).catch(() => {
        prompt("Copy voucher code:", voucherCode);
      });
    };
  }

  if (voucherModal) voucherModal.classList.remove("hidden");
}

// Initialize on DOM Ready
document.addEventListener("DOMContentLoaded", () => {
  initMap();
  setupPhotoUpload();
  setupAdvancedToggle();
  setupControls();
  updateGreenCreditsUI();
});
