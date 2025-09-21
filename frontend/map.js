/**
 * Frontend JavaScript for Indian Railways DSS
 * Handles Leaflet map, WebSocket communication, and UI controls
 */

// Global variables
let map;
let socket;
let trainMarkers = {};
let trackLayers = {};
let stationMarkers = {};
let isSimulationRunning = false;
let simulationStartTime = null;

// Configuration
const CONFIG = {
    BACKEND_URL: 'http://localhost:5000',
    MAP_CENTER: [12.6, 77.2],
    MAP_ZOOM: 10,
    UPDATE_INTERVAL: 1000, // ms
    NOTIFICATION_DURATION: 3000 // ms
};

// Train status colors and icons
const TRAIN_STATUS = {
    'running': { icon: '🚂', color: '#27ae60' },
    'dwelling': { icon: '🚃', color: '#f39c12' },
    'delayed': { icon: '🚂', color: '#e74c3c' },
    'completed': { icon: '🏁', color: '#95a5a6' },
    'waiting': { icon: '⏸️', color: '#7f8c8d' }
};

// Track type styles
const TRACK_STYLES = {
    'main': { color: '#2c3e50', weight: 6, opacity: 0.9 },
    'siding': { color: '#7f8c8d', weight: 4, opacity: 0.7, dashArray: '10,5' },
    'secondary': { color: '#95a5a6', weight: 5, opacity: 0.8 }
};

/**
 * Initialize the application
 */
function init() {
    console.log('Initializing Railway DSS Frontend...');
    
    // Initialize map
    initMap();
    
    // Initialize WebSocket connection
    initWebSocket();
    
    // Setup event listeners
    setupEventListeners();
    
    // Load initial data
    loadInitialData();
    
    console.log('Frontend initialized successfully');
}

/**
 * Initialize Leaflet map
 */
function initMap() {
    // Create map
    map = L.map('map', {
        center: CONFIG.MAP_CENTER,
        zoom: CONFIG.MAP_ZOOM,
        zoomControl: true
    });
    
    // Add base layer (offline-capable)
    L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
        subdomains: 'abcd',
        maxZoom: 19
    }).addTo(map);
    
    console.log('Map initialized');
}

/**
 * Initialize WebSocket connection
 */
function initWebSocket() {
    socket = io(CONFIG.BACKEND_URL);
    
    socket.on('connect', () => {
        console.log('Connected to backend');
        updateConnectionStatus(true);
        showNotification('Connected to Railway DSS Backend', 'success');
    });
    
    socket.on('disconnect', () => {
        console.log('Disconnected from backend');
        updateConnectionStatus(false);
        showNotification('Disconnected from backend', 'error');
    });
    
    socket.on('train_positions', (data) => {
        updateTrainPositions(data.positions);
    });
    
    socket.on('simulation_stats', (stats) => {
        updateKPIs(stats);
    });
    
    socket.on('error', (error) => {
        console.error('WebSocket error:', error);
        showNotification(`Error: ${error.message}`, 'error');
    });
}

/**
 * Setup event listeners for UI controls
 */
function setupEventListeners() {
    // Simulation controls
    document.getElementById('startBtn').addEventListener('click', startSimulation);
    document.getElementById('stopBtn').addEventListener('click', stopSimulation);
    document.getElementById('resetBtn').addEventListener('click', resetSimulation);
    
    // Disruption management
    document.getElementById('addDisruptionBtn').addEventListener('click', addDisruption);
    
    // What-if analysis
    document.getElementById('addSpecialTrainBtn').addEventListener('click', addSpecialTrain);
    
    // Manual controls
    document.getElementById('optimizeBtn').addEventListener('click', optimizeSchedule);
    document.getElementById('refreshBtn').addEventListener('click', refreshData);
}

/**
 * Load initial data (tracks, stations, trains)
 */
async function loadInitialData() {
    try {
        // Load tracks
        const tracksResponse = await fetch(`${CONFIG.BACKEND_URL}/tracks`);
        const tracksData = await tracksResponse.json();
        loadTracks(tracksData.tracks);
        
        // Load stations
        const stationsResponse = await fetch(`${CONFIG.BACKEND_URL}/stations`);
        const stationsData = await stationsResponse.json();
        loadStations(stationsData.stations);
        
        // Load train list for disruption dropdown
        loadTrainList();
        
        console.log('Initial data loaded');
    } catch (error) {
        console.error('Error loading initial data:', error);
        showNotification('Failed to load initial data', 'error');
    }
}

/**
 * Load and display tracks on map
 */
