CWD=$(shell pwd)
PY_FILES=$(shell find cloudinit bin -name "*.py")

all: test

pylint:
	$(CWD)/tools/run-pylint $(PY_FILES)

pyflakes:
	pyflakes $(PY_FILES)

test:
	nosetests tests/unittests/

2to3:
	2to3 $(PY_FILES)

.PHONY: test pylint pyflakes 2to3

