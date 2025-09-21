"""
MILP-based train rescheduling optimizer for Indian Railways DSS
Based on Törnquist & Persson (2007) with rerouting and stop preservation
"""

import pulp
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional, Set
import logging
from dataclasses import dataclass
from itertools import combinations

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class Event:
    """Represents a train-segment event"""
    train_id: str
    segment: str
    event_type: str  # 'arrival', 'departure'
    scheduled_time: float
    station: Optional[str] = None
    mandatory_stop: bool = False

@dataclass
class OptimizationResult:
    """Results from MILP optimization"""
    success: bool
    objective_value: float
    new_schedule: Dict[str, List[Event]]
    rerouted_trains: Set[str]
    total_delay: float
    solve_time: float
    message: str

class MILPOptimizer:
    """MILP-based train rescheduling optimizer"""
    
    def __init__(self, track_data: Dict, station_data: Dict):
        self.track_data = track_data
        self.station_data = station_data
        self.segments = self._extract_segments()
        self.tracks_per_segment = self._get_track_capacities()
        
        # Optimization parameters
        self.headway_minutes = 5  # Minimum headway between trains
        self.max_delay_minutes = 120  # Maximum allowable delay
        self.reroute_penalty = 50  # Penalty for using alternative routes
        self.delay_penalty = 1  # Penalty per minute of delay
        self.max_order_swaps = 3  # Limit order changes for speed
        
    def _extract_segments(self) -> List[str]:
        """Extract unique segments from track data"""
        segments = set()
        for track_name, track_info in self.track_data.items():
            if 'segment' in track_info:
                segments.add(track_info['segment'])
        return list(segments)
    
    def _get_track_capacities(self) -> Dict[str, int]:
        """Get track capacity for each segment"""
        capacities = {}
        for segment in self.segments:
            # Sum capacities of all tracks in segment
            total_capacity = 0
            for track_name, track_info in self.track_data.items():
                if track_info.get('segment') == segment:
                    total_capacity += track_info.get('capacity', 1)
            capacities[segment] = max(1, total_capacity)
        return capacities
    
    def _create_events(self, trains: Dict) -> List[Event]:
        """Create events from train schedules"""
        events = []
        
        # Segment travel times (estimated)
        segment_times = {
            'SBC-Kengeri': 45,  # minutes
            'Kengeri-Mandya': 35,
            'Mandya-MYS': 20
        }
        
        for train_id, train in trains.items():
            current_time = train.dep_time
            stops = train.stops if hasattr(train, 'stops') else []
            
            # Create events for each segment
            for i, segment in enumerate(self.segments):
                # Arrival event
                arrival_event = Event(
                    train_id=train_id,
                    segment=segment,
                    event_type='arrival',
                    scheduled_time=current_time,
                    mandatory_stop=self._is_mandatory_stop(train_id, segment, stops)
                )
                events.append(arrival_event)
                
                # Add travel time
                travel_time = segment_times.get(segment, 30)
                current_time += travel_time
                
                # Departure event
                departure_event = Event(
                    train_id=train_id,
                    segment=segment,
                    event_type='departure',
                    scheduled_time=current_time,
                    mandatory_stop=self._is_mandatory_stop(train_id, segment, stops)
                )
                events.append(departure_event)
                
                # Add dwell time if stopping
                if self._is_mandatory_stop(train_id, segment, stops):
                    current_time += 2  # 2 minutes dwell time
        
        return sorted(events, key=lambda e: e.scheduled_time)
    
    def _is_mandatory_stop(self, train_id: str, segment: str, stops: List[str]) -> bool:
        """Check if train must stop in this segment"""
        segment_stations = {
            'SBC-Kengeri': ['SBC', 'Bangarpet', 'Kengeri'],
            'Kengeri-Mandya': ['Kengeri', 'Channapatna', 'Mandya'],
            'Mandya-MYS': ['Mandya', 'MYS']
        }
        
        stations_in_segment = segment_stations.get(segment, [])
        return any(station in stops for station in stations_in_segment)
    
    def optimize(self, trains: Dict, disruptions: List = None) -> OptimizationResult:
        """Main optimization function using MILP"""
        import time
        start_time = time.time()
        
        try:
            # Create events
            events = self._create_events(trains)
            logger.info(f"Created {len(events)} events for optimization")
            
            # Create MILP problem
            prob = pulp.LpProblem("TrainRescheduling", pulp.LpMinimize)
            
            # Decision variables
            variables = self._create_variables(events, trains)
            
            # Objective function
            objective = self._create_objective(events, variables, disruptions)
            prob += objective
            
            # Constraints
            self._add_constraints(prob, events, variables, trains, disruptions)
            
            # Solve
            solver = pulp.PULP_CBC_CMD(msg=0, timeLimit=30)
            prob.solve(solver)
            
            solve_time = time.time() - start_time
            
            if prob.status == pulp.LpStatusOptimal:
                result = self._extract_solution(prob, events, variables, trains)
                result.solve_time = solve_time
                result.success = True
                result.message = "Optimal solution found"
                logger.info(f"Optimization completed in {solve_time:.2f}s")
                return result
            else:
                return OptimizationResult(
                    success=False,
                    objective_value=float('inf'),
                    new_schedule={},
                    rerouted_trains=set(),
                    total_delay=0,
                    solve_time=solve_time,
                    message=f"Optimization failed: {pulp.LpStatus[prob.status]}"
                )
                
        except Exception as e:
            logger.error(f"Optimization error: {str(e)}")
            return OptimizationResult(
                success=False,
                objective_value=float('inf'),
                new_schedule={},
                rerouted_trains=set(),
                total_delay=0,
                solve_time=time.time() - start_time,
                message=f"Error: {str(e)}"
            )
    
    def _create_variables(self, events: List[Event], trains: Dict) -> Dict:
        """Create decision variables for MILP"""
        variables = {}
        
        # Time variables: t_k for each event k
        variables['times'] = {}
        for i, event in enumerate(events):
            var_name = f"t_{event.train_id}_{event.segment}_{event.event_type}_{i}"
            variables['times'][i] = pulp.LpVariable(
                var_name, 
                lowBound=event.scheduled_time,
                upBound=event.scheduled_time + self.max_delay_minutes,
                cat='Continuous'
            )
        
        # Order variables: x_kl binary for event precedence
        variables['order'] = {}
        for i in range(len(events)):
            for j in range(i + 1, len(events)):
                if events[i].segment == events[j].segment:
                    var_name = f"x_{i}_{j}"
                    variables['order'][(i, j)] = pulp.LpVariable(var_name, cat='Binary')
        
        # Track assignment variables: y_kt for event k on track t
        variables['tracks'] = {}
        for i, event in enumerate(events):
            segment = event.segment
            num_tracks = self.tracks_per_segment.get(segment, 1)
            for track in range(num_tracks):
                var_name = f"y_{i}_{track}"
                variables['tracks'][(i, track)] = pulp.LpVariable(var_name, cat='Binary')
        
        # Rerouting variables: r_kk' for using alternative route
        variables['reroutes'] = {}
        available_routes = self._get_alternative_routes()
        
        for i, event in enumerate(events):
            train_id = event.train_id
            segment = event.segment
            
            if segment in available_routes:
                for alt_route in available_routes[segment]:
                    var_name = f"r_{i}_{alt_route}"
                    variables['reroutes'][(i, alt_route)] = pulp.LpVariable(var_name, cat='Binary')
        
        return variables
    
    def _get_alternative_routes(self) -> Dict[str, List[str]]:
        """Get alternative routes for each segment"""
        alternatives = {}
        
        # Group tracks by segment
        segment_tracks = {}
        for track_name, track_info in self.track_data.items():
            segment = track_info.get('segment', '')
            if segment not in segment_tracks:
                segment_tracks[segment] = []
            segment_tracks[segment].append(track_name)
        
        # Find alternatives (non-main tracks)
        for segment, tracks in segment_tracks.items():
            alternatives[segment] = [
                track for track in tracks 
                if 'siding' in track.lower() or 'secondary' in track.lower()
            ]
        
        return alternatives
    
    def _create_objective(self, events: List[Event], variables: Dict, disruptions: List) -> pulp.LpAffineExpression:
        """Create objective function: minimize total delay + rerouting costs"""
        objective = 0
        
        # Delay costs
        for i, event in enumerate(events):
            delay = variables['times'][i] - event.scheduled_time
            objective += self.delay_penalty * delay
        
        # Rerouting costs
        for (event_idx, alt_route), var in variables['reroutes'].items():
            objective += self.reroute_penalty * var
        
        return objective
    
    def _add_constraints(self, prob: pulp.LpProblem, events: List[Event], 
                        variables: Dict, trains: Dict, disruptions: List):
        """Add constraints to MILP problem"""
        
        # 1. Headway constraints
        self._add_headway_constraints(prob, events, variables)
        
        # 2. Track capacity constraints
        self._add_capacity_constraints(prob, events, variables)
        
        # 3. Mandatory stop constraints (preserve stops)
        self._add_stop_preservation_constraints(prob, events, variables, trains)
        
        # 4. Precedence constraints
        self._add_precedence_constraints(prob, events, variables)
        
        # 5. Rerouting constraints
        self._add_rerouting_constraints(prob, events, variables)
        
        # 6. Disruption constraints
        if disruptions:
            self._add_disruption_constraints(prob, events, variables, disruptions)
    
    def _add_headway_constraints(self, prob: pulp.LpProblem, events: List[Event], variables: Dict):
        """Add minimum headway constraints between trains"""
        for i in range(len(events)):
            for j in range(i + 1, len(events)):
                if events[i].segment == events[j].segment:
                    # If train i precedes train j
                    if (i, j) in variables['order']:
                        prob += (variables['times'][j] - variables['times'][i] >= 
                                self.headway_minutes * variables['order'][(i, j)])
                        
                        # If train j precedes train i
                        prob += (variables['times'][i] - variables['times'][j] >= 
                                self.headway_minutes * (1 - variables['order'][(i, j)]))
    
    def _add_capacity_constraints(self, prob: pulp.LpProblem, events: List[Event], variables: Dict):
        """Add track capacity constraints"""
        for i, event in enumerate(events):
            segment = event.segment
            num_tracks = self.tracks_per_segment.get(segment, 1)
            
            # Each event must be assigned to exactly one track
            track_sum = 0
            for track in range(num_tracks):
                if (i, track) in variables['tracks']:
                    track_sum += variables['tracks'][(i, track)]
            
            if track_sum != 0:  # Only add constraint if variables exist
                prob += track_sum == 1
    
    def _add_stop_preservation_constraints(self, prob: pulp.LpProblem, events: List[Event], 
                                         variables: Dict, trains: Dict):
        """Add constraints to preserve mandatory stops"""
        for i, event in enumerate(events):
            if event.mandatory_stop:
                # Mandatory stops cannot be rerouted to bypass routes
                for alt_route_key in variables['reroutes']:
                    if alt_route_key[0] == i:  # This event
                        alt_route = alt_route_key[1]
                        # Only allow rerouting if it preserves the stop
                        if not self._route_preserves_stop(alt_route, event):
                            prob += variables['reroutes'][alt_route_key] == 0
    
    def _route_preserves_stop(self, route_name: str, event: Event) -> bool:
        """Check if alternative route preserves the mandatory stop"""
        # Simplified logic - in practice, would check actual route geometry
        if event.mandatory_stop:
            # Sidings typically preserve stops, bypass routes don't
            return 'siding' in route_name.lower()
        return True
    
    def _add_precedence_constraints(self, prob: pulp.LpProblem, events: List[Event], variables: Dict):
        """Add train precedence constraints"""
        # Limit the number of order changes to improve solve time
        order_changes = 0
        for (i, j), var in variables['order'].items():
            # If originally i < j, then changing order incurs a penalty
            order_changes += var
        
        prob += order_changes <= self.max_order_swaps
    
    def _add_rerouting_constraints(self, prob: pulp.LpProblem, events: List[Event], variables: Dict):
        """Add rerouting logic constraints"""
        for i, event in enumerate(events):
            # Each event can use at most one alternative route
            reroute_sum = 0
            for alt_route_key in variables['reroutes']:
                if alt_route_key[0] == i:
                    reroute_sum += variables['reroutes'][alt_route_key]
            
            if reroute_sum != 0:
                prob += reroute_sum <= 1
    
    def _add_disruption_constraints(self, prob: pulp.LpProblem, events: List[Event], 
                                  variables: Dict, disruptions: List):
        """Add constraints for disruptions"""
        for disruption in disruptions:
            # Find events affected by this disruption
            for i, event in enumerate(events):
                if (event.train_id == disruption.train_id and 
                    event.segment == disruption.segment):
                    # Add minimum delay
                    prob += (variables['times'][i] >= 
                            event.scheduled_time + disruption.delay_minutes)
    
    def _extract_solution(self, prob: pulp.LpProblem, events: List[Event], 
                         variables: Dict, trains: Dict) -> OptimizationResult:
        """Extract solution from solved MILP"""
        new_schedule = {}
        rerouted_trains = set()
        total_delay = 0
        
        # Extract new event times
        for i, event in enumerate(events):
            if event.train_id not in new_schedule:
                new_schedule[event.train_id] = []
            
            new_time = variables['times'][i].varValue
            delay = new_time - event.scheduled_time
            total_delay += delay
            
            # Update event with new time
            new_event = Event(
                train_id=event.train_id,
                segment=event.segment,
                event_type=event.event_type,
                scheduled_time=new_time,
                station=event.station,
                mandatory_stop=event.mandatory_stop
            )
            new_schedule[event.train_id].append(new_event)
        
        # Check for rerouted trains
        for (event_idx, alt_route), var in variables['reroutes'].items():
            if var.varValue and var.varValue > 0.5:
                event = events[event_idx]
                rerouted_trains.add(event.train_id)
        
        return OptimizationResult(
            success=True,
            objective_value=pulp.value(prob.objective),
            new_schedule=new_schedule,
            rerouted_trains=rerouted_trains,
            total_delay=total_delay,
            solve_time=0,  # Will be set by caller
            message="Optimization successful"
        )
    
    def create_what_if_scenario(self, base_trains: Dict, special_train: Dict) -> Dict:
        """Create what-if scenario with additional special train"""
        scenario_trains = base_trains.copy()
        scenario_trains[special_train['train_id']] = special_train
        
        # Re-optimize with the new train
        result = self.optimize(scenario_trains)
        
        return {
            'scenario_trains': scenario_trains,
            'optimization_result': result,
            'impact': {
                'additional_delay': result.total_delay,
                'affected_trains': len(result.rerouted_trains),
                'feasible': result.success
            }
        }

