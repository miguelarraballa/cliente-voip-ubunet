"""
Interfaz gráfica del cliente VoIP — customtkinter.
"""
import os
import time
import threading
import subprocess
from tkinter import filedialog, messagebox
from typing import Optional

import customtkinter as ctk

from sip_client import SIPClient, Status
from contacts import ContactManager, Contact, _read_settings, _write_settings
from call_log import CallLog, TYPE_ICONS, TYPE_LABELS

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

APP_VERSION = "1.0.8"
APP_RELEASE = "20260702121800"
APP_AUTHOR  = "Miguel Arrabal"

_STATUS_DOT = {
    Status.DISCONNECTED: ("●", "#666666"),
    Status.CONNECTING:   ("●", "#FFA500"),
    Status.REGISTERED:   ("●", "#22CC44"),
    Status.INCOMING:     ("●", "#FFD700"),
    Status.CALLING:      ("●", "#4499FF"),
    Status.IN_CALL:      ("●", "#22CC44"),
    Status.ERROR:        ("●", "#CC2222"),
}

_STATUS_LABEL = {
    Status.DISCONNECTED: "Sin conexión",
    Status.CONNECTING:   "Conectando…",
    Status.REGISTERED:   "Conectado",
    Status.INCOMING:     "Llamada entrante",
    Status.CALLING:      "Llamando…",
    Status.IN_CALL:      "En llamada",
    Status.ERROR:        "Error de conexión",
}


class VoIPApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Ubutel VoIP")
        self.geometry("460x600")
        self.resizable(False, False)

        self._sip = SIPClient()
        self._contacts = ContactManager()
        self._call_log = CallLog()
        self._call_start: Optional[float] = None
        self._incoming_caller: str = ""
        self._last_contacts_path: Optional[str] = self._contacts.last_imported_path()
        self._ringing: bool = False
        self._ringback_playing: bool = False
        self._ring_path: Optional[str] = None  # ruta al .wav; None = bell() del sistema
        self._call_who_label: str = ""
        self._rec_folder: str = os.path.join(os.path.expanduser("~"), "ubutelbeta5")
        self._recording: bool = False

        # ── Estado de tracking para el historial ────────────────────────────
        self._log_type:     Optional[str]   = None   # "outgoing"|"incoming"
        self._log_number:   str             = ""
        self._log_name:     Optional[str]   = None
        self._log_start:    Optional[float] = None   # time.monotonic()
        self._log_answered: bool            = False

        self._sip.on_status_change = self._on_status_change
        self._sip.on_incoming_call = self._on_incoming_call
        self._sip.on_call_ended = self._on_call_ended
        self._sip.on_transfer_update = self._on_transfer_update

        self._build_ui()
        self._update_status_ui(Status.DISCONNECTED)
        self._autoload_contacts()
        self._load_audio_settings()
        self._load_connection_settings()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(600, self._sip.connect)

        # Abrir ajustes automáticamente si no hay credenciales configuradas
        import config as _cfg
        if not _cfg.SIP_PASSWORD:
            self.after(400, lambda: self._open_settings(tab="Conexión"))

    # ─── Construcción UI ─────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Cabecera ──
        self._header = ctk.CTkFrame(self, height=56, corner_radius=0, fg_color=("gray85", "gray20"))
        self._header.pack(fill="x")
        self._header.pack_propagate(False)

        self._dot_lbl = ctk.CTkLabel(self._header, text="●", font=ctk.CTkFont(size=22))
        self._dot_lbl.pack(side="left", padx=(14, 6))

        ctk.CTkLabel(self._header, text="Ubutel VoIP", font=ctk.CTkFont(size=15, weight="bold")).pack(side="left")

        _btn_font = ctk.CTkFont(size=16)
        self._reconnect_btn = ctk.CTkButton(
            self._header, text="⟳", width=38, height=34, fg_color="transparent",
            font=_btn_font,
            text_color=("gray40", "gray70"), hover_color=("gray75", "gray30"),
            command=lambda: threading.Thread(target=self._sip.reconnect, daemon=True).start(),
        )
        self._reconnect_btn.pack(side="right", padx=(0, 4))

        ctk.CTkButton(
            self._header, text="⚙", width=38, height=34, fg_color="transparent",
            font=_btn_font,
            text_color=("gray40", "gray70"), hover_color=("gray75", "gray30"),
            command=self._open_settings,
        ).pack(side="right", padx=(0, 0))

        ctk.CTkButton(
            self._header, text="ℹ", width=38, height=34, fg_color="transparent",
            font=_btn_font,
            text_color=("gray40", "gray70"), hover_color=("gray75", "gray30"),
            command=self._open_about,
        ).pack(side="right", padx=(0, 0))

        self._status_lbl = ctk.CTkLabel(self._header, text="", font=ctk.CTkFont(size=12))
        self._status_lbl.pack(side="right", padx=(0, 4))

        # ── Panel llamada activa (oculto por defecto) ──
        self._call_panel = ctk.CTkFrame(self, fg_color=("#d4edda", "#1a3a1a"), corner_radius=0)
        # No se hace pack aquí — se muestra/oculta dinámicamente

        inner = ctk.CTkFrame(self._call_panel, fg_color="transparent")
        inner.pack(pady=10, padx=16, fill="x")

        # Botones primero (side="right") para que siempre tengan espacio garantizado
        ctk.CTkButton(
            inner, text="Colgar", width=80, height=30,
            fg_color="#CC2222", hover_color="#AA1111",
            command=self._do_hangup,
        ).pack(side="right")

        self._transfer_btn = ctk.CTkButton(
            inner, text="↗ Transferir", width=100, height=30,
            fg_color="#2266AA", hover_color="#1a4d88",
            command=self._do_transfer,
        )
        self._transfer_btn.pack(side="right", padx=(0, 6))

        self._rec_btn = ctk.CTkButton(
            inner, text="⏺", width=38, height=30,
            fg_color=("gray55", "gray30"), hover_color=("gray45", "gray25"),
            command=self._do_record_toggle,
        )
        self._rec_btn.pack(side="right", padx=(0, 6))

        # Etiquetas después: ocupan el espacio restante a la izquierda
        self._call_who = ctk.CTkLabel(inner, text="", font=ctk.CTkFont(size=14, weight="bold"))
        self._call_who.pack(side="left")

        self._call_timer = ctk.CTkLabel(inner, text="00:00", font=ctk.CTkFont(size=13), text_color="gray")
        self._call_timer.pack(side="left", padx=10)

        # ── Panel llamada entrante (oculto por defecto) ──
        self._incoming_panel = ctk.CTkFrame(self, fg_color=("#fff3cd", "#3a3a00"), corner_radius=0)

        inc_inner = ctk.CTkFrame(self._incoming_panel, fg_color="transparent")
        inc_inner.pack(pady=10, padx=16, fill="x")

        self._incoming_lbl = ctk.CTkLabel(inc_inner, text="", font=ctk.CTkFont(size=13, weight="bold"))
        self._incoming_lbl.pack(side="left")

        ctk.CTkButton(
            inc_inner, text="✓ Contestar", width=100, height=30,
            fg_color="#22AA44", hover_color="#1a8833",
            command=self._do_answer,
        ).pack(side="right", padx=(6, 0))

        ctk.CTkButton(
            inc_inner, text="✗ Rechazar", width=90, height=30,
            fg_color="#CC2222", hover_color="#AA1111",
            command=self._do_deny,
        ).pack(side="right")

        # ── Contactos ──
        contacts_outer = ctk.CTkFrame(self)
        contacts_outer.pack(fill="both", expand=True, padx=10, pady=(10, 0))

        bar = ctk.CTkFrame(contacts_outer, fg_color="transparent")
        bar.pack(fill="x", padx=6, pady=(6, 4))

        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._refresh_contacts())

        ctk.CTkEntry(
            bar, textvariable=self._search_var,
            placeholder_text="Buscar contacto…", width=230,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(bar, text="Importar", width=90, command=self._import_contacts).pack(side="left")
        ctk.CTkButton(bar, text="Historial", width=100, command=self._open_call_log).pack(side="left", padx=(6, 0))

        self._contact_scroll = ctk.CTkScrollableFrame(contacts_outer)
        self._contact_scroll.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        self._empty_lbl = ctk.CTkLabel(
            self._contact_scroll,
            text="Sin contactos. Importa un CSV o XML.",
            text_color="gray",
        )
        self._empty_lbl.pack(pady=24)

        # ── Marcación manual ──
        dial_frame = ctk.CTkFrame(self, height=52, corner_radius=0, fg_color=("gray85", "gray20"))
        dial_frame.pack(fill="x", side="bottom")
        dial_frame.pack_propagate(False)

        dial_inner = ctk.CTkFrame(dial_frame, fg_color="transparent")
        dial_inner.pack(fill="both", expand=True, padx=10)

        self._dial_var = ctk.StringVar()
        dial_entry = ctk.CTkEntry(
            dial_inner, textvariable=self._dial_var,
            placeholder_text="Número o extensión…",
        )
        dial_entry.pack(side="left", fill="x", expand=True, padx=(0, 8), pady=10)
        dial_entry.bind("<Return>", lambda _: self._do_call(self._dial_var.get()))

        self._call_btn = ctk.CTkButton(
            dial_inner, text="Llamar", width=84, height=32,
            fg_color="#22AA44", hover_color="#1a8833",
            command=lambda: self._do_call(self._dial_var.get()),
        )
        self._call_btn.pack(side="left", pady=10)

    # ─── Acciones de usuario ─────────────────────────────────────────────────────

    def _resolve_name(self, number: str) -> Optional[str]:
        """Devuelve el nombre del contacto si el número está en la lista."""
        c = self._contacts.find_by_extension(number)
        return c.name if c else None

    def _do_call(self, number: str):
        number = number.strip()
        if not number:
            return
        if self._sip.status != Status.REGISTERED:
            messagebox.showwarning("Sin conexión", "No hay conexión con el servidor SIP.")
            return
        # Preparar tracking del historial
        self._log_type     = "outgoing"
        self._log_number   = number
        self._log_name     = self._resolve_name(number)
        self._log_start    = None   # se asigna cuando la llamada se establece
        self._log_answered = False
        self._call_btn.configure(state="disabled")
        threading.Thread(target=self._call_thread, args=(number,), daemon=True).start()

    def _call_thread(self, number: str):
        ok = self._sip.make_call(number)
        if not ok:
            self._log_type = None  # no loguear llamadas que ni llegan a marcar
            self.after(0, lambda: messagebox.showerror(
                "Error de llamada",
                f"No se pudo conectar con '{number}'.\nRevisa el número e inténtalo de nuevo."
            ))
        self.after(0, lambda: self._call_btn.configure(state="normal"))

    def _do_answer(self):
        self._stop_ring()
        self._log_answered = True
        self._log_start    = time.monotonic()
        self._sip.answer()
        self._incoming_panel.pack_forget()
        self._show_call_panel(f"📞  {self._incoming_caller}")

    def _do_deny(self):
        self._stop_ring()
        # Llamada perdida (rechazada por nosotros)
        if self._log_type == "incoming":
            self._call_log.add("missed", self._log_number, self._log_name)
            self._log_type = None
        self._sip.deny()
        self._incoming_panel.pack_forget()

    def _do_transfer(self):
        if hasattr(self, "_transfer_win") and self._transfer_win.winfo_exists():
            self._transfer_win.lift()
            return

        win = ctk.CTkToplevel(self)
        win.title("Transferir llamada")
        win.geometry("300x140")
        win.resizable(False, False)
        win.attributes("-topmost", True)
        self._transfer_win = win

        ctk.CTkLabel(win, text="Extensión destino:",
                     font=ctk.CTkFont(size=13)).pack(pady=(18, 4))

        ext_var = ctk.StringVar()
        entry = ctk.CTkEntry(win, textvariable=ext_var,
                             placeholder_text="Ej: 102", width=160)
        entry.pack(pady=4)
        entry.focus()

        def _confirm():
            ext = ext_var.get().strip()
            if not ext:
                return
            win.destroy()
            self._transfer_btn.configure(state="disabled")
            self._call_who.configure(text=f"↗  Transfiriendo a {ext}…")
            ok = self._sip.transfer(ext)
            if not ok:
                self._call_who.configure(text=f"📞  {self._incoming_caller or self._dial_var.get()}")
                self._transfer_btn.configure(state="normal")
                messagebox.showerror("Error de transferencia",
                                     "No se pudo enviar la solicitud de transferencia.")

        entry.bind("<Return>", lambda _: _confirm())
        ctk.CTkButton(win, text="Transferir", width=120,
                      fg_color="#2266AA", hover_color="#1a4d88",
                      command=_confirm).pack(pady=(8, 0))

    def _do_record_toggle(self):
        import datetime
        if not self._recording:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            number = "".join(c for c in (self._log_number or "llamada") if c.isalnum() or c in "-_")
            filename = f"rec_{ts}_{number}.wav"
            try:
                os.makedirs(self._rec_folder, exist_ok=True)
            except Exception as e:
                messagebox.showerror("Error de grabación", f"No se puede crear la carpeta:\n{e}")
                return
            path = os.path.join(self._rec_folder, filename)
            if self._sip.start_recording(path):
                self._recording = True
                self._rec_btn.configure(text="⏹", fg_color="#CC2222", hover_color="#AA1111")
        else:
            self._sip.stop_recording()
            self._recording = False
            self._rec_btn.configure(
                text="⏺",
                fg_color=("gray55", "gray30"), hover_color=("gray45", "gray25"),
            )

    def _on_transfer_update(self, extension: str, status_code: int):
        self.after(0, self._handle_transfer_update, extension, status_code)

    def _handle_transfer_update(self, extension: str, status_code: int):
        if status_code < 200:
            # En curso (100 Trying, 180 Ringing…)
            self._call_who.configure(text=f"↗  Sonando en {extension}…")
        elif status_code == 200:
            # Confirmado — hangup() se llama automáticamente desde sip_client
            self._call_who.configure(text=f"✓  Transferido a {extension}")
        else:
            # Error (486 Busy, 404 Not Found, …)
            self._transfer_btn.configure(state="normal")
            self._call_who.configure(text=getattr(self, "_call_who_label", "📞"))
            messagebox.showwarning(
                "Transferencia fallida",
                f"La extensión {extension} no está disponible ({status_code}).\n"
                "Sigues conectado con el interlocutor.",
            )

    def _do_hangup(self):
        if self._recording:
            self._sip.stop_recording()
            self._recording = False
        self._sip.hangup()
        self._call_panel.pack_forget()
        self._call_start = None

    def _autoload_contacts(self):
        if not self._last_contacts_path:
            return
        try:
            count = self._contacts.load_from_file(self._last_contacts_path)
            self._refresh_contacts()
        except Exception:
            pass

    def _import_contacts(self):
        path = filedialog.askopenfilename(
            title="Importar contactos",
            filetypes=[("CSV", "*.csv"), ("XML", "*.xml"), ("Todos", "*.*")],
        )
        if not path:
            return
        try:
            count = self._contacts.load_from_file(path)
            self._refresh_contacts()
            messagebox.showinfo("Importar contactos", f"Se importaron {count} contacto(s).")
        except Exception as e:
            messagebox.showerror("Error al importar", str(e))

    # ─── Callbacks SIP (vienen de hilos de fondo) ───────────────────────────────

    def _on_status_change(self, status: Status):
        self.after(0, self._handle_status_change, status)

    def _on_incoming_call(self, caller: str):
        self._incoming_caller = caller
        # Preparar tracking (asumimos perdida hasta que se conteste)
        self._log_type     = "incoming"
        self._log_number   = caller
        self._log_name     = self._resolve_name(caller)
        self._log_answered = False
        self._log_start    = None
        self.after(0, self._show_incoming, caller)

    def _on_call_ended(self):
        self.after(0, self._handle_call_ended)

    # ─── Handlers en hilo principal ──────────────────────────────────────────────

    def _handle_status_change(self, status: Status):
        self._update_status_ui(status)
        if status == Status.CALLING:
            self._show_call_panel(f"📞  Llamando a {self._dial_var.get()}…")
            self._start_ringback()
        elif status == Status.IN_CALL:
            self._stop_ringback()
            # Llamada saliente establecida → iniciar contador de duración
            if self._log_type == "outgoing" and self._log_start is None:
                self._log_start = time.monotonic()
            if self._call_start is None:
                pass  # panel ya visible
        elif status == Status.REGISTERED:
            self._stop_ringback()
            self._stop_ring()
            self._call_panel.pack_forget()
            self._incoming_panel.pack_forget()
            self._call_start = None

    def _show_incoming(self, caller: str):
        self._incoming_lbl.configure(text=f"📲  Llamada de: {caller}")
        self._incoming_panel.pack(fill="x", after=self._header)
        self.lift()
        self.focus_force()
        self._ringing = True
        if self._ring_path and os.path.exists(self._ring_path):
            threading.Thread(target=self._play_ring_wav, daemon=True, name="ring-wav").start()
        else:
            self._ring_tick()

    def _play_ring_wav(self):
        """Repite el archivo WAV hasta que _ringing sea False (multiplataforma)."""
        import sys
        while self._ringing:
            try:
                if sys.platform == "darwin":
                    proc = subprocess.Popen(
                        ["afplay", self._ring_path],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                    while proc.poll() is None:
                        if not self._ringing:
                            proc.kill()
                            break
                        time.sleep(0.05)
                elif sys.platform == "win32":
                    import winsound
                    winsound.PlaySound(self._ring_path, winsound.SND_FILENAME)
                    time.sleep(0.05)
                else:
                    proc = subprocess.Popen(
                        ["aplay", self._ring_path],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                    while proc.poll() is None:
                        if not self._ringing:
                            proc.kill()
                            break
                        time.sleep(0.05)
            except Exception:
                break
        self.after(0, lambda: self.title("Ubutel VoIP"))

    def _ring_tick(self):
        """Tono del sistema (fallback cuando no hay wav configurado)."""
        if not self._ringing:
            return
        self.bell()
        self.title("📲 LLAMADA ENTRANTE")
        self.after(1200, self._ring_tock)

    def _ring_tock(self):
        if not self._ringing:
            self.title("Ubutel VoIP")
            return
        self.title("Ubutel VoIP")
        self.after(800, self._ring_tick)

    def _stop_ring(self):
        self._ringing = False
        self.title("Ubutel VoIP")

    # ─── Tonos de llamada saliente ────────────────────────────────────────────────

    def _start_ringback(self):
        """Tono de retorno (ringback europeo): 400 Hz, 1 s encendido / 4 s apagado."""
        if self._ringback_playing:
            return
        self._ringback_playing = True
        threading.Thread(target=self._ringback_thread, daemon=True, name="ringback").start()

    def _stop_ringback(self):
        self._ringback_playing = False

    def _ringback_thread(self):
        import sounddevice as sd
        import numpy as np
        RATE, FREQ, CHUNK = 8000, 400, 160
        t = np.linspace(0, 1.0, RATE, endpoint=False)
        tone    = (np.sin(2 * np.pi * FREQ * t) * 12000).astype(np.int16).reshape(-1, 1)
        silence = np.zeros((RATE * 4, 1), dtype=np.int16)
        try:
            with sd.OutputStream(samplerate=RATE, channels=1, dtype="int16") as stream:
                while self._ringback_playing:
                    for i in range(0, RATE, CHUNK):
                        if not self._ringback_playing:
                            break
                        stream.write(tone[i:min(i + CHUNK, RATE)])
                    for i in range(0, RATE * 4, CHUNK):
                        if not self._ringback_playing:
                            break
                        stream.write(silence[i:min(i + CHUNK, RATE * 4)])
        except Exception:
            pass

    def _play_busy_tone(self):
        """Tono de ocupado europeo: 400 Hz, 0.5 s on / 0.5 s off × 3 ciclos."""
        def _thread():
            import sounddevice as sd
            import numpy as np
            RATE, FREQ = 8000, 400
            half = RATE // 2
            t    = np.linspace(0, 0.5, half, endpoint=False)
            tone    = (np.sin(2 * np.pi * FREQ * t) * 12000).astype(np.int16).reshape(-1, 1)
            silence = np.zeros((half, 1), dtype=np.int16)
            try:
                with sd.OutputStream(samplerate=RATE, channels=1, dtype="int16") as stream:
                    for _ in range(3):
                        stream.write(tone)
                        stream.write(silence)
            except Exception:
                pass
        threading.Thread(target=_thread, daemon=True, name="busy-tone").start()

    def _handle_call_ended(self):
        outgoing_unanswered = (self._log_type == "outgoing" and not self._log_answered)
        self._stop_ringback()
        self._stop_ring()
        self._finalize_log_entry()
        if outgoing_unanswered:
            self._play_busy_tone()
        if self._recording:
            self._sip.stop_recording()
            self._recording = False
            self._rec_btn.configure(
                text="⏺",
                fg_color=("gray55", "gray30"), hover_color=("gray45", "gray25"),
            )
        self._call_panel.pack_forget()
        self._incoming_panel.pack_forget()
        self._call_start = None

    def _finalize_log_entry(self):
        """Escribe la entrada del historial cuando termina una llamada."""
        if not self._log_type:
            return
        typ    = self._log_type
        num    = self._log_number
        name   = self._log_name
        start  = self._log_start
        answered = self._log_answered
        self._log_type = None  # evitar doble escritura

        duration = int(time.monotonic() - start) if start is not None else None

        if typ == "outgoing":
            if duration is not None:   # solo si llegó a establecerse
                self._call_log.add("outgoing", num, name, duration)
        elif typ == "incoming":
            if answered and duration is not None:
                self._call_log.add("incoming", num, name, duration)
            else:
                self._call_log.add("missed", num, name)

    # ─── UI helpers ──────────────────────────────────────────────────────────────

    def _update_status_ui(self, status: Status):
        dot, color = _STATUS_DOT[status]
        self._dot_lbl.configure(text=dot, text_color=color)
        self._status_lbl.configure(text=_STATUS_LABEL[status])
        enabled = status == Status.REGISTERED
        self._call_btn.configure(state="normal" if enabled else "disabled")

    def _show_call_panel(self, label: str):
        self._call_who.configure(text=label)
        self._call_who_label = label  # guardado para restaurar tras transferencia fallida
        self._transfer_btn.configure(state="normal")
        self._recording = False
        self._rec_btn.configure(
            text="⏺",
            fg_color=("gray55", "gray30"), hover_color=("gray45", "gray25"),
        )
        self._call_start = time.time()
        self._call_panel.pack(fill="x", after=self._header)
        self._incoming_panel.pack_forget()
        self._tick_timer()

    def _tick_timer(self):
        if self._call_start is None:
            return
        elapsed = int(time.time() - self._call_start)
        m, s = divmod(elapsed, 60)
        self._call_timer.configure(text=f"{m:02d}:{s:02d}")
        self.after(1000, self._tick_timer)

    def _refresh_contacts(self):
        for w in self._contact_scroll.winfo_children():
            w.destroy()

        results = self._contacts.search(self._search_var.get())

        if not results:
            msg = "No se encontraron contactos." if self._search_var.get() else "Sin contactos. Importa un CSV o XML."
            ctk.CTkLabel(self._contact_scroll, text=msg, text_color="gray").pack(pady=24)
            return

        for contact in results:
            self._add_contact_row(contact)

    def _add_contact_row(self, contact: Contact):
        row = ctk.CTkFrame(self._contact_scroll, height=42)
        row.pack(fill="x", pady=2, padx=2)
        row.pack_propagate(False)

        ctk.CTkLabel(row, text=contact.name, anchor="w").pack(side="left", padx=(10, 4), fill="y")

        ctk.CTkLabel(
            row, text=contact.extension,
            text_color=("gray40", "gray60"), width=60, anchor="e",
        ).pack(side="left", padx=(0, 4), fill="y")

        ctk.CTkButton(
            row, text="📞", width=36, height=28,
            fg_color="#22AA44", hover_color="#1a8833",
            command=lambda c=contact: self._do_call(c.extension),
        ).pack(side="right", padx=(0, 8), pady=6)

    # ─── Historial de llamadas ──────────────────────────────────────────────────

    def _open_call_log(self):
        if hasattr(self, "_log_win") and self._log_win.winfo_exists():
            self._log_win.lift()
            return

        win = ctk.CTkToplevel(self)
        win.title("Historial de llamadas")
        win.geometry("460x500")
        win.resizable(False, True)
        self._log_win = win

        # ── Filtros ──────────────────────────────────────────────────────────
        filter_bar = ctk.CTkFrame(win, fg_color="transparent")
        filter_bar.pack(fill="x", padx=12, pady=(10, 4))

        filter_var = ctk.StringVar(value="all")

        def rebuild(*_):
            for w in scroll.winfo_children():
                w.destroy()
            fval = filter_var.get()
            entries = self._call_log.entries()
            shown = [e for e in entries if fval == "all" or e.type == fval]
            if not shown:
                ctk.CTkLabel(scroll, text="Sin registros.",
                             text_color="gray").pack(pady=20)
                return
            for e in shown:
                _add_row(e)

        for val, lbl in [("all", "Todas"), ("outgoing", "Salientes"),
                         ("incoming", "Entrantes"), ("missed", "Perdidas")]:
            ctk.CTkRadioButton(filter_bar, text=lbl, variable=filter_var,
                               value=val, command=rebuild,
                               ).pack(side="left", padx=(0, 10))

        # ── Lista ─────────────────────────────────────────────────────────────
        scroll = ctk.CTkScrollableFrame(win)
        scroll.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        COLOR_BG = {
            "outgoing": ("#e8f5e9", "#1a3a1a"),
            "incoming": ("#e3f2fd", "#0d2a3a"),
            "missed":   ("#fce4ec", "#3a0d1a"),
        }

        def _add_row(e):
            bg = COLOR_BG.get(e.type, ("gray90", "gray20"))
            row = ctk.CTkFrame(scroll, fg_color=bg, corner_radius=6)
            row.pack(fill="x", padx=4, pady=3)

            icon_lbl = ctk.CTkLabel(row, text=TYPE_ICONS[e.type],
                                    font=ctk.CTkFont(size=18), width=36)
            icon_lbl.pack(side="left", padx=(8, 0), pady=6)

            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(side="left", fill="x", expand=True, padx=6, pady=4)

            ctk.CTkLabel(info, text=e.display_party,
                         font=ctk.CTkFont(size=12, weight="bold"),
                         anchor="w").pack(fill="x")
            ctk.CTkLabel(info, text=f"{TYPE_LABELS[e.type]}  ·  {e.display_ts}",
                         font=ctk.CTkFont(size=10), text_color="gray",
                         anchor="w").pack(fill="x")

            if e.type != "missed":
                ctk.CTkLabel(row, text=e.display_duration,
                             font=ctk.CTkFont(size=11), width=44, anchor="e"
                             ).pack(side="right", padx=(0, 10))

        rebuild()

    # ─── Ajustes (conexión + audio) ─────────────────────────────────────────────

    def _load_audio_settings(self):
        s = _read_settings()
        if "noise_gate_dbfs"  in s: self._sip.noise_gate_dbfs  = float(s["noise_gate_dbfs"])
        if "echo_gate_rms"    in s: self._sip.echo_gate_rms    = int(s["echo_gate_rms"])
        if "echo_gate_factor" in s: self._sip.echo_gate_factor = float(s["echo_gate_factor"])
        rp = s.get("ring_path", "")
        self._ring_path = rp if rp and os.path.exists(rp) else None
        rdir = s.get("rec_folder", "")
        if rdir:
            self._rec_folder = rdir
        import config as _cfg
        if "audio_input"  in s: _cfg.AUDIO_INPUT  = s["audio_input"]
        if "audio_output" in s: _cfg.AUDIO_OUTPUT = s["audio_output"]

    def _load_connection_settings(self):
        """Lee credenciales SIP guardadas y las aplica en el módulo config."""
        import config as _cfg
        s = _read_settings()
        if "sip_server"   in s: _cfg.SIP_SERVER   = s["sip_server"]
        if "sip_port"     in s: _cfg.SIP_PORT      = int(s["sip_port"])
        if "sip_user"     in s: _cfg.SIP_USER      = s["sip_user"]
        if "sip_password" in s: _cfg.SIP_PASSWORD  = s["sip_password"]
        if "sip_domain"   in s: _cfg.SIP_DOMAIN    = s["sip_domain"]

    def _open_settings(self, tab: str = "Conexión"):
        if hasattr(self, "_settings_win") and self._settings_win.winfo_exists():
            self._settings_win.lift()
            try:
                self._settings_win._tabview.set(tab)
            except Exception:
                pass
            return

        import config as _cfg

        win = ctk.CTkToplevel(self)
        win.title("Ajustes")
        win.geometry("420x720")
        win.resizable(False, False)
        win.attributes("-topmost", True)
        self._settings_win = win

        tabs = ctk.CTkTabview(win)
        tabs.pack(fill="both", expand=True, padx=10, pady=10)
        win._tabview = tabs
        tabs.add("Conexión")
        tabs.add("Audio")
        tabs.set(tab)

        # ════════════════════════════════════════════════════════════════════
        # PESTAÑA CONEXIÓN
        # ════════════════════════════════════════════════════════════════════
        ct = tabs.tab("Conexión")

        ctk.CTkLabel(ct, text="Credenciales del servidor SIP",
                     font=ctk.CTkFont(weight="bold"), anchor="w"
                     ).pack(fill="x", padx=4, pady=(8, 4))

        def _field(parent, label, value, show=""):
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", padx=4, pady=3)
            ctk.CTkLabel(row, text=label, width=110, anchor="w").pack(side="left")
            var = ctk.StringVar(value=value)
            ctk.CTkEntry(row, textvariable=var, show=show).pack(side="left", fill="x", expand=True)
            return var

        srv_var  = _field(ct, "Servidor SIP",  _cfg.SIP_SERVER)
        port_var = _field(ct, "Puerto",         str(_cfg.SIP_PORT))
        user_var = _field(ct, "Usuario",        _cfg.SIP_USER)
        pwd_var  = _field(ct, "Contraseña",     _cfg.SIP_PASSWORD, show="●")
        dom_var  = _field(ct, "Dominio",        _cfg.SIP_DOMAIN or _cfg.SIP_SERVER)

        ctk.CTkLabel(ct, text="El Dominio suele ser el mismo que el Servidor SIP.",
                     text_color="gray", font=ctk.CTkFont(size=10), anchor="w"
                     ).pack(fill="x", padx=4)

        def save_connection():
            srv  = srv_var.get().strip()
            port = int(port_var.get().strip() or "5060")
            user = user_var.get().strip()
            pwd  = pwd_var.get().strip()
            dom  = dom_var.get().strip() or srv
            if not srv or not user or not pwd:
                messagebox.showwarning("Faltan datos",
                                       "Servidor, usuario y contraseña son obligatorios.")
                return
            import config as _c
            _c.SIP_SERVER  = srv
            _c.SIP_PORT    = port
            _c.SIP_USER    = user
            _c.SIP_PASSWORD = pwd
            _c.SIP_DOMAIN  = dom
            _write_settings({"sip_server": srv, "sip_port": port,
                              "sip_user": user, "sip_password": pwd,
                              "sip_domain": dom})
            win.destroy()
            threading.Thread(target=self._sip.reconnect, daemon=True).start()

        ctk.CTkButton(ct, text="💾  Guardar y reconectar",
                      command=save_connection
                      ).pack(fill="x", padx=4, pady=(16, 4))

        # ════════════════════════════════════════════════════════════════════
        # PESTAÑA AUDIO
        # ════════════════════════════════════════════════════════════════════
        at = tabs.tab("Audio")

        def section(text):
            ctk.CTkLabel(at, text=text, font=ctk.CTkFont(weight="bold"), anchor="w"
                         ).pack(fill="x", padx=4, pady=(10, 2))

        def slider_row(label, from_, to, init, fmt, on_change):
            row = ctk.CTkFrame(at, fg_color="transparent")
            row.pack(fill="x", padx=4, pady=(2, 0))
            val_lbl = ctk.CTkLabel(row, text=fmt(init), width=72, anchor="e")
            val_lbl.pack(side="right")
            ctk.CTkLabel(row, text=label, anchor="w").pack(side="left")
            sl = ctk.CTkSlider(at, from_=from_, to=to,
                               number_of_steps=int((to - from_) * 10))
            sl.set(init)
            def _cb(v, lbl=val_lbl, f=fmt, cb=on_change):
                lbl.configure(text=f(v)); cb(v)
            sl.configure(command=_cb)
            sl.pack(fill="x", padx=4, pady=(0, 2))

        # ── Dispositivos de audio ────────────────────────────────────────────────
        section("Dispositivos de audio")

        import sounddevice as _sd
        import config as _cfg

        _DEFAULT_DEV = "(Por defecto)"

        try:
            _all_devs = _sd.query_devices()
        except Exception:
            _all_devs = []

        def _unique_dev_names(devs, channel_key):
            seen = set()
            names = [_DEFAULT_DEV]
            for d in devs:
                if d[channel_key] > 0 and d["name"] not in seen:
                    seen.add(d["name"])
                    names.append(d["name"])
            return names

        _input_names  = _unique_dev_names(_all_devs, "max_input_channels")
        _output_names = _unique_dev_names(_all_devs, "max_output_channels")

        def _match_dev(names, cfg_val):
            if cfg_val:
                for n in names:
                    if cfg_val.lower() in n.lower():
                        return n
            return _DEFAULT_DEV

        _in_var  = ctk.StringVar(value=_match_dev(_input_names,  _cfg.AUDIO_INPUT))
        _out_var = ctk.StringVar(value=_match_dev(_output_names, _cfg.AUDIO_OUTPUT))

        def _on_input_change(choice):
            val = "" if choice == _DEFAULT_DEV else choice
            _cfg.AUDIO_INPUT = val
            _write_settings({"audio_input": val})

        def _on_output_change(choice):
            val = "" if choice == _DEFAULT_DEV else choice
            _cfg.AUDIO_OUTPUT = val
            _write_settings({"audio_output": val})

        _in_row = ctk.CTkFrame(at, fg_color="transparent")
        _in_row.pack(fill="x", padx=4, pady=(2, 2))
        ctk.CTkLabel(_in_row, text="Micrófono", width=80, anchor="w").pack(side="left")
        ctk.CTkOptionMenu(
            _in_row, variable=_in_var, values=_input_names,
            command=_on_input_change, dynamic_resizing=False,
        ).pack(side="left", fill="x", expand=True)

        _out_row = ctk.CTkFrame(at, fg_color="transparent")
        _out_row.pack(fill="x", padx=4, pady=(0, 2))
        ctk.CTkLabel(_out_row, text="Altavoz", width=80, anchor="w").pack(side="left")
        ctk.CTkOptionMenu(
            _out_row, variable=_out_var, values=_output_names,
            command=_on_output_change, dynamic_resizing=False,
        ).pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(at, text="Los cambios de dispositivo se aplican en la próxima llamada.",
                     text_color="gray", font=ctk.CTkFont(size=10), anchor="w"
                     ).pack(fill="x", padx=4, pady=(0, 4))

        section("Filtro de ruido (Noise gate)")
        ctk.CTkLabel(at, text="Silencia el micro por debajo del umbral.\nSube para cortar más ruido/eco.",
                     text_color="gray", font=ctk.CTkFont(size=10), anchor="w"
                     ).pack(fill="x", padx=4)
        slider_row("Umbral", -50, -25, self._sip.noise_gate_dbfs,
                   lambda v: f"{v:.1f} dBFS",
                   lambda v: (setattr(self._sip, "noise_gate_dbfs", round(v, 1)),
                               _write_settings({"noise_gate_dbfs": round(v, 1)})))
        ctk.CTkLabel(at, text="← −50 permisivo   −25 agresivo →",
                     text_color="gray", font=ctk.CTkFont(size=10)
                     ).pack(pady=(0, 2))

        section("Eco gate")
        ctk.CTkLabel(at, text="Atenúa el micro cuando el interlocutor habla fuerte.",
                     text_color="gray", font=ctk.CTkFont(size=10), anchor="w"
                     ).pack(fill="x", padx=4)
        slider_row("Sensibilidad (RMS >)", 400, 4000, self._sip.echo_gate_rms,
                   lambda v: f"{int(v)} RMS",
                   lambda v: (setattr(self._sip, "echo_gate_rms", int(v)),
                               _write_settings({"echo_gate_rms": int(v)})))
        slider_row("Atenuación del micro", 2, 50,
                   round(self._sip.echo_gate_factor * 100),
                   lambda v: f"{int(v)} %",
                   lambda v: (setattr(self._sip, "echo_gate_factor", round(v / 100, 3)),
                               _write_settings({"echo_gate_factor": round(v / 100, 3)})))

        # ── Tono de llamada ──────────────────────────────────────────────────
        section("Tono de llamada")
        ctk.CTkLabel(at, text="Archivo WAV para llamadas entrantes.\nSin archivo: tono del sistema.",
                     text_color="gray", font=ctk.CTkFont(size=10), anchor="w"
                     ).pack(fill="x", padx=4)

        ring_row = ctk.CTkFrame(at, fg_color="transparent")
        ring_row.pack(fill="x", padx=4, pady=4)

        _ring_name = os.path.basename(self._ring_path) if self._ring_path else "(tono del sistema)"
        ring_name_lbl = ctk.CTkLabel(ring_row, text=_ring_name, anchor="w",
                                     font=ctk.CTkFont(size=11))
        ring_name_lbl.pack(side="left", fill="x", expand=True)

        def clear_ring():
            self._ring_path = None
            _write_settings({"ring_path": ""})
            ring_name_lbl.configure(text="(tono del sistema)")

        def pick_ring():
            path = filedialog.askopenfilename(
                title="Seleccionar tono de llamada",
                filetypes=[("WAV", "*.wav"), ("Todos", "*.*")],
                parent=win,
            )
            if path:
                self._ring_path = path
                _write_settings({"ring_path": path})
                ring_name_lbl.configure(text=os.path.basename(path))

        ctk.CTkButton(ring_row, text="✕", width=28, height=26,
                      fg_color="transparent", border_width=1,
                      command=clear_ring).pack(side="right", padx=(4, 0))
        ctk.CTkButton(ring_row, text="Seleccionar…", width=110, height=26,
                      command=pick_ring).pack(side="right")

        # ── Carpeta de grabaciones ───────────────────────────────────────────
        section("Grabaciones")
        ctk.CTkLabel(at, text="Carpeta donde se guardan los ficheros WAV grabados.",
                     text_color="gray", font=ctk.CTkFont(size=10), anchor="w"
                     ).pack(fill="x", padx=4)

        rec_row = ctk.CTkFrame(at, fg_color="transparent")
        rec_row.pack(fill="x", padx=4, pady=4)

        def _fmt_rec_path(p: str) -> str:
            home = os.path.expanduser("~")
            return ("~" + p[len(home):]) if p.startswith(home) else p

        rec_dir_lbl = ctk.CTkLabel(rec_row, text=_fmt_rec_path(self._rec_folder),
                                   anchor="w", font=ctk.CTkFont(size=11))
        rec_dir_lbl.pack(side="left", fill="x", expand=True)

        def reset_rec_folder():
            self._rec_folder = os.path.join(os.path.expanduser("~"), "ubutelbeta5")
            _write_settings({"rec_folder": ""})
            rec_dir_lbl.configure(text="~/ubutelbeta5")

        def pick_rec_folder():
            path = filedialog.askdirectory(
                title="Carpeta de grabaciones",
                parent=win,
            )
            if path:
                self._rec_folder = path
                _write_settings({"rec_folder": path})
                rec_dir_lbl.configure(text=_fmt_rec_path(path))

        ctk.CTkButton(rec_row, text="✕", width=28, height=26,
                      fg_color="transparent", border_width=1,
                      command=reset_rec_folder).pack(side="right", padx=(4, 0))
        ctk.CTkButton(rec_row, text="Seleccionar…", width=110, height=26,
                      command=pick_rec_folder).pack(side="right")

        # ── Reset / nota ─────────────────────────────────────────────────────
        def reset_audio():
            self._sip.noise_gate_dbfs  = -40.0
            self._sip.echo_gate_rms    = 1200
            self._sip.echo_gate_factor = 0.08
            _write_settings({"noise_gate_dbfs": -40.0,
                              "echo_gate_rms": 1200, "echo_gate_factor": 0.08})
            win.destroy()
            self._open_settings(tab="Audio")

        ctk.CTkButton(at, text="Restaurar audio por defecto",
                      fg_color="transparent", border_width=1,
                      command=reset_audio
                      ).pack(fill="x", padx=4, pady=(10, 4))
        ctk.CTkLabel(at, text="Los cambios de audio se aplican inmediatamente.",
                     text_color="gray", font=ctk.CTkFont(size=10)
                     ).pack(pady=(0, 8))

    def _open_about(self):
        if hasattr(self, "_about_win") and self._about_win.winfo_exists():
            self._about_win.lift()
            return

        win = ctk.CTkToplevel(self)
        win.title("Acerca de")
        win.geometry("320x220")
        win.resizable(False, False)
        win.attributes("-topmost", True)
        self._about_win = win

        ctk.CTkLabel(win, text="Ubutel VoIP",
                     font=ctk.CTkFont(size=20, weight="bold")).pack(pady=(24, 4))
        ctk.CTkLabel(win, text=f"Versión {APP_VERSION}",
                     font=ctk.CTkFont(size=13)).pack()
        ctk.CTkLabel(win, text=f"Release: {APP_RELEASE}",
                     font=ctk.CTkFont(size=11), text_color="gray").pack(pady=(2, 0))
        ctk.CTkLabel(win, text=f"Autor: {APP_AUTHOR}",
                     font=ctk.CTkFont(size=12)).pack(pady=(10, 0))

        ctk.CTkButton(win, text="Cerrar", width=100,
                      command=win.destroy).pack(pady=(20, 0))

    def _on_close(self):
        self._finalize_log_entry()
        self._sip.disconnect()
        self.destroy()
