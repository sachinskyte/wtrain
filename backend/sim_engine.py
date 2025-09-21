"""
SimPy-based train simulation engine for Indian Railways DSS
Handles discrete-event simulation with position interpolation
"""

import simpy
import pandas as pd
import json
import numpy as np
from geopy.distance import geodesic
from typing import Dict, List, Tuple, Optional
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class TrainPosition:
    """Current position and status of a train"""
    train_id: str
    lat: float
    lon: float
    speed: float
    status: str  # 'running', 'dwelling', 'delayed', 'completed'
    current_segment: str
    next_station: str
    delay: float  # minutes
    track_type: str  # 'main', 'siding', 'secondary'

@dataclass
class Disruption:
    """Represents a disruption event"""
    train_id: str
    segment: str
    delay_minutes: float
    timestamp: float
    reason: str

class TrackSegment:
    """Represents a track segment with coordinates and properties"""
    def __init__(self, name: str, coordinates: List[Tuple[float, float]], 
                 track_type: str, capacity: int, segment: str):
        self.name = name
        self.coordinates = coordinates
        self.track_type = track_type
        self.capacity = capacity
        self.segment = segment
        self.length_km = self._calculate_length()
        
    def _calculate_length(self) -> float:
        """Calculate segment length in kilometers"""
        total_length = 0
        for i in range(1, len(self.coordinates)):
            total_length += geodesic(self.coordinates[i-1], self.coordinates[i]).kilometers
        return total_length
    
    def interpolate_position(self, progress: float) -> Tuple[float, float]:
        """Get lat/lon at progress (0.0 to 1.0) along segment"""
        if progress <= 0:
            return self.coordinates[0]
        if progress >= 1:
            return self.coordinates[-1]
            
        # Find which segment we're in
        total_length = self.length_km
        target_distance = progress * total_length
        current_distance = 0
        
        for i in range(1, len(self.coordinates)):
            segment_length = geodesic(self.coordinates[i-1], self.coordinates[i]).kilometers
            if current_distance + segment_length >= target_distance:
                # Interpolate within this segment
                segment_progress = (target_distance - current_distance) / segment_length
                lat1, lon1 = self.coordinates[i-1]
                lat2, lon2 = self.coordinates[i]
                
                lat = lat1 + (lat2 - lat1) * segment_progress
                lon = lon1 + (lon2 - lon1) * segment_progress
                return (lat, lon)
            
            current_distance += segment_length
        
        return self.coordinates[-1]

class Train:
    """Represents a train with its schedule and current state"""
    def __init__(self, train_id: str, schedule: Dict, env: simpy.Environment):
        self.train_id = train_id
        self.env = env
        self.dep_time = schedule['dep_time']
        self.arr_time = schedule['arr_time']
        self.speed_kmh = schedule['speed_kmh']
        self.stops = eval(schedule['stops']) if isinstance(schedule['stops'], str) else schedule['stops']
        self.thru_dest = schedule.get('thru_dest')
        self.priority = schedule['priority']
        self.train_type = schedule['train_type']
        
        # Current state
        self.current_position = TrainPosition(
            train_id=train_id,
            lat=0, lon=0, speed=0,
            status='waiting',
            current_segment='',
            next_station=self.stops[0] if self.stops else '',
            delay=0,
            track_type='main'
        )
        
        self.disruptions = []
        self.route_segments = []
        self.current_segment_idx = 0
        self.segment_progress = 0.0
        self.stop_index = 0
        
    def add_disruption(self, disruption: Disruption):
        """Add a disruption to this train"""
        self.disruptions.append(disruption)
        self.current_position.delay += disruption.delay_minutes
        logger.info(f"Train {self.train_id} disrupted: +{disruption.delay_minutes}min delay")

