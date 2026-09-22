"""Run a reproducible investigation from a Submission JSON file."""
import argparse
from pathlib import Path

from .models import Submission
from .runtime import build_coordinator


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("submission", type=Path)
    args = parser.parse_args()
    submission = Submission.model_validate_json(args.submission.read_text())
    engine = build_coordinator()
    state = engine.create(submission)
    result = engine.execute(state.run_id, submission)
    print(result.model_dump_json(indent=2))
    raise SystemExit(1 if result.status == "failed" else 0)


if __name__ == "__main__":
    main()
