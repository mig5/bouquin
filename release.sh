#!/bin/bash

set -eo pipefail

rm -rf dist

# Publish to Pypi
poetry build
poetry publish

# Make AppImage
sudo apt-get install libfuse-dev
poetry run pyproject-appimage
mv Bouquin.AppImage dist/

# Sign packages
for file in `ls -1 dist/`; do qubes-gpg-client --batch  --armor --detach-sign dist/$file > dist/$file.asc; done

echo "Don't forget to update version string on remote server."
