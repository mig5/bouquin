from bouquin.db import DBManager
from bouquin.tags_widget import PageTagsWidget, TagChip
from bouquin.tag_browser import TagBrowserDialog


# ============================================================================
# DB Layer Tag Tests
# ============================================================================


def test_set_tags_for_page_creates_tags(fresh_db):
    """Test that setting tags for a page creates the tags in the database"""
    date_iso = "2024-01-15"
    tags = ["work", "important", "meeting"]

    fresh_db.set_tags_for_page(date_iso, tags)

    # Verify tags were created
    all_tags = fresh_db.list_tags()
    tag_names = [name for _, name, _ in all_tags]

    assert "work" in tag_names
    assert "important" in tag_names
    assert "meeting" in tag_names


def test_get_tags_for_page(fresh_db):
    """Test retrieving tags for a specific page"""
    date_iso = "2024-01-15"
    tags = ["work", "important"]

    fresh_db.set_tags_for_page(date_iso, tags)
    retrieved_tags = fresh_db.get_tags_for_page(date_iso)

    assert len(retrieved_tags) == 2
    tag_names = [name for _, name, _ in retrieved_tags]
    assert "work" in tag_names
    assert "important" in tag_names


def test_tags_have_colors(fresh_db):
    """Test that created tags have default colors assigned"""
    date_iso = "2024-01-15"
    fresh_db.set_tags_for_page(date_iso, ["test"])

    tags = fresh_db.get_tags_for_page(date_iso)
    assert len(tags) == 1
    tag_id, name, color = tags[0]

    assert color.startswith("#")
    assert len(color) in (4, 7)  # #RGB or #RRGGBB


def test_set_tags_replaces_existing(fresh_db):
    """Test that setting tags replaces the existing tag set"""
    date_iso = "2024-01-15"

    fresh_db.set_tags_for_page(date_iso, ["old1", "old2"])
    fresh_db.set_tags_for_page(date_iso, ["new1", "new2"])

    tags = fresh_db.get_tags_for_page(date_iso)
    tag_names = [name for _, name, _ in tags]

    assert "new1" in tag_names
    assert "new2" in tag_names
    assert "old1" not in tag_names
    assert "old2" not in tag_names


def test_set_tags_empty_clears_tags(fresh_db):
    """Test that setting empty tag list clears all tags for page"""
    date_iso = "2024-01-15"

    fresh_db.set_tags_for_page(date_iso, ["tag1", "tag2"])
    fresh_db.set_tags_for_page(date_iso, [])

    tags = fresh_db.get_tags_for_page(date_iso)
    assert len(tags) == 0


def test_tags_case_insensitive_deduplication(fresh_db):
    """Test that tags are deduplicated case-insensitively"""
    date_iso = "2024-01-15"

    # Try to set tags with different cases
    fresh_db.set_tags_for_page(date_iso, ["Work", "work", "WORK"])

    tags = fresh_db.get_tags_for_page(date_iso)
    assert len(tags) == 1


def test_tags_case_insensitive_reuse(fresh_db):
    """Test that existing tags are reused regardless of case"""
    date1 = "2024-01-15"
    date2 = "2024-01-16"

    # Create tag with lowercase
    fresh_db.set_tags_for_page(date1, ["work"])

    # Try to add same tag with different case on different page
    fresh_db.set_tags_for_page(date2, ["Work"])

    # Should reuse the existing tag
    all_tags = fresh_db.list_tags()
    work_tags = [t for t in all_tags if t[1].lower() == "work"]
    assert len(work_tags) == 1  # Only one "work" tag should exist


def test_tags_whitespace_normalization(fresh_db):
    """Test that tags are trimmed and empty strings ignored"""
    date_iso = "2024-01-15"

    fresh_db.set_tags_for_page(date_iso, ["  work  ", "", "  ", "meeting"])

    tags = fresh_db.get_tags_for_page(date_iso)
    tag_names = [name for _, name, _ in tags]

    assert "work" in tag_names
    assert "meeting" in tag_names
    assert len(tags) == 2  # Empty strings should be filtered


