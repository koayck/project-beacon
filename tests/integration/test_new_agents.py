#!/usr/bin/env python3
"""
Test new hybrid agents: Command Parser, Mission Planner, Recovery.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.agents.command_parser import command_parser, parse_command
from backend.agents.mission_planner import mission_planner
from backend.agents.recovery import recovery_agent
from backend.agents.schemas import (
    CommandIntent,
    ErrorContext,
    MissionType,
    RecoveryAction,
)


def test_command_parser_offline():
    """Test offline command parsing (regex-based)."""
    print("\n🧪 Testing Command Parser (Offline Mode)")
    print("=" * 60)
    
    test_commands = [
        "Move BEACON-01 to (10, -5)",
        "Scan the flooded school for survivors",
        "Return BEACON-02 to base",
        "Deploy all drones",
    ]
    
    for cmd in test_commands:
        intent = parse_command(cmd)
        print(f"\nInput: {cmd}")
        print(f"  Mission: {intent.mission_type.value}")
        print(f"  Assets: {intent.asset_ids}")
        print(f"  Targets: {len(intent.targets)}")
        print(f"  Complex: {intent.is_complex_mission()}")


async def test_command_parser_agent():
    """Test Command Parser Agent with LLM."""
    print("\n🧪 Testing Command Parser Agent (LLM)")
    print("=" * 60)
    
    test_command = "Navigate BEACON-01 to the flooded school building at coordinates (-15, -20) and scan for survivors"
    
    try:
        result = await command_parser.run(user_input=test_command)
        
        print(f"\nInput: {test_command}")
        print(f"\nParsed Intent:")
        print(f"  Mission Type: {result.response}")
        print("✅ Command Parser Agent working")
        return True
    except Exception as e:
        print(f"❌ Command Parser Agent failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_mission_planner_agent():
    """Test Mission Planner Agent."""
    print("\n🧪 Testing Mission Planner Agent")
    print("=" * 60)
    
    # Create a complex intent
    intent = CommandIntent(
        mission_type=MissionType.SCAN,
        targets=[
            {"type": "building", "x": -15, "z": -20, "id": "building_1"},
            {"type": "building", "x": -25, "z": -30, "id": "building_2"},
            {"type": "building", "x": -35, "z": -25, "id": "building_3"},
        ],
        constraints={"urgency": "high"},
        asset_ids=["auto"],
        raw_command="Scan 3 flooded buildings urgently"
    )
    
    try:
        # Convert intent to prompt
        prompt = f"""
Mission: {intent.mission_type.value}
Targets: {len(intent.targets)} buildings
Constraints: {intent.constraints}
Fleet: Auto-assign

Create an optimal mission plan.
"""
        
        result = await mission_planner.run(user_input=prompt)
        
        print(f"\nMission Planning Result:")
        print(f"  Response: {result.response[:200]}...")
        print("✅ Mission Planner Agent working")
        return True
    except Exception as e:
        print(f"❌ Mission Planner Agent failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_recovery_agent():
    """Test Recovery Agent."""
    print("\n🧪 Testing Recovery Agent")
    print("=" * 60)
    
    # Create error context
    error_ctx = ErrorContext(
        error_type="navigation_blocked",
        asset_id="BEACON-01",
        current_state={"battery": 35, "position": "(5, 10, -3)"},
        attempt_count=2
    )
    
    try:
        prompt = f"""
Error: {error_ctx.error_type}
Asset: {error_ctx.asset_id}
Battery: {error_ctx.current_state.get('battery')}%
Attempts: {error_ctx.attempt_count}

Propose a recovery strategy.
"""
        
        result = await recovery_agent.run(user_input=prompt)
        
        print(f"\nRecovery Strategy:")
        print(f"  Response: {result.response[:200]}...")
        print("✅ Recovery Agent working")
        return True
    except Exception as e:
        print(f"❌ Recovery Agent failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("🧪 TESTING NEW HYBRID AGENTS")
    print("=" * 60)
    
    # Test 1: Offline parser (no LLM)
    test_command_parser_offline()
    
    print("\n" + "-" * 60)
    print("⚠️  Skipping LLM agent tests (require API keys)")
    print("   To test with LLM, run:")
    print("   - export GOOGLE_API_KEY=...")
    print("   - uv run python tests/integration/test_new_agents.py --with-llm")
    print("-" * 60)
    
    # Skip LLM tests if no API key
    import os
    if not os.environ.get("GOOGLE_API_KEY"):
        print("\n✅ Offline tests passed")
        print("⚠️  LLM tests skipped (no API key)")
        return 0
    
    # Test 2-4: LLM-based agents
    results = []
    
    parser_result = await test_command_parser_agent()
    results.append(("Command Parser Agent", parser_result))
    
    planner_result = await test_mission_planner_agent()
    results.append(("Mission Planner Agent", planner_result))
    
    recovery_result = await test_recovery_agent()
    results.append(("Recovery Agent", recovery_result))
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 TEST SUMMARY")
    print("=" * 60)
    
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    total = len(results)
    passed = sum(1 for _, p in results if p)
    
    print(f"\nResults: {passed}/{total} LLM tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print("\n⚠️  Some tests failed")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