class SimulationEngine:
    """Main simulation engine using SimPy"""
    
    def __init__(self, schedules_file: str, geo_file: str):
        self.env = simpy.Environment()
        self.trains = {}
        self.track_segments = {}
        self.stations = {}
        self.train_positions = {}
        self.disruptions = []
        self.running = False
        
        # Load data
        self._load_schedules(schedules_file)
        self._load_geometry(geo_file)
        self._setup_routes()
        
        # Statistics
        self.stats = {
            'total_trains': len(self.trains),
            'on_time': 0,
            'delayed': 0,
            'avg_delay': 0,
            'throughput': 0
        }
        
    def _load_schedules(self, file_path: str):
        """Load train schedules from CSV"""
        df = pd.read_csv(file_path)
        for _, row in df.iterrows():
            train = Train(row['train_id'], row.to_dict(), self.env)
            self.trains[row['train_id']] = train
            
    def _load_geometry(self, file_path: str):
        """Load track geometry from GeoJSON"""
        with open(file_path, 'r') as f:
            geo_data = json.load(f)
            
        for feature in geo_data['features']:
            props = feature['properties']
            geom = feature['geometry']
            
            if geom['type'] == 'LineString':
                # Track segment
                coords = [(lon, lat) for lon, lat in geom['coordinates']]
                segment = TrackSegment(
                    name=props['name'],
                    coordinates=coords,
                    track_type=props['track_type'],
                    capacity=props['capacity'],
                    segment=props['segment']
                )
                self.track_segments[props['name']] = segment
                
            elif geom['type'] == 'Point':
                # Station
                lon, lat = geom['coordinates']
                self.stations[props['station_code']] = {
                    'name': props['name'],
                    'code': props['station_code'],
                    'lat': lat,
                    'lon': lon,
                    'platforms': props.get('platforms', 2),
                    'major': props.get('major', False)
                }
    
    def _setup_routes(self):
        """Setup route segments for each train based on stops"""
        segment_mapping = {
            ('SBC', 'Kengeri'): ['SBC-Kengeri Main Line'],
            ('SBC', 'Bangarpet'): ['SBC-Kengeri Main Line'],
            ('Kengeri', 'Mandya'): ['Kengeri-Mandya Main Line'],
            ('Mandya', 'MYS'): ['Mandya-MYS Main Line']
        }
        
        for train in self.trains.values():
            route_segments = []
            
            # Determine route based on stops
            stops = train.stops
            for i in range(len(stops) - 1):
                start_station = stops[i]
                end_station = stops[i + 1]
                
                # Find appropriate segments
                if start_station == 'SBC' and end_station in ['Kengeri', 'Bangarpet', 'Mandya', 'MYS']:
                    route_segments.append('SBC-Kengeri Main Line')
                    
                if 'Kengeri' in stops and 'Mandya' in stops:
                    route_segments.append('Kengeri-Mandya Main Line')
                    
                if 'Mandya' in stops and 'MYS' in stops:
                    route_segments.append('Mandya-MYS Main Line')
            
            # Remove duplicates while preserving order
            seen = set()
            train.route_segments = [x for x in route_segments if not (x in seen or seen.add(x))]
            
    def train_process(self, train: Train):
        """SimPy process for individual train movement"""
        # Wait for departure time
        yield self.env.timeout(train.dep_time)
        
        train.current_position.status = 'running'
        logger.info(f"Train {train.train_id} departed at {train.dep_time}")
        
        # Move through each segment
        for segment_name in train.route_segments:
            if segment_name not in self.track_segments:
                continue
                
            segment = self.track_segments[segment_name]
            train.current_position.current_segment = segment_name
            train.current_position.track_type = segment.track_type
            
            # Calculate time to traverse segment
            travel_time_hours = segment.length_km / train.speed_kmh
            travel_time_minutes = travel_time_hours * 60
            
            # Apply any disruptions
            total_delay = sum(d.delay_minutes for d in train.disruptions 
                            if d.segment == segment.segment)
            travel_time_minutes += total_delay
            
            # Move through segment with position updates
            steps = max(10, int(travel_time_minutes))  # At least 10 steps
            step_time = travel_time_minutes / steps
            
            for step in range(steps):
                progress = step / steps
                lat, lon = segment.interpolate_position(progress)
                
                train.current_position.lat = lat
                train.current_position.lon = lon
                train.current_position.speed = train.speed_kmh
                train.segment_progress = progress
                
                # Update global position tracking
                self.train_positions[train.train_id] = train.current_position
                
                yield self.env.timeout(step_time)
            
            # Check for station stops
            segment_end_stations = self._get_segment_end_stations(segment_name)
            for station_code in segment_end_stations:
                if station_code in train.stops:
                    # Dwell at station
                    train.current_position.status = 'dwelling'
                    dwell_time = 2 if station_code in ['SBC', 'MYS'] else 1  # minutes
                    
                    logger.info(f"Train {train.train_id} dwelling at {station_code}")
                    yield self.env.timeout(dwell_time)
                    
                    train.current_position.status = 'running'
        
        # Journey complete
        train.current_position.status = 'completed'
        logger.info(f"Train {train.train_id} completed journey at {self.env.now}")
        
        # Handle through trains
        if train.thru_dest:
            train.current_position.status = 'through'
            # Continue beyond MYS (simplified)
            yield self.env.timeout(60)  # 1 hour buffer
    
    def _get_segment_end_stations(self, segment_name: str) -> List[str]:
        """Get stations at the end of a segment"""
        mapping = {
            'SBC-Kengeri Main Line': ['KGI'],
            'Kengeri-Mandya Main Line': ['MYA'],
            'Mandya-MYS Main Line': ['MYS']
        }
        return mapping.get(segment_name, [])
    
    def add_disruption(self, train_id: str, segment: str, delay_minutes: float, reason: str = ""):
        """Add a disruption to a specific train"""
        if train_id in self.trains:
            disruption = Disruption(
                train_id=train_id,
                segment=segment,
                delay_minutes=delay_minutes,
                timestamp=self.env.now,
                reason=reason
            )
            self.trains[train_id].add_disruption(disruption)
            self.disruptions.append(disruption)
            return True
        return False
    
    def add_special_train(self, train_data: Dict):
        """Add a special train to the simulation"""
        train = Train(train_data['train_id'], train_data, self.env)
        self.trains[train_data['train_id']] = train
        
        # Setup route for new train
        self._setup_routes()
        
        # Start the train process
        self.env.process(self.train_process(train))
        
        logger.info(f"Special train {train_data['train_id']} added")
    
    def start_simulation(self):
        """Start the simulation"""
        self.running = True
        
        # Start all train processes
        for train in self.trains.values():
            self.env.process(self.train_process(train))
        
        logger.info(f"Simulation started with {len(self.trains)} trains")
    
    def step(self, duration: float = 1.0):
        """Advance simulation by duration (minutes)"""
        if self.running:
            self.env.run(until=self.env.now + duration)
            self._update_stats()
    
    def _update_stats(self):
        """Update simulation statistics"""
        completed_trains = [t for t in self.trains.values() 
                          if t.current_position.status == 'completed']
        
        if completed_trains:
            delays = [t.current_position.delay for t in completed_trains]
            self.stats['avg_delay'] = np.mean(delays)
            self.stats['on_time'] = len([d for d in delays if d <= 5])
            self.stats['delayed'] = len([d for d in delays if d > 5])
        
        # Throughput (trains per hour)
        active_trains = len([t for t in self.trains.values() 
                           if t.current_position.status in ['running', 'dwelling']])
        self.stats['throughput'] = active_trains
    
    def get_positions(self) -> Dict[str, TrainPosition]:
        """Get current positions of all trains"""
        return self.train_positions.copy()
    
    def get_stats(self) -> Dict:
        """Get current simulation statistics"""
        return self.stats.copy()
    
    def reset(self):
        """Reset simulation to initial state"""
        self.env = simpy.Environment()
        self.train_positions.clear()
        self.disruptions.clear()
        self.running = False
        
        # Reset all trains
        for train in self.trains.values():
            train.current_position.status = 'waiting'
            train.current_position.delay = 0
            train.disruptions.clear()
            train.current_segment_idx = 0
            train.segment_progress = 0.0
        
        logger.info("Simulation reset")

# Example usage and testing
if __name__ == "__main__":
    # Test the simulation engine
    sim = SimulationEngine('../data/sbc_mys_schedules.csv', '../data/sbc_mys_geo.json')
    
    print(f"Loaded {len(sim.trains)} trains")
    print(f"Loaded {len(sim.track_segments)} track segments")
    print(f"Loaded {len(sim.stations)} stations")
    
    # Start simulation
    sim.start_simulation()
    
    # Run for a few steps
    for i in range(10):
        sim.step(5)  # 5-minute steps
        positions = sim.get_positions()
        stats = sim.get_stats()
        
        print(f"Step {i+1}: {len(positions)} trains active")
        for train_id, pos in positions.items():
            print(f"  {train_id}: {pos.status} at ({pos.lat:.4f}, {pos.lon:.4f})")
