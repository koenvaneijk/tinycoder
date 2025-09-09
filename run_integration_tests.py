#!/usr/bin/env python3
"""
Run all integration tests for TinyCoder.
"""

import subprocess
import sys
from pathlib import Path


def run_simple_test():
    """Run the simple integration test."""
    print("Running simple integration test...")
    result = subprocess.run([sys.executable, 'test_integration_simple.py'], capture_output=True, text=True)
    if result.returncode == 0:
        print("✅ Simple integration test passed")
        return True
    else:
        print(f"❌ Simple integration test failed: {result.stderr}")
        return False


def run_comprehensive_test():
    """Run the comprehensive integration test with pytest."""
    print("Running comprehensive integration tests...")
    try:
        result = subprocess.run([
            sys.executable, '-m', 'pytest', 'tinycoder/test_integration.py', '-v'
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ Comprehensive integration tests passed")
            return True
        else:
            print(f"❌ Comprehensive integration tests failed:")
            print(result.stdout)
            print(result.stderr)
            return False
    except FileNotFoundError:
        print("⚠️  pytest not found, skipping comprehensive tests")
        print("Install with: pip install pytest")
        return True


def run_smoke_test():
    """Run the smoke test script."""
    print("Running smoke test...")
    result = subprocess.run(['bash', 'smoke_test.sh'], capture_output=True, text=True)
    if result.returncode == 0:
        print("✅ Smoke test passed")
        return True
    else:
        print(f"❌ Smoke test failed: {result.stderr}")
        return False


def main():
    """Run all integration tests."""
    print("🚀 Starting TinyCoder integration tests...")
    print("=" * 50)
    
    tests_passed = 0
    total_tests = 3
    
    # Run tests in order of complexity
    if run_smoke_test():
        tests_passed += 1
    
    if run_simple_test():
        tests_passed += 1
    
    if run_comprehensive_test():
        tests_passed += 1
    
    print("=" * 50)
    print(f"Tests passed: {tests_passed}/{total_tests}")
    
    if tests_passed == total_tests:
        print("🎉 All integration tests passed!")
        return 0
    else:
        print("⚠️  Some tests failed")
        return 1


if __name__ == '__main__':
    sys.exit(main())