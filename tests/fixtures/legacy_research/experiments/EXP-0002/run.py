"""Counterexample search (Milestone 50).

Searches a STATED domain for a counterexample to a conjecture. Records the exact
range so "no counterexample up to N" is stored as bounded evidence, not "true".
"""

import json

SEED = 0
START, STOP, STEP = 1, 10000, 1


def conjecture_holds(n: int) -> bool:
    # Return True if the conjecture holds for n. Replace with your predicate.
    # Example (true): n*n >= n for non-negative integers.
    return n * n >= n


def main() -> None:
    checked = 0
    counterexample = None
    n = START
    while n <= STOP:
        checked += 1
        if not conjecture_holds(n):
            counterexample = n
            break
        n += STEP
    print(
        json.dumps(
            {
                "seed": SEED,
                "kind": "counterexample_search",
                "searched_range": [START, STOP],
                "step": STEP,
                "checked": checked,
                "counterexample": counterexample,
                "result": (
                    f"counterexample at n={counterexample}"
                    if counterexample is not None
                    else f"no counterexample up to {STOP} (bounded evidence, not a proof)"
                ),
            }
        )
    )


if __name__ == "__main__":
    main()
