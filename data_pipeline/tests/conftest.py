"""Put the evidence_pipeline modules (sources, cache, package) on sys.path.

They import each other by bare name (`import sources as S`), so tests need the
package directory on the path rather than importing a package.
"""
import sys
from pathlib import Path

PIPELINE = Path(__file__).resolve().parent.parent / "evidence_pipeline"
sys.path.insert(0, str(PIPELINE))
