"""
gui.py
------
Tkinter GUI for TikTok Quality Fix (CompressBase Method).
Provides batch conversion, customizable encoding parameters, real-time progress bars,
color-coded execution log, and target specification validation.
"""

from __future__ import annotations

import os
import queue
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Dict, Any, List, Optional

from . import encoder as fw
from . import patcher as iso
from . import validator as val


class Msg:
    LOG = "log"
    PROGRESS_FILE = "progress_file"     # (index, percent)
    PROGRESS_TOTAL = "progress_total"   # (done, total)
    FILE_DONE = "file_done"             # (index, success, summary)
    ALL_DONE = "all_done"
    ERROR = "error"                     # (index, message)


def process_single_file(
    index: int,
    input_path: str,
    output_dir: str,
    params: Dict[str, Any],
    msg_queue: queue.Queue,
):
    """Process a single video through the CompressBase pipeline in a worker thread."""

    def log(text: str):
        msg_queue.put((Msg.LOG, text))

    def prog(pct: float, line: str = ""):
        msg_queue.put((Msg.PROGRESS_FILE, (index, pct)))
        if line:
            log(f"  ffmpeg: {line}")

    basename = os.path.basename(input_path)
    stem, _ = os.path.splitext(basename)
    output_path = os.path.join(output_dir, f"{stem}_compressbase.mp4")

    log(f"\n{'='*60}")
    log(f"[{index + 1}] Processing: {basename}")
    log(f"    Output : {output_path}")

    tmp_path: Optional[str] = None
    try:
        # 1. Probe input
        log("  Probing source video…")
        src_probe = fw.probe(input_path)
        log(fw.format_probe_summary(src_probe, "SOURCE"))

        # 2. Encode to temp file
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".mp4", prefix="cb_tmp_")
        os.close(tmp_fd)

        log("  Encoding via FFmpeg (H.264 CBL + Dual AAC)…")
        fw.encode(
            input_path=input_path,
            output_path=tmp_path,
            bitrate_multiplier=params["bitrate_multiplier"],
            audio_bitrate1_kbps=params["audio_bitrate1"],
            audio_bitrate2_kbps=params["audio_bitrate2"],
            preset=params["preset"],
            level=params["level"],
            comment=params["comment"],
            progress_callback=prog,
        )

        # 3. Binary ISOBMFF patches
        log("  Applying ISOBMFF binary patches (ftyp, timestamps, hdlr, audio2)…")
        iso.apply_isobmff_patches(
            input_path=tmp_path,
            output_path=output_path,
            major_brand="isom",
            minor_version=512,
            compatible_brands=["isom", "iso2", "avc1", "mp41"],
            remove_creation_time=True,
            encoder="Lavf59.27.100",
            audio_multiplier=params.get("audio_multiplier", 10),
        )

        # 4. Probe output & validate
        log("  Probing output and validating…")
        final_probe = fw.probe(output_path)
        log(fw.format_probe_summary(final_probe, "OUTPUT"))

        issues = val.validate_output(final_probe)
        if issues:
            log("  [!] Validation issues:")
            for iss in issues:
                log(f"    - {iss}")
        else:
            log("  [+] Validation passed: 100% compliant with TikTok / CompressBase spec.")

        src_size = os.path.getsize(input_path)
        dst_size = os.path.getsize(output_path)
        ratio = (dst_size / src_size * 100) if src_size > 0 else 0
        log(f"  Size: {src_size / 1024 / 1024:.2f} MB -> {dst_size / 1024 / 1024:.2f} MB ({ratio:.0f}%)")

        status_text = "OK" if not issues else f"{len(issues)} warnings"
        summary = f"{os.path.basename(output_path)} ({dst_size / 1024 / 1024:.1f} MB) - {status_text}"
        msg_queue.put((Msg.FILE_DONE, (index, True, summary)))

    except Exception as exc:
        log(f"  [x] ERROR: {exc}")
        msg_queue.put((Msg.ERROR, (index, str(exc))))
        msg_queue.put((Msg.FILE_DONE, (index, False, f"FAILED: {exc}")))
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def batch_worker(files: List[str], output_dir: str, params: Dict[str, Any], msg_queue: queue.Queue):
    """Worker thread running batch queue."""
    total = len(files)
    for i, path in enumerate(files):
        process_single_file(i, path, output_dir, params, msg_queue)
        msg_queue.put((Msg.PROGRESS_TOTAL, (i + 1, total)))
    msg_queue.put((Msg.ALL_DONE, None))


