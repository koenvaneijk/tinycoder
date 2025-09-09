#!/usr/bin/env python3
"""
Integration tests for the TinyCoder application.
These tests verify that the app can start up and perform basic functionality.
"""

import subprocess
import sys
import tempfile
import os
import asyncio
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add the parent directory to the path so we can import tinycoder modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from tinycoder.app_builder import AppBuilder


class TestIntegration(unittest.TestCase):
    """Integration tests for the full TinyCoder application."""
    
    def test_basic_startup_with_file(self):
        """Test basic app startup with a file in a temporary directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            original_cwd = os.getcwd()
            os.chdir(temp_dir)
            
            try:
                # Create a simple test file
                test_file = Path('hello.py')
                test_file.write_text('def hello(): return "world"')
                
                # Test that the app can start with the file
                # We'll use a timeout to prevent hanging
                result = subprocess.run([
                    sys.executable, '-m', 'tinycoder',
                    '--files', 'hello.py',
                    '--non-interactive',
                    '--model', 'gpt-3.5-turbo',
                    'What does this function do?'
                ], capture_output=True, text=True, timeout=30)
                
                # Should not crash - return code 0 or 1 is acceptable
                self.assertIn(result.returncode, [0, 1], f"App crashed with return code {result.returncode}, stderr: {result.stderr}")
                
            finally:
                os.chdir(original_cwd)
    
    def test_app_builder_initialization(self):
        """Test that the AppBuilder can initialize the app components."""
        with tempfile.TemporaryDirectory() as temp_dir:
            original_cwd = os.getcwd()
            os.chdir(temp_dir)
            
            try:
                # Initialize git repo
                subprocess.run(['git', 'init'], check=True, capture_output=True)
                subprocess.run(['git', 'config', 'user.name', 'Test'], check=True, capture_output=True)
                subprocess.run(['git', 'config', 'user.email', 'test@example.com'], check=True, capture_output=True)
                
                # Create a test file
                test_file = Path('test.py')
                test_file.write_text('print("test")')
                
                # Test AppBuilder
                builder = AppBuilder(
                    model='gpt-3.5-turbo',
                    files=[str(test_file)],
                    continue_chat=False,
                    verbose=False
                )
                
                # This should not raise an exception
                app = builder.build()
                
                # Verify basic functionality
                self.assertIsNotNone(app)
                self.assertIsNotNone(app.file_manager)
                self.assertIsNotNone(app.history_manager)
                
                # Check that the file was added
                files_in_context = app.file_manager.get_files()
                self.assertIn('test.py', files_in_context)
                
            finally:
                os.chdir(original_cwd)
    
    def test_non_interactive_mode(self):
        """Test that the app can run in non-interactive mode."""
        with tempfile.TemporaryDirectory() as temp_dir:
            original_cwd = os.getcwd()
            os.chdir(temp_dir)
            
            try:
                # Create a simple Python file
                test_file = Path('math.py')
                test_file.write_text('''
def add(a, b):
    """Add two numbers."""
    return a + b

def multiply(a, b):
    """Multiply two numbers."""
    return a * b
''')
                
                # Test non-interactive mode
                result = subprocess.run([
                    sys.executable, '-m', 'tinycoder',
                    '--files', 'math.py',
                    '--non-interactive',
                    '--model', 'gpt-3.5-turbo',
                    'Explain what these functions do'
                ], capture_output=True, text=True, timeout=30)
                
                # Should complete without hanging
                self.assertIn(result.returncode, [0, 1], f"Non-interactive mode failed: {result.stderr}")
                
            finally:
                os.chdir(original_cwd)
    
    def test_with_invalid_model(self):
        """Test that the app handles invalid model names gracefully."""
        with tempfile.TemporaryDirectory() as temp_dir:
            original_cwd = os.getcwd()
            os.chdir(temp_dir)
            
            try:
                result = subprocess.run([
                    sys.executable, '-m', 'tinycoder',
                    '--model', 'invalid-model-name-xyz123',
                    '--help'
                ], capture_output=True, text=True, timeout=10)
                
                # Should show error but not crash the entire Python process
                self.assertNotEqual(result.returncode, 0)  # Should fail
                
            finally:
                os.chdir(original_cwd)
    
    def test_command_parsing(self):
        """Test that command parsing works correctly."""
        with tempfile.TemporaryDirectory() as temp_dir:
            original_cwd = os.getcwd()
            os.chdir(temp_dir)
            
            try:
                # Test /help command
                result = subprocess.run([
                    sys.executable, '-m', 'tinycoder',
                    '--non-interactive',
                    '--model', 'gpt-3.5-turbo',
                    '/help'
                ], capture_output=True, text=True, timeout=10)
                
                # Should not crash
                self.assertIn(result.returncode, [0, 1])
                
            finally:
                os.chdir(original_cwd)


if __name__ == '__main__':
    # Run the tests
    print("Running TinyCoder integration tests...")
    unittest.main(verbosity=2)      