import ctypes, os, win32api, win32con
from pathlib import Path
from PIL import Image as img

# Windows Shell 通知常量（用于不重命名文件夹即可刷新图标缓存）
SHCNE_ATTRIBUTES = 0x00002000    # 文件夹属性发生了变化
SHCNE_UPDATEITEM = 0x00008000    # 文件夹本身发生了变化（未改名）
SHCNE_ASSOCCHANGED = 0x08000000  # 文件关联/图标缓存整体失效
SHCNF_PATHW = 0x0005             # 参数为 Unicode 路径
SHCNF_IDLIST = 0x0000            # 参数为 PIDL（此处不需要传具体项）
SHCNF_FLUSH = 0x1000             # 等待通知送达后再返回

# SHGetSetFolderCustomSettings 相关常量
FCSM_ICONFILE = 0x00000010        # 只设置"图标文件"这一项
FCS_FORCEWRITE = 0x00000002       # 无论设置是否已存在都强制写入

# desktop.ini / 图标文件通常需要的属性：隐藏 + 系统
FILE_ATTRIBUTE_HIDDEN_SYSTEM = 0x00000002 | 0x00000004


class SHFOLDERCUSTOMSETTINGS(ctypes.Structure):
    """与 Windows SDK ShlObj_core.h 中 pshpack8 布局一致（64 位下为 104 字节）。"""

    _fields_ = [
        ("dwSize", ctypes.c_ulong),
        ("dwMask", ctypes.c_ulong),
        ("pvid", ctypes.c_void_p),
        ("pszWebViewTemplate", ctypes.c_wchar_p),
        ("cchWebViewTemplate", ctypes.c_ulong),
        ("pszWebViewTemplateVersion", ctypes.c_wchar_p),
        ("pszInfoTip", ctypes.c_wchar_p),
        ("cchInfoTip", ctypes.c_ulong),
        ("pclsid", ctypes.c_void_p),
        ("cchCLSID", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("pszIconFile", ctypes.c_wchar_p),
        ("cchIconFile", ctypes.c_ulong),
        ("iIconIndex", ctypes.c_int),
        ("pszLogo", ctypes.c_wchar_p),
        ("cchLogo", ctypes.c_ulong),
    ]


def _add_file_attributes(path, attrs):
    """保留原有属性，只追加指定属性，避免覆盖隐藏/系统等其他标记。"""
    try:
        current = win32api.GetFileAttributes(path)
    except Exception:
        current = 0
    win32api.SetFileAttributes(path, current | attrs)


def _notify_shell(w_event_id, u_flags, item1=None, item2=None):
    """调用 SHChangeNotify 通知 Windows Shell 发生了变更。"""
    shell32 = ctypes.windll.shell32
    shell32.SHChangeNotify.argtypes = (
        ctypes.c_long,
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.c_void_p,
    )
    shell32.SHChangeNotify.restype = None
    shell32.SHChangeNotify(w_event_id, u_flags, item1, item2)


def _set_folder_custom_icon(folder_path, icon_path):
    """调用资源管理器"属性→自定义"内部使用的 SHGetSetFolderCustomSettings 写入 desktop.ini。"""
    shell32 = ctypes.windll.shell32
    shell32.SHGetSetFolderCustomSettings.argtypes = [
        ctypes.POINTER(SHFOLDERCUSTOMSETTINGS),
        ctypes.c_wchar_p,
        ctypes.c_ulong,
    ]
    shell32.SHGetSetFolderCustomSettings.restype = ctypes.c_long

    pfcs = SHFOLDERCUSTOMSETTINGS()
    pfcs.dwSize = ctypes.sizeof(SHFOLDERCUSTOMSETTINGS)
    pfcs.dwMask = FCSM_ICONFILE
    pfcs.pszIconFile = icon_path
    pfcs.cchIconFile = 0
    pfcs.iIconIndex = 0
    return shell32.SHGetSetFolderCustomSettings(
        ctypes.byref(pfcs), folder_path, FCS_FORCEWRITE
    )


class SetAsIcon:
    def __init__(self):
        # 可以根据需要添加其他图片格式的扩展名
        self.allowed_extensions = [
            ".jpg",
            ".jpeg",
            ".png",
            ".webp",
            ".bmp",
            ".tiff",
            ".gif",
            ".jfif",
        ]

    # 自动寻找文件夹中第一张图（按文件名排序，保证"第一张"是稳定、可预期的）
    def get_first_image_paths(self, folder_path):
        self.jpg_path = None
        image_paths = []
        for filename in os.listdir(folder_path):
            file_path = os.path.join(folder_path, filename)
            if (
                os.path.isfile(file_path)
                and filename.lower().endswith(tuple(self.allowed_extensions))
            ):
                image_paths.append(file_path)
        if image_paths:
            image_paths.sort(key=lambda p: os.path.basename(p).lower())
            self.jpg_path = image_paths[0]
        return self.jpg_path

    # 自动寻找 cover 图片
    def get_cover_image_paths(self, folder_path):
        self.jpg_path = None
        for file in os.listdir(folder_path):
            file_path = os.path.join(folder_path, file)
            if os.path.isfile(file_path):
                file_name, file_ext = os.path.splitext(file)
                if (
                    file_name.lower() == "cover"
                    and file_ext.lower() in self.allowed_extensions
                ):
                    self.jpg_path = file_path
                    break
        return self.jpg_path

    # 用图片生成 ico 文件；源图比图标新时重新生成，避免图标永远是旧的
    def create_icon(self, folder_name: str, icon_dir: str):
        icon_name = f"@folder-icon-{folder_name}.ico"
        icon_path = Path(os.path.join(icon_dir, icon_name))

        need_create = not os.path.exists(icon_path)
        if not need_create and self.jpg_path and os.path.isfile(self.jpg_path):
            source_mtime = os.path.getmtime(self.jpg_path)
            icon_mtime = os.path.getmtime(icon_path)
            need_create = source_mtime > icon_mtime

        if need_create and self.jpg_path and os.path.isfile(self.jpg_path):
            # Windows 下带隐藏/系统/只读属性的文件无法用 open("w+b") 覆写，
            # 重新生成前先临时清掉这些属性（稍后 changeIcon 会重新隐藏）
            if os.path.exists(icon_path):
                win32api.SetFileAttributes(
                    str(icon_path), win32con.FILE_ATTRIBUTE_NORMAL
                )
            with img.open(self.jpg_path) as image:
                x, y = image.size
                size = max(x, y)
                new_im = img.new("RGBA", (size, size), (255, 255, 255, 0))
                new_im.paste(image, ((size - x) // 2, (size - y) // 2))
                new_im.save(icon_path)

        return icon_name, need_create

    # 判断 desktop.ini 是否真的指向了存在的图标文件
    @staticmethod
    def _has_valid_icon_setting(ini_file_path, icon_path):
        if not os.path.exists(ini_file_path) or not os.path.exists(icon_path):
            return False
        try:
            text = Path(ini_file_path).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return False
        icon_filename = os.path.basename(icon_path)
        return "IconResource" in text and icon_filename.lower() in text.lower()

    # 将 ico 文件设置为图标，并隐藏 desktop.ini 文件 & .ico 文件
    def changeIcon(self, folder_name: str, icon_dir: str):
        ini_file_path = Path(os.path.join(icon_dir, "desktop.ini"))
        icon_name, icon_updated = self.create_icon(folder_name, icon_dir)
        icon_path = os.path.join(icon_dir, icon_name)

        has_valid_setting = self._has_valid_icon_setting(ini_file_path, icon_path)
        if not has_valid_setting:
            # 使用资源管理器"属性→自定义"对话框内部同一个 API 写入 desktop.ini：
            # 它会创建 desktop.ini（并自动设为隐藏+系统属性），同时让 Explorer 立即刷新图标
            hr = _set_folder_custom_icon(icon_dir, icon_path)
            if hr != 0 or not os.path.exists(ini_file_path):
                # 兜底：API 不可用时手动写 desktop.ini
                if os.path.exists(ini_file_path):
                    # 同 ICO 一样，先临时清掉隐藏/系统属性才能覆写
                    win32api.SetFileAttributes(
                        str(ini_file_path), win32con.FILE_ATTRIBUTE_NORMAL
                    )
                iniline = (
                    f'[.ShellClassInfo]\nIconResource="{icon_name}",0\n'
                    "[ViewState]\nMode=\nVid=\nFolderType=Generic"
                )
                with open(ini_file_path, "w", encoding="utf-8") as inifile:
                    inifile.write(iniline)
                _add_file_attributes(
                    str(ini_file_path), FILE_ATTRIBUTE_HIDDEN_SYSTEM
                )

        # 无论 desktop.ini 之前是否存在，都要确保 .ico 文件是隐藏的
        _add_file_attributes(icon_path, FILE_ATTRIBUTE_HIDDEN_SYSTEM)

        # 与"属性→自定义"一致：文件夹设为只读，Explorer 才会读取 desktop.ini
        # 保留原有属性，只追加只读位，避免清掉隐藏/系统等其他属性
        _add_file_attributes(str(icon_dir), win32con.FILE_ATTRIBUTE_READONLY)

        # True 表示"已拥有有效且最新的封面"；False 表示本次重新写入/更新了图标
        return has_valid_setting and not icon_updated

    # 删除文件夹自定义图标：移除 desktop.ini 与 @folder-icon-cover.ico，
    # 并还原设置图标时加上的文件夹只读标记；返回实际删除的文件名列表
    def removeIcon(self, folder_path):
        removed = []
        target_files = ["desktop.ini", "@folder-icon-cover.ico"]
        for file_name in target_files:
            file_path = Path(os.path.join(folder_path, file_name))
            if not file_path.exists():
                continue
            # 图标相关文件都带隐藏+系统属性，先清掉这些属性才能删除
            win32api.SetFileAttributes(
                str(file_path), win32con.FILE_ATTRIBUTE_NORMAL
            )
            file_path.unlink()
            removed.append(file_name)

        if removed:
            # 删除自定义图标后，还原文件夹只读标记（changeIcon 会加上它）；
            # 读取失败时跳过，避免误清掉文件夹其他属性
            try:
                current = win32api.GetFileAttributes(folder_path)
            except Exception:
                current = None
            if current is not None:
                win32api.SetFileAttributes(
                    folder_path, current & ~win32con.FILE_ATTRIBUTE_READONLY
                )

        return removed

    # 不重命名文件夹，通知 Explorer 重新读取并刷新该文件夹的图标
    @staticmethod
    def refresh_folder_icon(folder_path):
        # 文件夹的属性发生了变化（系统文件夹标记），让 Explorer 立即重新解析
        _notify_shell(
            SHCNE_ATTRIBUTES,
            SHCNF_PATHW | SHCNF_FLUSH,
            ctypes.c_wchar_p(folder_path),
        )
        # 文件夹本身（未改名）发生了变化，重新读取 desktop.ini 中的图标
        _notify_shell(
            SHCNE_UPDATEITEM,
            SHCNF_PATHW | SHCNF_FLUSH,
            ctypes.c_wchar_p(folder_path),
        )

    # 使 Windows 图标缓存整体失效，确保不会残留同名文件夹的旧图标
    @staticmethod
    def refresh_icon_cache():
        _notify_shell(SHCNE_ASSOCCHANGED, SHCNF_IDLIST | SHCNF_FLUSH)


if __name__ == "__main__":
    folder_path = r"C:\Users\test"
    SetAsIcon = SetAsIcon()
    SetAsIcon.get_cover_image_paths(folder_path)
    SetAsIcon.changeIcon("cover", folder_path)
    SetAsIcon.refresh_folder_icon(folder_path)
    SetAsIcon.refresh_icon_cache()
