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
import ast
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
    
    # Load tracks from GeoJSON
    tracks_file = os.path.join(os.path.dirname(__file__), '..', 'bangalore_mysore_tracks.geojson')
    try:
        with open(tracks_file, 'r', encoding='utf-8') as f:
            tracks_data = json.load(f)
            
        # Process all track features
        track_count = 0
        for i, feature in enumerate(tracks_data['features']):
            if feature['geometry']['type'] == 'LineString':
                coords = feature['geometry']['coordinates']
                if len(coords) >= 2:  # Valid track segment
                    track_id = f"track_{i}"
                    track_type = feature['properties'].get('railway', 'rail')
                    service = feature['properties'].get('service', 'main')
                    
                    actual_tracks[track_id] = {
                        'name': f'Track {i+1}',
                        'coordinates': coords,
                        'track_type': track_type,
                        'service': service,
                        'capacity': 1,
                        'segment': f'Segment-{i+1}',
                        'length_km': calculate_route_length(coords)
                    }
                    track_count += 1
        
        logger.info(f"Loaded {track_count} track segments from GeoJSON")
        
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

def create_train_route(stops):
    """Create a route based on train stops using actual station coordinates and track data"""
    if not stops or not actual_stations:
        return []
    
    route = []
    
    # Add coordinates for each stop in order
    for stop_code in stops:
        if stop_code in actual_stations:
            station = actual_stations[stop_code]
            route.append([station['lon'], station['lat']])
        else:
            logger.warning(f"Station {stop_code} not found in actual stations")
    
    # If we have track data, try to interpolate between stations
    if len(route) >= 2 and actual_tracks:
        enhanced_route = []
        
        for i in range(len(route) - 1):
            start_coord = route[i]
            end_coord = route[i + 1]
            
            # Add start coordinate
            enhanced_route.append(start_coord)
            
            # Find track segments that might connect these stations
            connecting_points = find_connecting_track_points(start_coord, end_coord)
            enhanced_route.extend(connecting_points)
        
        # Add final coordinate
        enhanced_route.append(route[-1])
        return enhanced_route
    
    return route

def find_connecting_track_points(start_coord, end_coord):
    """Find track points that lie between two stations"""
    connecting_points = []
    
    # Calculate bounding box between stations
    min_lon = min(start_coord[0], end_coord[0]) - 0.01
    max_lon = max(start_coord[0], end_coord[0]) + 0.01
    min_lat = min(start_coord[1], end_coord[1]) - 0.01
    max_lat = max(start_coord[1], end_coord[1]) + 0.01
    
    # Find track points within this bounding box
    for track in actual_tracks.values():
        if track['coordinates']:
            for coord in track['coordinates']:
                lon, lat = coord[0], coord[1]
                if min_lon <= lon <= max_lon and min_lat <= lat <= max_lat:
                    # Calculate distance from the direct line between stations
                    distance_to_line = point_to_line_distance(coord, start_coord, end_coord)
                    if distance_to_line < 0.02:  # Within ~2km of direct line
                        connecting_points.append(coord)
    
    # Sort points by distance from start
    connecting_points.sort(key=lambda p: 
        math.sqrt((p[0] - start_coord[0])**2 + (p[1] - start_coord[1])**2))
    
    # Return a subset to avoid too many points
    return connecting_points[::max(1, len(connecting_points) // 5)]

def point_to_line_distance(point, line_start, line_end):
    """Calculate distance from a point to a line segment"""
    px, py = point[0], point[1]
    x1, y1 = line_start[0], line_start[1]
    x2, y2 = line_end[0], line_end[1]
    
    # Calculate the distance
    A = px - x1
    B = py - y1
    C = x2 - x1
    D = y2 - y1
    
    dot = A * C + B * D
    len_sq = C * C + D * D
    
    if len_sq == 0:
        return math.sqrt(A * A + B * B)
    
    param = dot / len_sq
    
    if param < 0:
        xx, yy = x1, y1
    elif param > 1:
        xx, yy = x2, y2
    else:
        xx = x1 + param * C
        yy = y1 + param * D
    
    dx = px - xx
    dy = py - yy
    return math.sqrt(dx * dx + dy * dy)

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
                try:
                    # Safely parse the stops list
                    stops_str = row['stops'].strip()
                    if stops_str.startswith('[') and stops_str.endswith(']'):
                        stops = ast.literal_eval(stops_str)
                    else:
                        stops = [s.strip().strip("'") for s in stops_str.split(',')]
                    
                    trains_data[row['train_id']] = {
                        'train_id': row['train_id'],
                        'dep_time': int(row['dep_time']),
                        'arr_time': int(row['arr_time']),
                        'speed_kmh': int(row['speed_kmh']),
                        'stops': stops,
                        'train_type': row['train_type'],
                        'priority': row['priority'],
                        'delay': 0  # Added delay tracking
                    }
                except (ValueError, SyntaxError) as e:
                    logger.error(f"Error parsing train {row['train_id']}: {e}")
                    continue
        logger.info(f"Loaded {len(trains_data)} trains")
    except Exception as e:
        logger.error(f"Error loading train data: {e}")

def calculate_position(train_id, current_time):
    """Calculate train position with better movement visualization"""
    if train_id not in trains_data:
        return None
    
    train = trains_data[train_id]
    
    # Get track coordinates - create a comprehensive route
    if not actual_tracks or not actual_stations:
        return None
    
    # Create a route that connects all stations the train visits
    route_coords = create_train_route(train['stops'])
    
    if not route_coords or len(route_coords) < 2:
        # Fallback to first available track
        first_track = list(actual_tracks.values())[0]
        route_coords = first_track['coordinates']
    
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
    print("Loading GeoJSON data...")
    load_actual_geojson()
    
    print("Loading train schedules...")
    load_train_data()
    
    print(f"✓ Loaded {len(actual_stations)} stations")
    print(f"✓ Loaded {len(actual_tracks)} track segments") 
    print(f"✓ Loaded {len(trains_data)} trains")
    
    if not actual_stations or not actual_tracks or not trains_data:
        print("⚠️  Warning: Some data files may be missing or corrupted")
        print("   Make sure you have:")
        print("   - bangalore_mysore_stations.geojson")
        print("   - bangalore_mysore_tracks.geojson") 
        print("   - data/sbc_mys_schedules.csv")
    
    print("Starting Flask server on http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
