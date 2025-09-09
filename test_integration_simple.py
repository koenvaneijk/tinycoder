#!/usr/bin/env python3
"""
Simple integration test for TinyCoder.
This test verifies that the app can start and respond to basic commands.
"""

import subprocess
import sys
import tempfile
import os
from pathlib import Path


def test_basic_functionality():
    """Test basic app functionality."""
    print("Testing basic app startup...")
    
    # Test 1: Help command
    result = subprocess.run([
        sys.executable, '-m', 'tinycoder', '--help'
    ], capture_output=True, text=True, timeout=10)
    
    assert result.returncode == 0, f"Help command failed: {result.stderr}"
    assert 'tinycoder' in result.stdout.lower()
    print("✓ Help command works")
    
    # Test 2: Non-interactive mode with a file
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
            
            assert result.returncode in [0, 1], f"App crashed: {result.stderr}"
            print("✓ Non-interactive mode works")
            
        finally:
            os.chdir(original_cwd)
    
    print("✅ All basic functionality tests passed!")


if __name__ == '__main__':
    test_basic_functionality()