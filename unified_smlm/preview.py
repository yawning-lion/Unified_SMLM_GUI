from __future__ import annotations

import numpy
from PyQt5 import QtCore, QtGui, QtWidgets


class CameraPreviewWidget(QtWidgets.QFrame):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._frame_background = "#0f1720"
        self._frame_border = "#314150"
        self._auto_contrast_enabled = False
        self._contrast_low_percentile = 1.0
        self._contrast_high_percentile = 99.5
        self._fit_mode = QtCore.Qt.KeepAspectRatio
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self._apply_frame_style()

        self._scene = QtWidgets.QGraphicsScene(self)
        self._pixmap_item = QtWidgets.QGraphicsPixmapItem()
        self._scene.addItem(self._pixmap_item)

        self._view = QtWidgets.QGraphicsView(self)
        self._view.setScene(self._scene)
        self._view.setFrameShape(QtWidgets.QFrame.NoFrame)
        self._view.setBackgroundBrush(QtGui.QColor("#0b1118"))
        self._view.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, False)

        self._overlay = QtWidgets.QLabel(self)
        self._overlay.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        self._overlay.setWordWrap(True)
        self._overlay.setStyleSheet(
            "QLabel { color: white; background: rgba(14, 22, 30, 170); padding: 10px; border-radius: 6px; }"
        )

        self._info = QtWidgets.QLabel(self)
        self._info.setStyleSheet("QLabel { color: #dbe7f1; padding: 4px 6px; }")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._view, stretch=1)
        layout.addWidget(self._info)

        self._last_image: QtGui.QImage | None = None
        self._frame_counter = 0
        self._overlay.setText("Select a Micro-Manager cfg and click Load Config.")
        self._info.setText("Preview idle")

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._overlay.setGeometry(12, 12, max(260, self.width() - 24), 84)
        self._fit_view()

    def set_overlay_text(self, text: str) -> None:
        self._overlay.setText(text)

    def set_overlay_visible(self, visible: bool) -> None:
        self._overlay.setVisible(bool(visible))

    def set_info_visible(self, visible: bool) -> None:
        self._info.setVisible(bool(visible))

    def set_chrome_visible(self, visible: bool) -> None:
        if visible:
            self.setFrameShape(QtWidgets.QFrame.StyledPanel)
            self._frame_border = "#314150"
        else:
            self.setFrameShape(QtWidgets.QFrame.NoFrame)
            self._frame_border = self._frame_background
        self._apply_frame_style()

    def set_auto_contrast_enabled(
        self,
        enabled: bool,
        *,
        low_percentile: float = 1.0,
        high_percentile: float = 99.5,
    ) -> None:
        self._auto_contrast_enabled = bool(enabled)
        self._contrast_low_percentile = float(low_percentile)
        self._contrast_high_percentile = float(high_percentile)

    def set_fit_mode(self, fit_mode: QtCore.Qt.AspectRatioMode) -> None:
        self._fit_mode = fit_mode
        self._fit_view()

    def set_frame(
        self,
        frame: numpy.ndarray,
        *,
        circles: list[dict[str, object]] | None = None,
        auto_contrast: bool | None = None,
    ) -> None:
        if frame.ndim != 2:
            raise ValueError("Only grayscale frames are supported")
        image = self._to_qimage(frame, auto_contrast=auto_contrast)
        if circles:
            image = self._draw_circles(image, circles)
        self._last_image = image
        pixmap = QtGui.QPixmap.fromImage(image)
        self._pixmap_item.setPixmap(pixmap)
        self._scene.setSceneRect(QtCore.QRectF(pixmap.rect()))
        self._fit_view()
        self._frame_counter += 1
        self._info.setText(f"Preview: {frame.shape[1]} x {frame.shape[0]}   Frame {self._frame_counter}")

    def autoscale(self) -> None:
        self._fit_view()

    def clear(self) -> None:
        self._pixmap_item.setPixmap(QtGui.QPixmap())
        self._scene.setSceneRect(QtCore.QRectF())
        self._last_image = None
        self._frame_counter = 0
        self._info.setText("Preview idle")

    def _fit_view(self) -> None:
        rect = self._pixmap_item.boundingRect()
        if not rect.isNull():
            self._view.fitInView(rect, self._fit_mode)

    def _to_qimage(self, frame: numpy.ndarray, *, auto_contrast: bool | None = None) -> QtGui.QImage:
        use_auto_contrast = self._auto_contrast_enabled if auto_contrast is None else bool(auto_contrast)
        if frame.dtype == numpy.uint8 and not use_auto_contrast:
            array8 = frame
        else:
            array = frame.astype(numpy.float32, copy=False)
            if use_auto_contrast and array.size > 0:
                min_value = float(numpy.percentile(array, self._contrast_low_percentile))
                max_value = float(numpy.percentile(array, self._contrast_high_percentile))
            else:
                min_value = float(array.min()) if array.size else 0.0
                max_value = float(array.max()) if array.size else 0.0
            if max_value <= min_value:
                array8 = numpy.zeros_like(array, dtype=numpy.uint8)
            else:
                scaled = (array - min_value) * (255.0 / (max_value - min_value))
                array8 = numpy.clip(scaled, 0.0, 255.0).astype(numpy.uint8)
        height, width = array8.shape
        qimage = QtGui.QImage(array8.data, width, height, array8.strides[0], QtGui.QImage.Format_Grayscale8)
        return qimage.copy()

    def _draw_circles(self, image: QtGui.QImage, circles: list[dict[str, object]]) -> QtGui.QImage:
        annotated = image.convertToFormat(QtGui.QImage.Format_RGB32)
        painter = QtGui.QPainter(annotated)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        for circle in circles:
            x_value = float(circle.get("x", 0.0))
            y_value = float(circle.get("y", 0.0))
            radius = max(2.0, float(circle.get("radius", 8.0)))
            width = max(1.5, float(circle.get("width", max(2.0, radius * 0.16))))
            color_value = circle.get("color", (0, 255, 0))
            if isinstance(color_value, QtGui.QColor):
                color = color_value
            else:
                color = QtGui.QColor(*tuple(color_value))
            pen = QtGui.QPen(color)
            pen.setWidthF(width)
            painter.setPen(pen)
            painter.setBrush(QtCore.Qt.NoBrush)
            center = QtCore.QPointF(x_value + 0.5, y_value + 0.5)
            painter.drawEllipse(center, radius, radius)
            painter.setBrush(color)
            painter.drawEllipse(center, max(1.5, width * 0.6), max(1.5, width * 0.6))
        painter.end()
        return annotated

    def _apply_frame_style(self) -> None:
        self.setStyleSheet(
            f"QFrame {{ background: {self._frame_background}; border: 1px solid {self._frame_border}; }}"
        )
