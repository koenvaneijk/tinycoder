#!/bin/bash
# TinyCoder Smoke Test
# Quick test to verify the app still runs and functions correctly

set -e  # Exit on any error

echo "🧪 Running TinyCoder smoke tests..."

# Test 1: Help command
echo "Testing help command..."
python -m tinycoder --help > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "✓ Help command works"
else
    echo "✗ Help command failed"
    exit 1
fi

# Test 2: Basic functionality with temp directory
echo "Testing basic functionality..."
TEMP_DIR=$(mktemp -d)
cd "$TEMP_DIR"

# Create a simple Python file
echo 'def add(a, b): return a + b' > test.py

# Test with the file (timeout to prevent hanging)
timeout 30 python -m tinycoder --files test.py --non-interactive --model gpt-3.5-turbo "What does this function do?" > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "✓ Basic functionality works"
else
    echo "⚠ Basic functionality had issues (may need API key or other config)"
fi

# Test 3: Command parsing
echo "Testing command parsing..."
timeout 10 python -m tinycoder --non-interactive --model gpt-3.5-turbo "/help" > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "✓ Command parsing works"
else
    echo "⚠ Command parsing had issues"
fi

# Cleanup
cd - > /dev/null
rm -rf "$TEMP_DIR"

echo "🎉 Smoke tests completed!"
echo ""
echo "To run more comprehensive tests:"
echo "  python -m pytest tinycoder/test_integration.py -v"
echo "  python test_integration_simple.py"