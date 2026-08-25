# bouquin Fedora 42 RPM spec using Fedora's pyproject RPM macros (Poetry backend).
#
# NOTE: Bouquin depends on "bouquin-sqlcipher4" project, but the RPM actually
# provides the Python distribution/module as "sqlcipher4". To keep Fedora's
# auto-generated python3dist() Requires correct, we rewrite the dependency key in
# pyproject.toml at build time.
%global upstream_version 0.10.0

Name:           bouquin
Version:        %{upstream_version}
Release:        1%{?dist}.bouquin1
Summary:        A simple, opinionated notebook application (Python/Qt/SQLCipher)

License:        GPL-3.0-or-later
URL:            https://git.mig5.net/mig5/bouquin
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch

BuildRequires:  pyproject-rpm-macros
BuildRequires:  python3-devel
BuildRequires:  python3-poetry-core
BuildRequires:  desktop-file-utils

# Non-Python runtime dep (Fedora equivalent of Debian's libxcb-cursor0)
Requires:       xcb-util-cursor

# Make sure private repo dependency is pulled in by package name as well.
Requires:       python3-sqlcipher4 >= 4.12.0

%description
Bouquin is a simple, opinionated notebook application written in Python and Qt,
storing data using SQLCipher.

%prep
%autosetup -n bouquin

# Patch dependency name so Fedora's python dependency generator targets the
# provider from bouquin-sqlcipher4 RPM (python3dist(sqlcipher4)).
%{python3} - <<'PY'
from pathlib import Path
import re

p = Path("pyproject.toml")
txt = p.read_text(encoding="utf-8")

pattern = re.compile(r'(?ms)(^\[tool\.poetry\.dependencies\]\n.*?)(^\[|\Z)')
m = pattern.search(txt)
if not m:
    raise SystemExit("Could not locate [tool.poetry.dependencies] in pyproject.toml")

deps_block = m.group(1)
deps_block2 = re.sub(r'(?m)^bouquin-sqlcipher4\s*=\s*(".*?")\s*$', r'sqlcipher4 = \1', deps_block)
if deps_block == deps_block2:
    raise SystemExit("Did not find bouquin-sqlcipher4 dependency to rewrite")

p.write_text(txt[:m.start(1)] + deps_block2 + txt[m.end(1):], encoding="utf-8")
PY

desktop-file-validate debian/bouquin.desktop

%generate_buildrequires
%pyproject_buildrequires

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files bouquin

# Desktop integration (mirrors debian/bouquin.install)
install -Dpm 0644 debian/bouquin.desktop %{buildroot}%{_datadir}/applications/bouquin.desktop
install -Dpm 0644 bouquin/icons/bouquin.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/bouquin.svg

%files -f %{pyproject_files}
%license LICENSE
%doc README.md CHANGELOG.md
%{_bindir}/bouquin

%{_datadir}/applications/bouquin.desktop
%{_datadir}/icons/hicolor/scalable/apps/bouquin.svg

%changelog
* Tue Aug 25 2026 Miguel Jacq <mig@mig5.net> - %{version}-%{release}
- New 'Earnings' interface for viewing/tracking earnings across reporting periods (e.g for BAS)
- Dependency updates (including upgrade to SQLCipher 4.18.0)
* Sun Jun 07 2026 Miguel Jacq <mig@mig5.net> - %{version}-%{release}
- Add 'Projects' interface for unified time/invoice/docs view.
- Add ability to set a 'bucket' of (prepaid) hours for a project and warn when time logged approaches it.
- Add ability to invoice for the increase in prepaid project bucket hours (without having had to 'log' them).
* Wed May 13 2026 Miguel Jacq <mig@mig5.net> - %{version}-%{release}
- Dependency updates
- SQLCipher 4.16.0
* Fri Jan 30 2026 Miguel Jacq <mig@mig5.net> - %{version}-%{release}
- Update urllib3 dependency to resolve CVE-2026-21441
- Fix carrying over data to next day from over-capturing data belonging to next header section
- Other dependency updates
* Wed Dec 31 2025 Miguel Jacq <mig@mig5.net> - %{version}-%{release}
- Add ability to delete an invoice via 'Manage Invoices' dialog
* Fri Dec 26 2025 Miguel Jacq <mig@mig5.net> - %{version}-%{release}
- Fix bold/italic/strikethrough styling in certain conditions when toolbar action is used.
- Move a code block or collapsed section (or generally, anything after a checkbox line until the next checkbox line) when moving an unchecked checkbox line to another day.
* Wed Dec 24 2025 Miguel Jacq <mig@mig5.net> - %{version}-%{release}
- Initial RPM packaging for Fedora 42
