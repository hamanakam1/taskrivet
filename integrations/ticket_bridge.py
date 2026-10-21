#!/usr/bin/env python3
"""Run the optional local bridge from a source checkout."""
import runpy,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
runpy.run_module('taskrivet.dashboard_bridge',run_name='__main__')
