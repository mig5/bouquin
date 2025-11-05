# 0.1.10

 * Improve search results window and highlight in calendar when there are matches.
 * Fix styling issue with text that comes after a URL, so it doesn't appear as part of the URL.
 * Add ability to export to Markdown (and fix heading styles)

# 0.1.9

 * More styling/toolbar fixes to support toggled-on styles, exclusive styles (e.g it should not be
   possible to set both H1 and H2 at once)
 * Fix small bug in export of HTML or arbitrary extension
 * Add plaintext SQLite3 Export option
 * Add Backup option (database remains encrypted with SQLCipher)
 * Add ability to run VACUUM (compact) on the database in settings
 * Add ability to store images in the page
 * Lots more tests, over 80% coverage

# 0.1.8

 * Fix saving the new key to the settings if the 'remember key' option was set and the DB was rekeyed
 * Fixes for multi-line code blocks
 * Fix URL href linking
 * Render the history version dates in user's local timezone

# 0.1.7

 * More fixes for shortcuts and move the Change Key button in settings

# 0.1.6

 * Fix shortcuts for next/previous day to not collide with Normal text (Ctrl+N)

# 0.1.5

 * Refactor schema to support versioning of pages. Add HistoryDialog and diff with ability to revert.

# 0.1.4

 * Add auto-lock of app (configurable in Settings, defaults to 15 minutes)
 * Add 'Report a bug' to Help nav

# 0.1.3

 * Fix bold toggle
 * Improvements to preview size in search results
 * Make URLs highlighted and clickable (Ctrl+click)
 * Explain the purpose of the encryption key for first-time use
 * Support saving the encryption key to the settings file to avoid being prompted (off by default)
 * Abbreviated toolbar symbols to keep things tidier. Add tooltips
 * Add ability to export the database to different formats
 * Add Documentation/Help menu

# 0.1.2

 * Switch from Markdown to HTML via QTextEdit, with a toolbar
 * Add search ability
 * Fix Settings shortcut and change nav menu from 'File' to 'Application'

# 0.1.1

 * Add ability to change the key
 * Add ability to jump to today's date
 * Add shortcut for Settings (Ctrl+E) so as not to collide with Ctrl+S (Save)

# 0.1.0

 * Initial release.
