.PHONY: all zip clean mypy pylint fix vendor
all: zip

PACKAGE_NAME := create_sub2srs_cards_with_mpv

zip: $(PACKAGE_NAME).ankiaddon

$(PACKAGE_NAME).ankiaddon: src/*
	rm -f $@
	find -L src/ -type f -name '*.py[co]' -delete -o -type d -name __pycache__ -delete
	( cd src/; zip -r ../$@ * -x user_files/config.json )

vendor:
	pip install pysubs2==1.6.0 -U -t src/vendor
	pip install git+https://github.com/abdnh/intersubs@45815cddaf20fe8f725ea9aa5b16d5af8416c37c -U --no-deps -t src/vendor

fix:
	python -m black src --exclude="vendor"
	python -m isort src

mypy:
	python -m mypy src

pylint:
	python -m pylint src

clean:
	rm -f $(PACKAGE_NAME).ankiaddon