def test_list_all_tags(fresh_db):
    """Test listing all tags in the database"""
    fresh_db.set_tags_for_page("2024-01-15", ["tag1", "tag2"])
    fresh_db.set_tags_for_page("2024-01-16", ["tag2", "tag3"])

    all_tags = fresh_db.list_tags()
    tag_names = [name for _, name, _ in all_tags]

    assert len(all_tags) == 3
    assert "tag1" in tag_names
    assert "tag2" in tag_names
    assert "tag3" in tag_names


def test_update_tag_name_and_color(fresh_db):
    """Test updating a tag's name and color"""
    date_iso = "2024-01-15"
    fresh_db.set_tags_for_page(date_iso, ["oldname"])

    tags = fresh_db.list_tags()
    tag_id = tags[0][0]

    fresh_db.update_tag(tag_id, "newname", "#FF0000")

    updated_tags = fresh_db.list_tags()
    assert len(updated_tags) == 1
    assert updated_tags[0][1] == "newname"
    assert updated_tags[0][2] == "#FF0000"


def test_delete_tag(fresh_db):
    """Test deleting a tag removes it globally"""
    fresh_db.set_tags_for_page("2024-01-15", ["tag1", "tag2"])
    fresh_db.set_tags_for_page("2024-01-16", ["tag1"])

    tags = fresh_db.list_tags()
    tag1_id = [tid for tid, name, _ in tags if name == "tag1"][0]

    fresh_db.delete_tag(tag1_id)

    # Tag should be removed from all pages
    tags_page1 = fresh_db.get_tags_for_page("2024-01-15")
    tags_page2 = fresh_db.get_tags_for_page("2024-01-16")

    assert len(tags_page1) == 1
    assert tags_page1[0][1] == "tag2"
    assert len(tags_page2) == 0


def test_get_pages_for_tag(fresh_db):
    """Test retrieving all pages that have a specific tag"""
    fresh_db.save_new_version("2024-01-15", "Content 1", "note")
    fresh_db.save_new_version("2024-01-16", "Content 2", "note")
    fresh_db.save_new_version("2024-01-17", "Content 3", "note")

    fresh_db.set_tags_for_page("2024-01-15", ["work"])
    fresh_db.set_tags_for_page("2024-01-16", ["work", "meeting"])
    fresh_db.set_tags_for_page("2024-01-17", ["personal"])

    pages = fresh_db.get_pages_for_tag("work")
    dates = [date_iso for date_iso, _ in pages]

    assert "2024-01-15" in dates
    assert "2024-01-16" in dates
    assert "2024-01-17" not in dates


def test_tags_persist_across_reconnect(fresh_db, tmp_db_cfg):
    """Test that tags persist when database is closed and reopened"""
    date_iso = "2024-01-15"
    fresh_db.set_tags_for_page(date_iso, ["persistent", "tag"])
    fresh_db.close()

    # Reopen database
    db2 = DBManager(tmp_db_cfg)
    assert db2.connect()

    tags = db2.get_tags_for_page(date_iso)
    tag_names = [name for _, name, _ in tags]

    assert "persistent" in tag_names
    assert "tag" in tag_names
    db2.close()


# ============================================================================
# PageTagsWidget Tests
# ============================================================================


def test_page_tags_widget_creation(app, fresh_db):
    """Test that PageTagsWidget can be created"""
    widget = PageTagsWidget(fresh_db)
    assert widget is not None
    assert widget._db == fresh_db


def test_page_tags_widget_set_current_date(app, fresh_db):
    """Test setting the current date on the widget"""
    widget = PageTagsWidget(fresh_db)
    date_iso = "2024-01-15"

    fresh_db.set_tags_for_page(date_iso, ["test"])
    widget.set_current_date(date_iso)

    assert widget._current_date == date_iso


def test_page_tags_widget_hidden_when_collapsed(app, fresh_db):
    """Test that tag chips are hidden when widget is collapsed"""
    widget = PageTagsWidget(fresh_db)
    date_iso = "2024-01-15"

    fresh_db.set_tags_for_page(date_iso, ["tag1", "tag2"])
    widget.set_current_date(date_iso)

    # Body should be hidden when collapsed
    assert not widget.body.isVisible()
    assert not widget.toggle_btn.isChecked()


