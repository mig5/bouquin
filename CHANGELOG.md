# 0.5

 * More Italian translations, thank you @mdaleo404
 * Set locked status on window title when locked
 * Don't exit on incorrect key, let it be tried again
 * Make reminders be its own dataset rather than tied to current string.
 * Add support for repeated reminders
 * Make reminders be a feature that can be turned on and off
 * Add syntax highlighting for code blocks (right-click to set it)
 * Add a Pomodoro-style timer for measuring time spent on a task (stopping the timer offers to log it to Time Log)
 * Add ability to create markdown tables. Right-click to edit the table in a friendlier table dialog

# 0.4.5

 * Make it possible to delete revisions
 * Make it possible to force-lock the screen even if idle timer hasn't tripped
 * Add shortcuts for lock and unlock of screen
 * Other misc bug fixes

# 0.4.4.1

 * Adjust some widget heights/settings text wrap
 * Adjust shortcuts
 * History unicode symbol
 * Icon in version dialog

# 0.4.4

 * Moving unchecked TODOs now includes those up to 7 days ago, not just yesterday
 * Moving unchecked TODOs now skips placing them on weekends.
 * Moving unchecked TODOs now automatically occurs after midnight if the app is open (not just on startup)
 * Check for new version / download new AppImage via the Help -> Version screen.
 * Remove extra newline after headings

# 0.4.3

 * Ship Noto Sans Symbols2 font, which seems to work better for unicode symbols on Fedora

# 0.4.2

 * Improve Statistics widget height
 * Improve SaveDialog widget width
 * Make Tags and TimeLog optional features that can be switched on/off in Settings (enabled by default)
 * Make it possible to change regular text size
 * Refactored Settings dialog to use tabs to reduce its size

# 0.4.1

 * Allow time log entries to be edited directly in their table cells
 * Miscellaneous bug fixes for editing (list cursor positions/text selectivity, alarm removing newline)
 * Add 'Close tab' nav item and shortcut

# 0.4

 * Remove screenshot tool
 * Improve width of bug report dialog
 * Improve size of checkboxes
 * Convert bullet - to actual unicode bullets
 * Add alarm option to set reminders
 * Add time logging and reporting

# 0.3.2

 * Add weekday letters on left axis of Statistics page
 * Allow clicking on a date in the Statistics heatmap and have it open that page
 * Add the ability to choose the database path at startup
 * Add in-app bug report functionality

# 0.3.1

 * Make it possible to add a tag from the Tag Browser
 * Add a statistics dialog with heatmap
 * Remove export to .txt (just use .md)
 * Restore link styling and clickability

# 0.3

 * Introduce Tags
 * Make translations dynamically detected from the locales dir rather than hardcoded
 * Add Italian translations (thanks @mdaleo404)
 * Add version information in the navigation
 * Increase line spacing between lines (except for code blocks)
 * Prevent being able to left-click a date and have it load in current tab if it is already open in another tab
 * Avoid second checkbox/bullet on second newline after first newline
 * Avoid Home/left arrow jumping to the left side of a list symbol
 * Various test additions/fixes

# 0.2.1.8

 * Translate all strings, add French, add locale choice in settings
 * Fix hiding status bar (including find bar) when locked

# 0.2.1.7

 * Fix being able to set bold, italic and strikethrough at the same time.
 * Fixes for system dark theme and move stylesheets for Calendar/Lock Overlay into the ThemeManager
 * Add AppImage

# 0.2.1.6

 * Some code cleanup and more coverage
 * Improve code block styling / escaping out of the block in various scenarios

# 0.2.1.5

 * Go back to font size 10 (I might add a switcher later)
 * Fix bug with not syncing the right calendar date on search (History item would then be wrong too)

# 0.2.1.4

 * Increase font size of normal text
 * Fix auto-save of a tab if we are moving to another tab and it has not yet saved
 * DRY up some code

# 0.2.1.3

 * Ensure checkbox only can get checked on/off if it is clicked right on its block position, not any click on the whole line
 * Fix code backticks to not show but still be able to type code easily

# 0.2.1.2

 * Ensure tabs are ordered by calendar date
 * Some other code cleanups

# 0.2.1.1

 * Fix history preview pane to be in markdown
 * Some other code cleanups

# 0.2.1

 * Introduce tabs!

# 0.2.0.1

 * Fix chomping images when TODO is typed and converts to a checkbox

# 0.2.0

 * Switch back to Markdown editor

# 0.1.12.1

 * Fix newline after URL keeps URL style formatting

# 0.1.12

 * Add find bar for searching for text in the editor

# 0.1.11

 * Add missing export extensions to export_by_extension
 * Fix focusing on editor after leaving the app and returning
 * More code coverage and removing obsolete bits of code

# 0.1.10.2

 * Fix for code blocks in dark mode

# 0.1.10.1

 * Small bugfix for a debug message left in

# 0.1.10

 * Improve search results window and highlight in calendar when there are matches.
 * Fix styling issue with text that comes after a URL, so it doesn't appear as part of the URL.
 * Add ability to export to Markdown (and fix heading styles)
 * Represent in the History diff pane when an image was the thing that changed
 * Support theme choice in settings (light/dark/system)
 * Add Checkboxes in the editor. Typing 'TODO' at the start of a line will auto-convert into a checkbox.
 * Add option to automatically move yesterday's unchecked TODOs to today on startup

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
