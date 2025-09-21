"""
Flask backend for Indian Railways DSS
Provides REST API and WebSocket for real-time train simulation
"""

from flask import Flask, request, jsonify, render_template_string
from flask_socketio import SocketIO, emit
import json
import threading
import time
from typing import Dict, List
import logging
import os
import sys

# Add current directory to path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sim_engine import SimulationEngine, TrainPosition, Disruption
from milp_optimizer import MILPOptimizer, OptimizationResult

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = 'railway-dss-secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Global simulation state
simulation = None
optimizer = None
simulation_thread = None
running = False

def initialize_system():
    """Initialize simulation engine and optimizer"""
    global simulation, optimizer
    
    try:
        # Paths to data files
        schedules_file = os.path.join(os.path.dirname(__file__), '..', 'data', 'sbc_mys_schedules.csv')
        geo_file = os.path.join(os.path.dirname(__file__), '..', 'data', 'sbc_mys_geo.json')
        
        # Initialize simulation engine
        simulation = SimulationEngine(schedules_file, geo_file)
        logger.info("Simulation engine initialized")
        
        # Initialize MILP optimizer
        optimizer = MILPOptimizer(simulation.track_segments, simulation.stations)
        logger.info("MILP optimizer initialized")
        
        return True
    except Exception as e:
        logger.error(f"Failed to initialize system: {str(e)}")
        return False

def simulation_loop():
    """Main simulation loop running in separate thread"""
    global running, simulation
    
    while running:
        try:
            if simulation and running:
                # Step simulation forward
                simulation.step(1.0)  # 1-minute steps
                
                # Get current positions and stats
                positions = simulation.get_positions()
                stats = simulation.get_stats()
                
                # Emit updates to connected clients
                socketio.emit('train_positions', {
                    'positions': {
                        train_id: {
                            'train_id': pos.train_id,
                            'lat': pos.lat,
                            'lon': pos.lon,
                            'speed': pos.speed,
                            'status': pos.status,
                            'current_segment': pos.current_segment,
                            'next_station': pos.next_station,
                            'delay': pos.delay,
                            'track_type': pos.track_type
                        } for train_id, pos in positions.items()
                    },
                    'timestamp': time.time()
                })
                
                socketio.emit('simulation_stats', stats)
                
            time.sleep(1)  # Update every second
            
        except Exception as e:
            logger.error(f"Simulation loop error: {str(e)}")
            time.sleep(5)

# REST API Endpoints

@app.route('/')
def index():
    """Serve basic info page"""
    return jsonify({
        'name': 'Indian Railways DSS Backend',
        'version': '1.0.0',
        'status': 'running' if running else 'stopped',
        'endpoints': [
            '/start_sim',
            '/stop_sim',
            '/reset_sim',
            '/positions',
            '/stats',
            '/disrupt',
            '/optimize',
            '/special_train',
            '/tracks',
            '/stations'
        ]
    })

