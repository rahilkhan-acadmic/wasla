"""
Guards against a specific, real bug class: every market plugin's build(args)
reads attributes populated from its own CLI arguments (via add_cli_args) --
locally, argparse supplies them; inside the Lambda, fetch_data_handler.py's
_EnvArgs stand-in has to supply the same attributes by hand.

When the india_gsm plugin was added, _EnvArgs was NOT updated -- meaning that
switching FETCH_MARKETS to include india_gsm would have crashed the deployed
FetchData step with an AttributeError on every scheduled run. Nothing local
caught it, because locally argparse populates those attributes automatically.

This test checks the contract generically, for EVERY plugin in
MARKET_REGISTRY (including ones added in the future): each plugin's CLI
arguments must have a matching attribute on _EnvArgs.

Run from the project root: python tests/test_env_args_contract.py
"""
import os
import sys
import argparse

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(_ROOT, "src"))
sys.path.insert(0, os.path.join(_ROOT, "data"))

from build_dataset import MARKET_REGISTRY  # noqa: E402
from fetch_data_handler import _EnvArgs  # noqa: E402


def run_test():
    problems = []

    for market_code, module in MARKET_REGISTRY.items():
        parser = argparse.ArgumentParser()
        module.add_cli_args(parser)
        expected_attrs = sorted(
            action.dest for action in parser._actions if action.dest != "help"
        )
        missing = [a for a in expected_attrs if not hasattr(_EnvArgs, a)]

        status = "OK" if not missing else f"MISSING {missing}"
        print(f"  {market_code:12s} needs {len(expected_attrs)} attribute(s): {status}")
        if missing:
            problems.append((market_code, missing))

    if problems:
        print("\nFAILED: fetch_data_handler._EnvArgs is missing attributes that "
              "these plugins' build() functions read:")
        for market_code, missing in problems:
            print(f"  {market_code}: {missing}")
        print("\nAdd them to _EnvArgs in src/fetch_data_handler.py, or the "
              "deployed FetchData Lambda will crash with an AttributeError "
              "the first time that market is listed in FETCH_MARKETS.")
        raise AssertionError(f"{len(problems)} plugin(s) not covered by _EnvArgs")

    print(f"\nAll {len(MARKET_REGISTRY)} registered plugins are covered by "
          f"_EnvArgs. PASSED")


if __name__ == "__main__":
    run_test()