PY ?= python3
extract:  ; $(PY) -m src.pipeline.extract
extract-full: ; $(PY) -m src.pipeline.extract --force
gate1:    ; $(PY) -m src.pipeline.extract --gate
build:    ; $(PY) -m src.pipeline.build
gate3:    ; $(PY) -m pytest -q tests/test_reference.py
all:      extract build
test:     ; $(PY) -m pytest -q tests
docs:     ; $(PY) -m src.pipeline.governance $(if $(DASH),--dashboard $(DASH))
docs-strict: ; $(PY) -m src.pipeline.governance --strict $(if $(DASH),--dashboard $(DASH))
.PHONY: extract extract-full gate1 build gate3 all test docs docs-strict
