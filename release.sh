#!/bin/bash

poetry build
poetry publish

rm -rf dist

for file in `ls -1 dist/`; do qubes-gpg-client --batch  --armor --detach-sign dist/$file > dist/$file.asc; done
