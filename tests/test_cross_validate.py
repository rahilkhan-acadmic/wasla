"""
Tests that src/cross_validate.py is a trustworthy yardstick before anyone
relies on its numbers.

1. REAL labels (synthetic data, clearly separable): the model and the ratio
   baselines should score high -- the harness can detect genuine signal.
2. SHUFFLED labels: same features, labels randomly permuted, so there is NO
   relationship to find. Every method must score about 0.5. This is the
   standard permutation check -- if anything scores well here, the harness
   itself is leaking (e.g. testing on data a model trained on) and every
   number it has ever printed is suspect.
3. Every method is scored on identical folds (array lengths match), which the
   paired comparison depends on.
4. Too few records in a class fails loudly instead of returning garbage.

Run from the project root: python tests/test_cross_validate.py
"""
import os
import sys

import numpy as np

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(_ROOT, "src"))

from cross_validate import MODEL_NAME, format_report, run_cross_validation  # noqa: E402
from train_classifier import load_dataset  # noqa: E402

DATA = os.path.join(_ROOT, "data", "sample_companies.json")


def run_test():
    X, y, _ = load_dataset(DATA)

    print("=== 1. Real labels: the harness detects genuine signal ===")
    real = run_cross_validation(X, y, n_splits=5, n_repeats=4)
    for name, s in real.items():
        print(f"  {name:36s} AUC {s['auc'].mean():.3f}")
    assert real[MODEL_NAME]["auc"].mean() > 0.95, \
        "On clearly separable data the model should score high"
    print("PASSED\n")

    print("=== 2. Shuffled labels: nothing to find, so EVERY method must score ~0.5 ===")
    y_shuffled = np.random.RandomState(0).permutation(y)
    shuffled = run_cross_validation(X, y_shuffled, n_splits=5, n_repeats=4)
    for name, s in shuffled.items():
        mean = s["auc"].mean()
        print(f"  {name:36s} AUC {mean:.3f}")
        assert 0.35 < mean < 0.65, (
            f"{name} scored {mean:.3f} on SHUFFLED labels -- that means the "
            f"evaluation is leaking, not that the method found signal")
    print("PASSED\n")

    print("=== 3. All methods are scored on identical folds ===")
    lengths = {len(s["auc"]) for s in real.values()}
    assert len(lengths) == 1, f"Methods scored on different numbers of folds: {lengths}"
    print(f"PASSED ({lengths.pop()} folds each)\n")

    print("=== 4. Too few records in a class fails loudly ===")
    tiny_y = y.copy()
    tiny_y[:] = 0
    tiny_y[:3] = 1  # only 3 positives, but 5 splits requested
    try:
        run_cross_validation(X, tiny_y, n_splits=5, n_repeats=1)
    except ValueError as e:
        print(f"PASSED (raised: {e})\n")
    else:
        raise AssertionError("A class smaller than n_splits must raise, not silently proceed")

    report = format_report(real, len(y))
    assert "Paired:" in report and MODEL_NAME in report
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    run_test()
