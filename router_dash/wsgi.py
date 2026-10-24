"""
WSGI entrypoint for production deployments.

The config file path is read from the ROUTER_DASH_CONFIG_FILE environment
variable.
"""

import os
import sys

from router_dash.app import create_app
from router_dash.config import ConfigError, load_config

_config_path = os.environ.get("ROUTER_DASH_CONFIG_FILE")
if not _config_path:
    print(
        "Error: ROUTER_DASH_CONFIG_FILE environment variable is not set",
        file=sys.stderr,
    )
    sys.exit(1)

try:
    _config = load_config(_config_path)
except ConfigError as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)

application = create_app(_config)