# Example usage and testing
if __name__ == "__main__":
    # Mock data for testing
    track_data = {
        'SBC-Kengeri Main Line': {'segment': 'SBC-Kengeri', 'capacity': 1, 'track_type': 'main'},
        'SBC-Kengeri Siding': {'segment': 'SBC-Kengeri', 'capacity': 1, 'track_type': 'siding'},
        'Kengeri-Mandya Main Line': {'segment': 'Kengeri-Mandya', 'capacity': 2, 'track_type': 'main'},
        'Mandya-MYS Main Line': {'segment': 'Mandya-MYS', 'capacity': 1, 'track_type': 'main'}
    }
    
    station_data = {
        'SBC': {'name': 'Bangalore City Junction'},
        'Kengeri': {'name': 'Kengeri'},
        'Mandya': {'name': 'Mandya Junction'},
        'MYS': {'name': 'Mysuru Junction'}
    }
    
    # Mock trains
    trains = {
        '12614': type('Train', (), {
            'dep_time': 0, 'arr_time': 180, 'stops': ['SBC', 'Kengeri', 'Mandya', 'MYS']
        })(),
        '12615': type('Train', (), {
            'dep_time': 15, 'arr_time': 195, 'stops': ['SBC', 'Kengeri', 'Mandya', 'MYS']
        })()
    }
    
    optimizer = MILPOptimizer(track_data, station_data)
    
    # Test optimization
    result = optimizer.optimize(trains)
    print(f"Optimization result: {result.success}")
    print(f"Total delay: {result.total_delay:.1f} minutes")
    print(f"Rerouted trains: {result.rerouted_trains}")
    print(f"Solve time: {result.solve_time:.2f} seconds")
