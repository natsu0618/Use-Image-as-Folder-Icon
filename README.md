# SetFolderIcon — 将图片应用为文件夹图标

一个 Windows 下的 Python 小工具：把文件夹里的图片自动转换成 `.ico`，设置为该文件夹的自定义图标，并提供图形界面（GUI）进行批量操作。

## 功能特性

- **批量设置图标**：可一次处理多个文件夹，后台线程执行，界面不卡顿。
- **两种选图模式**：
  - **使用首张图片**：按文件名排序，取文件夹中的第一张图片。
  - **使用 cover 图片**：取名为 `cover`（不区分大小写）的图片。
- **可选删除源图片**：设置图标成功后删除源图，可显著节省空间（删除前有确认提示）。
- **自动生成 `.ico`**：任意支持的图片格式都会先居中贴到正方形透明画布上，再保存为 `@folder-icon-cover.ico`。
- **自动更新**：当源图片比图标新时重新生成图标，避免图标“永远停留在旧版本”。
- **后台刷新图标**：通过 `SHChangeNotify` 通知资源管理器立即刷新，无需重命名文件夹或重启电脑。
- **删除自定义图标**：删除 `desktop.ini` 和 `@folder-icon-cover.ico`，并还原文件夹的只读属性。
- **友好的图形界面**：支持拖拽文件夹、路径列表管理、操作日志、失败项保留重试。

## 环境要求

- Windows 系统（核心功能依赖 Windows Shell API）
- Python 3.8+（已在 Python 3.13 下验证）
- 依赖库：
  - `pywin32`（调用 Windows API）
  - `Pillow`（图片处理与 ICO 生成）
  - `PyQt5`（图形界面）

## 安装

```bash
pip install pywin32 Pillow PyQt5
```

## 使用方法

### 图形界面（推荐）

```bash
python GUI.py
```

操作步骤：

1. 把文件夹拖入窗口，或点击 **选择文件夹** 添加；也可以从列表中 **移除选中文件夹**。
2. 选择图片来源：**使用首张图片** 或 **使用 cover 图片**。
3. 选择是否 **删除源图片**（默认保留）。
4. 点击 **设置图标**，等待处理完成；日志区会逐条显示每个文件夹的结果。
5. 需要恢复时，点击 **删除图标** 移除自定义图标并还原文件夹。

说明：

- 处理失败的文件夹会保留在列表中，方便修正后重试；成功的会被清空。
- 选择“删除源图片”或“删除图标”时会有二次确认，防止误操作。
- 任务处理期间无法关闭窗口，避免中断批量操作。

### 命令行直接调用

`SetAsIcon.py` 也可以作为库单独使用，例如把 `C:\Users\test` 下的 `cover` 图片设为图标：

```python
from SetAsIcon import SetAsIcon

folder_path = r"C:\Users\test"
setter = SetAsIcon()
setter.get_cover_image_paths(folder_path)
setter.changeIcon("cover", folder_path)
setter.refresh_folder_icon(folder_path)
setter.refresh_icon_cache()
```

## 工作原理

### 1. 图标生成

用 Pillow 打开源图片，按最长边创建正方形 RGBA 透明画布，把原图居中粘贴后保存为 `.ico`。图标文件统一命名为 `@folder-icon-cover.ico`，存放在文件夹内。

如果图标已存在，会比较源图片与图标的修改时间，源图片更新时重新生成。

### 2. 写入 desktop.ini

调用资源管理器“属性 → 自定义”内部使用的同一个 API `SHGetSetFolderCustomSettings` 写入 `desktop.ini`，内容指向图标文件：

```ini
[.ShellClassInfo]
IconResource="@folder-icon-cover.ico",0
```

若 API 调用失败，则手动写入相同内容作为兜底。`desktop.ini` 和 `.ico` 文件都会被加上 **隐藏 + 系统** 属性；文件夹本身会被加上 **只读** 属性——这与资源管理器的行为一致，只读标记会告诉 Explorer 去读取 `desktop.ini`。

### 3. 刷新图标缓存

不重命名文件夹，而是通过 `SHChangeNotify` 发送三类通知：

- `SHCNE_ATTRIBUTES`：提示文件夹属性变化；
- `SHCNE_UPDATEITEM`：重新解析该文件夹的 `desktop.ini`；
- `SHCNE_ASSOCCHANGED`：整体使图标缓存失效，避免残留同名文件夹的旧图标。

### 4. 删除图标

先清除相关文件的隐藏/系统属性再删除 `desktop.ini` 与 `@folder-icon-cover.ico`，最后清除文件夹上的只读标记，并同样刷新图标缓存。

## 文件结构

| 文件 | 说明 |
| --- | --- |
| `SetAsIcon.py` | 核心库：图片查找、ICO 生成、desktop.ini 写入、图标刷新/删除 |
| `图片应用为文件夹图标GUI.py` | PyQt5 图形界面：拖拽、批量设置/删除、日志与后台线程 |

`图片应用为文件夹图标GUI.py` 中的 `IconWorker` 和 `IconRemoveWorker` 基于 `QThread` 在后台执行批量任务，通过信号把日志和失败列表传回界面，避免阻塞 UI。

## 注意事项

- 仅支持 Windows，其他系统无法调用 `SHGetSetFolderCustomSettings` 等 Shell API。
- 支持 `jpg / png / webp / bmp / tiff / gif / jfif` 等常见图片格式。
- 设置图标后源图片若被删除，则原图无法找回；删除源图片前请确认。
- 处理带隐藏/系统/只读属性的文件时会先临时清除属性再写入，处理完恢复，不影响原有其他属性。
- 若文件夹被其他程序占用（如资源管理器正在预览），可能出现“进程无法访问”的错误，重试即可。

## 代码来源

本项目代码来源：

- 由 AI 生成
- 参考自 [yodhcn/dlsite-doujin-renamer](https://github.com/yodhcn/dlsite-doujin-renamer)
