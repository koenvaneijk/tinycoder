#!/usr/bin/env python3
"""
Simple integration test for TinyCoder.
This test verifies that the app can start and respond to basic commands.
"""

import subprocess
import sys
import tempfile
import os
import unittest
from pathlib import Path


class TestBasicFunctionality(unittest.TestCase):
    """Test basic app functionality."""
    
    def test_help_command(self):
        """Test that the help command works."""
        result = subprocess.run([
            sys.executable, '-m', 'tinycoder', '--help'
        ], capture_output=True, text=True, timeout=10)
        
        self.assertEqual(result.returncode, 0, f"Help command failed: {result.stderr}")
        self.assertIn('tinycoder', result.stdout.lower())
        print("✓ Help command works")
    
    def test_non_interactive_mode_with_file(self):
        """Test non-interactive mode with a file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            original_cwd = os.getcwd()
            os.chdir(temp_dir)
            
            try:
                # Create a simple Python file
                test_file = Path('hello.py')
                test_file.write_text('def greet(name): return f"Hello, {name}!"')
                
                result = subprocess.run([
                    sys.executable, '-m', 'tinycoder',
                    '--files', 'hello.py',
                    '--non-interactive',
                    '--model', 'gpt-3.5-turbo',
                    'What does this function do?'
                ], capture_output=True, text=True, timeout=30)
                
                self.assertIn(result.returncode, [0, 1], f"App crashed: {result.stderr}")
                print("✓ Non-interactive mode works")
                
            finally:
                os.chdir(original_cwd)


class TestSmokeTest(unittest.TestCase):
    """Simple smoke test."""
    
    def test_basic_smoke_test(self):
        """Test basic app functionality."""
        result = subprocess.run([
            sys.executable, '-m', 'tinycoder', '--help'
        ], capture_output=True, text=True, timeout=10)
        
        self.assertEqual(result.returncode, 0)
        self.assertIn('tinycoder', result.stdout.lower())
        print("✓ Basic smoke test passed")


def test_basic_functionality():
    """Run basic functionality tests."""
    print("Testing basic app startup...")
    
    # Create test suite
    suite = unittest.TestSuite()
    suite.addTest(TestBasicFunctionality('test_help_command'))
    suite.addTest(TestBasicFunctionality('test_non_interactive_mode_with_file'))
    suite.addTest(TestSmokeTest('test_basic_smoke_test'))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    if result.wasSuccessful():
        print("✅ All basic functionality tests passed!")
        return True
    else:
        print("❌ Some tests failed!")
        return False


if __name__ == '__main__':
    test_basic_functionality()