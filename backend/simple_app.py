"""
Simplified Flask backend for Railway DSS - minimal dependencies
Works with just Flask and basic Python libraries
"""

from flask import Flask, request, jsonify, render_template_string
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

# Global state
trains_data = {}
simulation_running = False
simulation_time = 0
train_positions = {}

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
                    'priority': row['priority']
                }
        logger.info(f"Loaded {len(trains_data)} trains")
    except Exception as e:
        logger.error(f"Error loading train data: {e}")

def calculate_position(train_id, current_time):
    """Calculate train position based on time"""
    if train_id not in trains_data:
        return None
    
    train = trains_data[train_id]
    
    # Simple linear interpolation along route
    # SBC to MYS coordinates
    route_coords = [
        [77.5946, 12.9716],  # SBC
        [77.0000, 12.4200],  # Kengeri  
        [76.7600, 12.2800],  # Mandya
        [76.6500, 12.3000]   # MYS
    ]
    
    if current_time < train['dep_time']:
        # Not departed yet
        return {
            'train_id': train_id,
            'lat': route_coords[0][1],
            'lon': route_coords[0][0],
            'speed': 0,
            'status': 'waiting',
            'current_segment': 'SBC',
            'next_station': train['stops'][0] if train['stops'] else 'SBC',
            'delay': 0,
            'track_type': 'main'
        }
    
    if current_time > train['arr_time']:
        # Journey completed
        return {
            'train_id': train_id,
            'lat': route_coords[-1][1],
            'lon': route_coords[-1][0],
            'speed': 0,
            'status': 'completed',
            'current_segment': 'MYS',
            'next_station': 'MYS',
            'delay': 0,
            'track_type': 'main'
        }
    
    # Calculate progress
    journey_time = train['arr_time'] - train['dep_time']
    elapsed_time = current_time - train['dep_time']
    progress = elapsed_time / journey_time
    
    # Interpolate position
    total_segments = len(route_coords) - 1
    segment_progress = progress * total_segments
    segment_index = int(segment_progress)
    local_progress = segment_progress - segment_index
    
    if segment_index >= total_segments:
        segment_index = total_segments - 1
        local_progress = 1.0
    
    # Linear interpolation between two points
    start_coord = route_coords[segment_index]
    end_coord = route_coords[segment_index + 1]
    
    lat = start_coord[1] + (end_coord[1] - start_coord[1]) * local_progress
    lon = start_coord[0] + (end_coord[0] - start_coord[0]) * local_progress
    
    # Determine current segment
    segments = ['SBC-Kengeri', 'Kengeri-Mandya', 'Mandya-MYS']
    current_segment = segments[min(segment_index, len(segments)-1)]
    
    return {
        'train_id': train_id,
        'lat': lat,
        'lon': lon,
        'speed': train['speed_kmh'],
        'status': 'running',
        'current_segment': current_segment,
        'next_station': train['stops'][min(segment_index + 1, len(train['stops'])-1)] if train['stops'] else 'MYS',
        'delay': 0,
        'track_type': 'main'
    }

def simulation_loop():
    """Simple simulation loop"""
    global simulation_running, simulation_time, train_positions
    
    while simulation_running:
        # Update train positions
        train_positions = {}
        for train_id in trains_data:
            pos = calculate_position(train_id, simulation_time)
            if pos:
                train_positions[train_id] = pos
        
        simulation_time += 1  # Advance 1 minute
        time.sleep(0.1)  # 100ms update rate (10x speed)

# API Routes

@app.route('/')
def index():
    return jsonify({
        'name': 'Railway DSS - Simplified Backend',
        'status': 'running' if simulation_running else 'stopped',
        'trains': len(trains_data),
        'time': simulation_time
    })

@app.route('/start_sim', methods=['POST'])
def start_simulation():
    global simulation_running, simulation_time
    
    if not simulation_running:
        simulation_running = True
        simulation_time = 0
        
        # Start simulation thread
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
    return jsonify({'success': True, 'message': 'Simulation reset'})

@app.route('/positions', methods=['GET'])
def get_positions():
    return jsonify({
        'positions': train_positions,
        'timestamp': time.time(),
        'simulation_time': simulation_time
    })

