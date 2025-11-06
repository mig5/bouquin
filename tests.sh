#!/bin/bash

poetry run pytest -vvvv --cov=bouquin --cov-report=term-missing --disable-warnings
