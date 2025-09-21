#!/usr/bin/env python3
"""
Quick start script for Indian Railways DSS
Checks dependencies and starts the system
"""

import sys
import os
import subprocess
import webbrowser
import time

def check_dependencies():
    """Check if all required dependencies are available"""
    required_packages = [
        'flask', 'flask_socketio', 'simpy', 'pulp', 
        'pandas', 'numpy', 'geopy', 'shapely'
    ]
    
    missing = []
    for package in required_packages:
        try:
            __import__(package.replace('-', '_'))
            print(f"✓ {package}")
        except ImportError:
            missing.append(package)
            print(f"✗ {package}")
    
    if missing:
        print(f"\nMissing packages: {', '.join(missing)}")
        print("Install with: pip install -r requirements.txt")
        return False
    
    print("\n✓ All dependencies available!")
    return True

def check_data_files():
    """Check if data files exist"""
    data_dir = os.path.join(os.path.dirname(__file__), 'data')
    required_files = [
        'sbc_mys_schedules.csv',
        'sbc_mys_geo.json'
    ]
    
    for filename in required_files:
        filepath = os.path.join(data_dir, filename)
        if os.path.exists(filepath):
            print(f"✓ {filename}")
        else:
            print(f"✗ {filename}")
            return False
    
    print("✓ All data files present!")
    return True

def start_backend():
    """Start the Flask backend"""
    backend_dir = os.path.join(os.path.dirname(__file__), 'backend')
    app_file = os.path.join(backend_dir, 'app.py')
    
    if not os.path.exists(app_file):
        print("✗ Backend app.py not found!")
        return None
    
    print("Starting backend server...")
    try:
        # Start backend in subprocess
        process = subprocess.Popen([
            sys.executable, app_file
        ], cwd=backend_dir)
        
        # Give it time to start
        time.sleep(3)
        
        if process.poll() is None:  # Still running
            print("✓ Backend started successfully!")
            return process
        else:
            print("✗ Backend failed to start!")
            return None
            
    except Exception as e:
        print(f"✗ Error starting backend: {e}")
        return None

def open_frontend():
    """Open the frontend in browser"""
    frontend_file = os.path.join(os.path.dirname(__file__), 'frontend', 'index.html')
    
    if os.path.exists(frontend_file):
        print("Opening frontend in browser...")
        webbrowser.open(f'file://{os.path.abspath(frontend_file)}')
        print("✓ Frontend opened!")
        return True
    else:
        print("✗ Frontend index.html not found!")
        return False

def main():
    """Main startup function"""
    print("=" * 60)
    print("🚂 Indian Railways DSS - Quick Start")
    print("=" * 60)
    
    print("\n1. Checking dependencies...")
    if not check_dependencies():
        return 1
    
    print("\n2. Checking data files...")
    if not check_data_files():
        return 1
    
    print("\n3. Starting backend...")
    backend_process = start_backend()
    if not backend_process:
        return 1
    
    print("\n4. Opening frontend...")
    if not open_frontend():
        backend_process.terminate()
        return 1
    
    print("\n" + "=" * 60)
    print("🎉 System started successfully!")
    print("=" * 60)
    print("\nBackend running at: http://localhost:5000")
    print("Frontend opened in browser")
    print("\nTo use the system:")
    print("1. Click 'Start' to begin simulation")
    print("2. Watch trains move on the map")
    print("3. Try adding disruptions or special trains")
    print("4. Monitor KPIs in the control panel")
    print("\nPress Ctrl+C to stop the system")
    
    try:
        # Keep running until user stops
        backend_process.wait()
    except KeyboardInterrupt:
        print("\n\nStopping system...")
        backend_process.terminate()
        print("✓ System stopped!")
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
