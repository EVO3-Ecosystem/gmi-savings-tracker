PY ?= python3
extract:  ; $(PY) -m src.pipeline.extract
extract-full: ; $(PY) -m src.pipeline.extract --force
gate1:    ; $(PY) -m src.pipeline.extract --gate
test:     ; $(PY) -m pytest -q tests
.PHONY: extract extract-full gate1 test
