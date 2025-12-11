from unittest.mock import Mock, patch

from bouquin.pomodoro_timer import PomodoroManager, PomodoroTimer
from bouquin.theme import Theme, ThemeConfig, ThemeManager
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel, QToolBar, QVBoxLayout, QWidget


class DummyTimeLogWidget(QWidget):
    """Minimal stand-in for the real TimeLogWidget used by PomodoroManager."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.summary_label = QLabel(self)
        # toggle_btn and _reload_summary are used by PomodoroManager._on_timer_stopped
        self.toggle_btn = Mock()
        self.toggle_btn.isChecked.return_value = True

    def show_pomodoro_widget(self, widget):
        # Manager calls this when embedding the timer
        if widget is not None:
            self.layout.addWidget(widget)

    def clear_pomodoro_widget(self):
        # Manager calls this when removing the embedded timer
        while self.layout.count():
            item = self.layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

    def _reload_summary(self):
        # Called after TimeLogDialog closes; no-op is fine for tests
        pass


class DummyMainWindow(QWidget):
    """Minimal stand-in for MainWindow that PomodoroManager expects."""

    def __init__(self, app, parent=None):
        super().__init__(parent)
        # Sidebar time log widget
        self.time_log = DummyTimeLogWidget(self)

        # Toolbar with an actTimer QAction so QSignalBlocker works
        self.toolBar = QToolBar(self)
        self.toolBar.actTimer = QAction(self)
        self.toolBar.addAction(self.toolBar.actTimer)

        # Themes attribute used when constructing TimeLogDialog
        self.themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))


def test_pomodoro_timer_init(qtbot, app, fresh_db):
    """Test PomodoroTimer initialization."""
    task_text = "Write unit tests"
    timer = PomodoroTimer(task_text)
    qtbot.addWidget(timer)

    assert timer._task_text == task_text
    assert timer._elapsed_seconds == 0
    assert timer._running is False
    assert timer.time_label.text() == "00:00:00"
    assert timer.stop_btn.isEnabled() is False


def test_pomodoro_timer_start(qtbot, app):
    """Test starting the timer."""
    timer = PomodoroTimer("Test task")
    qtbot.addWidget(timer)

    timer._toggle_timer()

    assert timer._running is True
    assert timer.stop_btn.isEnabled() is True


def test_pomodoro_timer_pause(qtbot, app):
    """Test pausing the timer."""
    timer = PomodoroTimer("Test task")
    qtbot.addWidget(timer)

    # Start the timer
    timer._toggle_timer()
    assert timer._running is True

    # Pause the timer
    timer._toggle_timer()
    assert timer._running is False


def test_pomodoro_timer_resume(qtbot, app):
    """Test resuming the timer after pause."""
    timer = PomodoroTimer("Test task")
    qtbot.addWidget(timer)

    # Start, pause, then resume
    timer._toggle_timer()  # Start
    timer._toggle_timer()  # Pause
    timer._toggle_timer()  # Resume

    assert timer._running is True


def test_pomodoro_timer_tick(qtbot, app):
    """Test timer tick increments elapsed time."""
    timer = PomodoroTimer("Test task")
    qtbot.addWidget(timer)

    initial_time = timer._elapsed_seconds
    timer._tick()

    assert timer._elapsed_seconds == initial_time + 1


def test_pomodoro_timer_display_update(qtbot, app):
    """Test display updates with various elapsed times."""
    timer = PomodoroTimer("Test task")
    qtbot.addWidget(timer)

    # Test 0 seconds
    timer._elapsed_seconds = 0
    timer._update_display()
    assert timer.time_label.text() == "00:00:00"

    # Test 65 seconds (1 min 5 sec)
    timer._elapsed_seconds = 65
    timer._update_display()
    assert timer.time_label.text() == "00:01:05"

    # Test 3665 seconds (1 hour 1 min 5 sec)
    timer._elapsed_seconds = 3665
    timer._update_display()
    assert timer.time_label.text() == "01:01:05"

    # Test 3600 seconds (1 hour exactly)
    timer._elapsed_seconds = 3600
    timer._update_display()
    assert timer.time_label.text() == "01:00:00"


def test_pomodoro_timer_stop_and_log_running(qtbot, app):
    """Test stopping the timer while it's running."""
    timer = PomodoroTimer("Test task")
    qtbot.addWidget(timer)

    # Start the timer
    timer._toggle_timer()
    timer._elapsed_seconds = 100

    # Connect a mock to the signal
    signal_received = []
    timer.timerStopped.connect(lambda s, t: signal_received.append((s, t)))

    timer._stop_and_log()

    assert timer._running is False
    assert len(signal_received) == 1
    assert signal_received[0][0] == 100  # elapsed seconds
    assert signal_received[0][1] == "Test task"


