# Legacy research fixture

A trimmed `.opentorus/` subtree produced by `opentorus research "Is a(n) prime for
every n?" -n 2` under the mock provider (OpenTorus 0.0.14) with one active dossier
(`PROBLEM-0001`, "Euler prime polynomial"): the research state file
(`research/<slug>.json`), its progress note, the journal (one entry per iteration),
the workspace claim / evidence / graph ledgers, the two counterexample-search
experiments and the reviews index. `tests/test_research_facade.py` copies it into a
fresh workspace to exercise `campaign import-research`, which must read these files
and never modify them (the test compares sha256s before and after).
