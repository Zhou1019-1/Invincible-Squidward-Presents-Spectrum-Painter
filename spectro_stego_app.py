# -*- coding: utf-8 -*-
"""
音频频谱隐写工具 - 图形界面（纯 PyQt，无 matplotlib 依赖，启动快、体积小）
在频谱图上框选区域，将文字嵌入超声波频段，导出 24-bit/192kHz WAV/FLAC
"""
import os
import sys
import traceback
import numpy as np

from PyQt5.QtCore import Qt, QThread, pyqtSignal, QRect, QPoint
from PyQt5.QtGui import QImage, QPixmap, QPainter, QPen, QColor, QFont, QIcon
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QLabel, QLineEdit, QSpinBox, QComboBox, QSlider,
    QCheckBox,
    QFileDialog, QMessageBox, QProgressBar, QGroupBox, QFormLayout,
)

import stego_core as core


def resource_path(rel):
    """兼容开发环境与 PyInstaller 打包后的资源路径"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


# ---------- Spek 风格 hot 配色 LUT ----------
def _hot_lut():
    x = np.arange(256, dtype=np.float32) / 255.0
    r = np.clip(3.0 * x, 0, 1)
    g = np.clip(3.0 * x - 1.0, 0, 1)
    b = np.clip(3.0 * x - 2.0, 0, 1)
    return (np.stack([r, g, b], axis=1) * 255).astype(np.uint8)

HOT_LUT = _hot_lut()


class SpectrogramWidget(QWidget):
    """纯 Qt 频谱图控件，支持鼠标拖框选择 时间×频率 区域"""
    regionSelected = pyqtSignal(float, float, float, float)  # t0,t1,f0,f1 (s, kHz)

    ML, MR, MT, MB = 60, 12, 10, 30  # 坐标轴留白

    def __init__(self):
        super().__init__()
        self.setMinimumSize(500, 400)
        self.setMouseTracking(False)
        self._qimg = None          # 频谱图 QImage
        self._keep = None          # 防止 numpy 缓冲被 GC
        self.extent = None         # (t0, t1, f0, f1) 数据坐标范围
        self._drag_start = None
        self._drag_cur = None
        self.selection = None      # (t0,t1,f0,f1)

    # ---- 数据 ----
    def set_spectrogram(self, t, f_khz, S_db):
        vmin = np.percentile(S_db, 40)
        vmax = np.percentile(S_db, 99.5)
        norm = np.clip((S_db - vmin) / max(vmax - vmin, 1e-6), 0, 1)
        idx = (norm * 255).astype(np.uint8)
        rgb = HOT_LUT[idx][::-1]                    # 翻转：顶部=高频
        rgb = np.ascontiguousarray(rgb)
        self._keep = rgb
        h, w, _ = rgb.shape
        self._qimg = QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888).copy()
        self.extent = (float(t[0]), float(t[-1]),
                       float(f_khz[0]), float(f_khz[-1]))
        self.selection = None
        self.update()

    # ---- 坐标换算 ----
    def _plot_rect(self):
        return QRect(self.ML, self.MT,
                     self.width() - self.ML - self.MR,
                     self.height() - self.MT - self.MB)

    def _px_to_data(self, pos):
        r = self._plot_rect()
        t0, t1, f0, f1 = self.extent
        fx = (pos.x() - r.left()) / max(r.width(), 1)
        fy = 1.0 - (pos.y() - r.top()) / max(r.height(), 1)
        return t0 + fx * (t1 - t0), f0 + fy * (f1 - f0)

    # ---- 绘制 ----
    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#0a0a0a"))
        if self._qimg is None:
            p.setPen(QColor("#888888"))
            p.drawText(self.rect(), Qt.AlignCenter,
                       "请先打开音频文件，频谱将显示在这里")
            return
        r = self._plot_rect()
        p.drawImage(r, self._qimg)

        # 网格与刻度
        t0, t1, f0, f1 = self.extent
        p.setFont(QFont("Consolas", 8))
        grid_pen = QPen(QColor(255, 255, 255, 28))
        text_pen = QPen(QColor("#aaaaaa"))
        # 频率刻度（kHz）
        fstep = self._nice_step((f1 - f0) / 6)
        f = np.ceil(f0 / fstep) * fstep
        while f <= f1:
            y = r.top() + (1 - (f - f0) / (f1 - f0)) * r.height()
            p.setPen(grid_pen)
            p.drawLine(r.left(), int(y), r.right(), int(y))
            p.setPen(text_pen)
            p.drawText(2, int(y) + 4, f"{f:.0f}k")
            f += fstep
        # 时间刻度（s）
        tstep = self._nice_step((t1 - t0) / 8)
        t = np.ceil(t0 / tstep) * tstep
        while t <= t1:
            x = r.left() + (t - t0) / (t1 - t0) * r.width()
            p.setPen(grid_pen)
            p.drawLine(int(x), r.top(), int(x), r.bottom())
            p.setPen(text_pen)
            p.drawText(int(x) - 12, self.height() - 8, f"{t:.1f}s")
            t += tstep
        p.setPen(QPen(QColor("#444444")))
        p.drawRect(r)

        # 框选矩形
        sel = self._current_sel_rect()
        if sel:
            p.setPen(QPen(QColor("#ff4444"), 2, Qt.DashLine))
            p.fillRect(sel, QColor(255, 68, 68, 40))
            p.drawRect(sel)
        p.end()

    @staticmethod
    def _nice_step(raw):
        for m in (0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50):
            if raw <= m:
                return m
        return 100

    def _current_sel_rect(self):
        if self._drag_start and self._drag_cur:
            return QRect(self._drag_start, self._drag_cur).normalized()
        return None

    # ---- 鼠标交互 ----
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self._qimg is not None \
                and self._plot_rect().contains(e.pos()):
            self._drag_start = e.pos()
            self._drag_cur = e.pos()
            self.update()

    def mouseMoveEvent(self, e):
        if self._drag_start:
            self._drag_cur = e.pos()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._drag_start:
            rect = QRect(self._drag_start, e.pos()).normalized()
            self._drag_start = self._drag_cur = None
            pr = self._plot_rect()
            rect = rect.intersected(pr)
            if rect.width() > 4 and rect.height() > 4:
                t_a, f_a = self._px_to_data(rect.topLeft())
                t_b, f_b = self._px_to_data(rect.bottomRight())
                self.selection = (min(t_a, t_b), max(t_a, t_b),
                                  min(f_a, f_b), max(f_a, f_b))
                self.regionSelected.emit(*self.selection)
            self.update()


class SynthWorker(QThread):
    """后台线程：渲染文字 -> 超声编码 -> 混音"""
    progress = pyqtSignal(int, str)
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, music, sr, source, region, gain_db):
        super().__init__()
        self.music, self.sr = music, sr
        # source: ("text", 文字) 或 ("image", 路径, 填充模式, 是否反色)
        self.source = source
        self.region = region  # (t0, t1, f_low_hz, f_high_hz)
        self.gain_db = gain_db

    def run(self):
        try:
            t0, t1, f_low, f_high = self.region
            dur = t1 - t0
            # 按区域像素网格原生渲染，清晰度最高
            w, h = core.region_geometry(self.sr, f_low, f_high, dur)
            if self.source[0] == "text":
                img = core.render_text_fit(self.source[1], w, h)
            elif self.source[0] == "qrcode":
                img = core.load_qr_image(self.source[1], w, h)
            else:
                _, path, mode, invert = self.source
                img = core.load_stego_image(path, w, h, mode, invert)
            self.progress.emit(5, "内容渲染完成，开始超声编码...")
            hidden = core.synthesize_ultrasound(
                img, self.sr, f_low, f_high, dur,
                progress_cb=lambda p, m: self.progress.emit(5 + int(p * 0.75), m))
            self.progress.emit(85, "混音...")
            mixed = core.mix_audio(self.music, hidden,
                                   int(t0 * self.sr), self.gain_db)
            self.progress.emit(90, "计算频谱预览...")
            mono = mixed.mean(axis=1)
            self.done.emit((mixed, mono))
        except Exception:
            self.failed.emit(traceback.format_exc())


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("无敌章鱼哥出品，必属精品 — 频谱画家 (24-bit / 192kHz)")
        self.setWindowIcon(QIcon(resource_path("icon/icon.png")))
        self.resize(1280, 800)

        self.music = None       # (N, C) float32
        self.sr = core.TARGET_SR
        self.mixed = None
        self.region = None      # (t0, t1, f_low_hz, f_high_hz)
        self.f_view = (15, 96)  # 频谱显示范围 kHz

        self._build_ui()

    # ---------- UI ----------
    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        lay = QHBoxLayout(root)

        # 左侧面板
        panel = QVBoxLayout()
        panel.setSpacing(8)
        left = QWidget()
        left.setLayout(panel)
        left.setFixedWidth(320)
        lay.addWidget(left)

        self.btn_open = QPushButton("① 打开音频 (WAV/FLAC/OGG/MP3)")
        self.btn_open.clicked.connect(self.open_audio)
        panel.addWidget(self.btn_open)
        self.lbl_info = QLabel("未加载音频")
        self.lbl_info.setWordWrap(True)
        panel.addWidget(self.lbl_info)

        grp_text = QGroupBox("② 绘制内容")
        form = QFormLayout(grp_text)
        self.cmb_type = QComboBox()
        self.cmb_type.addItems(["文字", "图片 / Logo", "二维码 / QR Code"])
        self.cmb_type.currentIndexChanged.connect(self.on_type_changed)
        form.addRow("类型:", self.cmb_type)

        # 文字选项
        self.text_opts = QWidget()
        ft = QFormLayout(self.text_opts)
        ft.setContentsMargins(0, 0, 0, 0)
        self.edt_text = QLineEdit("HELLO")
        self.edt_text.textChanged.connect(self.update_preview)
        self.cmb_color = QComboBox()
        self.cmb_color.addItems(["白色", "红色"])
        self.cmb_color.currentIndexChanged.connect(self.update_preview)
        ft.addRow("文字:", self.edt_text)
        ft.addRow("颜色:", self.cmb_color)
        form.addRow(self.text_opts)

        # 图片选项
        self.img_opts = QWidget()
        fi = QFormLayout(self.img_opts)
        fi.setContentsMargins(0, 0, 0, 0)
        self.btn_img = QPushButton("选择图片...")
        self.btn_img.clicked.connect(self.choose_image)
        self.lbl_imgname = QLabel("未选择")
        self.lbl_imgname.setWordWrap(True)
        fi.addRow(self.btn_img)
        fi.addRow(self.lbl_imgname)
        # 普通图片的额外选项（二维码模式下隐藏）
        self.img_extra = QWidget()
        fe = QFormLayout(self.img_extra)
        fe.setContentsMargins(0, 0, 0, 0)
        self.cmb_fit = QComboBox()
        self.cmb_fit.addItems(["保持比例（推荐）", "拉伸填满"])
        self.chk_invert = QCheckBox("反色（深色 Logo 勾选）")
        fe.addRow("填充:", self.cmb_fit)
        fe.addRow(self.chk_invert)
        fi.addRow(self.img_extra)
        self.lbl_qr_hint = QLabel("提示：建议框选接近正方形的区域；\n二值化 + 反色已自动处理")
        self.lbl_qr_hint.setWordWrap(True)
        self.lbl_qr_hint.setStyleSheet("color:#ffaa44;")
        self.lbl_qr_hint.setVisible(False)
        fi.addRow(self.lbl_qr_hint)
        self.img_opts.setVisible(False)
        form.addRow(self.img_opts)

        self.img_path = None
        self.lbl_preview = QLabel()
        self.lbl_preview.setFixedHeight(90)
        self.lbl_preview.setStyleSheet("background:#000; border:1px solid #333;")
        form.addRow(self.lbl_preview)
        panel.addWidget(grp_text)

        grp_region = QGroupBox("③ 绘制区域（在右侧频谱图上拖框选择）")
        vr = QVBoxLayout(grp_region)
        self.lbl_region = QLabel("未选择")
        self.lbl_region.setWordWrap(True)
        vr.addWidget(self.lbl_region)
        row = QHBoxLayout()
        row.addWidget(QLabel("隐藏增益:"))
        self.slider_gain = QSlider(Qt.Horizontal)
        self.slider_gain.setRange(-50, -20)
        self.slider_gain.setValue(-40)
        self.lbl_gain = QLabel("-40 dB")
        self.slider_gain.valueChanged.connect(
            lambda v: self.lbl_gain.setText(f"{v} dB"))
        row.addWidget(self.slider_gain)
        row.addWidget(self.lbl_gain)
        vr.addLayout(row)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("显示范围:"))
        self.cmb_view = QComboBox()
        self.cmb_view.addItems(["15–96 kHz", "0–96 kHz", "20–60 kHz"])
        self.cmb_view.currentIndexChanged.connect(self.change_view)
        row2.addWidget(self.cmb_view)
        vr.addLayout(row2)
        panel.addWidget(grp_region)

        self.btn_synth = QPushButton("④ 合成到音频")
        self.btn_synth.clicked.connect(self.synthesize)
        panel.addWidget(self.btn_synth)
        self.progress = QProgressBar()
        self.progress.setValue(0)
        panel.addWidget(self.progress)
        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        panel.addWidget(self.lbl_status)

        row3 = QHBoxLayout()
        self.btn_wav = QPushButton("导出 WAV (24-bit)")
        self.btn_flac = QPushButton("导出 FLAC (24-bit)")
        self.btn_wav.clicked.connect(lambda: self.export("WAV"))
        self.btn_flac.clicked.connect(lambda: self.export("FLAC"))
        row3.addWidget(self.btn_wav)
        row3.addWidget(self.btn_flac)
        panel.addLayout(row3)
        panel.addStretch(1)

        # 右侧频谱图
        self.canvas = SpectrogramWidget()
        self.canvas.regionSelected.connect(self.on_region_selected)
        lay.addWidget(self.canvas, 1)

        self.update_preview()

    # ---------- 逻辑 ----------
    def open_audio(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择音频文件", "",
            "音频文件 (*.wav *.flac *.ogg *.mp3);;所有文件 (*)")
        if not path:
            return
        try:
            self.music, self.sr, orig_sr = core.load_audio(path)
        except Exception as e:
            QMessageBox.critical(self, "加载失败", str(e))
            return
        n, ch = self.music.shape
        dur = n / self.sr
        warn = "" if orig_sr == self.sr else \
            f"\n⚠ 原始采样率 {orig_sr}Hz，已重采样到 {self.sr}Hz"
        self.lbl_info.setText(
            f"时长 {dur:.2f}s | {ch} 声道 | 采样率 {self.sr}Hz{warn}")
        self.mixed = None
        self.region = None
        self.lbl_region.setText("未选择")
        self.refresh_spectrogram(self.music.mean(axis=1))
        self.lbl_status.setText("请在频谱图上拖动鼠标框选绘制区域")

    def refresh_spectrogram(self, mono):
        self.lbl_status.setText("正在计算频谱...")
        QApplication.processEvents()
        t, f, S = core.compute_spectrogram(
            mono, self.sr, f_min=self.f_view[0] * 1000,
            f_max=self.f_view[1] * 1000)
        self.canvas.set_spectrogram(t, f, S)
        self.lbl_status.setText("")

    def change_view(self, idx):
        self.f_view = [(15, 96), (0, 96), (20, 60)][idx]
        src = self.mixed if self.mixed is not None else self.music
        if src is not None:
            self.refresh_spectrogram(src.mean(axis=1))

    def on_region_selected(self, t0, t1, f0, f1):
        self.region = (t0, t1, f0 * 1000.0, f1 * 1000.0)
        self.lbl_region.setText(
            f"时间: {t0:.2f}s – {t1:.2f}s  (时长 {t1 - t0:.2f}s)\n"
            f"频率: {f0:.1f} – {f1:.1f} kHz")

    def on_type_changed(self, idx):
        self.text_opts.setVisible(idx == 0)
        self.img_opts.setVisible(idx > 0)
        self.img_extra.setVisible(idx == 1)       # 二维码模式隐藏填充/反色
        self.lbl_qr_hint.setVisible(idx == 2)
        self.update_preview()

    def choose_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp);;所有文件 (*)")
        if path:
            self.img_path = path
            self.lbl_imgname.setText(os.path.basename(path))
            self.update_preview()

    def update_preview(self):
        if self.cmb_type.currentIndex() == 0:
            text = self.edt_text.text() or " "
            try:
                img = core.render_text_image(text, 64)
            except Exception:
                return
            rgb = np.zeros((img.shape[0], img.shape[1], 3), dtype=np.uint8)
            if self.cmb_color.currentText() == "红色":
                rgb[..., 0] = img
            else:
                rgb[...] = img[..., None]
        else:
            if not self.img_path:
                self.lbl_preview.clear()
                return
            try:
                if self.cmb_type.currentIndex() == 2:
                    img = core.load_qr_image(self.img_path, 400, 80)
                else:
                    img = core.load_stego_image(self.img_path, 400, 80)
            except Exception:
                return
            rgb = np.repeat(img[..., None], 3, axis=2)
        rgb = np.ascontiguousarray(rgb)
        h, w, _ = rgb.shape
        qimg = QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888).copy()
        self.lbl_preview.setPixmap(QPixmap.fromImage(qimg).scaled(
            self.lbl_preview.size(), Qt.KeepAspectRatio,
            Qt.SmoothTransformation))

    def synthesize(self):
        if self.music is None:
            QMessageBox.warning(self, "提示", "请先打开音频文件")
            return
        if self.region is None:
            QMessageBox.warning(self, "提示", "请先在频谱图上框选绘制区域")
            return
        idx = self.cmb_type.currentIndex()
        if idx == 0:
            if not self.edt_text.text().strip():
                QMessageBox.warning(self, "提示", "请输入要绘制的文字")
                return
            source = ("text", self.edt_text.text())
        elif idx == 1:
            if not self.img_path:
                QMessageBox.warning(self, "提示", "请先选择图片")
                return
            mode = "stretch" if self.cmb_fit.currentIndex() == 1 else "fit"
            source = ("image", self.img_path, mode, self.chk_invert.isChecked())
        else:
            if not self.img_path:
                QMessageBox.warning(self, "提示", "请先选择二维码图片")
                return
            source = ("qrcode", self.img_path)
        self.btn_synth.setEnabled(False)
        self.worker = SynthWorker(
            self.music, self.sr, source, self.region,
            self.slider_gain.value())
        self.worker.progress.connect(
            lambda p, m: (self.progress.setValue(p), self.lbl_status.setText(m)))
        self.worker.done.connect(self.on_synth_done)
        self.worker.failed.connect(self.on_synth_failed)
        self.worker.start()

    def on_synth_done(self, result):
        self.mixed, mono = result
        self.btn_synth.setEnabled(True)
        self.progress.setValue(100)
        self.refresh_spectrogram(mono)
        self.lbl_status.setText("✔ 合成完成，可在频谱图中验证，然后导出")

    def on_synth_failed(self, err):
        self.btn_synth.setEnabled(True)
        QMessageBox.critical(self, "合成失败", err)

    def export(self, fmt):
        if self.mixed is None:
            QMessageBox.warning(self, "提示", "请先执行「合成到音频」")
            return
        ext = "wav" if fmt == "WAV" else "flac"
        path, _ = QFileDialog.getSaveFileName(
            self, f"导出 {fmt}", f"hidden_output.{ext}",
            f"{fmt} 文件 (*.{ext})")
        if not path:
            return
        try:
            core.export_audio(path, self.mixed, self.sr, fmt)
            self.lbl_status.setText(f"✔ 已导出: {path}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))


DARK_STYLE = """
QMainWindow, QWidget { background:#1a1a1a; color:#dddddd; }
QGroupBox { border:1px solid #333; margin-top:10px; padding-top:8px; }
QGroupBox::title { subcontrol-origin:margin; left:8px; color:#ff4444; }
QPushButton { background:#2a2a2a; border:1px solid #444; padding:8px; border-radius:4px; }
QPushButton:hover { background:#3a3a3a; border-color:#ff4444; }
QPushButton:disabled { color:#666; }
QLineEdit, QSpinBox, QComboBox { background:#0a0a0a; border:1px solid #444;
    padding:4px; color:#eee; }
QProgressBar { background:#0a0a0a; border:1px solid #444; text-align:center; }
QProgressBar::chunk { background:#ff4444; }
QSlider::groove:horizontal { height:6px; background:#0a0a0a; }
QSlider::handle:horizontal { width:14px; background:#ff4444; margin:-5px 0;
    border-radius:7px; }
"""


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_STYLE)
    app.setWindowIcon(QIcon(resource_path("icon/icon.png")))  # 任务栏图标
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