@app.route('/start_sim', methods=['POST'])
def start_simulation():
    """Start the simulation"""
    global running, simulation_thread, simulation
    
    try:
        if not simulation:
            if not initialize_system():
                return jsonify({'error': 'Failed to initialize system'}), 500
        
        if not running:
            simulation.start_simulation()
            running = True
            
            # Start simulation thread
            simulation_thread = threading.Thread(target=simulation_loop, daemon=True)
            simulation_thread.start()
            
            logger.info("Simulation started")
            return jsonify({'message': 'Simulation started', 'success': True})
        else:
            return jsonify({'message': 'Simulation already running', 'success': True})
            
    except Exception as e:
        logger.error(f"Error starting simulation: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/stop_sim', methods=['POST'])
def stop_simulation():
    """Stop the simulation"""
    global running
    
    try:
        running = False
        logger.info("Simulation stopped")
        return jsonify({'message': 'Simulation stopped', 'success': True})
        
    except Exception as e:
        logger.error(f"Error stopping simulation: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/reset_sim', methods=['POST'])
def reset_simulation():
    """Reset the simulation"""
    global running, simulation
    
    try:
        running = False
        time.sleep(1)  # Allow thread to stop
        
        if simulation:
            simulation.reset()
        
        logger.info("Simulation reset")
        return jsonify({'message': 'Simulation reset', 'success': True})
        
    except Exception as e:
        logger.error(f"Error resetting simulation: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/positions', methods=['GET'])
def get_positions():
    """Get current train positions"""
    try:
        if not simulation:
            return jsonify({'positions': {}, 'timestamp': time.time()})
        
        positions = simulation.get_positions()
        return jsonify({
            'positions': {
                train_id: {
                    'train_id': pos.train_id,
                    'lat': pos.lat,
                    'lon': pos.lon,
                    'speed': pos.speed,
                    'status': pos.status,
                    'current_segment': pos.current_segment,
                    'next_station': pos.next_station,
                    'delay': pos.delay,
                    'track_type': pos.track_type
                } for train_id, pos in positions.items()
            },
            'timestamp': time.time()
        })
        
    except Exception as e:
        logger.error(f"Error getting positions: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/stats', methods=['GET'])
def get_stats():
    """Get simulation statistics"""
    try:
        if not simulation:
            return jsonify({'stats': {}})
        
        stats = simulation.get_stats()
        return jsonify({'stats': stats})
        
    except Exception as e:
        logger.error(f"Error getting stats: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/disrupt', methods=['POST'])
def add_disruption():
    """Add a disruption to a train"""
    try:
        data = request.get_json()
        train_id = data.get('train_id')
        segment = data.get('segment')
        delay_minutes = float(data.get('delay_minutes', 0))
        reason = data.get('reason', 'Manual disruption')
        
        if not all([train_id, segment]):
            return jsonify({'error': 'Missing required fields'}), 400
        
        if simulation:
            success = simulation.add_disruption(train_id, segment, delay_minutes, reason)
            
            if success:
                # Trigger optimization
                optimization_result = None
                if optimizer:
                    try:
                        optimization_result = optimizer.optimize(
                            simulation.trains, 
                            simulation.disruptions
                        )
                        logger.info(f"Optimization triggered: {optimization_result.success}")
                    except Exception as opt_error:
                        logger.error(f"Optimization failed: {str(opt_error)}")
                
                return jsonify({
                    'message': 'Disruption added',
                    'success': True,
                    'optimization': {
                        'triggered': optimization_result is not None,
                        'success': optimization_result.success if optimization_result else False,
                        'total_delay': optimization_result.total_delay if optimization_result else 0,
                        'rerouted_trains': list(optimization_result.rerouted_trains) if optimization_result else []
                    }
                })
            else:
                return jsonify({'error': 'Failed to add disruption'}), 400
        else:
            return jsonify({'error': 'Simulation not initialized'}), 500
            
    except Exception as e:
        logger.error(f"Error adding disruption: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/optimize', methods=['POST'])
def optimize_schedule():
    """Manually trigger schedule optimization"""
    try:
        if not optimizer or not simulation:
            return jsonify({'error': 'System not initialized'}), 500
        
        result = optimizer.optimize(simulation.trains, simulation.disruptions)
        
        return jsonify({
            'success': result.success,
            'objective_value': result.objective_value,
            'total_delay': result.total_delay,
            'rerouted_trains': list(result.rerouted_trains),
            'solve_time': result.solve_time,
            'message': result.message
        })
        
    except Exception as e:
        logger.error(f"Error in optimization: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/special_train', methods=['POST'])
def add_special_train():
    """Add a special train for what-if analysis"""
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['train_id', 'dep_time', 'arr_time', 'speed_kmh', 'stops']
        if not all(field in data for field in required_fields):
            return jsonify({'error': 'Missing required fields'}), 400
        
        if simulation:
            simulation.add_special_train(data)
            
            # Trigger optimization with new train
            if optimizer:
                try:
                    result = optimizer.optimize(simulation.trains, simulation.disruptions)
                    
                    return jsonify({
                        'message': 'Special train added',
                        'success': True,
                        'optimization': {
                            'success': result.success,
                            'total_delay': result.total_delay,
                            'rerouted_trains': list(result.rerouted_trains),
                            'solve_time': result.solve_time
                        }
                    })
                except Exception as opt_error:
                    logger.error(f"Optimization after special train failed: {str(opt_error)}")
                    return jsonify({
                        'message': 'Special train added but optimization failed',
                        'success': True,
                        'optimization': {'success': False, 'error': str(opt_error)}
                    })
            else:
                return jsonify({
                    'message': 'Special train added',
                    'success': True,
                    'optimization': {'success': False, 'error': 'Optimizer not available'}
                })
        else:
            return jsonify({'error': 'Simulation not initialized'}), 500
            
    except Exception as e:
        logger.error(f"Error adding special train: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/tracks', methods=['GET'])
def get_tracks():
    """Get track geometry data"""
    try:
        if not simulation:
            return jsonify({'tracks': {}})
        
        tracks = {}
        for name, segment in simulation.track_segments.items():
            tracks[name] = {
                'name': segment.name,
                'coordinates': segment.coordinates,
                'track_type': segment.track_type,
                'capacity': segment.capacity,
                'segment': segment.segment,
                'length_km': segment.length_km
            }
        
        return jsonify({'tracks': tracks})
        
    except Exception as e:
        logger.error(f"Error getting tracks: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/stations', methods=['GET'])
def get_stations():
    """Get station data"""
    try:
        if not simulation:
            return jsonify({'stations': {}})
        
        return jsonify({'stations': simulation.stations})
        
    except Exception as e:
        logger.error(f"Error getting stations: {str(e)}")
        return jsonify({'error': str(e)}), 500

# WebSocket Events

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    logger.info(f"Client connected: {request.sid}")
    emit('connected', {'message': 'Connected to IR-DSS backend'})

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    logger.info(f"Client disconnected: {request.sid}")

@socketio.on('request_update')
def handle_update_request():
    """Handle request for current state"""
    try:
        if simulation:
            positions = simulation.get_positions()
            stats = simulation.get_stats()
            
            emit('train_positions', {
                'positions': {
                    train_id: {
                        'train_id': pos.train_id,
                        'lat': pos.lat,
                        'lon': pos.lon,
                        'speed': pos.speed,
                        'status': pos.status,
                        'current_segment': pos.current_segment,
                        'next_station': pos.next_station,
                        'delay': pos.delay,
                        'track_type': pos.track_type
                    } for train_id, pos in positions.items()
                },
                'timestamp': time.time()
            })
            
            emit('simulation_stats', stats)
        
    except Exception as e:
        logger.error(f"Error handling update request: {str(e)}")
        emit('error', {'message': str(e)})

# Error handlers

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

# Static file serving for frontend
@app.route('/frontend/<path:filename>')
def serve_frontend(filename):
    """Serve frontend files"""
    frontend_dir = os.path.join(os.path.dirname(__file__), '..', 'frontend')
    return app.send_static_file(os.path.join(frontend_dir, filename))

if __name__ == '__main__':
    # Initialize system on startup
    logger.info("Starting Indian Railways DSS Backend...")
    
    if initialize_system():
        logger.info("System initialized successfully")
    else:
        logger.error("System initialization failed")
    
    # Start Flask-SocketIO server
    socketio.run(
        app, 
        host='0.0.0.0', 
        port=5000, 
        debug=False,
        use_reloader=False  # Disable reloader to prevent duplicate processes
    )