function loadTracks(tracks) {
    Object.entries(tracks).forEach(([name, track]) => {
        const coordinates = track.coordinates.map(coord => [coord[1], coord[0]]); // Swap lon/lat
        
        const style = TRACK_STYLES[track.track_type] || TRACK_STYLES['main'];
        
        const trackLayer = L.polyline(coordinates, {
            ...style,
            className: `track-${track.track_type}`
        }).addTo(map);
        
        // Add popup with track information
        trackLayer.bindPopup(`
            <div style="font-family: Arial, sans-serif;">
                <h4 style="margin: 0 0 10px 0; color: #2c3e50;">🛤️ ${track.name}</h4>
                <p><strong>Type:</strong> ${track.track_type}</p>
                <p><strong>Segment:</strong> ${track.segment}</p>
                <p><strong>Capacity:</strong> ${track.capacity} train(s)</p>
                <p><strong>Length:</strong> ${track.length_km.toFixed(1)} km</p>
            </div>
        `);
        
        trackLayers[name] = trackLayer;
    });
    
    console.log(`Loaded ${Object.keys(tracks).length} tracks`);
}

/**
 * Load and display stations on map
 */
function loadStations(stations) {
    Object.entries(stations).forEach(([code, station]) => {
        const marker = L.circleMarker([station.lat, station.lon], {
            radius: station.major ? 12 : 8,
            fillColor: '#e74c3c',
            color: '#ffffff',
            weight: 3,
            opacity: 1,
            fillOpacity: 0.9
        }).addTo(map);
        
        // Add popup with station information
        marker.bindPopup(`
            <div style="font-family: Arial, sans-serif;">
                <h4 style="margin: 0 0 10px 0; color: #2c3e50;">🚉 ${station.name}</h4>
                <p><strong>Code:</strong> ${station.code}</p>
                <p><strong>Platforms:</strong> ${station.platforms}</p>
                <p><strong>Type:</strong> ${station.major ? 'Major Junction' : 'Station'}</p>
            </div>
        `);
        
        stationMarkers[code] = marker;
    });
    
    console.log(`Loaded ${Object.keys(stations).length} stations`);
}

/**
 * Load train list for dropdowns
 */
async function loadTrainList() {
    try {
        const response = await fetch(`${CONFIG.BACKEND_URL}/positions`);
        const data = await response.json();
        
        const trainSelect = document.getElementById('disruptTrain');
        trainSelect.innerHTML = '<option value="">Select train...</option>';
        
        Object.keys(data.positions).forEach(trainId => {
            const option = document.createElement('option');
            option.value = trainId;
            option.textContent = trainId;
            trainSelect.appendChild(option);
        });
        
    } catch (error) {
        console.error('Error loading train list:', error);
    }
}

/**
 * Update train positions on map
 */
function updateTrainPositions(positions) {
    // Update active trains counter
    document.getElementById('activeTrains').textContent = Object.keys(positions).length;
    
    Object.entries(positions).forEach(([trainId, position]) => {
        if (trainMarkers[trainId]) {
            // Update existing marker
            trainMarkers[trainId].setLatLng([position.lat, position.lon]);
            updateTrainMarker(trainMarkers[trainId], position);
        } else {
            // Create new marker
            createTrainMarker(trainId, position);
        }
    });
    
    // Remove markers for trains no longer active
    Object.keys(trainMarkers).forEach(trainId => {
        if (!positions[trainId]) {
            map.removeLayer(trainMarkers[trainId]);
            delete trainMarkers[trainId];
        }
    });
}

/**
 * Create a new train marker
 */
function createTrainMarker(trainId, position) {
    const status = TRAIN_STATUS[position.status] || TRAIN_STATUS['running'];
    
    const marker = L.marker([position.lat, position.lon], {
        icon: L.divIcon({
            html: `<div class="train-marker" style="color: ${status.color};">${status.icon}</div>`,
            iconSize: [24, 24],
            iconAnchor: [12, 12],
            className: 'custom-train-icon'
        })
    }).addTo(map);
    
    // Add click handler
    marker.on('click', () => showTrainDetails(trainId, position));
    
    trainMarkers[trainId] = marker;
    updateTrainMarker(marker, position);
}

/**
 * Update existing train marker
 */
