# Reproducible README demo: the honesty linter catching an overclaim.
# Uses the deterministic offline mock provider — no API key, no model needed.
#
# Regenerate with `opentorus` on PATH (needs vhs, ttyd, ffmpeg):
#   vhs docs/media/demo.tape

Output docs/media/demo.gif

Set FontSize 15
Set Width 1100
Set Height 500
Set Padding 14
Set TypingSpeed 35ms

Hide
Type `cd "$(mktemp -d)" && clear`
Enter
Sleep 1s
Show

Type `# OpenTorus: a research agent for open math problems — honest by design`
Enter
Sleep 1.2s
Type `opentorus init`
Enter
Sleep 3s
Type `opentorus problem new "Is the nuclear-norm Nystrom error submodular for SDD matrices?"`
Enter
Sleep 2.5s
Type `# state a claim the way an overeager model would:`
Enter
Sleep 1s
Type `opentorus problem claim PROBLEM-0001 --type OBSERVATION --statement "Experiments up to n=10^4 prove the conjecture."`
Enter
Sleep 2.5s
Type `opentorus problem report PROBLEM-0001 --lint   # build + honesty-lint the report`
Enter
Sleep 3.5s
Type `# "experiments prove" has no verification artifact -> flagged, exit 1.`
Enter
Sleep 1s
Type `# Evidence is not proof — enforced in code, not left to the model.`
Enter
Sleep 4.5s
