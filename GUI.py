import sys, os
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QLabel,
    QRadioButton,
    QListWidget,
    QPushButton,
    QFileDialog,
    QGroupBox,
    QMainWindow,
    QHBoxLayout,
    QDesktopWidget,
    QAbstractItemView,
    QMessageBox,
    QPlainTextEdit,
)
from SetAsIcon import SetAsIcon


class IconWorker(QThread):
    """后台批量设置图标，避免阻塞界面。"""

    log_message = pyqtSignal(str)
    done = pyqtSignal(list)  # 处理失败的文件夹路径

    def __init__(self, folder_paths, select_img_mode, delete_img_mode):
        super().__init__()
        self._folder_paths = list(folder_paths)
        self._select_img_mode = select_img_mode
        self._delete_img_mode = delete_img_mode

    def run(self):
        setter = SetAsIcon()
        refreshed_folders = []
        failed = []

        try:
            for folder_path in self._folder_paths:
                try:
                    if self._select_img_mode:
                        jpg_path = setter.get_first_image_paths(folder_path)
                    else:
                        jpg_path = setter.get_cover_image_paths(folder_path)

                    if not jpg_path:
                        message = (
                            f"{folder_path} 没有图片。"
                            if self._select_img_mode
                            else f"{folder_path} 没有 cover 命名的图片。"
                        )
                        self.log_message.emit(message)
                        failed.append(folder_path)
                        continue

                    already_had_icon = setter.changeIcon("cover", folder_path)
                    if already_had_icon:
                        self.log_message.emit(f"{folder_path} 已拥有封面。")
                    else:
                        refreshed_folders.append(folder_path)
                        self.log_message.emit(
                            f"{folder_path} 已设置封面（{os.path.basename(jpg_path)}）。"
                        )

                    if self._delete_img_mode:
                        try:
                            os.remove(jpg_path)
                        except Exception as exc:
                            self.log_message.emit(
                                f"{folder_path} 封面已设置，但源图片删除失败：{exc}"
                            )
                            failed.append(folder_path)
                except PermissionError:
                    self.log_message.emit(
                        f"{folder_path} 另一个程序正在占用，进程无法访问。"
                    )
                    failed.append(folder_path)
                except Exception as exc:
                    self.log_message.emit(f"{folder_path} 处理失败：{exc}")
                    failed.append(folder_path)

            # 不重命名文件夹，改用 Shell 通知刷新图标缓存：
            # 先定向刷新每个文件夹，再整体使图标缓存失效，避免显示旧图标
            for folder_path in refreshed_folders:
                setter.refresh_folder_icon(folder_path)
            if refreshed_folders:
                setter.refresh_icon_cache()
        except Exception as exc:
            self.log_message.emit(f"批量处理中断：{exc}")
            failed.extend(self._folder_paths)
        finally:
            self.log_message.emit("设置封面完成")
            self.done.emit(failed)


class IconRemoveWorker(QThread):
    """后台批量删除文件夹图标，避免阻塞界面。"""

    log_message = pyqtSignal(str)
    done = pyqtSignal(list)  # 处理失败的文件夹路径

    def __init__(self, folder_paths):
        super().__init__()
        self._folder_paths = list(folder_paths)

    def run(self):
        setter = SetAsIcon()
        changed_folders = []
        failed = []

        try:
            for folder_path in self._folder_paths:
                try:
                    removed = setter.removeIcon(folder_path)
                    if removed:
                        changed_folders.append(folder_path)
                        self.log_message.emit(
                            f"{folder_path} 已删除图标（{'、'.join(removed)}）。"
                        )
                    else:
                        self.log_message.emit(
                            f"{folder_path} 没有自定义图标，无需删除。"
                        )
                except PermissionError:
                    self.log_message.emit(
                        f"{folder_path} 另一个程序正在占用，进程无法访问。"
                    )
                    failed.append(folder_path)
                except Exception as exc:
                    self.log_message.emit(f"{folder_path} 处理失败：{exc}")
                    failed.append(folder_path)

            # 删除后同样需要刷新：先定向刷新每个文件夹，再整体使图标缓存失效
            for folder_path in changed_folders:
                setter.refresh_folder_icon(folder_path)
            if changed_folders:
                setter.refresh_icon_cache()
        except Exception as exc:
            self.log_message.emit(f"批量处理中断：{exc}")
            failed.extend(self._folder_paths)
        finally:
            self.log_message.emit("删除封面完成")
            self.done.emit(failed)