function updateTrainMarker(marker, position) {
    const status = TRAIN_STATUS[position.status] || TRAIN_STATUS['running'];
    
    // Update icon
    marker.setIcon(L.divIcon({
        html: `<div class="train-marker" style="color: ${status.color};">${status.icon}</div>`,
        iconSize: [24, 24],
        iconAnchor: [12, 12],
        className: 'custom-train-icon'
    }));
    
    // Update popup content
    marker.bindPopup(`
        <div style="font-family: Arial, sans-serif; min-width: 200px;">
            <h4 style="margin: 0 0 10px 0; color: #2c3e50;">🚂 Train ${position.train_id}</h4>
            <p><strong>Status:</strong> ${position.status}</p>
            <p><strong>Speed:</strong> ${position.speed} km/h</p>
            <p><strong>Current Segment:</strong> ${position.current_segment}</p>
            <p><strong>Next Station:</strong> ${position.next_station}</p>
            <p><strong>Delay:</strong> ${position.delay.toFixed(1)} min</p>
            <p><strong>Track Type:</strong> ${position.track_type}</p>
        </div>
    `);
}

/**
 * Show detailed train information
 */
function showTrainDetails(trainId, position) {
    const details = `
        Train: ${trainId}
        Status: ${position.status}
        Speed: ${position.speed} km/h
        Segment: ${position.current_segment}
        Next Station: ${position.next_station}
        Delay: ${position.delay.toFixed(1)} minutes
        Track: ${position.track_type}
    `;
    
    showNotification(`Train ${trainId} Details:\n${details}`, 'info');
}

/**
 * Update KPIs display
 */
function updateKPIs(stats) {
    const punctuality = stats.total_trains > 0 ? 
        ((stats.on_time / stats.total_trains) * 100).toFixed(1) : '0';
    
    document.getElementById('punctualityKPI').textContent = `${punctuality}%`;
    document.getElementById('avgDelayKPI').textContent = stats.avg_delay.toFixed(1);
    document.getElementById('throughputKPI').textContent = stats.throughput;
    
    // Calculate utilization (simplified)
    const utilization = stats.throughput > 0 ? Math.min(100, stats.throughput * 10) : 0;
    document.getElementById('utilizationKPI').textContent = `${utilization.toFixed(0)}%`;
}

/**
 * Update connection status indicator
 */
function updateConnectionStatus(connected) {
    const statusEl = document.getElementById('connectionStatus');
    if (connected) {
        statusEl.textContent = 'Connected';
        statusEl.className = 'connection-status connected';
    } else {
        statusEl.textContent = 'Disconnected';
        statusEl.className = 'connection-status disconnected';
    }
}

/**
 * Show notification message
 */
function showNotification(message, type = 'info') {
    const notification = document.getElementById('notification');
    notification.textContent = message;
    notification.className = `notification ${type} show`;
    
    setTimeout(() => {
        notification.classList.remove('show');
    }, CONFIG.NOTIFICATION_DURATION);
}

/**
 * Update simulation time display
 */
