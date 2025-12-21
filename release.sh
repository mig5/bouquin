#!/bin/bash

set -eo pipefail

# Parse the args
while getopts "v:" OPTION
do
  case $OPTION in
    v)
      VERSION=$OPTARG
      ;;
    ?)
      usage
      exit
      ;;
  esac
done

if [[ -z "${VERSION}" ]]; then
  echo "You forgot to pass -v [version]!"
  exit 1
fi

set +e
sed -i s/version.*$/version\ =\ \"${VERSION}\"/g pyproject.toml

git add pyproject.toml
git commit -m "Bump to ${VERSION}"
git push origin main

set -e

# Clean caches etc
filedust -y .

# Publish to Pypi
poetry build
poetry publish

# Make AppImage
sudo apt-get -y install libfuse-dev
poetry run pyproject-appimage
mv Bouquin.AppImage dist/

# Sign packages
for file in `ls -1 dist/`; do qubes-gpg-client --batch  --armor --detach-sign dist/$file > dist/$file.asc; done

# Deb stuff
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
  reprepro -b /home/user/git/repo includedeb "${release}" "${debfile}"
done

ssh wolverine.mig5.net "echo ${VERSION} | tee /opt/www/mig5.net/bouquin/version.txt"
