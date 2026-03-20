#!/usr/bin/env python3
"""
Integration test for hybrid agent architecture.

Tests orchestrator functions against live drone simulation.
"""
import asyncio
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.orchestrator import (
    execute_navigation_sequence,
    execute_single_building_scan,
    Building,
    Point3D,
)
from backend.grpc.client import DroneGrpcClient


async def setup_drones():
    """Register drones for testing."""
    print("\n🔗 Registering drones...")
    print("=" * 60)
    
    client = DroneGrpcClient()
    
    # Register BEACON-01 and BEACON-02
    try:
        client.register("BEACON-01", "localhost", 50051)
        print("✅ BEACON-01 registered")
    except Exception as e:
        print(f"❌ BEACON-01 registration failed: {e}")
        return False
    
    try:
        client.register("BEACON-02", "localhost", 50052)
        print("✅ BEACON-02 registered")
    except Exception as e:
        print(f"❌ BEACON-02 registration failed: {e}")
        return False
    
    # Update the grpc client in services
    from backend.services.api.control import set_client
    set_client(client)
    
    return True


async def test_navigation():
    """Test navigation orchestrator with live drone."""
    print("\n🚁 Testing Navigation Orchestrator...")
    print("=" * 60)
    
    try:
        result = await execute_navigation_sequence(
            asset_id="BEACON-01",
            target_x=10.0,
            target_z=-5.0,
            target_y=None  # Auto-calculate
        )
        
        if result.success:
            print(f"✅ Navigation SUCCESS")
            print(f"   Final position: {result.final_position}")
            print(f"   Waypoints completed: {result.waypoints_completed}")
            print(f"   Route summary: {result.route_summary}")
            return True
        else:
            print(f"❌ Navigation FAILED")
            print(f"   Error: {result.error}")
            return False
    except Exception as e:
        print(f"❌ Navigation TEST ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_building_scan():
    """Test scan orchestrator with live drone."""
    print("\n🔍 Testing Scan Orchestrator...")
    print("=" * 60)
    
    try:
        building = Building(
            center_x=-15.0,
            center_z=-20.0,
            height=12.0
        )
        
        result = await execute_single_building_scan(
            asset_id="BEACON-02",
            building=building,
            scan_radius=8.0
        )
        
        if result.success:
            print(f"✅ Scan SUCCESS")
            print(f"   Building: ({building.center_x}, {building.center_z})")
            print(f"   Survivors detected: {result.survivors_detected}")
            print(f"   Battery remaining: {result.battery_remaining}%")
            print(f"   Summary: {result.scan_summary}")
            return True
        else:
            print(f"❌ Scan FAILED")
            print(f"   Error: {result.error}")
            return False
    except Exception as e:
        print(f"❌ Scan TEST ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all integration tests."""
    print("\n" + "=" * 60)
    print("🧪 HYBRID ARCHITECTURE INTEGRATION TESTS")
    print("=" * 60)
    
    # Setup: Uplink drones
    if not await setup_drones():
        print("\n❌ Setup failed. Cannot proceed with tests.")
        return 1
    
    print("\n✅ Setup complete. Starting tests...")
    
    results = []
    
    # Test 1: Navigation Orchestrator
    nav_result = await test_navigation()
    results.append(("Navigation Orchestrator", nav_result))
    
    await asyncio.sleep(2)  # Let drone settle
    
    # Test 2: Scan Orchestrator
    scan_result = await test_building_scan()
    results.append(("Scan Orchestrator", scan_result))
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 TEST SUMMARY")
    print("=" * 60)
    
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    total = len(results)
    passed = sum(1 for _, p in results if p)
    
    print(f"\nResults: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed! Hybrid architecture validated.")
        return 0
    else:
        print("\n⚠️  Some tests failed. Check output above.")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
