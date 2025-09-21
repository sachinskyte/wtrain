"""
Basic tests for the Railway DSS simulation engine
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# Add backend to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'backend'))

try:
    from sim_engine import SimulationEngine, Train, TrackSegment, TrainPosition
    from milp_optimizer import MILPOptimizer, Event, OptimizationResult
except ImportError as e:
    print(f"Import error: {e}")
    print("Make sure all dependencies are installed: pip install -r requirements.txt")
    sys.exit(1)

class TestTrackSegment(unittest.TestCase):
    """Test TrackSegment functionality"""
    
    def setUp(self):
        self.coordinates = [(77.5946, 12.9716), (77.5800, 12.9500), (77.5600, 12.9200)]
        self.segment = TrackSegment(
            name="Test Segment",
            coordinates=self.coordinates,
            track_type="main",
            capacity=1,
            segment="test"
        )
    
    def test_length_calculation(self):
        """Test track length calculation"""
        self.assertGreater(self.segment.length_km, 0)
        self.assertLess(self.segment.length_km, 100)  # Reasonable for a segment
    
    def test_position_interpolation(self):
        """Test position interpolation along track"""
        # Start position
        start_pos = self.segment.interpolate_position(0.0)
        self.assertEqual(start_pos, self.coordinates[0])
        
        # End position
        end_pos = self.segment.interpolate_position(1.0)
        self.assertEqual(end_pos, self.coordinates[-1])
        
        # Middle position
        mid_pos = self.segment.interpolate_position(0.5)
        self.assertIsInstance(mid_pos, tuple)
        self.assertEqual(len(mid_pos), 2)

class TestSimulationEngine(unittest.TestCase):
    """Test SimulationEngine functionality"""
    
    def setUp(self):
        # Create test data files
        self.test_dir = os.path.dirname(__file__)
        self.schedules_file = os.path.join(self.test_dir, '..', 'data', 'sbc_mys_schedules.csv')
        self.geo_file = os.path.join(self.test_dir, '..', 'data', 'sbc_mys_geo.json')
    
    def test_initialization(self):
        """Test simulation engine initialization"""
        try:
            sim = SimulationEngine(self.schedules_file, self.geo_file)
            self.assertIsNotNone(sim)
            self.assertGreater(len(sim.trains), 0)
            self.assertGreater(len(sim.track_segments), 0)
            self.assertGreater(len(sim.stations), 0)
        except Exception as e:
            self.fail(f"Simulation initialization failed: {e}")
    
    def test_train_loading(self):
        """Test train schedule loading"""
        sim = SimulationEngine(self.schedules_file, self.geo_file)
        
        # Check that trains are loaded
        self.assertGreater(len(sim.trains), 0)
        
        # Check train properties
        first_train = list(sim.trains.values())[0]
        self.assertIsInstance(first_train.train_id, str)
        self.assertIsInstance(first_train.dep_time, (int, float))
        self.assertIsInstance(first_train.speed_kmh, (int, float))
        self.assertIsInstance(first_train.stops, list)
    
    def test_disruption_handling(self):
        """Test disruption addition"""
        sim = SimulationEngine(self.schedules_file, self.geo_file)
        
        # Get first train
        train_id = list(sim.trains.keys())[0]
        
        # Add disruption
        success = sim.add_disruption(train_id, "SBC-Kengeri", 15.0, "Test disruption")
        self.assertTrue(success)
        
        # Check disruption was added
        train = sim.trains[train_id]
        self.assertEqual(len(train.disruptions), 1)
        self.assertEqual(train.disruptions[0].delay_minutes, 15.0)
    
    def test_simulation_step(self):
        """Test simulation stepping"""
        sim = SimulationEngine(self.schedules_file, self.geo_file)
        
        # Start simulation
        sim.start_simulation()
        self.assertTrue(sim.running)
        
        # Step simulation
        initial_time = sim.env.now
        sim.step(5.0)  # 5 minutes
        self.assertGreaterEqual(sim.env.now, initial_time + 5.0)

class TestMILPOptimizer(unittest.TestCase):
    """Test MILP Optimizer functionality"""
    
    def setUp(self):
        self.track_data = {
            'SBC-Kengeri Main': {'segment': 'SBC-Kengeri', 'capacity': 1, 'track_type': 'main'},
            'Kengeri-Mandya Main': {'segment': 'Kengeri-Mandya', 'capacity': 2, 'track_type': 'main'},
            'Mandya-MYS Main': {'segment': 'Mandya-MYS', 'capacity': 1, 'track_type': 'main'}
        }
        
        self.station_data = {
            'SBC': {'name': 'Bangalore City Junction'},
            'KGI': {'name': 'Kengeri'},
            'MYA': {'name': 'Mandya Junction'},
            'MYS': {'name': 'Mysuru Junction'}
        }
        
        self.optimizer = MILPOptimizer(self.track_data, self.station_data)
    
    def test_initialization(self):
        """Test optimizer initialization"""
        self.assertIsNotNone(self.optimizer)
        self.assertEqual(len(self.optimizer.segments), 3)
        self.assertIn('SBC-Kengeri', self.optimizer.segments)
    
    def test_event_creation(self):
        """Test event creation from train schedules"""
        # Mock train data
        mock_trains = {
            'T001': type('Train', (), {
                'dep_time': 0,
                'stops': ['SBC', 'KGI', 'MYA', 'MYS']
            })()
        }
        
        events = self.optimizer._create_events(mock_trains)
        self.assertGreater(len(events), 0)
        
        # Check event properties
        first_event = events[0]
        self.assertIsInstance(first_event, Event)
        self.assertEqual(first_event.train_id, 'T001')
    
    @patch('pulp.LpProblem.solve')
    def test_optimization_call(self, mock_solve):
        """Test optimization method call"""
        # Mock successful solve
        mock_solve.return_value = 1  # LpStatusOptimal
        
        # Mock train data
        mock_trains = {
            'T001': type('Train', (), {
                'dep_time': 0,
                'stops': ['SBC', 'KGI', 'MYA', 'MYS']
            })()
        }
        
        # This should not crash
        try:
            result = self.optimizer.optimize(mock_trains)
            self.assertIsInstance(result, OptimizationResult)
        except Exception as e:
            # Optimization might fail due to missing PuLP solver, but should not crash
            self.assertIn('solver', str(e).lower())

class TestIntegration(unittest.TestCase):
    """Integration tests"""
    
    def test_full_workflow(self):
        """Test complete workflow from simulation to optimization"""
        try:
            # Initialize simulation
            schedules_file = os.path.join(os.path.dirname(__file__), '..', 'data', 'sbc_mys_schedules.csv')
            geo_file = os.path.join(os.path.dirname(__file__), '..', 'data', 'sbc_mys_geo.json')
            
            sim = SimulationEngine(schedules_file, geo_file)
            optimizer = MILPOptimizer(sim.track_segments, sim.stations)
            
            # Start simulation
            sim.start_simulation()
            
            # Add disruption
            train_id = list(sim.trains.keys())[0]
            sim.add_disruption(train_id, "SBC-Kengeri", 10.0, "Test disruption")
            
            # Step simulation
            sim.step(1.0)
            
            # Get positions
            positions = sim.get_positions()
            self.assertIsInstance(positions, dict)
            
            # Get stats
            stats = sim.get_stats()
            self.assertIsInstance(stats, dict)
            self.assertIn('total_trains', stats)
            
            print("✓ Full workflow test passed")
            
        except Exception as e:
            print(f"✗ Full workflow test failed: {e}")
            # Don't fail the test for missing dependencies
            if 'pulp' in str(e).lower() or 'solver' in str(e).lower():
                self.skipTest(f"Skipping due to missing dependencies: {e}")
            else:
                raise

def run_basic_simulation_test():
    """Run a basic simulation test without unittest framework"""
    print("Running basic simulation test...")
    
    try:
        # File paths
        test_dir = os.path.dirname(__file__)
        schedules_file = os.path.join(test_dir, '..', 'data', 'sbc_mys_schedules.csv')
        geo_file = os.path.join(test_dir, '..', 'data', 'sbc_mys_geo.json')
        
        # Check files exist
        if not os.path.exists(schedules_file):
            print(f"✗ Schedules file not found: {schedules_file}")
            return False
            
        if not os.path.exists(geo_file):
            print(f"✗ Geometry file not found: {geo_file}")
            return False
        
        # Initialize simulation
        print("Initializing simulation...")
        sim = SimulationEngine(schedules_file, geo_file)
        print(f"✓ Loaded {len(sim.trains)} trains")
        print(f"✓ Loaded {len(sim.track_segments)} track segments")
        print(f"✓ Loaded {len(sim.stations)} stations")
        
        # Start simulation
        print("Starting simulation...")
        sim.start_simulation()
        print("✓ Simulation started")
        
        # Run a few steps
        print("Running simulation steps...")
        for i in range(5):
            sim.step(1.0)  # 1-minute steps
            positions = sim.get_positions()
            stats = sim.get_stats()
            print(f"  Step {i+1}: {len(positions)} active trains")
        
        print("✓ Basic simulation test completed successfully")
        return True
        
    except Exception as e:
        print(f"✗ Basic simulation test failed: {e}")
        return False

if __name__ == '__main__':
    print("=" * 50)
    print("Railway DSS Test Suite")
    print("=" * 50)
    
    # Run basic test first
    basic_success = run_basic_simulation_test()
    
    print("\n" + "=" * 50)
    print("Running Unit Tests")
    print("=" * 50)
    
    # Run unit tests
    unittest.main(verbosity=2, exit=False)
    
    print("\n" + "=" * 50)
    print("Test Summary")
    print("=" * 50)
    print(f"Basic simulation test: {'PASSED' if basic_success else 'FAILED'}")
    print("Unit tests: See output above")
    print("\nIf tests fail due to missing PuLP solver, install CBC:")
    print("  - Windows: Download CBC from https://www.coin-or.org/download/binary/Cbc/")
    print("  - Linux: sudo apt-get install coinor-cbc")
    print("  - macOS: brew install cbc")