class MainGui(QMainWindow):
    def __init__(self):
        super().__init__()

        self.folder_paths = []  # 用于存储文件夹路径的列表
        self.select_img_mode = True
        self.delete_img_mode = False
        self.worker = None
        self._removing_icons = False
        self._processing_paths = []

        self.list_widget = QListWidget()  # 路径列表
        self.list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.label = QLabel("拖拽文件夹到窗口中")  # 状态标签
        self.log_widget = QPlainTextEdit()  # 日志区域（与路径列表分离）
        self.log_widget.setReadOnly(True)
        self.log_widget.setMaximumHeight(130)

        top_layout = QHBoxLayout()
        self.mode_group_box("图片选择：", "使用首张图片", "使用cover图片", top_layout)
        self.mode_group_box("是否删除源图片：", "保留源图片", "删除源图片", top_layout)

        button_layout = QVBoxLayout()
        button_layout.setSpacing(12)  # 增大按钮间隔，防止误点
        self.remove_button = self.create_button(
            "删除图标", self.remove_icons, button_layout
        )
        self.create_button("选择文件夹", self.select_folder, button_layout)
        self.create_button("移除选中文件夹", self.remove_selected, button_layout)
        self.set_button = self.create_button("设置图标", self.next_step, button_layout)
        top_layout.addLayout(button_layout)

        # 窗口布局
        main_layout = QVBoxLayout()
        main_layout.addLayout(top_layout)
        main_layout.addWidget(self.label)
        main_layout.addWidget(self.list_widget)
        main_layout.addWidget(self.log_widget)

        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)
        self.setWindowTitle("将图片应用为文件夹图标")

        # 窗口位置和大小
        screen = QDesktopWidget().screenGeometry()  # 获取屏幕尺寸
        window_width = 900
        window_height = 600
        x = (screen.width() - window_width) // 2  # 水平居中
        y = (screen.height() - window_height) // 2  # 垂直居中
        self.setGeometry(x, y, window_width, window_height)

        self.setAcceptDrops(True)  # 启用拖拽功能

    # ---------- 拖拽 ----------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(
            url.isLocalFile() and os.path.isdir(url.toLocalFile())
            for url in event.mimeData().urls()
        ):
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        paths = [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        self._add_folders(paths)

    # ---------- 路径列表管理 ----------
    def _add_folders(self, paths):
        added = 0
        for path in paths:
            if not os.path.isdir(path):
                self._log(f"已跳过（不是文件夹）：{path}")
                continue
            if path in self.folder_paths:
                self._log(f"已跳过（重复）：{path}")
                continue
            self.folder_paths.append(path)
            added += 1
        if added:
            self._refresh_path_list()

    def _refresh_path_list(self):
        self.list_widget.clear()
        for folder_path in self.folder_paths:
            self.list_widget.addItem(folder_path)

    def remove_selected(self):
        items = self.list_widget.selectedItems()
        if not items:
            self._log("请先在列表中选择要移除的文件夹")
            return
        rows = sorted(
            (self.list_widget.row(item) for item in items), reverse=True
        )
        for row in rows:
            removed = self.folder_paths.pop(row)
            self._log(f"已移除：{removed}")
        self._refresh_path_list()

    def _log(self, text):
        self.log_widget.appendPlainText(text)

    # ---------- 模式与按钮 ----------
    def mode_group_box(self, arg0, arg1, arg2, layout):  # 模式选择
        mode_group_box = QGroupBox(arg0)
        mode_layout = QVBoxLayout()

        first_mode_radio = QRadioButton(arg1)
        first_mode_radio.setChecked(True)
        first_mode_radio.clicked.connect(lambda: self.select_mode(arg1))
        mode_layout.addWidget(first_mode_radio)

        second_mode_radio = QRadioButton(arg2)
        second_mode_radio.clicked.connect(lambda: self.select_mode(arg2))
        mode_layout.addWidget(second_mode_radio)

        mode_group_box.setLayout(mode_layout)
        layout.addWidget(mode_group_box)

    def select_mode(self, mode):
        if str(mode) == "使用cover图片":
            self.select_img_mode = False
        elif str(mode) == "使用首张图片":
            self.select_img_mode = True
        elif str(mode) == "保留源图片":
            self.delete_img_mode = False
        elif str(mode) == "删除源图片":
            self.delete_img_mode = True
        self._log(f"切换至{mode}模式")

    def create_button(self, text, arg, layout):  # 创建按钮
        button = QPushButton(text)
        button.clicked.connect(arg)
        layout.addWidget(button)
        return button

    def select_folder(self):
        if folder_path := QFileDialog.getExistingDirectory(self, "选择文件夹"):
            self._add_folders([folder_path])

    # ---------- 执行 ----------
    def next_step(self):
        if self.worker is not None and self.worker.isRunning():
            return
        if not self.folder_paths:
            self.label.setText("列表中没有路径")
            return

        if self.delete_img_mode:
            reply = QMessageBox.question(
                self,
                "确认删除源图片",
                f"将处理 {len(self.folder_paths)} 个文件夹，"
                "并删除其中被用作图标的源图片。\n此操作不可撤销，是否继续？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                self._log("已取消：没有删除任何源图片")
                return

        self.label.setText("正在设置图标…")
        self.set_button.setEnabled(False)
        self.remove_button.setEnabled(False)
        self._processing_paths = list(self.folder_paths)
        self._removing_icons = False
        self.worker = IconWorker(
            self._processing_paths, self.select_img_mode, self.delete_img_mode
        )
        self.worker.log_message.connect(self._log)
        self.worker.done.connect(self._on_worker_done)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.start()

    def remove_icons(self):
        if self.worker is not None and self.worker.isRunning():
            return
        if not self.folder_paths:
            self.label.setText("列表中没有路径")
            return

        reply = QMessageBox.question(
            self,
            "确认删除文件夹图标",
            f"将处理 {len(self.folder_paths)} 个文件夹，"
            "并删除其中的 desktop.ini 和 @folder-icon-cover.ico 文件。\n"
            "此操作不可撤销，是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            self._log("已取消：没有删除任何图标")
            return

        self.label.setText("正在删除图标…")
        self.set_button.setEnabled(False)
        self.remove_button.setEnabled(False)
        self._processing_paths = list(self.folder_paths)
        self._removing_icons = True
        self.worker = IconRemoveWorker(self._processing_paths)
        self.worker.log_message.connect(self._log)
        self.worker.done.connect(self._on_worker_done)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.start()

    def _on_worker_done(self, failed_paths):
        failed_set = set(failed_paths)
        processed_count = len(self._processing_paths) - len(failed_set)
        # 失败项保留在列表中便于重试；成功项清空；处理期间新加入的项保留
        kept = [p for p in self._processing_paths if p in failed_set]
        kept += [p for p in self.folder_paths if p not in self._processing_paths]
        self.folder_paths = kept
        self._refresh_path_list()

        if failed_paths:
            self.label.setText(
                f"已处理 {processed_count} 个，失败 {len(failed_set)} 个，"
                "失败项已保留在列表中"
            )
        else:
            if self._removing_icons:
                self.label.setText("已删除文件夹图标，路径列表清空")
            else:
                self.label.setText("已设置文件夹图标，路径列表清空")

    def _on_worker_finished(self):
        self.set_button.setEnabled(True)
        self.remove_button.setEnabled(True)
        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, "提示", "正在处理图标，请稍候再关闭窗口。")
            event.ignore()
        else:
            event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainGui()
    window.show()
    sys.exit(app.exec_())
