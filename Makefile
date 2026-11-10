PY ?= python3
extract:  ; $(PY) -m src.pipeline.extract
extract-full: ; $(PY) -m src.pipeline.extract --force
gate1:    ; $(PY) -m src.pipeline.extract --gate
build:    ; $(PY) -m src.pipeline.build
gate3:    ; $(PY) -m pytest -q tests/test_reference.py
all:      extract build
test:     ; $(PY) -m pytest -q tests
test-fault: ; $(PY) -m pytest -q tests/test_fault_injection.py
reconcile: ; $(PY) -m src.pipeline.reconcile $(RECONCILE_FLAGS)
parity:   ; $(PY) -m src.pipeline.parity --legacy $(or $(LEGACY),../gst/out) --strict
export:   ; $(PY) -m src.pipeline.export $(EXPORT_FLAGS)
snapshot: ; $(PY) -m src.pipeline.snapshot create
restore:  ; $(PY) -m src.pipeline.snapshot restore $(SNAP) $(RESTORE_FLAGS)
figures:  ; $(PY) -m src.pipeline.figures
diagrams: ; mmdc -i docs/figures/pipeline.mmd -o docs/figures/pipeline.png -b white -s 2 && mmdc -i docs/figures/data_hierarchy.mmd -o docs/figures/data_hierarchy.png -b white -s 2 \
	&& mmdc -i docs/figures/readme/pipeline.mmd -o docs/figures/readme/pipeline_light.png -t default -b white -w 1800 -s 2 \
	&& mmdc -i docs/figures/readme/pipeline.mmd -o docs/figures/readme/pipeline_dark.png -t dark -b '#0d1117' -w 1800 -s 2
readme-shots: site ; $(PY) -m src.pipeline.readme_shots
docs:     ; $(PY) -m src.pipeline.governance $(if $(DASH),--dashboard $(DASH))
site:     ; $(PY) -m src.pipeline.site $(SITE_FLAGS)
site-snapshot: ; $(PY) -m src.pipeline.site --refresh-snapshot
site-artifact: ; $(PY) -m src.pipeline.site --artifact $(or $(ARTIFACT_OUT),$${TMPDIR:-/tmp}/gmi-site-artifact)
docs-strict: ; $(PY) -m src.pipeline.governance --strict $(if $(DASH),--dashboard $(DASH))

.PHONY: readme-shots
.PHONY: extract extract-full gate1 build gate3 all test test-fault docs docs-strict reconcile figures diagrams parity export snapshot restore site site-snapshot site-artifact
