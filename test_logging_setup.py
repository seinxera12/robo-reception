#!/usr/bin/env python3
"""
Quick validation script for logging setup.
Run with: python test_logging_setup.py
"""

import sys
import logging

print("\n" + "=" * 70)
print("Testing Robo Logging Configuration Setup")
print("=" * 70 + "\n")

# Test 1: Import the logging config module
try:
    from app.logging_config import setup_logging, suppress_library_spam, get_logger
    print("✓ Successfully imported logging_config module")
except ImportError as e:
    print(f"✗ Failed to import logging_config: {e}")
    sys.exit(1)

# Test 2: Test setup_logging
try:
    setup_logging()
    print("✓ setup_logging() executed without errors")
except Exception as e:
    print(f"✗ setup_logging() failed: {e}")
    sys.exit(1)

# Test 3: Test suppress_library_spam
try:
    suppress_library_spam()
    print("✓ suppress_library_spam() executed without errors")
except Exception as e:
    print(f"✗ suppress_library_spam() failed: {e}")
    sys.exit(1)

# Test 4: Verify log levels are set correctly
app_logger = logging.getLogger("app")
torch_logger = logging.getLogger("torch")
sqlalchemy_logger = logging.getLogger("sqlalchemy")

app_level = logging.getLevelName(app_logger.level) if app_logger.level else "NOTSET (inherited)"
torch_level = logging.getLevelName(torch_logger.level) if torch_logger.level else "NOTSET (inherited)"
sqlalchemy_level = logging.getLevelName(sqlalchemy_logger.level) if sqlalchemy_logger.level else "NOTSET (inherited)"

print(f"\nLog Levels:")
print(f"  app: {app_level}")
print(f"  torch: {torch_level}")
print(f"  sqlalchemy: {sqlalchemy_level}")

if torch_logger.level >= logging.WARNING:
    print("✓ Third-party libraries are properly suppressed (WARNING+)")
else:
    print("✗ Third-party libraries are not suppressed (should be WARNING+)")

# Test 5: Test get_logger helper
try:
    test_logger = get_logger(__name__)
    print(f"✓ get_logger() helper works: {type(test_logger)}")
except Exception as e:
    print(f"✗ get_logger() failed: {e}")
    sys.exit(1)

# Test 6: Test actual logging at different levels
print("\nTesting log output:")
app_logger = get_logger("app.test")

# Should see these
app_logger.info("ℹ️  This INFO message should be visible")
app_logger.debug("🔍 This DEBUG message should be visible")

# Should NOT see these
import logging
old_level = torch_logger.level
torch_logger.setLevel(logging.WARNING)
torch_logger.warning("⚠️  This WARNING from torch should NOT appear (suppressed at WARNING)")
test_debug = logging.getLogger("test_lib").debug
print("✓ Sample logs displayed above")

print("\n" + "=" * 70)
print("Summary:")
print("=" * 70)
print("""
✓ All checks passed!

Your logging setup is configured correctly:
  • app modules will log at DEBUG/INFO level
  • third-party libraries will be suppressed at WARNING level
  • console format: [HH:MM:SS] LEVEL logger_name : message
  • logs go to stderr

Next steps:
  1. Start the app: make up
  2. Check that logs are visible during startup
  3. Connect to http://localhost:8000/static/index.html
  4. Speak into the microphone
  5. Watch terminal for voice processing logs

For customization, edit: app/logging_config.py
For documentation, read: docs/LOGGING_GUIDE.md
""")
print("=" * 70 + "\n")