function updateSimulationTime() {
    if (isSimulationRunning && simulationStartTime) {
        const elapsed = Math.floor((Date.now() - simulationStartTime) / 1000);
        const minutes = Math.floor(elapsed / 60);
        const seconds = elapsed % 60;
        document.getElementById('simTime').textContent = 
            `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
    }
}

// Simulation control functions

/**
 * Start simulation
 */
async function startSimulation() {
    try {
        const response = await fetch(`${CONFIG.BACKEND_URL}/start_sim`, {
            method: 'POST'
        });
        const result = await response.json();
        
        if (result.success) {
            isSimulationRunning = true;
            simulationStartTime = Date.now();
            
            document.getElementById('startBtn').disabled = true;
            document.getElementById('stopBtn').disabled = false;
            document.getElementById('simStatus').textContent = 'Running';
            
            // Start time update interval
            setInterval(updateSimulationTime, 1000);
            
            showNotification('Simulation started', 'success');
        } else {
            showNotification('Failed to start simulation', 'error');
        }
    } catch (error) {
        console.error('Error starting simulation:', error);
        showNotification('Error starting simulation', 'error');
    }
}

/**
 * Stop simulation
 */
async function stopSimulation() {
    try {
        const response = await fetch(`${CONFIG.BACKEND_URL}/stop_sim`, {
            method: 'POST'
        });
        const result = await response.json();
        
        if (result.success) {
            isSimulationRunning = false;
            
            document.getElementById('startBtn').disabled = false;
            document.getElementById('stopBtn').disabled = true;
            document.getElementById('simStatus').textContent = 'Stopped';
            
            showNotification('Simulation stopped', 'info');
        } else {
            showNotification('Failed to stop simulation', 'error');
        }
    } catch (error) {
        console.error('Error stopping simulation:', error);
        showNotification('Error stopping simulation', 'error');
    }
}

/**
 * Reset simulation
 */
async function resetSimulation() {
    try {
        const response = await fetch(`${CONFIG.BACKEND_URL}/reset_sim`, {
            method: 'POST'
        });
        const result = await response.json();
        
        if (result.success) {
            isSimulationRunning = false;
            simulationStartTime = null;
            
            // Clear train markers
            Object.values(trainMarkers).forEach(marker => map.removeLayer(marker));
            trainMarkers = {};
            
            // Reset UI
            document.getElementById('startBtn').disabled = false;
            document.getElementById('stopBtn').disabled = true;
            document.getElementById('simStatus').textContent = 'Reset';
            document.getElementById('simTime').textContent = '00:00';
            document.getElementById('activeTrains').textContent = '0';
            
            // Reset KPIs
            document.getElementById('punctualityKPI').textContent = '0%';
            document.getElementById('avgDelayKPI').textContent = '0';
            document.getElementById('throughputKPI').textContent = '0';
            document.getElementById('utilizationKPI').textContent = '0%';
            
            showNotification('Simulation reset', 'info');
        } else {
            showNotification('Failed to reset simulation', 'error');
        }
    } catch (error) {
        console.error('Error resetting simulation:', error);
        showNotification('Error resetting simulation', 'error');
    }
}

/**
 * Add disruption
 */
async function addDisruption() {
    const trainId = document.getElementById('disruptTrain').value;
    const segment = document.getElementById('disruptSegment').value;
    const delayMinutes = parseFloat(document.getElementById('delayMinutes').value);
    
    if (!trainId) {
        showNotification('Please select a train', 'error');
        return;
    }
    
    try {
        const response = await fetch(`${CONFIG.BACKEND_URL}/disrupt`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                train_id: trainId,
                segment: segment,
                delay_minutes: delayMinutes,
                reason: 'Manual disruption from DSS'
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            showNotification(
                `Disruption added: ${trainId} delayed by ${delayMinutes} min in ${segment}`, 
                'success'
            );
            
            if (result.optimization && result.optimization.triggered) {
                showNotification(
                    `Optimization completed: ${result.optimization.rerouted_trains.length} trains rerouted`,
                    'info'
                );
            }
        } else {
            showNotification('Failed to add disruption', 'error');
        }
    } catch (error) {
        console.error('Error adding disruption:', error);
        showNotification('Error adding disruption', 'error');
    }
}

/**
 * Add special train
 */
async function addSpecialTrain() {
    const trainId = document.getElementById('specialTrainId').value;
    const depTime = parseInt(document.getElementById('specialDepTime').value);
    const speed = parseInt(document.getElementById('specialSpeed').value);
    
    if (!trainId) {
        showNotification('Please enter a train ID', 'error');
        return;
    }
    
    try {
        const response = await fetch(`${CONFIG.BACKEND_URL}/special_train`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                train_id: trainId,
                dep_time: depTime,
                arr_time: depTime + 180, // 3 hours journey
                speed_kmh: speed,
                stops: ['SBC', 'Kengeri', 'Mandya', 'MYS'],
                priority: 'high',
                train_type: 'special'
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            showNotification(`Special train ${trainId} added`, 'success');
            
            // Clear form
            document.getElementById('specialTrainId').value = '';
            
            // Reload train list
            loadTrainList();
        } else {
            showNotification('Failed to add special train', 'error');
        }
    } catch (error) {
        console.error('Error adding special train:', error);
        showNotification('Error adding special train', 'error');
    }
}

/**
 * Manually trigger optimization
 */
async function optimizeSchedule() {
    try {
        const response = await fetch(`${CONFIG.BACKEND_URL}/optimize`, {
            method: 'POST'
        });
        const result = await response.json();
        
        if (result.success) {
            showNotification(
                `Optimization completed in ${result.solve_time.toFixed(2)}s. Total delay: ${result.total_delay.toFixed(1)} min`,
                'success'
            );
        } else {
            showNotification(`Optimization failed: ${result.message}`, 'error');
        }
    } catch (error) {
        console.error('Error optimizing schedule:', error);
        showNotification('Error optimizing schedule', 'error');
    }
}

/**
 * Refresh data from backend
 */
async function refreshData() {
    try {
        socket.emit('request_update');
        showNotification('Data refreshed', 'info');
    } catch (error) {
        console.error('Error refreshing data:', error);
        showNotification('Error refreshing data', 'error');
    }
}

// Initialize application when DOM is loaded
document.addEventListener('DOMContentLoaded', init);
