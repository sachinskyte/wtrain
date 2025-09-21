# Indian Railways Decision Support System (IR-DSS)
## Bangalore (SBC) to Mysuru (MYS) Section

A complete offline decision-support system for Indian Railways operations, featuring train simulation, MILP optimization, and interactive visualization.

## Features

- **Offline Simulation**: 10-15 trains with realistic movement interpolation
- **MILP Optimization**: Törnquist & Persson (2007) based rescheduling with PuLP
- **Interactive Visualization**: Leaflet-based map with real-time train positions
- **Disruption Management**: Manual disruption injection and what-if analysis
- **Rerouting**: Preserves station stops while optimizing intra-segment paths
- **KPIs Dashboard**: Punctuality, delays, throughput, and utilization metrics

## Quick Start

### Prerequisites
- Python 3.8+
- Modern web browser

### Installation & Run

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Start the backend:**
   ```bash
   cd backend
   python app.py
   ```

3. **Open the frontend:**
   - Open `frontend/index.html` in your browser
   - Or navigate to `http://localhost:5000` if using Flask's static serving

## System Architecture

### Backend (Python)
- **Flask Server**: REST API and WebSocket for real-time updates
- **SimPy Engine**: Discrete-event simulation with position interpolation
- **PuLP Optimizer**: MILP-based rescheduling with rerouting capabilities

### Frontend (JavaScript)
- **Leaflet Map**: Interactive visualization with offline tiles
- **Real-time Updates**: WebSocket-based train position updates
- **Control Panel**: Play/Pause, disruptions, special trains, manual overrides

### Data Structure
- **CSV Schedules**: Train timetables with stops and priorities
- **GeoJSON Tracks**: Railway infrastructure with main lines and sidings

## Usage

### Basic Simulation
1. Click **Start Simulation** to begin train movements
2. Use **Play/Pause** controls to manage simulation
3. Click on trains for detailed information

### Disruption Management
1. Click **Add Disruption** to inject delays
2. System automatically triggers MILP optimization
3. View rescheduled routes and preserved stops

### What-If Analysis
1. Use **Insert Special Train** for scenario testing
2. **Override Order** for manual precedence changes
3. Monitor KPIs in the dashboard

## Technical Details

### Simulation Engine
- Uses SimPy for discrete-event simulation
- Position interpolation every 1 second
- Handles through-trains with post-MYS buffer

### MILP Optimization
- Event-based model with train-segment pairs
- Variables for timing, ordering, track assignment, rerouting
- Constraints for headways (5min), capacities, mandatory stops
- Objective: minimize total delay + rerouting penalties

### Rerouting Logic
- Preserves mandatory stops (e.g., Mandya Junction)
- Optimizes only intra-segment paths
- Uses sidings when beneficial (>5min savings)

## File Structure

```
ir-dss/
├── README.md
├── requirements.txt
├── data/
│   ├── sbc_mys_schedules.csv    # Train schedules
│   └── sbc_mys_geo.json         # Track geometry
├── backend/
│   ├── app.py                   # Flask server
│   ├── sim_engine.py            # SimPy simulation
│   └── milp_optimizer.py        # PuLP optimization
├── frontend/
│   ├── index.html               # Main interface
│   └── map.js                   # Map controls
└── tests/
    └── test_sim.py              # Basic tests
```

## Sample Data

The system includes realistic sample data:
- **10 trains**: Mix of passenger (60%) and freight (40%)
- **5-7 segments**: SBC-Kengeri (single), Kengeri-Mandya (double), etc.
- **Track infrastructure**: Main lines plus 1-2 sidings per segment

## Performance

- **MILP solving**: <30 seconds for ~50-100 events
- **Simulation**: Real-time with 1-second position updates
- **Optimization scope**: Limited to 3 order swaps post-disruption for speed

## Development

### Adding New Features
1. Extend the MILP model in `milp_optimizer.py`
2. Update simulation logic in `sim_engine.py`
3. Add frontend controls in `map.js`

### Testing
```bash
cd tests
python test_sim.py
```

## License

Internal hackathon project - Educational use only
