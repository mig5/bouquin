#!/bin/bash

set -eou pipefail

DISTS=(
  debian:trixie
)

for dist in ${DISTS[@]}; do
  release=$(echo ${dist} | cut -d: -f2)
  mkdir -p dist/${release}

  docker build -f Dockerfile.debbuild -t bouquin-deb:${release} \
    --no-cache \
    --progress=plain \
    --build-arg BASE_IMAGE=${dist} .

  docker run --rm \
    -e SUITE="${release}" \
    -v "$PWD":/src \
    -v "$PWD/dist/${release}":/out \
    bouquin-deb:${release}

  debfile=$(ls -1 dist/${release}/*.deb)
done
