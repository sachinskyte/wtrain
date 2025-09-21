#!/usr/bin/env python3
"""
Simple start script for Railway DSS - minimal dependencies
Only requires Flask (which you already have)
"""

import sys
import os
import subprocess
import webbrowser
import time

def check_basic_dependencies():
    """Check basic dependencies"""
    try:
        import flask
        print("✓ Flask available")
        return True
    except ImportError:
        print("✗ Flask not available")
        print("Install with: pip install flask")
        return False

def start_simple_backend():
    """Start the simplified backend"""
    backend_dir = os.path.join(os.path.dirname(__file__), 'backend')
    app_file = os.path.join(backend_dir, 'simple_app.py')
    
    print("Starting simplified backend server...")
    try:
        process = subprocess.Popen([
            sys.executable, app_file
        ], cwd=backend_dir)
        
        time.sleep(2)
        
        if process.poll() is None:
            print("✓ Backend started successfully!")
            return process
        else:
            print("✗ Backend failed to start!")
            return None
            
    except Exception as e:
        print(f"✗ Error starting backend: {e}")
        return None

def create_simple_frontend():
    """Create a simplified frontend that works with basic backend"""
    frontend_dir = os.path.join(os.path.dirname(__file__), 'frontend')
    simple_html = os.path.join(frontend_dir, 'simple.html')
    
    html_content = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Railway DSS - Simple Version</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <style>
        body { margin: 0; font-family: Arial, sans-serif; }
        #map { height: 100vh; width: 100%; }
        .control-panel {
            position: absolute; top: 10px; right: 10px; background: white;
            padding: 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            z-index: 1000; min-width: 250px;
        }
        .btn {
            padding: 8px 16px; margin: 5px; border: none; border-radius: 4px;
            cursor: pointer; font-weight: bold;
        }
        .btn-success { background: #28a745; color: white; }
        .btn-warning { background: #ffc107; color: black; }
        .btn-danger { background: #dc3545; color: white; }
        .status { margin: 10px 0; padding: 10px; background: #f8f9fa; border-radius: 4px; }
    </style>
</head>
<body>
    <div id="map"></div>
    <div class="control-panel">
        <h3>🚂 Railway DSS</h3>
        <div>
            <button id="startBtn" class="btn btn-success">▶ Start</button>
            <button id="stopBtn" class="btn btn-warning">⏸ Stop</button>
            <button id="resetBtn" class="btn btn-danger">⏹ Reset</button>
        </div>
        <div class="status">
            <div>Status: <span id="status">Stopped</span></div>
            <div>Time: <span id="time">00:00</span></div>
            <div>Active Trains: <span id="activeTrains">0</span></div>
        </div>
    </div>

    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script>
        const BACKEND_URL = 'http://localhost:5000';
        let map, trainMarkers = {}, updateInterval;

        // Initialize map
        map = L.map('map').setView([12.6, 77.2], 10);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '© OpenStreetMap contributors'
        }).addTo(map);

        // Load tracks and stations
        async function loadData() {
            try {
                // Load tracks
                const tracksResp = await fetch(`${BACKEND_URL}/tracks`);
                const tracksData = await tracksResp.json();
                
                Object.values(tracksData.tracks).forEach(track => {
                    const coords = track.coordinates.map(c => [c[1], c[0]]);
                    L.polyline(coords, {color: '#2c3e50', weight: 6}).addTo(map)
                        .bindPopup(`<b>${track.name}</b><br>Type: ${track.track_type}`);
                });

                // Load stations
                const stationsResp = await fetch(`${BACKEND_URL}/stations`);
                const stationsData = await stationsResp.json();
                
                Object.values(stationsData.stations).forEach(station => {
                    L.circleMarker([station.lat, station.lon], {
                        radius: 8, fillColor: '#e74c3c', color: '#fff', weight: 2, fillOpacity: 0.8
                    }).addTo(map).bindPopup(`<b>${station.name}</b><br>Code: ${station.code}`);
                });

            } catch (error) {
                console.error('Error loading data:', error);
            }
        }

        // Update train positions
        async function updatePositions() {
            try {
                const resp = await fetch(`${BACKEND_URL}/positions`);
                const data = await resp.json();
                
                // Update UI
                document.getElementById('activeTrains').textContent = 
                    Object.keys(data.positions).length;
                document.getElementById('time').textContent = 
                    Math.floor(data.simulation_time / 60).toString().padStart(2, '0') + ':' +
                    (data.simulation_time % 60).toString().padStart(2, '0');

                // Update train markers
                Object.entries(data.positions).forEach(([trainId, pos]) => {
                    if (trainMarkers[trainId]) {
                        trainMarkers[trainId].setLatLng([pos.lat, pos.lon]);
                    } else {
                        trainMarkers[trainId] = L.marker([pos.lat, pos.lon], {
                            icon: L.divIcon({
                                html: '🚂',
                                iconSize: [20, 20],
                                className: 'train-icon'
                            })
                        }).addTo(map).bindPopup(`
                            <b>Train ${trainId}</b><br>
                            Status: ${pos.status}<br>
                            Speed: ${pos.speed} km/h<br>
                            Segment: ${pos.current_segment}
                        `);
                    }
                });

                // Remove old markers
                Object.keys(trainMarkers).forEach(trainId => {
                    if (!data.positions[trainId]) {
                        map.removeLayer(trainMarkers[trainId]);
                        delete trainMarkers[trainId];
                    }
                });

            } catch (error) {
                console.error('Error updating positions:', error);
            }
        }

        // Control functions
        async function startSim() {
            try {
                await fetch(`${BACKEND_URL}/start_sim`, {method: 'POST'});
                document.getElementById('status').textContent = 'Running';
                updateInterval = setInterval(updatePositions, 1000);
            } catch (error) {
                console.error('Error starting simulation:', error);
            }
        }

        async function stopSim() {
            try {
                await fetch(`${BACKEND_URL}/stop_sim`, {method: 'POST'});
                document.getElementById('status').textContent = 'Stopped';
                if (updateInterval) clearInterval(updateInterval);
            } catch (error) {
                console.error('Error stopping simulation:', error);
            }
        }

        async function resetSim() {
            try {
                await fetch(`${BACKEND_URL}/reset_sim`, {method: 'POST'});
                document.getElementById('status').textContent = 'Reset';
                document.getElementById('time').textContent = '00:00';
                document.getElementById('activeTrains').textContent = '0';
                
                Object.values(trainMarkers).forEach(marker => map.removeLayer(marker));
                trainMarkers = {};
                
                if (updateInterval) clearInterval(updateInterval);
            } catch (error) {
                console.error('Error resetting simulation:', error);
            }
        }

        // Event listeners
        document.getElementById('startBtn').addEventListener('click', startSim);
        document.getElementById('stopBtn').addEventListener('click', stopSim);
        document.getElementById('resetBtn').addEventListener('click', resetSim);

        // Initialize
        loadData();
    </script>
</body>
</html>'''
    
    with open(simple_html, 'w') as f:
        f.write(html_content)
    
    return simple_html

def main():
    print("=" * 50)
    print("🚂 Railway DSS - Simple Start")
    print("=" * 50)
    
    print("1. Checking basic dependencies...")
    if not check_basic_dependencies():
        print("\nTry installing Flask:")
        print("pip install flask")
        return 1
    
    print("\n2. Starting simplified backend...")
    backend_process = start_simple_backend()
    if not backend_process:
        return 1
    
    print("\n3. Creating simple frontend...")
    frontend_file = create_simple_frontend()
    
    print("\n4. Opening in browser...")
    webbrowser.open(f'file://{os.path.abspath(frontend_file)}')
    
    print("\n" + "=" * 50)
    print("🎉 Simple Railway DSS Started!")
    print("=" * 50)
    print("\nBackend: http://localhost:5000")
    print("Frontend: Opened in browser")
    print("\nFeatures available:")
    print("- Basic train simulation")
    print("- Interactive map with tracks/stations")
    print("- Real-time train movement")
    print("- Start/Stop/Reset controls")
    print("\nPress Ctrl+C to stop")
    
    try:
        backend_process.wait()
    except KeyboardInterrupt:
        print("\n\nStopping...")
        backend_process.terminate()
        print("✓ Stopped!")
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
