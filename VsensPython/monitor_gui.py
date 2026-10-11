"""
GUI Monitor for Vsens Agent using PySide6.
Displays real-time statistics about agent interactions, token usage,
agent status transitions, and server/agent log output.
"""
import sys
from datetime import datetime
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QGroupBox, QGridLayout, QSplitter,
    QListWidget, QListWidgetItem, QSizePolicy,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QPainter, QPen, QColor
from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis
from monitor_stats import monitor_stats

# ---------------------------------------------------------------------------
# Agent-state colour map
# ---------------------------------------------------------------------------
_STATE_COLORS = {
    "idle":         "#00cc44",
    "listening":    "#00aacc",
    "transcribing": "#ff9900",
    "thinking":     "#3380ff",
    "planning":     "#aa33ff",
    "executing":    "#ff6600",
    "speaking":     "#00cc99",
    "waiting":      "#999999",
    "scripting":    "#cc0066",
}
_STATE_DEFAULT_COLOR = "#cccccc"


class MonitorWindow(QMainWindow):
    """Main monitoring window"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Vsens Agent Monitor")
        self.setMinimumSize(1050, 820)
        self._selected_client_id = None

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        root_layout = QVBoxLayout(central_widget)
        root_layout.setSpacing(6)
        root_layout.setContentsMargins(8, 8, 8, 8)

        # ── Title ──────────────────────────────────────────────────────────
        title = QLabel("Vsens Agent Monitor")
        title_font = QFont()
        title_font.setPointSize(15)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignCenter)
        root_layout.addWidget(title)

        # ── Row 1: Server Status | Agent State ────────────────────────────
        row1 = QHBoxLayout()
        row1.addWidget(self._create_server_status_section(), stretch=1)
        row1.addWidget(self._create_agent_state_section(), stretch=1)
        row1.addWidget(self._create_clients_section(), stretch=1)
        root_layout.addLayout(row1)

        # ── Row 2: Token Chart | Token Stats ──────────────────────────────
        row2 = QHBoxLayout()
        row2.addWidget(self._create_token_chart_section(), stretch=3)
        row2.addWidget(self._create_token_stats_section(), stretch=1)
        root_layout.addLayout(row2)

        # ── Row 3: Recent Interactions (upper) + Log Console (lower) ──────
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self._create_interactions_section())
        splitter.addWidget(self._create_log_section())
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        root_layout.addWidget(splitter, stretch=1)

        # ── Control buttons ───────────────────────────────────────────────
        root_layout.addWidget(self._create_control_buttons())

        # ── Refresh timer ─────────────────────────────────────────────────
        self._update_timer = QTimer()
        self._update_timer.timeout.connect(self._refresh)
        self._update_timer.start(1000)

        self._apply_styling()

    # -----------------------------------------------------------------------
    # Section builders
    # -----------------------------------------------------------------------

    def _create_server_status_section(self):
        group = QGroupBox("Server Status")
        layout = QGridLayout()
        layout.setColumnStretch(2, 1)

        self._status_dot = QLabel("●")
        self._status_dot.setStyleSheet("color: red; font-size: 20px;")
        self._status_text = QLabel("Stopped")
        layout.addWidget(QLabel("Status:"), 0, 0)
        layout.addWidget(self._status_dot, 0, 1)
        layout.addWidget(self._status_text, 0, 2)

        layout.addWidget(QLabel("Address:"), 1, 0)
        self._address_label = QLabel("ws://localhost:8765")
        layout.addWidget(self._address_label, 1, 1, 1, 2)

        layout.addWidget(QLabel("Clients:"), 2, 0)
        self._clients_label = QLabel("0")
        layout.addWidget(self._clients_label, 2, 1, 1, 2)

        layout.addWidget(QLabel("Uptime:"), 3, 0)
        self._uptime_label = QLabel("00:00:00")
        layout.addWidget(self._uptime_label, 3, 1, 1, 2)

        layout.addWidget(QLabel("Conv. Round:"), 4, 0)
        self._round_label = QLabel("0")
        self._round_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #0066cc;")
        layout.addWidget(self._round_label, 4, 1, 1, 2)

        group.setLayout(layout)
        return group

    def _create_agent_state_section(self):
        group = QGroupBox("Agent State")
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignCenter)

        # Large coloured badge
        self._state_badge = QLabel("IDLE")
        badge_font = QFont()
        badge_font.setPointSize(22)
        badge_font.setBold(True)
        self._state_badge.setFont(badge_font)
        self._state_badge.setAlignment(Qt.AlignCenter)
        self._state_badge.setMinimumHeight(60)
        self._state_badge.setStyleSheet(
            f"color: {_STATE_COLORS['idle']}; padding: 8px;"
        )
        layout.addWidget(self._state_badge)

        # Detail label
        self._state_detail = QLabel("")
        self._state_detail.setAlignment(Qt.AlignCenter)
        self._state_detail.setWordWrap(True)
        self._state_detail.setStyleSheet("color: #666666; font-size: 11px;")
        layout.addWidget(self._state_detail)

        # State history (last 5 transitions)
        layout.addWidget(QLabel("Recent transitions:"))
        self._state_history = QTextEdit()
        self._state_history.setReadOnly(True)
        self._state_history.setMaximumHeight(70)
        self._state_history.setStyleSheet("font-size: 11px;")
        layout.addWidget(self._state_history)

        group.setLayout(layout)
        return group

    def _create_clients_section(self):
        group = QGroupBox("Connected Clients")
        layout = QVBoxLayout()
        self._clients_list = QListWidget()
        self._clients_list.currentItemChanged.connect(self._on_client_selection_changed)
        layout.addWidget(self._clients_list)
        group.setLayout(layout)
        return group

    def _create_token_chart_section(self):
        group = QGroupBox("Token Usage Trend")
        layout = QVBoxLayout()

        self._chart = QChart()
        self._chart.setAnimationOptions(QChart.NoAnimation)

        self._series_total = QLineSeries()
        self._series_total.setName("Total Tokens")
        self._series_cached = QLineSeries()
        self._series_cached.setName("Cached Tokens")

        pen_total = QPen(QColor("#3380ff"))
        pen_total.setWidth(2)
        self._series_total.setPen(pen_total)

        pen_cached = QPen(QColor("#00cc44"))
        pen_cached.setWidth(2)
        self._series_cached.setPen(pen_cached)

        self._chart.addSeries(self._series_total)
        self._chart.addSeries(self._series_cached)

        self._axis_x = QValueAxis()
        self._axis_x.setTitleText("Interaction #")
        self._axis_x.setLabelFormat("%d")
        self._axis_x.setRange(0, 10)

        self._axis_y = QValueAxis()
        self._axis_y.setTitleText("Tokens")
        self._axis_y.setLabelFormat("%d")
        self._axis_y.setRange(0, 1000)

        self._chart.addAxis(self._axis_x, Qt.AlignBottom)
        self._chart.addAxis(self._axis_y, Qt.AlignLeft)
        self._series_total.attachAxis(self._axis_x)
        self._series_total.attachAxis(self._axis_y)
        self._series_cached.attachAxis(self._axis_x)
        self._series_cached.attachAxis(self._axis_y)

        chart_view = QChartView(self._chart)
        chart_view.setRenderHint(QPainter.Antialiasing)
        chart_view.setMinimumHeight(230)
        layout.addWidget(chart_view)

        group.setLayout(layout)
        return group

    def _create_token_stats_section(self):
        group = QGroupBox("Token Usage")
        layout = QGridLayout()

        def _row(label, row):
            layout.addWidget(QLabel(label), row, 0)

        _row("Total Tokens:", 0)
        self._lbl_total = QLabel("0")
        self._lbl_total.setStyleSheet("font-weight: bold; color: #3380ff;")
        layout.addWidget(self._lbl_total, 0, 1)

        _row("Prompt Tokens:", 1)
        self._lbl_prompt = QLabel("0")
        layout.addWidget(self._lbl_prompt, 1, 1)

        _row("Completion:", 2)
        self._lbl_completion = QLabel("0")
        layout.addWidget(self._lbl_completion, 2, 1)

        _row("Cached Tokens:", 3)
        self._lbl_cached = QLabel("0")
        self._lbl_cached.setStyleSheet("color: #00cc44;")
        layout.addWidget(self._lbl_cached, 3, 1)

        _row("Cache Hit Rate:", 4)
        self._lbl_cache_rate = QLabel("0.0%")
        self._lbl_cache_rate.setStyleSheet("color: #00cc44;")
        layout.addWidget(self._lbl_cache_rate, 4, 1)

        group.setLayout(layout)
        return group

    def _create_interactions_section(self):
        group = QGroupBox("Recent Interactions")
        layout = QVBoxLayout()

        self._interactions_text = QTextEdit()
        self._interactions_text.setReadOnly(True)
        self._interactions_text.setMinimumHeight(180)
        layout.addWidget(self._interactions_text)

        group.setLayout(layout)
        return group

    def _create_log_section(self):
        group = QGroupBox("Server / Agent Log")
        layout = QVBoxLayout()

        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setMinimumHeight(120)
        self._log_text.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 11px; "
            "background: #1e1e1e; color: #d4d4d4;"
        )
        layout.addWidget(self._log_text)

        group.setLayout(layout)
        return group

    def _create_control_buttons(self):
        widget = QWidget()
        layout = QHBoxLayout()
        layout.addStretch()

        # ── Export Log button ──────────────────────────────────────────
        self._export_btn = QPushButton("Export Log")
        self._export_btn.setStyleSheet("""
            QPushButton {
                padding: 8px 24px;
                border-radius: 4px;
                background-color: #1565c0;
                color: white;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #0d47a1; }
            QPushButton:pressed { background-color: #0a3576; }
        """)
        self._export_btn.clicked.connect(self._export_log)
        layout.addWidget(self._export_btn)

        # ── Export status label ────────────────────────────────────────
        self._export_status_lbl = QLabel("")
        self._export_status_lbl.setStyleSheet("color: #00aa44; font-size: 11px;")
        layout.addWidget(self._export_status_lbl)

        layout.addSpacing(20)

        # ── Stop Server button ────────────────────────────────────────
        self._stop_btn = QPushButton("Stop Server")
        self._stop_btn.setStyleSheet("""
            QPushButton {
                padding: 8px 24px;
                border-radius: 4px;
                background-color: #d32f2f;
                color: white;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #c62828; }
            QPushButton:pressed { background-color: #b71c1c; }
        """)
        self._stop_btn.clicked.connect(self._stop_server)
        layout.addWidget(self._stop_btn)

        layout.addStretch()
        widget.setLayout(layout)
        return widget

    # -----------------------------------------------------------------------
    # Refresh logic
    # -----------------------------------------------------------------------

    def _refresh(self):
        global_stats = monitor_stats.get_stats_snapshot()
        stats = monitor_stats.get_stats_snapshot(client_id=self._selected_client_id)

        # Server status
        running = global_stats["is_server_running"]
        if running:
            self._status_dot.setStyleSheet("color: #00cc44; font-size: 20px;")
            self._status_text.setText("Running")
        else:
            self._status_dot.setStyleSheet("color: red; font-size: 20px;")
            self._status_text.setText("Stopped")

        self._clients_label.setText(str(global_stats["current_clients"]))
        uptime = int(global_stats["server_uptime"])
        self._uptime_label.setText(
            f"{uptime // 3600:02d}:{(uptime % 3600) // 60:02d}:{uptime % 60:02d}"
        )
        self._round_label.setText(str(stats["conversation_round"]))
        self._refresh_client_list(global_stats.get("clients", []))

        # Agent state badge
        state = stats.get("agent_state", "idle")
        color = _STATE_COLORS.get(state, _STATE_DEFAULT_COLOR)
        self._state_badge.setText(state.upper())
        self._state_badge.setStyleSheet(f"color: {color}; padding: 8px; font-weight: bold;")

        # State history from log entries that contain "[AgentStatus]"
        state_lines = [
            l for l in stats.get("recent_logs", []) if "[AgentStatus]" in l
        ][-5:]
        self._state_history.setPlainText("\n".join(state_lines))

        # Token stats
        self._lbl_total.setText(f"{stats['total_tokens']:,}")
        self._lbl_prompt.setText(f"{stats['total_prompt_tokens']:,}")
        self._lbl_completion.setText(f"{stats['total_completion_tokens']:,}")
        self._lbl_cached.setText(f"{stats['total_cached_tokens']:,}")
        self._lbl_cache_rate.setText(f"{stats['cache_hit_rate']:.1f}%")

        # Chart
        self._refresh_chart(stats["recent_interactions"])

        # Interactions log
        self._refresh_interactions(stats["recent_interactions"])

        # Log console
        self._refresh_log(stats.get("recent_logs", []))

    def _refresh_chart(self, interactions):
        self._series_total.clear()
        self._series_cached.clear()

        items = interactions[-20:] if len(interactions) > 20 else interactions
        if not items:
            return

        max_tokens = 0
        for idx, rec in enumerate(items, 1):
            self._series_total.append(idx, rec.total_tokens)
            self._series_cached.append(idx, rec.cached_tokens)
            max_tokens = max(max_tokens, rec.total_tokens)

        self._axis_x.setRange(0, max(len(items) + 1, 10))
        self._axis_y.setRange(0, max(int(max_tokens * 1.2), 100))

    def _refresh_interactions(self, interactions):
        lines = []
        for rec in interactions:
            ts = rec.timestamp.strftime("%H:%M:%S")
            lines.append(
                f"[{ts}] [{rec.interaction_type}] "
                f"Tokens: {rec.total_tokens:,}  Cached: {rec.cached_tokens:,}"
            )
            lines.append(f"  User : {rec.user_input}")
            lines.append(f"  Agent: {rec.agent_reply}")
            lines.append("─" * 80)
        self._interactions_text.setPlainText("\n".join(lines))
        sb = self._interactions_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _refresh_log(self, log_entries):
        text = "\n".join(log_entries)
        if self._log_text.toPlainText() == text:
            return  # nothing changed
        self._log_text.setPlainText(text)
        sb = self._log_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _refresh_client_list(self, clients):
        self._clients_list.blockSignals(True)
        self._clients_list.clear()

        all_item = QListWidgetItem("All Clients")
        all_item.setData(Qt.UserRole, None)
        self._clients_list.addItem(all_item)

        for client in clients:
            item = QListWidgetItem(f"{client['username']} / {client['us']} ({client['client_id']})")
            item.setData(Qt.UserRole, client["client_id"])
            self._clients_list.addItem(item)

        selected_row = 0
        for row in range(self._clients_list.count()):
            if self._clients_list.item(row).data(Qt.UserRole) == self._selected_client_id:
                selected_row = row
                break
        self._clients_list.setCurrentRow(selected_row)
        self._clients_list.blockSignals(False)

    def _on_client_selection_changed(self, current, previous):
        if current is None:
            self._selected_client_id = None
            return
        self._selected_client_id = current.data(Qt.UserRole)

    # -----------------------------------------------------------------------
    # Actions
    # -----------------------------------------------------------------------

    def _export_log(self) -> None:
        """Export the full session log to data/logs/ with an auto-generated name."""
        log_dir = Path(__file__).parent / "data" / "logs"
        try:
            filepath = monitor_stats.export_log(str(log_dir), client_id=self._selected_client_id)
            short = Path(filepath).name
            self._export_status_lbl.setText(f"Saved: {short}")
            monitor_stats.add_log(f"[Monitor] Log exported → {filepath}")
            # Clear the status label after 5 seconds
            QTimer.singleShot(5000, lambda: self._export_status_lbl.setText(""))
        except Exception as exc:
            self._export_status_lbl.setStyleSheet("color: #cc0000; font-size: 11px;")
            self._export_status_lbl.setText(f"Export failed: {exc}")
            monitor_stats.add_log(f"[Monitor] Log export failed: {exc}")

    def _stop_server(self):
        monitor_stats.set_server_running(False)
        monitor_stats.add_log("[Monitor] Stop requested — shutting down.")
        print("[Monitor] Stopping server and exiting application...")
        QApplication.quit()

    # -----------------------------------------------------------------------
    # Styling
    # -----------------------------------------------------------------------

    def _apply_styling(self):
        self.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #cccccc;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)


def run_monitor_gui():
    """Run the monitor GUI application (blocking — call from the main thread)."""
    app = QApplication.instance() or QApplication(sys.argv)
    window = MonitorWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    run_monitor_gui()