def test_pomodoro_timer_stop_and_log_paused(qtbot, app):
    """Test stopping the timer when it's paused."""
    timer = PomodoroTimer("Test task")
    qtbot.addWidget(timer)

    timer._elapsed_seconds = 50

    signal_received = []
    timer.timerStopped.connect(lambda s, t: signal_received.append((s, t)))

    timer._stop_and_log()

    assert len(signal_received) == 1
    assert signal_received[0][0] == 50


def test_pomodoro_timer_multiple_ticks(qtbot, app):
    """Test multiple timer ticks."""
    timer = PomodoroTimer("Test task")
    qtbot.addWidget(timer)

    for i in range(10):
        timer._tick()

    assert timer._elapsed_seconds == 10
    assert "00:00:10" in timer.time_label.text()


def test_pomodoro_timer_modal_state(qtbot, app):
    """Test that timer is non-modal."""
    timer = PomodoroTimer("Test task")
    qtbot.addWidget(timer)

    assert timer.isModal() is False


def test_pomodoro_manager_init(app, fresh_db):
    """Test PomodoroManager initialization."""
    parent = Mock()
    manager = PomodoroManager(fresh_db, parent)

    assert manager._db is fresh_db
    assert manager._parent is parent
    assert manager._active_timer is None


def test_pomodoro_manager_start_timer(qtbot, app, fresh_db):
    """Test starting a timer through the manager."""
    parent = DummyMainWindow(app)
    qtbot.addWidget(parent)
    qtbot.addWidget(parent.time_log)

    manager = PomodoroManager(fresh_db, parent)

    line_text = "Important task"
    date_iso = "2024-01-15"

    manager.start_timer_for_line(line_text, date_iso)

    assert manager._active_timer is not None
    assert manager._active_timer._task_text == line_text
    # Timer should be embedded in the sidebar time log widget
    assert manager._active_timer.parent() is parent.time_log


def test_pomodoro_manager_replace_active_timer(qtbot, app, fresh_db):
    """Test that starting a new timer closes/replaces the previous one."""
    parent = DummyMainWindow(app)
    qtbot.addWidget(parent)
    qtbot.addWidget(parent.time_log)

    manager = PomodoroManager(fresh_db, parent)

    # Start first timer
    manager.start_timer_for_line("Task 1", "2024-01-15")
    first_timer = manager._active_timer
    qtbot.addWidget(first_timer)
    first_timer.show()

    # Start second timer
    manager.start_timer_for_line("Task 2", "2024-01-16")
    second_timer = manager._active_timer
    qtbot.addWidget(second_timer)

    assert first_timer is not second_timer
    assert second_timer._task_text == "Task 2"
    assert second_timer.parent() is parent.time_log


def test_pomodoro_manager_on_timer_stopped_minimum_hours(
    qtbot, app, fresh_db, monkeypatch
):
    """Timer stopped with very short time logs should enforce minimum hours."""
    parent = DummyMainWindow(app)
    qtbot.addWidget(parent)
    qtbot.addWidget(parent.time_log)

    manager = PomodoroManager(fresh_db, parent)

    # Mock TimeLogDialog to avoid showing it
    mock_dialog = Mock()
    mock_dialog.hours_spin = Mock()
    mock_dialog.note = Mock()
    mock_dialog.exec = Mock()

    with patch("bouquin.pomodoro_timer.TimeLogDialog", return_value=mock_dialog):
        manager._on_timer_stopped(10, "Quick task", "2024-01-15")

        # Should set minimum of 0.25 hours
        mock_dialog.hours_spin.setValue.assert_called_once()
        hours_set = mock_dialog.hours_spin.setValue.call_args[0][0]
        assert hours_set >= 0.25


