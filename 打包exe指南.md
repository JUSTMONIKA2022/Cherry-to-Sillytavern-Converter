# Cherry Chat Converter - 打包指南

本指南将教您如何将 `gui_converter.py` 脚本打包成一个独立的 `.exe` 可执行文件，方便在任何 Windows 电脑上运行。

## 前置准备

1.  确保您已安装 Python。
2.  确保已安装 `tkinter`（Python 通常自带，无需单独安装）。
3.  安装打包工具 `PyInstaller`：
    打开命令行（CMD 或 PowerShell），运行：
    ```bash
    pip install pyinstaller
    ```

## 打包步骤

1.  打开命令行，进入脚本所在的目录：
    ```bash
    cd c:\Users\win\Desktop\project_S\proj.s
    ```

2.  运行以下打包命令：
    ```bash
    pyinstaller --noconsole --onefile --name "CherryConverter" gui_converter.py
    ```
    *   `--noconsole`：运行时不显示黑色的命令行窗口。
    *   `--onefile`：打包成单个 `.exe` 文件，而不是一堆文件。
    *   `--name "CherryConverter"`：生成的文件名。

3.  等待命令执行完毕。
    *   成功后，您会在当前目录下的 `dist` 文件夹中找到 `CherryConverter.exe`。

## 如何使用

双击 `CherryConverter.exe` 即可启动软件界面。
您现在可以将这个文件发送给任何人，他们无需安装 Python 即可使用。
