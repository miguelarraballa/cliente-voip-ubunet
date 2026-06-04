"""
Interfaz gráfica del cliente VoIP — customtkinter.
"""
import time
import threading
from tkinter import filedialog, messagebox
from typing import Optional

import customtkinter as ctk

from sip_client import SIPClient, Status
from contacts import ContactManager, Contact

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

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
        self.geometry("420x600")
        self.resizable(False, False)

        self._sip = SIPClient()
        self._contacts = ContactManager()
        self._call_start: Optional[float] = None
        self._incoming_caller: str = ""

        self._sip.on_status_change = self._on_status_change
        self._sip.on_incoming_call = self._on_incoming_call
        self._sip.on_call_ended = self._on_call_ended

        self._build_ui()
        self._update_status_ui(Status.DISCONNECTED)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(600, self._sip.connect)

    # ─── Construcción UI ─────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Cabecera ──
        self._header = ctk.CTkFrame(self, height=56, corner_radius=0, fg_color=("gray85", "gray20"))
        self._header.pack(fill="x")
        self._header.pack_propagate(False)

        self._dot_lbl = ctk.CTkLabel(self._header, text="●", font=ctk.CTkFont(size=22))
        self._dot_lbl.pack(side="left", padx=(14, 6))

        ctk.CTkLabel(self._header, text="Ubutel VoIP", font=ctk.CTkFont(size=15, weight="bold")).pack(side="left")

        self._reconnect_btn = ctk.CTkButton(
            self._header, text="⟳", width=32, height=28, fg_color="transparent",
            text_color=("gray40", "gray70"), hover_color=("gray75", "gray30"),
            command=lambda: threading.Thread(target=self._sip.reconnect, daemon=True).start(),
        )
        self._reconnect_btn.pack(side="right", padx=(0, 8))

        self._status_lbl = ctk.CTkLabel(self._header, text="", font=ctk.CTkFont(size=12))
        self._status_lbl.pack(side="right", padx=(0, 4))

        # ── Panel llamada activa (oculto por defecto) ──
        self._call_panel = ctk.CTkFrame(self, fg_color=("#d4edda", "#1a3a1a"), corner_radius=0)
        # No se hace pack aquí — se muestra/oculta dinámicamente

        inner = ctk.CTkFrame(self._call_panel, fg_color="transparent")
        inner.pack(pady=10, padx=16, fill="x")

        self._call_who = ctk.CTkLabel(inner, text="", font=ctk.CTkFont(size=14, weight="bold"))
        self._call_who.pack(side="left")

        self._call_timer = ctk.CTkLabel(inner, text="00:00", font=ctk.CTkFont(size=13), text_color="gray")
        self._call_timer.pack(side="left", padx=10)

        ctk.CTkButton(
            inner, text="Colgar", width=80, height=30,
            fg_color="#CC2222", hover_color="#AA1111",
            command=self._do_hangup,
        ).pack(side="right")

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

        ctk.CTkButton(bar, text="Importar", width=100, command=self._import_contacts).pack(side="left")

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

    def _do_call(self, number: str):
        number = number.strip()
        if not number:
            return
        if self._sip.status != Status.REGISTERED:
            messagebox.showwarning("Sin conexión", "No hay conexión con el servidor SIP.")
            return
        # Ejecutar en background: phone.call() bloquea hasta recibir 100 Trying.
        # Si se llama desde el hilo de la UI, congela la ventana.
        self._call_btn.configure(state="disabled")
        threading.Thread(target=self._call_thread, args=(number,), daemon=True).start()

    def _call_thread(self, number: str):
        ok = self._sip.make_call(number)
        if not ok:
            self.after(0, lambda: messagebox.showerror(
                "Error de llamada",
                f"No se pudo conectar con '{number}'.\nRevisa el número e inténtalo de nuevo."
            ))
        self.after(0, lambda: self._call_btn.configure(state="normal"))

    def _do_answer(self):
        self._sip.answer()
        self._incoming_panel.pack_forget()
        self._show_call_panel(f"📞  {self._incoming_caller}")

    def _do_deny(self):
        self._sip.deny()
        self._incoming_panel.pack_forget()

    def _do_hangup(self):
        self._sip.hangup()
        self._call_panel.pack_forget()
        self._call_start = None

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
        self.after(0, self._show_incoming, caller)

    def _on_call_ended(self):
        self.after(0, self._handle_call_ended)

    # ─── Handlers en hilo principal ──────────────────────────────────────────────

    def _handle_status_change(self, status: Status):
        self._update_status_ui(status)
        if status == Status.CALLING:
            self._show_call_panel(f"📞  Llamando a {self._dial_var.get()}…")
        elif status == Status.IN_CALL and self._call_start is None:
            pass  # El panel ya está visible
        elif status == Status.REGISTERED:
            self._call_panel.pack_forget()
            self._incoming_panel.pack_forget()
            self._call_start = None

    def _show_incoming(self, caller: str):
        self._incoming_lbl.configure(text=f"📲  Llamada de: {caller}")
        self._incoming_panel.pack(fill="x", after=self._header)
        self.lift()
        self.focus_force()

    def _handle_call_ended(self):
        self._call_panel.pack_forget()
        self._incoming_panel.pack_forget()
        self._call_start = None

    # ─── UI helpers ──────────────────────────────────────────────────────────────

    def _update_status_ui(self, status: Status):
        dot, color = _STATUS_DOT[status]
        self._dot_lbl.configure(text=dot, text_color=color)
        self._status_lbl.configure(text=_STATUS_LABEL[status])
        enabled = status == Status.REGISTERED
        self._call_btn.configure(state="normal" if enabled else "disabled")

    def _show_call_panel(self, label: str):
        self._call_who.configure(text=label)
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

    def _on_close(self):
        self._sip.disconnect()
        self.destroy()
