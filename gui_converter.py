import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import json
import re
import os
import sys
import subprocess
from datetime import datetime, timedelta
import queue

# --- Dependency Check ---
def check_and_install_dependencies():
    """检测并安装必要的依赖库 (chardet)"""
    # 如果是打包后的环境 (Frozen)，直接跳过检测
    # 因为 PyInstaller 已经把依赖打进去了，且打包环境中通常没有 pip
    if getattr(sys, 'frozen', False):
        global chardet
        import chardet
        return

    required_packages = {'chardet'}
    installed_packages = set()
    
    # 尝试导入 chardet
    try:
        import chardet
        installed_packages.add('chardet')
    except ImportError:
        pass

    missing = required_packages - installed_packages
    
    if missing:
        print(f"检测到缺失依赖: {', '.join(missing)}，正在尝试自动安装...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
            print("依赖安装成功！")
            # 重新导入
            global chardet
            import chardet
        except subprocess.CalledProcessError as e:
            messagebox.showerror("依赖错误", f"自动安装依赖失败，请手动运行:\npip install {' '.join(missing)}\n\n错误信息: {e}")
            sys.exit(1)
    else:
        # 如果已经安装，确保全局可用
        global chardet
        import chardet

# --- Core Logic ---

def detect_file_encoding(file_path):
    """使用 chardet 检测文件编码"""
    # 读取一部分文件内容进行检测
    rawdata = open(file_path, 'rb').read(10000)
    result = chardet.detect(rawdata)
    encoding = result['encoding']
    confidence = result['confidence']
    return encoding, confidence

def format_st_date(dt):
    date_str = dt.strftime("%B %d, %Y %I:%M%p").replace("AM", "am").replace("PM", "pm")
    day = dt.day
    date_str = date_str.replace(f" {dt.strftime('%d')},", f" {day},")
    return date_str

class ConverterThread(threading.Thread):
    def __init__(self, config, callback_queue):
        super().__init__()
        self.config = config
        self.queue = callback_queue
        self._stop_event = threading.Event()

    def run(self):
        try:
            self.convert()
        except Exception as e:
            self.queue.put(("error", str(e)))

    def stop(self):
        self._stop_event.set()

    def convert(self):
        input_path = self.config['input_path']
        output_dir = self.config['output_dir'] # Changed from output_path
        user_name = self.config['user_name']
        char_name = self.config['char_name']
        start_time = self.config['start_time']
        
        # Determine output file path
        input_filename = os.path.basename(input_path)
        base_name = os.path.splitext(input_filename)[0]
        output_filename = f"{base_name}_converted.jsonl"
        output_path = os.path.join(output_dir, output_filename)

        self.queue.put(("log", f"目标输出文件: {output_path}"))
        
        # Regex
        role_pattern = re.compile(r'^##\s+(?:🧑‍💻|🤖)\s+(User|Assistant)')
        separator_pattern = re.compile(r'^---')

        current_role = None 
        current_message_lines = []
        current_time = start_time
        
        # Metadata
        metadata = {
            "user_name": user_name,
            "character_name": char_name,
            "create_date": start_time.strftime("%Y-%m-%d@%Hh%Mm%Ss"),
            "chat_metadata": {
                "integrity": "generated-by-converter",
                "chat_id_hash": 0,
                "extensions": {},
                "note_prompt": "",
                "note_interval": 1,
                "note_position": 1,
                "note_depth": 4,
                "note_role": 0,
                "attachments": [],
                "timedWorldInfo": {"sticky": {}, "cooldown": {}},
                "tainted": True,
                "lastInContextMessageId": 0
            }
        }

        # Determine file size for progress bar
        total_size = os.path.getsize(input_path)
        processed_size = 0

        # Encoding detection
        try:
            self.queue.put(("log", "正在检测文件编码..."))
            encoding, confidence = detect_file_encoding(input_path)
            self.queue.put(("log", f"检测到编码: {encoding} (置信度: {confidence:.2f})"))
            
            if not encoding:
                encoding = 'utf-8' # Fallback
                self.queue.put(("log", "编码检测失败，默认使用 UTF-8"))
        except Exception as e:
            self.queue.put(("log", f"编码检测出错: {e}，尝试使用 UTF-8"))
            encoding = 'utf-8'

        try:
            infile = open(input_path, 'r', encoding=encoding)
            # Try reading a bit to ensure encoding is valid
            infile.read(10)
            infile.seek(0)
        except UnicodeDecodeError:
            if encoding.lower() != 'gb18030':
                 self.queue.put(("log", f"警告: {encoding} 解码失败，尝试 GB18030..."))
                 encoding = 'gb18030'
                 infile = open(input_path, 'r', encoding=encoding)
            else:
                 raise Exception("无法识别文件编码，请确保文件是 UTF-8 或 GB18030 格式。")

        with infile, open(output_path, 'w', encoding='utf-8') as outfile:
            outfile.write(json.dumps(metadata, ensure_ascii=False) + '\n')

            def write_message(role, lines, time_obj):
                if not lines: return
                content = '\n'.join(lines).strip()
                if not content: return

                is_user = (role == 'User')
                name = user_name if is_user else char_name
                send_date = format_st_date(time_obj)

                message_obj = {
                    "name": name,
                    "is_user": is_user,
                    "is_system": False,
                    "send_date": send_date,
                    "mes": content,
                    "extra": {},
                    "variables": {"0": {}},
                    "is_ejs_processed": [True]
                }
                
                if not is_user:
                    message_obj["swipe_id"] = 0
                    message_obj["swipes"] = [content]
                else:
                    message_obj["force_avatar"] = "/thumbnail?type=persona&file=user-default.png"

                outfile.write(json.dumps(message_obj, ensure_ascii=False) + '\n')

            count = 0
            for line in infile:
                if self._stop_event.is_set():
                    self.queue.put(("log", "Conversion stopped by user."))
                    return

                processed_size += len(line.encode(encoding)) # Approx size
                
                # Update progress every 100 lines to avoid UI freeze
                if count % 100 == 0:
                    progress = min(100, (processed_size / total_size) * 100)
                    self.queue.put(("progress", progress))

                line = line.rstrip()
                role_match = role_pattern.match(line)
                
                if role_match:
                    if current_role:
                        write_message(current_role, current_message_lines, current_time)
                        current_time += timedelta(minutes=1)
                        current_message_lines = []
                        count += 1
                    current_role = role_match.group(1)
                    continue
                
                if separator_pattern.match(line):
                    continue
                
                if current_role:
                    current_message_lines.append(line)

            # Last message
            if current_role and current_message_lines:
                write_message(current_role, current_message_lines, current_time)
                count += 1

            self.queue.put(("progress", 100))
            self.queue.put(("done", (count, output_path))) # Pass path back


# --- GUI Application ---

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Cherry Chat Converter Pro")
        self.root.geometry("650x600")
        self.root.resizable(False, False)

        self.queue = queue.Queue()
        self.worker = None
        self.last_output_path = None

        self._init_ui()
        self.root.after(100, self._process_queue)

    def _init_ui(self):
        # Styles
        style = ttk.Style()
        style.configure("TButton", padding=6)
        style.configure("TLabel", padding=5)

        # Main Frame
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 1. File Selection
        file_frame = ttk.LabelFrame(main_frame, text="文件设置", padding="10")
        file_frame.pack(fill=tk.X, pady=(0, 10))

        # Input
        ttk.Label(file_frame, text="源文件 (.md):").grid(row=0, column=0, sticky="w")
        self.input_path_var = tk.StringVar()
        ttk.Entry(file_frame, textvariable=self.input_path_var, width=45).grid(row=0, column=1, padx=5)
        ttk.Button(file_frame, text="浏览文件", command=self._browse_input).grid(row=0, column=2)

        # Output Directory
        ttk.Label(file_frame, text="输出文件夹:").grid(row=1, column=0, sticky="w")
        self.output_dir_var = tk.StringVar()
        ttk.Entry(file_frame, textvariable=self.output_dir_var, width=45).grid(row=1, column=1, padx=5)
        ttk.Button(file_frame, text="选择目录", command=self._browse_output_dir).grid(row=1, column=2)

        # 2. Parameters
        param_frame = ttk.LabelFrame(main_frame, text="参数配置", padding="10")
        param_frame.pack(fill=tk.X, pady=(0, 10))

        # User Name
        ttk.Label(param_frame, text="用户角色名:").grid(row=0, column=0, sticky="w")
        self.user_name_var = tk.StringVar(value="user")
        ttk.Entry(param_frame, textvariable=self.user_name_var, width=20).grid(row=0, column=1, sticky="w", padx=5)

        # AI Name
        ttk.Label(param_frame, text="AI 角色名:").grid(row=0, column=2, sticky="w")
        self.ai_name_var = tk.StringVar(value="monika")
        ttk.Entry(param_frame, textvariable=self.ai_name_var, width=20).grid(row=0, column=3, sticky="w", padx=5)

        # Time
        ttk.Label(param_frame, text="起始时间:").grid(row=1, column=0, sticky="w")
        self.time_var = tk.StringVar(value="2025-12-01 10:00:00")
        ttk.Entry(param_frame, textvariable=self.time_var, width=20).grid(row=1, column=1, sticky="w", padx=5)
        ttk.Label(param_frame, text="(格式: YYYY-MM-DD HH:MM:SS)").grid(row=1, column=2, columnspan=2, sticky="w")

        # 3. Actions
        action_frame = ttk.Frame(main_frame)
        action_frame.pack(fill=tk.X, pady=10)
        
        self.start_btn = ttk.Button(action_frame, text="开始转换", command=self._start_conversion)
        self.start_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        self.open_dir_btn = ttk.Button(action_frame, text="打开输出文件夹", command=self._open_output_folder, state='disabled')
        self.open_dir_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))

        # 4. Progress & Log
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(main_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill=tk.X, pady=(0, 10))

        log_frame = ttk.LabelFrame(main_frame, text="运行日志", padding="5")
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        self.log_area = scrolledtext.ScrolledText(log_frame, height=10, state='disabled', font=("Consolas", 9))
        self.log_area.pack(fill=tk.BOTH, expand=True)

        # Footer
        footer_label = ttk.Label(main_frame, text="by Hakureimu", font=("Segoe UI", 8), foreground="gray")
        footer_label.pack(side=tk.BOTTOM, pady=(5, 0))

    def _log(self, message):
        self.log_area.config(state='normal')
        self.log_area.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] {message}\n")
        self.log_area.see(tk.END)
        self.log_area.config(state='disabled')

    def _browse_input(self):
        path = filedialog.askopenfilename(filetypes=[("Markdown Files", "*.md"), ("All Files", "*.*")])
        if path:
            self.input_path_var.set(path)
            # Auto-set output dir if empty
            if not self.output_dir_var.get():
                self.output_dir_var.set(os.path.dirname(path))

    def _browse_output_dir(self):
        path = filedialog.askdirectory()
        if path:
            self.output_dir_var.set(path)
            
    def _open_output_folder(self):
        if self.last_output_path:
             # Open folder and select file if possible
            folder = os.path.dirname(self.last_output_path)
            if os.path.exists(folder):
                os.startfile(folder)
            else:
                messagebox.showerror("错误", "文件夹不存在！")
        elif self.output_dir_var.get():
             folder = self.output_dir_var.get()
             if os.path.exists(folder):
                os.startfile(folder)

    def _start_conversion(self):
        input_path = self.input_path_var.get()
        output_dir = self.output_dir_var.get()
        
        if not input_path or not os.path.exists(input_path):
            messagebox.showerror("错误", "请选择有效的源文件！")
            return
            
        if not output_dir:
            messagebox.showerror("错误", "请选择输出文件夹！")
            return
            
        if not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir)
            except Exception as e:
                messagebox.showerror("错误", f"无法创建输出目录: {e}")
                return
            
        try:
            start_time = datetime.strptime(self.time_var.get(), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            messagebox.showerror("错误", "时间格式错误！\n请使用 YYYY-MM-DD HH:MM:SS")
            return

        config = {
            'input_path': input_path,
            'output_dir': output_dir,
            'user_name': self.user_name_var.get(),
            'char_name': self.ai_name_var.get(),
            'start_time': start_time
        }

        self.start_btn.config(state='disabled')
        self.open_dir_btn.config(state='disabled')
        self.progress_var.set(0)
        self.log_area.config(state='normal')
        self.log_area.delete(1.0, tk.END)
        self.log_area.config(state='disabled')
        
        self._log("任务开始...")
        
        self.worker = ConverterThread(config, self.queue)
        self.worker.start()

    def _process_queue(self):
        try:
            while True:
                msg_type, data = self.queue.get_nowait()
                
                if msg_type == "progress":
                    self.progress_var.set(data)
                elif msg_type == "log":
                    self._log(data)
                elif msg_type == "done":
                    count, output_path = data
                    self.last_output_path = output_path
                    self._log(f"转换完成！共处理 {count} 条消息。")
                    self._log(f"文件保存至: {output_path}")
                    messagebox.showinfo("成功", f"转换完成！\n共 {count} 条消息。")
                    self.start_btn.config(state='normal')
                    self.open_dir_btn.config(state='normal')
                elif msg_type == "error":
                    self._log(f"错误: {data}")
                    messagebox.showerror("运行错误", data)
                    self.start_btn.config(state='normal')
                    
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._process_queue)

if __name__ == "__main__":
    check_and_install_dependencies()
    root = tk.Tk()
    app = App(root)
    root.mainloop()
