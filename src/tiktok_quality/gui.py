"""
gui.py
------
Modern GUI for TikTok Quality Fix (CompressBase Method) using CustomTkinter.
Provides batch video queuing, hardware acceleration selection, preset management,
dual progress bars, real-time logging, and output validation.
Includes graceful fallback to ttk if CustomTkinter is unavailable.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import tempfile
import threading
from typing import Dict, Any, List, Optional

from . import __version__
from . import encoder as fw
from . import patcher as iso
from . import validator as val
from .compressbase import process_video

# Attempt to import CustomTkinter, with fallback to standard tkinter
try:
    import customtkinter as ctk
    _USE_CTK = True
except ImportError:
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog
    ctk = None  # type: ignore
    _USE_CTK = False

if _USE_CTK:
    import tkinter as tk
    from tkinter import filedialog, messagebox


class Msg:
    LOG = "log"
    PROGRESS_FILE = "progress_file"     # (index, percent, status_line)
    PROGRESS_TOTAL = "progress_total"   # (done, total)
    FILE_DONE = "file_done"             # (index, success, summary)
    ALL_DONE = "all_done"
    ERROR = "error"                     # (index, message)


PRESETS = {
    "⚡ TikTok 1080p60 (Рекомендуемый)": {
        "bitrate_multiplier": 1.0,
        "preset": "fast",
        "level": "4.2",
        "audio_bitrate1": 190,
        "audio_bitrate2": 215,
        "encoder": "auto",
    },
    "💎 Максимальное качество (HQ)": {
        "bitrate_multiplier": 1.25,
        "preset": "slow",
        "level": "4.2",
        "audio_bitrate1": 192,
        "audio_bitrate2": 256,
        "encoder": "auto",
    },
    "🚀 Ультра-быстрый (Fast)": {
        "bitrate_multiplier": 1.0,
        "preset": "ultrafast",
        "level": "4.2",
        "audio_bitrate1": 190,
        "audio_bitrate2": 215,
        "encoder": "auto",
    },
    "⚙️ Пользовательский (Custom)": None,
}


def process_single_file(
    index: int,
    input_path: str,
    output_dir: str,
    params: Dict[str, Any],
    msg_queue: queue.Queue,
    cancel_event: threading.Event,
):
    """Process a single video through the CompressBase pipeline in a worker thread."""

    def log(text: str):
        msg_queue.put((Msg.LOG, text))

    def prog(pct: float, line: str = ""):
        msg_queue.put((Msg.PROGRESS_FILE, (index, pct, line)))

    basename = os.path.basename(input_path)
    stem, _ = os.path.splitext(basename)
    output_path = os.path.join(output_dir, f"{stem}_compressbase.mp4")

    log(f"\n{'='*60}")
    log(f"[{index + 1}] Обработка файла: {basename}")
    log(f"    Куда: {output_path}")

    try:
        if cancel_event.is_set():
            log("  [!] Отменено пользователем.")
            msg_queue.put((Msg.FILE_DONE, (index, False, "Отменено")))
            return

        result = process_video(
            input_path=input_path,
            output_path=output_path,
            bitrate_multiplier=params["bitrate_multiplier"],
            audio_bitrate1=params["audio_bitrate1"],
            audio_bitrate2=params["audio_bitrate2"],
            preset=params["preset"],
            level=params["level"],
            comment=params["comment"],
            audio_multiplier=params.get("audio_multiplier", 10),
            video_encoder=params.get("video_encoder", "libx264"),
            progress_callback=prog,
            cancel_event=cancel_event,
        )

        val_info = result.get("validation", {})
        issues = val_info.get("issues", [])
        if issues:
            log("  [!] Замечания валидации:")
            for iss in issues:
                log(f"    - {iss}")
        else:
            log("  [+] Валидация успешна: 100% совместимо с TikTok CompressBase!")

        src_mb = result["sourceSizeBytes"] / 1024 / 1024
        out_mb = result["sizeBytes"] / 1024 / 1024
        ratio = result["compressionRatio"]
        elapsed = result["elapsedSeconds"]
        log(f"  Размер: {src_mb:.2f} MB -> {out_mb:.2f} MB ({ratio}%) за {elapsed}с")

        status_txt = "OK" if not issues else f"{len(issues)} пред."
        summary = f"{os.path.basename(output_path)} ({out_mb:.1f} MB) - {status_txt}"
        msg_queue.put((Msg.FILE_DONE, (index, True, summary)))

    except Exception as exc:
        if cancel_event.is_set():
            log("  [!] Обработка прервана пользователем.")
            msg_queue.put((Msg.FILE_DONE, (index, False, "Прервано")))
        else:
            log(f"  [x] ОШИБКА: {exc}")
            msg_queue.put((Msg.ERROR, (index, str(exc))))
            msg_queue.put((Msg.FILE_DONE, (index, False, f"Ошибка: {exc}")))


def batch_worker(
    files: List[str],
    output_dir: str,
    params: Dict[str, Any],
    msg_queue: queue.Queue,
    cancel_event: threading.Event,
):
    """Worker thread running batch queue."""
    total = len(files)
    for i, path in enumerate(files):
        if cancel_event.is_set():
            break
        process_single_file(i, path, output_dir, params, msg_queue, cancel_event)
        msg_queue.put((Msg.PROGRESS_TOTAL, (i + 1, total)))
    msg_queue.put((Msg.ALL_DONE, None))


if _USE_CTK:
    # ---------------------------------------------------------------------------
    # CustomTkinter Modern UI Implementation
    # ---------------------------------------------------------------------------
    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("blue")

    class ModernTikTokQualityApp(ctk.CTk):
        def __init__(self):
            super().__init__()

            self.title(f"TikTok Quality Fix v{__version__} — Modern Edition")
            self.geometry("960x780")
            self.minsize(860, 680)

            self._files: List[str] = []
            self._output_dir = ctk.StringVar(value="")
            self._running = False
            self._msg_queue: queue.Queue = queue.Queue()
            self._cancel_event = threading.Event()

            # Parameters
            self._preset_var = ctk.StringVar(value=list(PRESETS.keys())[0])
            self._multiplier_var = ctk.StringVar(value="1.0")
            self._ffmpeg_preset_var = ctk.StringVar(value="fast")
            self._level_var = ctk.StringVar(value="4.2")
            self._audio1_var = ctk.StringVar(value="190")
            self._audio2_var = ctk.StringVar(value="215")
            self._comment_var = ctk.StringVar(value="Patched by CompressBase")
            self._encoder_var = ctk.StringVar(value="Auto")
            self._theme_var = ctk.StringVar(value="Dark")

            self._build_ui()
            self._poll_queue()

        def _build_ui(self):
            # Header Frame
            header = ctk.CTkFrame(self, corner_radius=10, fg_color=("gray85", "gray17"))
            header.pack(fill="x", padx=14, pady=(12, 6))

            title_lbl = ctk.CTkLabel(
                header,
                text="🎵 TikTok Quality Fix",
                font=ctk.CTkFont(size=20, weight="bold"),
            )
            title_lbl.pack(side="left", padx=16, pady=10)

            sub_lbl = ctk.CTkLabel(
                header,
                text="1080p 60fps CompressBase Engine",
                font=ctk.CTkFont(size=12),
                text_color="gray",
            )
            sub_lbl.pack(side="left", padx=4, pady=10)

            theme_menu = ctk.CTkOptionMenu(
                header,
                values=["Dark", "Light", "System"],
                variable=self._theme_var,
                command=self._change_theme,
                width=100,
            )
            theme_menu.pack(side="right", padx=16, pady=10)

            # Main content layout (Two columns: Files & Settings)
            content_grid = ctk.CTkFrame(self, fg_color="transparent")
            content_grid.pack(fill="both", expand=True, padx=14, pady=4)
            content_grid.grid_columnconfigure(0, weight=3)
            content_grid.grid_columnconfigure(1, weight=2)
            content_grid.grid_rowconfigure(0, weight=1)

            # Left Card: Files Queue
            files_card = ctk.CTkFrame(content_grid, corner_radius=10)
            files_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=0)

            files_header = ctk.CTkLabel(
                files_card,
                text="📁 Очередь видеофайлов",
                font=ctk.CTkFont(size=14, weight="bold"),
            )
            files_header.pack(anchor="w", padx=12, pady=(10, 6))

            btn_row = ctk.CTkFrame(files_card, fg_color="transparent")
            btn_row.pack(fill="x", padx=10, pady=(0, 6))
            ctk.CTkButton(btn_row, text="+ Добавить файлы", width=120, command=self._add_files).pack(side="left", padx=4)
            ctk.CTkButton(btn_row, text="Удалить выбранные", width=130, fg_color="gray40", hover_color="gray30", command=self._remove_selected).pack(side="left", padx=4)
            ctk.CTkButton(btn_row, text="Очистить всё", width=100, fg_color="#b83232", hover_color="#992626", command=self._clear_files).pack(side="left", padx=4)

            self._file_textbox = ctk.CTkTextbox(
                files_card,
                font=ctk.CTkFont(family="Consolas", size=11),
                wrap="none",
                corner_radius=6,
            )
            self._file_textbox.pack(fill="both", expand=True, padx=10, pady=(0, 10))

            # Right Card: Settings & Presets
            settings_card = ctk.CTkFrame(content_grid, corner_radius=10)
            settings_card.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=0)

            settings_lbl = ctk.CTkLabel(
                settings_card,
                text="⚙️ Параметры кодирования",
                font=ctk.CTkFont(size=14, weight="bold"),
            )
            settings_lbl.pack(anchor="w", padx=12, pady=(10, 6))

            # Preset selector
            ctk.CTkLabel(settings_card, text="Быстрый пресет:", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=12, pady=(4, 0))
            self._preset_menu = ctk.CTkOptionMenu(
                settings_card,
                values=list(PRESETS.keys()),
                variable=self._preset_var,
                command=self._on_preset_change,
            )
            self._preset_menu.pack(fill="x", padx=12, pady=(2, 6))

            # Encoder selection
            detected_encoders = ["Auto (Рекомендуется)", "libx264 (CPU)"]
            avail = fw.get_available_video_encoders()
            if "h264_nvenc" in avail:
                detected_encoders.append("h264_nvenc (NVIDIA)")
            if "h264_qsv" in avail:
                detected_encoders.append("h264_qsv (Intel)")
            if "h264_amf" in avail:
                detected_encoders.append("h264_amf (AMD)")

            ctk.CTkLabel(settings_card, text="Видеокодек / Ускоритель:", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=12, pady=(4, 0))
            self._encoder_menu = ctk.CTkOptionMenu(
                settings_card,
                values=detected_encoders,
                variable=self._encoder_var,
            )
            self._encoder_menu.pack(fill="x", padx=12, pady=(2, 6))

            # Bitrate multiplier
            ctk.CTkLabel(settings_card, text="Множитель битрейта (1.0 = 100%):", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=12, pady=(4, 0))
            ctk.CTkEntry(settings_card, textvariable=self._multiplier_var).pack(fill="x", padx=12, pady=(2, 6))

            # Preset speed
            ctk.CTkLabel(settings_card, text="Скорость FFmpeg (Preset):", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=12, pady=(4, 0))
            ctk.CTkOptionMenu(
                settings_card,
                values=["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow"],
                variable=self._ffmpeg_preset_var,
            ).pack(fill="x", padx=12, pady=(2, 6))

            # Audio Bitrates
            audio_row = ctk.CTkFrame(settings_card, fg_color="transparent")
            audio_row.pack(fill="x", padx=12, pady=4)
            audio_row.grid_columnconfigure((0, 1), weight=1)

            ctk.CTkLabel(audio_row, text="Аудио 1 (кбит/с):", font=ctk.CTkFont(size=11)).grid(row=0, column=0, sticky="w")
            ctk.CTkEntry(audio_row, textvariable=self._audio1_var, width=80).grid(row=1, column=0, sticky="ew", padx=(0, 4))

            ctk.CTkLabel(audio_row, text="Аудио 2 (кбит/с):", font=ctk.CTkFont(size=11)).grid(row=0, column=1, sticky="w")
            ctk.CTkEntry(audio_row, textvariable=self._audio2_var, width=80).grid(row=1, column=1, sticky="ew", padx=(4, 0))

            # Output folder
            ctk.CTkLabel(settings_card, text="Папка сохранения:", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=12, pady=(8, 0))
            out_row = ctk.CTkFrame(settings_card, fg_color="transparent")
            out_row.pack(fill="x", padx=12, pady=(2, 10))
            ctk.CTkEntry(out_row, textvariable=self._output_dir).pack(side="left", fill="x", expand=True, padx=(0, 6))
            ctk.CTkButton(out_row, text="Обзор…", width=70, command=self._pick_output_dir).pack(side="right")

            # Progress & Control Frame
            control_card = ctk.CTkFrame(self, corner_radius=10)
            control_card.pack(fill="x", padx=14, pady=6)

            self._cur_file_lbl = ctk.CTkLabel(control_card, text="Ожидание запуска…", font=ctk.CTkFont(size=12), anchor="w")
            self._cur_file_lbl.pack(fill="x", padx=14, pady=(8, 2))

            self._file_prog = ctk.CTkProgressBar(control_card)
            self._file_prog.set(0)
            self._file_prog.pack(fill="x", padx=14, pady=2)

            self._total_lbl = ctk.CTkLabel(control_card, text="Очередь: 0 / 0", font=ctk.CTkFont(size=12), anchor="w")
            self._total_lbl.pack(fill="x", padx=14, pady=(4, 2))

            self._total_prog = ctk.CTkProgressBar(control_card)
            self._total_prog.set(0)
            self._total_prog.pack(fill="x", padx=14, pady=2)

            # Action Buttons Row
            actions_row = ctk.CTkFrame(control_card, fg_color="transparent")
            actions_row.pack(fill="x", padx=14, pady=(8, 10))

            self._start_btn = ctk.CTkButton(
                actions_row,
                text="▶ Запустить обработку",
                font=ctk.CTkFont(size=13, weight="bold"),
                fg_color="#107c41",
                hover_color="#0b5e31",
                command=self._start_batch,
                height=36,
            )
            self._start_btn.pack(side="left", padx=(0, 8))

            self._stop_btn = ctk.CTkButton(
                actions_row,
                text="⏹ Остановить",
                font=ctk.CTkFont(size=13),
                fg_color="#b83232",
                hover_color="#992626",
                command=self._stop_batch,
                state="disabled",
                height=36,
            )
            self._stop_btn.pack(side="left", padx=8)

            self._open_out_btn = ctk.CTkButton(
                actions_row,
                text="📂 Открыть папку вывода",
                font=ctk.CTkFont(size=12),
                fg_color="gray30",
                hover_color="gray40",
                command=self._open_output_folder,
                height=36,
            )
            self._open_out_btn.pack(side="right")

            # Activity Log Frame
            log_card = ctk.CTkFrame(self, corner_radius=10)
            log_card.pack(fill="both", expand=True, padx=14, pady=(0, 12))

            log_header_row = ctk.CTkFrame(log_card, fg_color="transparent")
            log_header_row.pack(fill="x", padx=12, pady=(6, 2))
            ctk.CTkLabel(log_header_row, text="📋 Журнал операций (Log):", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left")
            ctk.CTkButton(log_header_row, text="Очистить лог", width=90, height=24, fg_color="transparent", border_width=1, command=self._clear_log).pack(side="right")

            self._log_text = ctk.CTkTextbox(
                log_card,
                font=ctk.CTkFont(family="Consolas", size=10),
                wrap="none",
                corner_radius=6,
            )
            self._log_text.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        def _change_theme(self, new_theme: str):
            ctk.set_appearance_mode(new_theme)

        def _on_preset_change(self, preset_name: str):
            cfg = PRESETS.get(preset_name)
            if cfg:
                self._multiplier_var.set(str(cfg["bitrate_multiplier"]))
                self._ffmpeg_preset_var.set(cfg["preset"])
                self._level_var.set(cfg["level"])
                self._audio1_var.set(str(cfg["audio_bitrate1"]))
                self._audio2_var.set(str(cfg["audio_bitrate2"]))

        def _add_files(self):
            paths = filedialog.askopenfilenames(
                title="Выберите видео файлы",
                filetypes=[
                    ("Видео файлы", "*.mp4 *.mov *.mkv *.avi *.ts *.m4v *.webm"),
                    ("Все файлы", "*.*"),
                ],
            )
            for p in paths:
                if p not in self._files:
                    self._files.append(p)
            self._refresh_file_list()

        def _remove_selected(self):
            # For simplicity, removes last or clear
            if self._files:
                self._files.pop()
                self._refresh_file_list()

        def _clear_files(self):
            self._files.clear()
            self._refresh_file_list()

        def _refresh_file_list(self):
            self._file_textbox.delete("1.0", "end")
            for i, p in enumerate(self._files, start=1):
                sz = os.path.getsize(p) / 1024 / 1024 if os.path.isfile(p) else 0
                self._file_textbox.insert("end", f"[{i}] {os.path.basename(p)} ({sz:.1f} MB)\n    {p}\n")

        def _pick_output_dir(self):
            d = filedialog.askdirectory(title="Выберите папку для сохранения")
            if d:
                self._output_dir.set(d)

        def _open_output_folder(self):
            out = self._output_dir.get().strip()
            if out and os.path.isdir(out):
                if sys.platform == "win32":
                    os.startfile(out)
                else:
                    subprocess.Popen(["xdg-open", out])
            elif self._files:
                parent = os.path.dirname(self._files[0])
                if os.path.isdir(parent):
                    if sys.platform == "win32":
                        os.startfile(parent)

        def _collect_params(self) -> Optional[Dict[str, Any]]:
            try:
                enc_choice = self._encoder_var.get()
                codec = "libx264"
                if "nvenc" in enc_choice.lower():
                    codec = "h264_nvenc"
                elif "qsv" in enc_choice.lower():
                    codec = "h264_qsv"
                elif "amf" in enc_choice.lower():
                    codec = "h264_amf"

                return {
                    "bitrate_multiplier": float(self._multiplier_var.get()),
                    "audio_bitrate1": int(self._audio1_var.get()),
                    "audio_bitrate2": int(self._audio2_var.get()),
                    "preset": self._ffmpeg_preset_var.get(),
                    "level": self._level_var.get(),
                    "comment": self._comment_var.get(),
                    "video_encoder": codec,
                    "audio_multiplier": 10,
                }
            except ValueError as e:
                messagebox.showerror("Неверные параметры", f"Ошибка в числовых параметрах:\n{e}")
                return None

        def _start_batch(self):
            if not self._files:
                messagebox.showwarning("Нет файлов", "Пожалуйста, добавьте хотя бы одно видео для обработки.")
                return

            output_dir = self._output_dir.get().strip()
            if not output_dir:
                output_dir = os.path.dirname(self._files[0])
                self._output_dir.set(output_dir)

            if not os.path.isdir(output_dir):
                try:
                    os.makedirs(output_dir, exist_ok=True)
                except Exception as e:
                    messagebox.showerror("Ошибка папки", f"Не удалось создать директорию вывода:\n{e}")
                    return

            try:
                fw.find_ffmpeg()
            except RuntimeError as e:
                messagebox.showerror("FFmpeg не найден", str(e))
                return

            params = self._collect_params()
            if params is None:
                return

            self._running = True
            self._cancel_event.clear()
            self._start_btn.configure(state="disabled")
            self._stop_btn.configure(state="normal")
            self._file_prog.set(0)
            self._total_prog.set(0)
            self._total_lbl.configure(text=f"Очередь: 0 / {len(self._files)}")

            files_copy = list(self._files)
            t = threading.Thread(
                target=batch_worker,
                args=(files_copy, output_dir, params, self._msg_queue, self._cancel_event),
                daemon=True,
            )
            t.start()

        def _stop_batch(self):
            self._cancel_event.set()
            self._log("Запрошена остановка. Прерывание текущего процесса…")

        def _poll_queue(self):
            try:
                while True:
                    kind, data = self._msg_queue.get_nowait()
                    self._handle_msg(kind, data)
            except queue.Empty:
                pass
            self.after(60, self._poll_queue)

        def _handle_msg(self, kind: str, data: Any):
            if kind == Msg.LOG:
                self._log(data)

            elif kind == Msg.PROGRESS_FILE:
                index, pct, line = data
                base = os.path.basename(self._files[index]) if index < len(self._files) else ""
                self._cur_file_lbl.configure(text=f"[{index + 1}/{len(self._files)}] {base} — {pct:.1f}%")
                self._file_prog.set(pct / 100.0)

            elif kind == Msg.PROGRESS_TOTAL:
                done, total = data
                self._total_lbl.configure(text=f"Очередь: {done} / {total}")
                self._total_prog.set(done / total if total > 0 else 0)

            elif kind == Msg.FILE_DONE:
                _, success, summary = data
                self._log(f"  -> Итог: {summary}")

            elif kind == Msg.ALL_DONE:
                self._running = False
                self._start_btn.configure(state="normal")
                self._stop_btn.configure(state="disabled")
                self._cur_file_lbl.configure(text="Обработка завершена.")
                self._file_prog.set(1.0)
                self._total_prog.set(1.0)
                self._log("\n[+] Все задачи завершены успешно!")
                messagebox.showinfo("Готово", "Пакетная обработка видео успешно завершена!")

            elif kind == Msg.ERROR:
                index, msg = data
                self._log(f"  [x] Ошибка на файле [{index + 1}]: {msg}")

        def _log(self, text: str):
            self._log_text.insert("end", text + "\n")
            self._log_text.see("end")

        def _clear_log(self):
            self._log_text.delete("1.0", "end")

    TikTokQualityApp = ModernTikTokQualityApp

else:
    # ---------------------------------------------------------------------------
    # Fallback to standard Tkinter / ttk
    # ---------------------------------------------------------------------------
    class FallbackTikTokQualityApp(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title("TikTok Quality Fix (Fallback Mode)")
            self.geometry("800x600")
            lbl = ttk.Label(self, text="CustomTkinter не установлен. Запустите: pip install customtkinter", padding=20)
            lbl.pack()

    TikTokQualityApp = FallbackTikTokQualityApp


def main():
    """Launch GUI application."""
    app = TikTokQualityApp()
    app.mainloop()


if __name__ == "__main__":
    main()
