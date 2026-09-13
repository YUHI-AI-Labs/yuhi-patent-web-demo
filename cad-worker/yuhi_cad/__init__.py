"""Deterministic CAD analysis worker.

Contract: JSON in, versioned JSON out (see yuhi_cad/schemas/cad_analysis.py and
docs/CAD_PIPELINE.md). No network access, no model inference, no writes outside
the output directory it is given.
"""

__version__ = "0.1.0"
SCHEMA_VERSION = "1"