class TikTokQualityApp(tk.Tk):
    """CompressBase Tkinter Graphical Interface."""

    def __init__(self):
        super().__init__()
        self.title("TikTok Quality Fix - CompressBase Edition")
        self.resizable(True, True)
        self.minsize(800, 600)
        self._files: List[str] = []
        self._output_dir_var = tk.StringVar(value="")
        self._running = False
        self._msg_queue: queue.Queue = queue.Queue()
        self._params: Dict[str, tk.StringVar] = {}

        self._build_ui()
        self._poll_queue()

    def _build_ui(self):
        # 1. Input files frame
        top = ttk.LabelFrame(self, text="Input Videos", padding=8)
        top.pack(fill="both", expand=False, padx=10, pady=(10, 4))

        btn_row = ttk.Frame(top)
        btn_row.pack(fill="x", pady=(0, 6))
        ttk.Button(btn_row, text="Add Files…", command=self._add_files).pack(side="left", padx=2)
        ttk.Button(btn_row, text="Remove Selected", command=self._remove_selected).pack(side="left", padx=2)
        ttk.Button(btn_row, text="Clear All", command=self._clear_files).pack(side="left", padx=2)

        list_frame = ttk.Frame(top)
        list_frame.pack(fill="both", expand=True)
        scroll_y = ttk.Scrollbar(list_frame, orient="vertical")
        self._file_listbox = tk.Listbox(
            list_frame, height=5, selectmode="extended",
            yscrollcommand=scroll_y.set, font=("Consolas", 9),
        )
        scroll_y.config(command=self._file_listbox.yview)
        scroll_y.pack(side="right", fill="y")
        self._file_listbox.pack(side="left", fill="both", expand=True)

        # 2. Settings frame
        mid = ttk.LabelFrame(self, text="CompressBase Encoding Settings", padding=8)
        mid.pack(fill="x", padx=10, pady=4)

        row0 = ttk.Frame(mid)
        row0.pack(fill="x", pady=2)
        self._make_param(row0, "Bitrate Multiplier:", "bitrate_multiplier", "1.0",
                         tooltip="Output bitrate = source * multiplier (1.0 = 100%)")
        self._make_param(row0, "FFmpeg Preset:", "preset", "fast",
                         choices=["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow"])

        row1 = ttk.Frame(mid)
        row1.pack(fill="x", pady=2)
        self._make_param(row1, "H.264 Level:", "level", "4.2",
                         choices=["3.1", "3.2", "4.0", "4.1", "4.2"])
        self._make_param(row1, "Audio 1 kbps:", "audio_bitrate1", "190")
        self._make_param(row1, "Audio 2 kbps:", "audio_bitrate2", "215")

        row2 = ttk.Frame(mid)
        row2.pack(fill="x", pady=2)
        ttk.Label(row2, text="Comment Tag:").pack(side="left", padx=4)
        self._params["comment"] = tk.StringVar(value="Patched by CompressBase")
        ttk.Entry(row2, textvariable=self._params["comment"], width=32).pack(side="left", padx=2)

        # Output folder row
        out_row = ttk.Frame(mid)
        out_row.pack(fill="x", pady=6)
        ttk.Label(out_row, text="Output Folder:").pack(side="left", padx=4)
        ttk.Entry(out_row, textvariable=self._output_dir_var, width=40).pack(side="left", padx=2, fill="x", expand=True)
        ttk.Button(out_row, text="Browse…", command=self._pick_output_dir).pack(side="left", padx=2)

        # 3. Progress frame
        prog_frame = ttk.LabelFrame(self, text="Progress", padding=8)
        prog_frame.pack(fill="x", padx=10, pady=4)

        self._current_file_label = ttk.Label(prog_frame, text="Idle", anchor="w")
        self._current_file_label.pack(fill="x")
        self._file_progress = ttk.Progressbar(prog_frame, orient="horizontal", mode="determinate", maximum=100)
        self._file_progress.pack(fill="x", pady=2)

        self._total_label = ttk.Label(prog_frame, text="Total: 0 / 0", anchor="w")
        self._total_label.pack(fill="x")
        self._total_progress = ttk.Progressbar(prog_frame, orient="horizontal", mode="determinate", maximum=100)
        self._total_progress.pack(fill="x", pady=2)

        # Buttons
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", padx=10, pady=4)
        self._start_btn = ttk.Button(btn_frame, text="Start Batch", command=self._start_batch)
        self._start_btn.pack(side="left", padx=4)
        self._stop_btn = ttk.Button(btn_frame, text="Stop", command=self._stop_batch, state="disabled")
        self._stop_btn.pack(side="left", padx=4)

        # 4. Log frame
        log_frame = ttk.LabelFrame(self, text="Activity & Validation Log", padding=8)
        log_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        log_scroll_y = ttk.Scrollbar(log_frame, orient="vertical")
        log_scroll_x = ttk.Scrollbar(log_frame, orient="horizontal")
        self._log_text = tk.Text(
            log_frame, height=12, state="disabled", wrap="none",
            font=("Consolas", 8),
            yscrollcommand=log_scroll_y.set,
            xscrollcommand=log_scroll_x.set,
        )
        log_scroll_y.config(command=self._log_text.yview)
        log_scroll_x.config(command=self._log_text.xview)
        log_scroll_x.pack(side="bottom", fill="x")
        log_scroll_y.pack(side="right", fill="y")
        self._log_text.pack(side="left", fill="both", expand=True)

        clear_btn = ttk.Button(log_frame, text="Clear Log", command=self._clear_log)
        clear_btn.pack(side="bottom", anchor="w", pady=2)

        # Color tags
        self._log_text.tag_config("ok", foreground="#008800")
        self._log_text.tag_config("warn", foreground="#cc6600")
        self._log_text.tag_config("err", foreground="#cc0000")
        self._log_text.tag_config("head", foreground="#0044aa", font=("Consolas", 8, "bold"))

        self._stop_flag = threading.Event()

    def _make_param(self, parent, label, key, default, tooltip="", choices=None):
        f = ttk.Frame(parent)
        f.pack(side="left", padx=6)
        ttk.Label(f, text=label).pack(side="left")
        var = tk.StringVar(value=default)
        self._params[key] = var
        if choices:
            w = ttk.Combobox(f, textvariable=var, values=choices, width=10, state="readonly")
        else:
            w = ttk.Entry(f, textvariable=var, width=8)
        w.pack(side="left", padx=2)

    def _add_files(self):
        paths = filedialog.askopenfilenames(
            title="Select Video Files",
            filetypes=[("Video files", "*.mp4 *.mov *.mkv *.avi *.ts *.m4v"), ("All files", "*.*")],
        )
        for p in paths:
            if p not in self._files:
                self._files.append(p)
                self._file_listbox.insert("end", os.path.basename(p))

    def _remove_selected(self):
        sel = list(self._file_listbox.curselection())
        for i in reversed(sel):
            self._file_listbox.delete(i)
            del self._files[i]

    def _clear_files(self):
        self._file_listbox.delete(0, "end")
        self._files.clear()

    def _pick_output_dir(self):
        d = filedialog.askdirectory(title="Select Output Folder")
        if d:
            self._output_dir_var.set(d)

    def _collect_params(self) -> Optional[Dict[str, Any]]:
        try:
            return {
                "bitrate_multiplier": float(self._params["bitrate_multiplier"].get()),
                "audio_bitrate1": int(self._params["audio_bitrate1"].get()),
                "audio_bitrate2": int(self._params["audio_bitrate2"].get()),
                "preset": self._params["preset"].get(),
                "level": self._params["level"].get(),
                "comment": self._params["comment"].get(),
                "audio_multiplier": 10,
            }
        except ValueError as e:
            messagebox.showerror("Invalid Parameter", str(e))
            return None

    def _start_batch(self):
        if not self._files:
            messagebox.showwarning("No Files", "Please add at least one video file to process.")
            return

        output_dir = self._output_dir_var.get().strip()
        if not output_dir:
            output_dir = os.path.dirname(self._files[0])
            self._output_dir_var.set(output_dir)

        if not os.path.isdir(output_dir):
            try:
                os.makedirs(output_dir, exist_ok=True)
            except Exception as e:
                messagebox.showerror("Output Folder Error", f"Cannot create folder:\n{e}")
                return

        try:
            fw.find_ffmpeg()
        except RuntimeError as e:
            messagebox.showerror("FFmpeg Not Found", str(e))
            return

        params = self._collect_params()
        if params is None:
            return

        self._running = True
        self._stop_flag.clear()
        self._start_btn.config(state="disabled")
        self._stop_btn.config(state="normal")
        self._file_progress["value"] = 0
        self._total_progress["value"] = 0
        self._total_label.config(text=f"Total: 0 / {len(self._files)}")

        files_copy = list(self._files)
        t = threading.Thread(
            target=batch_worker,
            args=(files_copy, output_dir, params, self._msg_queue),
            daemon=True,
        )
        t.start()

    def _stop_batch(self):
        self._stop_flag.set()
        self._log("Stop requested. Waiting for current file to complete…", "warn")

    def _poll_queue(self):
        try:
            while True:
                kind, data = self._msg_queue.get_nowait()
                self._handle_msg(kind, data)
        except queue.Empty:
            pass
        self.after(80, self._poll_queue)

    def _handle_msg(self, kind: str, data: Any):
        if kind == Msg.LOG:
            tag = ""
            if "[+]" in data or "passed" in data.lower():
                tag = "ok"
            elif "[!]" in data or "warning" in data.lower():
                tag = "warn"
            elif "[x]" in data or "error" in data.lower():
                tag = "err"
            elif data.startswith("==="):
                tag = "head"
            self._log(data, tag)

        elif kind == Msg.PROGRESS_FILE:
            index, pct = data
            basename = os.path.basename(self._files[index]) if index < len(self._files) else ""
            self._current_file_label.config(text=f"File [{index + 1}]: {basename} - {pct:.0f}%")
            self._file_progress["value"] = pct

        elif kind == Msg.PROGRESS_TOTAL:
            done, total = data
            self._total_label.config(text=f"Total: {done} / {total}")
            self._total_progress["value"] = (done / total * 100) if total > 0 else 0

        elif kind == Msg.FILE_DONE:
            _, success, summary = data
            tag = "ok" if success else "err"
            self._log(f"  -> {summary}", tag)

        elif kind == Msg.ALL_DONE:
            self._running = False
            self._start_btn.config(state="normal")
            self._stop_btn.config(state="disabled")
            self._current_file_label.config(text="Done.")
            self._file_progress["value"] = 100
            self._total_progress["value"] = 100
            self._log("\nBatch complete!", "ok")
            messagebox.showinfo("Done", "Batch processing complete!")

        elif kind == Msg.ERROR:
            index, msg = data
            self._log(f"  ERROR [{index + 1}]: {msg}", "err")

    def _log(self, text: str, tag: str = ""):
        self._log_text.config(state="normal")
        if tag:
            self._log_text.insert("end", text + "\n", tag)
        else:
            self._log_text.insert("end", text + "\n")
        self._log_text.see("end")
        self._log_text.config(state="disabled")

    def _clear_log(self):
        self._log_text.config(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.config(state="disabled")


def main():
    """Launch GUI application."""
    app = TikTokQualityApp()
    app.mainloop()


if __name__ == "__main__":
    main()