@app.route('/stats', methods=['GET'])
def get_stats():
    active_trains = len([p for p in train_positions.values() if p['status'] == 'running'])
    completed_trains = len([p for p in train_positions.values() if p['status'] == 'completed'])
    
    return jsonify({
        'stats': {
            'total_trains': len(trains_data),
            'active_trains': active_trains,
            'completed_trains': completed_trains,
            'on_time': completed_trains,  # Simplified
            'delayed': 0,
            'avg_delay': 0,
            'throughput': active_trains,
            'simulation_time': simulation_time
        }
    })

@app.route('/tracks', methods=['GET'])
def get_tracks():
    # Simplified track data
    tracks = {
        'SBC-Kengeri Main Line': {
            'name': 'SBC-Kengeri Main Line',
            'coordinates': [
                [77.5946, 12.9716],
                [77.3000, 12.7000],
                [77.0000, 12.4200]
            ],
            'track_type': 'main',
            'capacity': 1,
            'segment': 'SBC-Kengeri',
            'length_km': 45
        },
        'Kengeri-Mandya Main Line': {
            'name': 'Kengeri-Mandya Main Line', 
            'coordinates': [
                [77.0000, 12.4200],
                [76.7600, 12.2800]
            ],
            'track_type': 'main',
            'capacity': 2,
            'segment': 'Kengeri-Mandya',
            'length_km': 35
        },
        'Mandya-MYS Main Line': {
            'name': 'Mandya-MYS Main Line',
            'coordinates': [
                [76.7600, 12.2800],
                [76.6500, 12.3000]
            ],
            'track_type': 'main',
            'capacity': 1,
            'segment': 'Mandya-MYS',
            'length_km': 20
        }
    }
    return jsonify({'tracks': tracks})

@app.route('/stations', methods=['GET'])
def get_stations():
    stations = {
        'SBC': {'name': 'Bangalore City Junction', 'code': 'SBC', 'lat': 12.9716, 'lon': 77.5946, 'platforms': 10, 'major': True},
        'KGI': {'name': 'Kengeri', 'code': 'KGI', 'lat': 12.4200, 'lon': 77.0000, 'platforms': 4, 'major': True},
        'MYA': {'name': 'Mandya Junction', 'code': 'MYA', 'lat': 12.2800, 'lon': 76.7600, 'platforms': 5, 'major': True},
        'MYS': {'name': 'Mysuru Junction', 'code': 'MYS', 'lat': 12.3000, 'lon': 76.6500, 'platforms': 6, 'major': True}
    }
    return jsonify({'stations': stations})

@app.route('/disrupt', methods=['POST'])
def add_disruption():
    # Simplified disruption handling
    data = request.get_json()
    train_id = data.get('train_id')
    delay_minutes = data.get('delay_minutes', 0)
    
    return jsonify({
        'success': True,
        'message': f'Disruption added to {train_id} (+{delay_minutes} min)',
        'optimization': {'triggered': False, 'success': False}
    })

@app.route('/special_train', methods=['POST'])
def add_special_train():
    data = request.get_json()
    train_id = data.get('train_id')
    
    # Add to trains_data
    trains_data[train_id] = {
        'train_id': train_id,
        'dep_time': data.get('dep_time', 30),
        'arr_time': data.get('arr_time', 210),
        'speed_kmh': data.get('speed_kmh', 65),
        'stops': data.get('stops', ['SBC', 'KGI', 'MYA', 'MYS']),
        'train_type': 'special',
        'priority': 'high'
    }
    
    return jsonify({
        'success': True,
        'message': f'Special train {train_id} added'
    })

# Serve frontend files
@app.route('/frontend/<path:filename>')
def serve_frontend(filename):
    frontend_dir = os.path.join(os.path.dirname(__file__), '..', 'frontend')
    return app.send_from_directory(frontend_dir, filename)

if __name__ == '__main__':
    print("Starting Railway DSS - Simplified Backend...")
    load_train_data()
    
    # Enable CORS for development
    from flask_cors import CORS
    try:
        CORS(app)
    except:
        print("CORS not available, continuing without it...")
    
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
