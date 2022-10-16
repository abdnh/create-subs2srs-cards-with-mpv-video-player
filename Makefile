.PHONY: all zip clean mypy pylint fix vendor
all: zip

PACKAGE_NAME := create_sub2srs_cards_with_mpv

zip: $(PACKAGE_NAME).ankiaddon

$(PACKAGE_NAME).ankiaddon: src/*
	rm -f $@
	find src/ -type f -name '*.py[co]' -delete -o -type d -name __pycache__ -delete
	rm -rf src/meta.json
	rm -rf src/user_files/config.json
	( cd src/; zip -r ../$@ * )

vendor:
	pip install -r requirements.txt --no-deps -t src/vendor

fix:
	python -m black src --exclude="vendor"
	python -m isort src

mypy:
	python -m mypy src

pylint:
	python -m pylint src

clean:
	rm -f $(PACKAGE_NAME).ankiaddon