def test_page_tags_widget_shows_tags_when_expanded(app, fresh_db):
    """Test that tags are shown when widget is expanded"""
    widget = PageTagsWidget(fresh_db)
    widget.show()  # Widget needs to be shown for visibility to work
    date_iso = "2024-01-15"

    fresh_db.set_tags_for_page(date_iso, ["tag1", "tag2"])
    widget.set_current_date(date_iso)

    # Expand the widget
    widget.toggle_btn.setChecked(True)
    widget._on_toggle(True)

    assert widget.body.isVisible()
    assert widget.chip_layout.count() == 2


def test_page_tags_widget_add_tag(app, fresh_db):
    """Test adding a tag through the widget"""
    widget = PageTagsWidget(fresh_db)
    date_iso = "2024-01-15"

    widget.set_current_date(date_iso)
    widget.toggle_btn.setChecked(True)
    widget._on_toggle(True)

    # Simulate adding a tag
    widget.add_edit.setText("newtag")
    widget._on_add_tag()

    # Verify tag was added
    tags = fresh_db.get_tags_for_page(date_iso)
    tag_names = [name for _, name, _ in tags]
    assert "newtag" in tag_names


def test_page_tags_widget_prevents_duplicates(app, fresh_db):
    """Test that duplicate tags are prevented"""
    widget = PageTagsWidget(fresh_db)
    date_iso = "2024-01-15"

    fresh_db.set_tags_for_page(date_iso, ["existing"])
    widget.set_current_date(date_iso)
    widget.toggle_btn.setChecked(True)
    widget._on_toggle(True)

    # Try to add the same tag
    widget.add_edit.setText("existing")
    widget._on_add_tag()

    # Should still only have one tag
    tags = fresh_db.get_tags_for_page(date_iso)
    assert len(tags) == 1


def test_page_tags_widget_case_insensitive_duplicates(app, fresh_db):
    """Test that duplicate checking is case-insensitive"""
    widget = PageTagsWidget(fresh_db)
    date_iso = "2024-01-15"

    fresh_db.set_tags_for_page(date_iso, ["Test"])
    widget.set_current_date(date_iso)
    widget.toggle_btn.setChecked(True)
    widget._on_toggle(True)

    # Try to add with different case
    widget.add_edit.setText("test")
    widget._on_add_tag()

    # Should still only have one tag
    tags = fresh_db.get_tags_for_page(date_iso)
    assert len(tags) == 1


def test_page_tags_widget_remove_tag(app, fresh_db):
    """Test removing a tag through the widget"""
    widget = PageTagsWidget(fresh_db)
    date_iso = "2024-01-15"

    fresh_db.set_tags_for_page(date_iso, ["tag1", "tag2"])
    widget.set_current_date(date_iso)
    widget.toggle_btn.setChecked(True)
    widget._on_toggle(True)

    # Get the first tag's ID
    tags = fresh_db.get_tags_for_page(date_iso)
    tag_id = tags[0][0]

    # Remove it
    widget._remove_tag(tag_id)

    # Verify tag was removed
    remaining_tags = fresh_db.get_tags_for_page(date_iso)
    assert len(remaining_tags) == 1


def test_page_tags_widget_empty_input_ignored(app, fresh_db):
    """Test that empty tag input is ignored"""
    widget = PageTagsWidget(fresh_db)
    date_iso = "2024-01-15"

    widget.set_current_date(date_iso)
    widget.toggle_btn.setChecked(True)
    widget._on_toggle(True)

    # Try to add empty tag
    widget.add_edit.setText("")
    widget._on_add_tag()

    tags = fresh_db.get_tags_for_page(date_iso)
    assert len(tags) == 0


def test_page_tags_widget_whitespace_trimmed(app, fresh_db):
    """Test that whitespace is trimmed from tags"""
    widget = PageTagsWidget(fresh_db)
    date_iso = "2024-01-15"

    widget.set_current_date(date_iso)
    widget.toggle_btn.setChecked(True)
    widget._on_toggle(True)

    # Add tag with whitespace
    widget.add_edit.setText("  spaced  ")
    widget._on_add_tag()

    tags = fresh_db.get_tags_for_page(date_iso)
    assert tags[0][1] == "spaced"


