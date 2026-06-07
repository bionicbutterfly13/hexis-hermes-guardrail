import logging

# Guards log every warn-mode firing; that's expected behavior, not test noise.
# Silence it so the test runner output stays readable.
logging.getLogger("guardcore").setLevel(logging.CRITICAL)
