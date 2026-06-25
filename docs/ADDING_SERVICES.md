# Adding Services

Add a service only when all are true:

- The hostname pattern is stable.
- A cloud API confirms the name can be claimed.
- CloudClaim can create a resource that reserves the hostname.
- Tests can prove check-before-create behavior.

Update:

- `services.py` or `catalog.py`
- `availability.py`
- `claims.py`
- `output.py`
- `README.md`
- `docs/USAGE.md`
- `tests/`

Do not add DNS-only checks or labels for known but unclaimable services.

Run:

```bash
uv run python -B -m unittest discover -s tests
python3 -B -m unittest discover -s tests
git diff --check
```