def test_page_tags_widget_autocomplete_setup(app, fresh_db):
    """Test that autocomplete is set up with existing tags"""
    widget = PageTagsWidget(fresh_db)

    # Create some tags
    fresh_db.set_tags_for_page("2024-01-15", ["alpha", "beta", "gamma"])

    # Setup autocomplete
    widget._setup_autocomplete()

    completer = widget.add_edit.completer()
    assert completer is not None

    # Check that model contains the tags
    model = completer.model()
    items = [model.index(i, 0).data() for i in range(model.rowCount())]
    assert "alpha" in items
    assert "beta" in items
    assert "gamma" in items


def test_page_tags_widget_signal_tag_added(app, fresh_db):
    """Test that tagAdded signal is emitted when tag is added"""
    widget = PageTagsWidget(fresh_db)
    date_iso = "2024-01-15"

    widget.set_current_date(date_iso)

    signal_emitted = {"emitted": False}

    def on_tag_added():
        signal_emitted["emitted"] = True

    widget.tagAdded.connect(on_tag_added)

    widget.add_edit.setText("testtag")
    widget._on_add_tag()

    assert signal_emitted["emitted"]


def test_page_tags_widget_signal_tag_activated(app, fresh_db):
    """Test that tagActivated signal is emitted when tag is clicked"""
    widget = PageTagsWidget(fresh_db)
    date_iso = "2024-01-15"

    fresh_db.set_tags_for_page(date_iso, ["clickable"])
    widget.set_current_date(date_iso)
    widget.toggle_btn.setChecked(True)
    widget._on_toggle(True)

    signal_data = {"tag_name": None}

    def on_tag_activated(name):
        signal_data["tag_name"] = name

    widget.tagActivated.connect(on_tag_activated)
    widget._on_chip_clicked("clickable")

    assert signal_data["tag_name"] == "clickable"


# ============================================================================
# TagChip Tests
# ============================================================================


def test_tag_chip_creation(app):
    """Test that TagChip can be created"""
    chip = TagChip(1, "test", "#FF0000")
    assert chip is not None
    assert chip.tag_id == 1


def test_tag_chip_with_remove_button(app):
    """Test TagChip with remove button"""
    chip = TagChip(1, "test", "#FF0000", show_remove=True)

    # Find the remove button (should be a QToolButton with text "×")
    buttons = chip.findChildren(object)
    assert any(hasattr(b, "text") and b.text() == "×" for b in buttons)


def test_tag_chip_without_remove_button(app):
    """Test TagChip without remove button"""
    chip = TagChip(1, "test", "#FF0000", show_remove=False)

    # Should not have remove button
    buttons = chip.findChildren(object)
    assert not any(hasattr(b, "text") and b.text() == "×" for b in buttons)


def test_tag_chip_color_display(app):
    """Test that TagChip displays the correct color"""
    chip = TagChip(1, "test", "#FF0000")

    # Find the color label
    labels = chip.findChildren(object)
    color_labels = [
        l
        for l in labels
        if hasattr(l, "styleSheet") and "background-color" in str(l.styleSheet())
    ]

    assert len(color_labels) > 0
    assert (
        "#FF0000" in color_labels[0].styleSheet()
        or "rgb(255, 0, 0)" in color_labels[0].styleSheet()
    )


def test_tag_chip_remove_signal(app):
    """Test that TagChip emits removeRequested signal"""
    chip = TagChip(1, "test", "#FF0000", show_remove=True)

    signal_data = {"tag_id": None}

    def on_remove(tag_id):
        signal_data["tag_id"] = tag_id

    chip.removeRequested.connect(on_remove)
    chip.removeRequested.emit(1)

    assert signal_data["tag_id"] == 1


def test_tag_chip_clicked_signal(app):
    """Test that TagChip emits clicked signal"""
    chip = TagChip(1, "test", "#FF0000")

    signal_data = {"tag_name": None}

    def on_clicked(name):
        signal_data["tag_name"] = name

    chip.clicked.connect(on_clicked)
    chip.clicked.emit("test")

    assert signal_data["tag_name"] == "test"


# ============================================================================
# TagBrowserDialog Tests
# ============================================================================


def test_tag_browser_creation(app, fresh_db):
    """Test that TagBrowserDialog can be created"""
    dialog = TagBrowserDialog(fresh_db)
    assert dialog is not None


def test_tag_browser_displays_tags(app, fresh_db):
    """Test that TagBrowserDialog displays tags in tree"""
    fresh_db.set_tags_for_page("2024-01-15", ["tag1", "tag2"])
    fresh_db.save_new_version("2024-01-15", "Content", "note")

    dialog = TagBrowserDialog(fresh_db)

    # Tree should have top-level items for each tag
    assert dialog.tree.topLevelItemCount() == 2


