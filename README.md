# Bouquin


## Introduction

Bouquin ("Book-ahn") is a simple, opinionated notebook application written in Python, PyQt and SQLCipher.

It uses [SQLCipher bindings](https://pypi.org/project/sqlcipher3-wheels) as a drop-in replacement
for SQLite3. This means that the underlying database for the notebook is encrypted at rest.

To increase security, the SQLCipher key is requested when the app is opened, and is not written
to disk unless the user configures it to be in the settings.

There is deliberately no network connectivity or syncing intended.

## Screenshot

![Screenshot of Bouquin](https://git.mig5.net/mig5/bouquin/raw/branch/main/screenshot.png)

## Features

 * Data is encrypted at rest
 * Encryption key is prompted for and never stored, unless user chooses to via Settings
 * Every 'page' is linked to the calendar day
 * All changes are version controlled, with ability to view/diff versions and revert
 * Text is Markdown with basic styling
 * Tabs are supported - right-click on a date from the calendar to open it in a new tab.
 * Images are supported
 * Search all pages, or find text on page (Ctrl+F)
 * Automatic periodic saving (or explicitly save)
 * Transparent integrity checking of the database when it opens
 * Automatic locking of the app after a period of inactivity (default 15 min)
 * Rekey the database (change the password)
 * Export the database to json, txt, html, csv, markdown or .sql (for sqlite3)
 * Backup the database to encrypted SQLCipher format (which can then be loaded back in to a Bouquin)
 * Dark and light themes
 * Automatically generate checkboxes when typing 'TODO'
 * Optionally automatically move unchecked checkboxes from yesterday to today, on startup


## How to install

Make sure you have `libxcb-cursor0` installed (it may be called something else on non-Debian distributions).

### From PyPi/pip

 * `pip install bouquin`

### From source

 * Clone this repo or download the tarball from the releases page
 * Ensure you have poetry installed
 * Run `poetry install` to install dependencies
 * Run `poetry run bouquin` to start the application.

### From the releases page

 * Download the whl and run it

## How to run the tests

 * Clone the repo
 * Ensure you have poetry installed
 * Run `poetry install --with test`
 * Run `./tests.sh`
