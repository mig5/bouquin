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

# RPM
sudo apt-get -y install createrepo-c rpm
docker build -f Dockerfile.rpmbuild -t bouquin-rpm:f42 --progress=plain .
docker run --rm -v "$PWD":/src -v "$PWD/dist/rpm":/out -v "$HOME/git/bouquin-sqlcipher4/dist/rpm":/deps:ro bouquin-rpm:f42
sudo chown -R "${USER}" "$PWD/dist"

REPO_ROOT="${HOME}/git/repo_rpm"
RPM_REPO="${REPO_ROOT}/rpm/x86_64"
BUILD_OUTPUT="${HOME}/git/bouquin/dist"
REMOTE="letessier.mig5.net:/opt/repo_rpm"
KEYID="00AE817C24A10C2540461A9C1D7CDE0234DB458D"

echo "==> Updating RPM repo..."
mkdir -p "$RPM_REPO"

for file in `ls -1 "${BUILD_OUTPUT}/rpm"`; do
  rpmsign --addsign "${BUILD_OUTPUT}/rpm/$file"
done

cp "${BUILD_OUTPUT}/rpm/"*.rpm "$RPM_REPO/"

createrepo_c "$RPM_REPO"

echo "==> Signing repomd.xml..."
qubes-gpg-client --local-user "$KEYID" --detach-sign --armor "$RPM_REPO/repodata/repomd.xml" > "$RPM_REPO/repodata/repomd.xml.asc"

echo "==> Syncing repo to server..."
rsync -aHPvz --exclude=.git --delete "$REPO_ROOT/" "$REMOTE/"

echo "Done!"

ssh wolverine.mig5.net "echo ${VERSION} | tee /opt/www/mig5.net/bouquin/version.txt"