def test_tag_browser_tag_with_pages(app, fresh_db):
    """Test that TagBrowserDialog shows pages under tags"""
    fresh_db.save_new_version("2024-01-15", "Content 1", "note")
    fresh_db.save_new_version("2024-01-16", "Content 2", "note")
    fresh_db.set_tags_for_page("2024-01-15", ["work"])
    fresh_db.set_tags_for_page("2024-01-16", ["work"])

    dialog = TagBrowserDialog(fresh_db)

    # Find the "work" tag item
    root = dialog.tree.topLevelItem(0)

    # Should have 2 child items (the dates)
    assert root.childCount() == 2


def test_tag_browser_focus_tag(app, fresh_db):
    """Test that TagBrowserDialog can focus on a specific tag"""
    fresh_db.set_tags_for_page("2024-01-15", ["alpha", "beta"])

    dialog = TagBrowserDialog(fresh_db, focus_tag="beta")

    # The focused tag should be expanded and selected
    current_item = dialog.tree.currentItem()
    assert current_item is not None


def test_tag_browser_color_display(app, fresh_db):
    """Test that tags display their colors in the browser"""
    fresh_db.set_tags_for_page("2024-01-15", ["colorful"])

    dialog = TagBrowserDialog(fresh_db)

    root = dialog.tree.topLevelItem(0)
    # Color should be shown in column 1
    color_text = root.text(1)
    assert color_text.startswith("#")


def test_tag_browser_edit_name_button_disabled(app, fresh_db):
    """Test that edit button is disabled when no tag selected"""
    dialog = TagBrowserDialog(fresh_db)

    assert not dialog.edit_name_btn.isEnabled()


def test_tag_browser_edit_name_button_enabled(app, fresh_db):
    """Test that edit button is enabled when tag selected"""
    fresh_db.set_tags_for_page("2024-01-15", ["test"])

    dialog = TagBrowserDialog(fresh_db)

    # Select the first item
    item = dialog.tree.topLevelItem(0)
    dialog.tree.setCurrentItem(item)
    dialog._on_item_clicked(item, 0)

    assert dialog.edit_name_btn.isEnabled()


def test_tag_browser_delete_button_state(app, fresh_db):
    """Test that delete button state changes with selection"""
    fresh_db.set_tags_for_page("2024-01-15", ["test"])

    dialog = TagBrowserDialog(fresh_db)

    # Initially disabled
    assert not dialog.delete_btn.isEnabled()

    # Select a tag
    item = dialog.tree.topLevelItem(0)
    dialog.tree.setCurrentItem(item)
    dialog._on_item_clicked(item, 0)

    # Should be enabled now
    assert dialog.delete_btn.isEnabled()


def test_tag_browser_change_color_button_state(app, fresh_db):
    """Test that change color button state changes with selection"""
    fresh_db.set_tags_for_page("2024-01-15", ["test"])

    dialog = TagBrowserDialog(fresh_db)

    # Initially disabled
    assert not dialog.change_color_btn.isEnabled()

    # Select a tag
    item = dialog.tree.topLevelItem(0)
    dialog.tree.setCurrentItem(item)
    dialog._on_item_clicked(item, 0)

    # Should be enabled now
    assert dialog.change_color_btn.isEnabled()


def test_tag_browser_open_date_signal(app, fresh_db):
    """Test that clicking a date emits openDateRequested signal"""
    fresh_db.save_new_version("2024-01-15", "Content", "note")
    fresh_db.set_tags_for_page("2024-01-15", ["test"])

    dialog = TagBrowserDialog(fresh_db)

    signal_data = {"date": None}

    def on_date_requested(date_iso):
        signal_data["date"] = date_iso

    dialog.openDateRequested.connect(on_date_requested)

    # Get the tag item and expand it
    root = dialog.tree.topLevelItem(0)
    dialog.tree.expandItem(root)

    # Get the date child item
    date_item = root.child(0)

    # Simulate activation
    dialog._on_item_activated(date_item, 0)

    assert signal_data["date"] == "2024-01-15"


