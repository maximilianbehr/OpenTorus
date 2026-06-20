# Tool-environment container images

OpenTorus does **not** ship container images. Provide your own Dockerfile in the
workspace and register it once:

```bash
opentorus env prepare python-sci --file docker/Dockerfile
opentorus env prepare julia --file docker/julia.Dockerfile
```

Rebuild after Dockerfile changes: `opentorus env prepare python-sci --rebuild`.

Then use `exp_new(..., environment="python-sci")` and `exp_run`.
