#!/bin/bash

set -e

rm -rf dist

poetry build
poetry publish

for file in `ls -1 dist/`; do qubes-gpg-client --batch  --armor --detach-sign dist/$file > dist/$file.asc; done