# ============================================================================
# Integration Tests
# ============================================================================


def test_tag_workflow_end_to_end(app, fresh_db, tmp_path):
    """Test complete tag workflow: create, list, update, delete"""
    # Create some entries with tags
    dates = ["2024-01-15", "2024-01-16", "2024-01-17"]
    for date in dates:
        fresh_db.save_new_version(date, f"Entry {date}", "note")

    fresh_db.set_tags_for_page(dates[0], ["work", "urgent"])
    fresh_db.set_tags_for_page(dates[1], ["work", "meeting"])
    fresh_db.set_tags_for_page(dates[2], ["personal"])

    # List all tags - should be 4 unique tags: work, urgent, meeting, personal
    all_tags = fresh_db.list_tags()
    assert len(all_tags) == 4

    # Get pages for "work" tag
    work_pages = fresh_db.get_pages_for_tag("work")
    work_dates = [d for d, _ in work_pages]
    assert dates[0] in work_dates
    assert dates[1] in work_dates
    assert dates[2] not in work_dates

    # Update a tag
    work_tag = [t for t in all_tags if t[1] == "work"][0]
    fresh_db.update_tag(work_tag[0], "office", "#0000FF")

    # Verify update
    updated_tags = fresh_db.list_tags()
    office_tag = [t for t in updated_tags if t[1] == "office"][0]
    assert office_tag[2] == "#0000FF"

    # Delete a tag
    urgent_tag = [t for t in all_tags if t[1] == "urgent"][0]
    fresh_db.delete_tag(urgent_tag[0])

    # Verify deletion - should have 3 tags now (office, meeting, personal)
    final_tags = fresh_db.list_tags()
    tag_names = [t[1] for t in final_tags]
    assert "urgent" not in tag_names
    assert len(final_tags) == 3


def test_tags_with_export(fresh_db, tmp_path):
    """Test that tags are preserved during export operations"""
    date_iso = "2024-01-15"
    fresh_db.save_new_version(date_iso, "Content", "note")
    fresh_db.set_tags_for_page(date_iso, ["exported", "preserved"])

    # Export to JSON
    entries = fresh_db.get_all_entries()
    json_path = tmp_path / "export.json"
    fresh_db.export_json(entries, str(json_path))

    assert json_path.exists()

    # Tags should still be in database
    tags = fresh_db.get_tags_for_page(date_iso)
    assert len(tags) == 2


def test_tags_survive_rekey(fresh_db, tmp_db_cfg):
    """Test that tags persist after database rekey"""
    date_iso = "2024-01-15"
    fresh_db.save_new_version(date_iso, "Content", "note")
    fresh_db.set_tags_for_page(date_iso, ["persistent"])

    # Rekey the database
    fresh_db.rekey("new-key-456")
    fresh_db.close()

    # Reopen with new key
    tmp_db_cfg.key = "new-key-456"
    db2 = DBManager(tmp_db_cfg)
    assert db2.connect()

    # Tags should still be there
    tags = db2.get_tags_for_page(date_iso)
    assert len(tags) == 1
    assert tags[0][1] == "persistent"
    db2.close()


def test_multiple_pages_same_tags(fresh_db):
    """Test multiple pages can share the same tags"""
    dates = ["2024-01-15", "2024-01-16", "2024-01-17"]

    for date in dates:
        fresh_db.save_new_version(date, f"Content {date}", "note")
        fresh_db.set_tags_for_page(date, ["shared", "tag"])

    # All pages should have the tags
    for date in dates:
        tags = fresh_db.get_tags_for_page(date)
        tag_names = [name for _, name, _ in tags]
        assert "shared" in tag_names
        assert "tag" in tag_names

    # But there should only be 2 unique tags in the database
    all_tags = fresh_db.list_tags()
    assert len(all_tags) == 2


def test_tag_page_without_content(fresh_db):
    """Test that pages can have tags even without content"""
    date_iso = "2024-01-15"

    # Set tags without saving any content
    fresh_db.set_tags_for_page(date_iso, ["tagonly"])

    # Tags should be retrievable
    tags = fresh_db.get_tags_for_page(date_iso)
    assert len(tags) == 1
    assert tags[0][1] == "tagonly"

    # Page should be created but with no content
    content = fresh_db.get_entry(date_iso)
    assert content is None or content == ""
