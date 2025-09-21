"""
Improved Flask backend for Railway DSS
Uses actual GeoJSON files and provides better train movement visualization
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import json
import threading
import time
import csv
import math
import os
from typing import Dict, List, Tuple
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Global state
trains_data = {}
simulation_running = False
simulation_time = 0
train_positions = {}
simulation_speed = 1.0  # Speed multiplier
actual_stations = {}
actual_tracks = {}

def load_actual_geojson():
    """Load actual GeoJSON files"""
    global actual_stations, actual_tracks
    
    # Load stations
    stations_file = os.path.join(os.path.dirname(__file__), '..', 'bangalore_mysore_stations.geojson')
    try:
        with open(stations_file, 'r', encoding='utf-8') as f:
            stations_data = json.load(f)
            for feature in stations_data['features']:
                props = feature['properties']
                coords = feature['geometry']['coordinates']
                actual_stations[props['station_code']] = {
                    'name': props['name'],
                    'code': props['station_code'],
                    'lat': coords[1],
                    'lon': coords[0],
                    'platforms': props.get('platforms', 2),
                    'major': props.get('platforms', 2) >= 5,
                    'dwell_time': props.get('dwell_time', 15)
                }
        logger.info(f"Loaded {len(actual_stations)} actual stations")
    except Exception as e:
        logger.error(f"Error loading stations: {e}")
    
    # Load tracks (simplified - take first few features due to size)
    tracks_file = os.path.join(os.path.dirname(__file__), '..', 'bangalore_mysore_tracks.geojson')
    try:
        with open(tracks_file, 'r', encoding='utf-8') as f:
            tracks_data = json.load(f)
            
        # Process tracks and create main route
        main_route_coords = []
        track_segments = []
        
        # Extract coordinates from all track features
        for i, feature in enumerate(tracks_data['features'][:50]):  # Limit to first 50 for performance
            if feature['geometry']['type'] == 'LineString':
                coords = feature['geometry']['coordinates']
                track_segments.extend(coords)
                
        # Create simplified main route from SBC to MYS
        if actual_stations:
            sbc_coords = [actual_stations['SBC']['lon'], actual_stations['SBC']['lat']]
            mys_coords = [actual_stations['MYS']['lon'], actual_stations['MYS']['lat']]
            
            # Create interpolated route
            main_route_coords = create_interpolated_route(sbc_coords, mys_coords, track_segments)
        
        actual_tracks['main_route'] = {
            'name': 'SBC-MYS Main Line',
            'coordinates': main_route_coords,
            'track_type': 'main',
            'capacity': 1,
            'segment': 'SBC-MYS',
            'length_km': calculate_route_length(main_route_coords)
        }
        
        logger.info(f"Created main route with {len(main_route_coords)} points")
        
    except Exception as e:
        logger.error(f"Error loading tracks: {e}")
        # Fallback to simple route
        if actual_stations:
            simple_route = [
                [actual_stations['SBC']['lon'], actual_stations['SBC']['lat']],
                [actual_stations['MYA']['lon'], actual_stations['MYA']['lat']],
                [actual_stations['MYS']['lon'], actual_stations['MYS']['lat']]
            ]
            actual_tracks['main_route'] = {
                'name': 'SBC-MYS Simple Route',
                'coordinates': simple_route,
                'track_type': 'main',
                'capacity': 1,
                'segment': 'SBC-MYS',
                'length_km': calculate_route_length(simple_route)
            }

def create_interpolated_route(start_coords, end_coords, track_points):
    """Create interpolated route using actual track points"""
    route = [start_coords]
    
    # Add some intermediate points from actual tracks
    if track_points:
        # Sort track points by distance from start
        sorted_points = sorted(track_points, key=lambda p: 
            math.sqrt((p[0] - start_coords[0])**2 + (p[1] - start_coords[1])**2))
        
        # Add a few intermediate points
        for i in range(0, min(20, len(sorted_points)), 4):
            route.append(sorted_points[i])
    
    # Add intermediate stations
    if 'MYA' in actual_stations:
        route.append([actual_stations['MYA']['lon'], actual_stations['MYA']['lat']])
    
    route.append(end_coords)
    return route

def calculate_route_length(coordinates):
    """Calculate route length in km"""
    total_length = 0
    for i in range(1, len(coordinates)):
        lat1, lon1 = coordinates[i-1][1], coordinates[i-1][0]
        lat2, lon2 = coordinates[i][1], coordinates[i][0]
        
        # Haversine formula
        R = 6371  # Earth's radius in km
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat/2)**2 + 
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * 
             math.sin(dlon/2)**2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        total_length += R * c
    
    return total_length

def load_train_data():
    """Load train data from CSV"""
    global trains_data
    csv_file = os.path.join(os.path.dirname(__file__), '..', 'data', 'sbc_mys_schedules.csv')
    
    try:
        with open(csv_file, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                trains_data[row['train_id']] = {
                    'train_id': row['train_id'],
                    'dep_time': int(row['dep_time']),
                    'arr_time': int(row['arr_time']),
                    'speed_kmh': int(row['speed_kmh']),
                    'stops': eval(row['stops']),
                    'train_type': row['train_type'],
                    'priority': row['priority'],
                    'delay': 0  # Added delay tracking
                }
        logger.info(f"Loaded {len(trains_data)} trains")
    except Exception as e:
        logger.error(f"Error loading train data: {e}")

def calculate_position(train_id, current_time):
    """Calculate train position with better movement visualization"""
    if train_id not in trains_data:
        return None
    
    train = trains_data[train_id]
    
    # Get main route coordinates
    if 'main_route' not in actual_tracks:
        return None
        
    route_coords = actual_tracks['main_route']['coordinates']
    
    # Adjust for delays
    effective_dep_time = train['dep_time'] + train['delay']
    effective_arr_time = train['arr_time'] + train['delay']
    
    if current_time < effective_dep_time:
        # Not departed yet - show at starting station
        return {
            'train_id': train_id,
            'lat': route_coords[0][1],
            'lon': route_coords[0][0],
            'speed': 0,
            'status': 'waiting',
            'current_segment': 'SBC',
            'next_station': train['stops'][0] if train['stops'] else 'SBC',
            'delay': train['delay'],
            'track_type': 'main',
            'progress': 0.0
        }
    
    if current_time > effective_arr_time:
        # Journey completed
        return {
            'train_id': train_id,
            'lat': route_coords[-1][1],
            'lon': route_coords[-1][0],
            'speed': 0,
            'status': 'completed',
            'current_segment': 'MYS',
            'next_station': 'MYS',
            'delay': train['delay'],
            'track_type': 'main',
            'progress': 1.0
        }
    
    # Calculate progress along route
    journey_time = effective_arr_time - effective_dep_time
    elapsed_time = current_time - effective_dep_time
    progress = min(1.0, elapsed_time / journey_time)
    
    # Interpolate position along route
    if len(route_coords) < 2:
        lat, lon = route_coords[0][1], route_coords[0][0]
    else:
        # Find which segment we're in
        segment_progress = progress * (len(route_coords) - 1)
        segment_index = int(segment_progress)
        local_progress = segment_progress - segment_index
        
        if segment_index >= len(route_coords) - 1:
            lat, lon = route_coords[-1][1], route_coords[-1][0]
        else:
            # Linear interpolation
            start_coord = route_coords[segment_index]
            end_coord = route_coords[segment_index + 1]
            
            lat = start_coord[1] + (end_coord[1] - start_coord[1]) * local_progress
            lon = start_coord[0] + (end_coord[0] - start_coord[0]) * local_progress
    
    # Determine current status and next station
    status = 'running'
    next_station = 'MYS'
    
    # Check if near a station (dwelling)
    for station_code, station in actual_stations.items():
        distance = math.sqrt((lat - station['lat'])**2 + (lon - station['lon'])**2)
        if distance < 0.01 and station_code in train['stops']:  # Within ~1km
            status = 'dwelling'
            break
    
    return {
        'train_id': train_id,
        'lat': lat,
        'lon': lon,
        'speed': train['speed_kmh'] if status == 'running' else 0,
        'status': status,
        'current_segment': 'SBC-MYS',
        'next_station': next_station,
        'delay': train['delay'],
        'track_type': 'main',
        'progress': progress
    }

def simulation_loop():
    """Enhanced simulation loop with configurable speed"""
    global simulation_running, simulation_time, train_positions
    
    while simulation_running:
        # Update train positions
        train_positions = {}
        for train_id in trains_data:
            pos = calculate_position(train_id, simulation_time)
            if pos:
                train_positions[train_id] = pos
        
        # Advance time based on simulation speed
        simulation_time += simulation_speed
        
        # Sleep time inversely proportional to simulation speed
        sleep_time = max(0.05, 0.5 / simulation_speed)  # Faster updates for higher speeds
        time.sleep(sleep_time)

# API Routes

@app.route('/')
def index():
    return jsonify({
        'name': 'Railway DSS - Improved Backend',
        'status': 'running' if simulation_running else 'stopped',
        'trains': len(trains_data),
        'stations': len(actual_stations),
        'tracks': len(actual_tracks),
        'time': simulation_time,
        'speed': simulation_speed
    })

@app.route('/start_sim', methods=['POST'])
def start_simulation():
    global simulation_running, simulation_time
    
    if not simulation_running:
        simulation_running = True
        if simulation_time == 0:  # Only reset time if starting fresh
            simulation_time = 0
        
        thread = threading.Thread(target=simulation_loop, daemon=True)
        thread.start()
        
        return jsonify({'success': True, 'message': 'Simulation started'})
    else:
        return jsonify({'success': True, 'message': 'Already running'})

@app.route('/stop_sim', methods=['POST'])
def stop_simulation():
    global simulation_running
    simulation_running = False
    return jsonify({'success': True, 'message': 'Simulation stopped'})

@app.route('/reset_sim', methods=['POST'])
def reset_simulation():
    global simulation_running, simulation_time, train_positions
    simulation_running = False
    simulation_time = 0
    train_positions = {}
    
    # Reset train delays
    for train in trains_data.values():
        train['delay'] = 0
    
    return jsonify({'success': True, 'message': 'Simulation reset'})

@app.route('/set_speed', methods=['POST'])
def set_simulation_speed():
    global simulation_speed
    data = request.get_json()
    new_speed = float(data.get('speed', 1.0))
    simulation_speed = max(0.1, min(10.0, new_speed))  # Limit between 0.1x and 10x
    return jsonify({'success': True, 'speed': simulation_speed})

@app.route('/positions', methods=['GET'])
def get_positions():
    return jsonify({
        'positions': train_positions,
        'timestamp': time.time(),
        'simulation_time': simulation_time,
        'speed': simulation_speed
    })

@app.route('/stats', methods=['GET'])
def get_stats():
    active_trains = len([p for p in train_positions.values() if p['status'] == 'running'])
    completed_trains = len([p for p in train_positions.values() if p['status'] == 'completed'])
    delayed_trains = len([p for p in train_positions.values() if p['delay'] > 0])
    
    return jsonify({
        'stats': {
            'total_trains': len(trains_data),
            'active_trains': active_trains,
            'completed_trains': completed_trains,
            'on_time': completed_trains - delayed_trains,
            'delayed': delayed_trains,
            'avg_delay': sum(p['delay'] for p in train_positions.values()) / max(1, len(train_positions)),
            'throughput': active_trains,
            'simulation_time': simulation_time,
            'simulation_speed': simulation_speed
        }
    })

@app.route('/tracks', methods=['GET'])
def get_tracks():
    return jsonify({'tracks': actual_tracks})

@app.route('/stations', methods=['GET'])
def get_stations():
    return jsonify({'stations': actual_stations})

@app.route('/disrupt', methods=['POST'])
def add_disruption():
    data = request.get_json()
    train_id = data.get('train_id')
    delay_minutes = float(data.get('delay_minutes', 0))
    
    if train_id in trains_data:
        trains_data[train_id]['delay'] += delay_minutes
        return jsonify({
            'success': True,
            'message': f'Added {delay_minutes} min delay to {train_id}',
            'total_delay': trains_data[train_id]['delay']
        })
    else:
        return jsonify({'success': False, 'message': 'Train not found'})

@app.route('/special_train', methods=['POST'])
def add_special_train():
    data = request.get_json()
    train_id = data.get('train_id')
    
    if train_id not in trains_data:
        trains_data[train_id] = {
            'train_id': train_id,
            'dep_time': data.get('dep_time', 30),
            'arr_time': data.get('arr_time', 210),
            'speed_kmh': data.get('speed_kmh', 65),
            'stops': data.get('stops', ['SBC', 'MYA', 'MYS']),
            'train_type': 'special',
            'priority': 'high',
            'delay': 0
        }
        return jsonify({'success': True, 'message': f'Special train {train_id} added'})
    else:
        return jsonify({'success': False, 'message': 'Train ID already exists'})

if __name__ == '__main__':
    print("Starting Railway DSS - Improved Backend...")
    load_actual_geojson()
    load_train_data()
    
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
