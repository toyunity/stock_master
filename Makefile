PY := .venv/bin/python

.PHONY: verify test eval eval-update ops ci
verify:      ; $(PY) -m harness verify
test:        ; $(PY) -m harness test
eval:        ; $(PY) -m harness eval
eval-update: ; $(PY) -m harness eval --update
ops:         ; $(PY) -m harness ops
ci: test eval