def test_pomodoro_manager_on_timer_stopped_rounding(qtbot, app, fresh_db, monkeypatch):
    """Elapsed time should be rounded up to the nearest 0.25 hours."""
    parent = DummyMainWindow(app)
    qtbot.addWidget(parent)
    qtbot.addWidget(parent.time_log)

    manager = PomodoroManager(fresh_db, parent)

    mock_dialog = Mock()
    mock_dialog.hours_spin = Mock()
    mock_dialog.note = Mock()
    mock_dialog.exec = Mock()

    with patch("bouquin.pomodoro_timer.TimeLogDialog", return_value=mock_dialog):
        # 1800 seconds (30 min) should round up to 0.5
        manager._on_timer_stopped(1800, "Task", "2024-01-15")

        mock_dialog.hours_spin.setValue.assert_called_once()
        hours_set = mock_dialog.hours_spin.setValue.call_args[0][0]

        assert hours_set > 0
        # Should be a multiple of 0.25
        assert hours_set * 4 == int(hours_set * 4)


def test_pomodoro_manager_on_timer_stopped_prefills_note(
    qtbot, app, fresh_db, monkeypatch
):
    """Timer stopped should pre-fill the note in the time log dialog."""
    parent = DummyMainWindow(app)
    qtbot.addWidget(parent)
    qtbot.addWidget(parent.time_log)

    manager = PomodoroManager(fresh_db, parent)

    mock_dialog = Mock()
    mock_dialog.hours_spin = Mock()
    mock_dialog.note = Mock()
    mock_dialog.exec = Mock()

    task_text = "Write documentation"

    with patch("bouquin.pomodoro_timer.TimeLogDialog", return_value=mock_dialog):
        manager._on_timer_stopped(3600, task_text, "2024-01-15")

        mock_dialog.note.setText.assert_called_once_with(task_text)


def test_pomodoro_manager_timer_stopped_signal_connection(
    qtbot, app, fresh_db, monkeypatch
):
    """Timer's stop button should result in TimeLogDialog being executed."""
    parent = DummyMainWindow(app)
    qtbot.addWidget(parent)
    qtbot.addWidget(parent.time_log)

    manager = PomodoroManager(fresh_db, parent)

    # Mock TimeLogDialog
    mock_dialog = Mock()
    mock_dialog.hours_spin = Mock()
    mock_dialog.note = Mock()
    mock_dialog.exec = Mock()

    with patch("bouquin.pomodoro_timer.TimeLogDialog", return_value=mock_dialog):
        manager.start_timer_for_line("Task", "2024-01-15")
        timer = manager._active_timer
        qtbot.addWidget(timer)

        # Simulate timer having run for a bit
        timer._elapsed_seconds = 1000

        # Clicking "Stop and log" should emit timerStopped and open the dialog
        timer._stop_and_log()

        assert mock_dialog.exec.called


def test_pomodoro_timer_accepts_parent(qtbot, app):
    """Test that timer accepts a parent widget."""
    from PySide6.QtWidgets import QWidget

    parent = QWidget()
    qtbot.addWidget(parent)
    timer = PomodoroTimer("Task", parent)
    qtbot.addWidget(timer)

    assert timer.parent() is parent


def test_pomodoro_manager_no_active_timer_initially(app, fresh_db):
    """Test that manager starts with no active timer."""
    parent = Mock()
    manager = PomodoroManager(fresh_db, parent)

    assert manager._active_timer is None


def test_pomodoro_timer_start_stop_cycle(qtbot, app):
    """Test a complete start-stop cycle."""
    timer = PomodoroTimer("Complete cycle")
    qtbot.addWidget(timer)

    signal_received = []
    timer.timerStopped.connect(lambda s, t: signal_received.append((s, t)))

    # Start
    timer._toggle_timer()
    assert timer._running is True

    # Simulate some ticks
    for _ in range(5):
        timer._tick()

    # Stop
    timer._stop_and_log()
    assert timer._running is False
    assert len(signal_received) == 1
    assert signal_received[0][0] == 5


def test_pomodoro_timer_long_elapsed_time(qtbot, app):
    """Test display with very long elapsed time."""
    timer = PomodoroTimer("Long task")
    qtbot.addWidget(timer)

    # Set to 2 hours, 34 minutes, 56 seconds
    timer._elapsed_seconds = 2 * 3600 + 34 * 60 + 56
    timer._update_display()

    assert timer.time_label.text() == "02:34:56"
