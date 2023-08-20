.PHONY: all zip clean mypy pylint fix vendor
all: zip

PACKAGE_NAME := create_sub2srs_cards_with_mpv

zip: $(PACKAGE_NAME).ankiaddon

$(PACKAGE_NAME).ankiaddon: src/*
	rm -f $@
	find -L src/ -type f -name '*.py[co]' -delete -o -type d -name __pycache__ -delete
	( cd src/; zip -r ../$@ * -x user_files/config.json )

vendor:
	pip install -r requirements.txt -t src/vendor
fix:
	python -m black src --exclude="vendor"
	python -m isort src

mypy:
	python -m mypy src

pylint:
	python -m pylint src

clean:
	rm -f $(PACKAGE_NAME).ankiaddon
