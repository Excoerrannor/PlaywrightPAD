"""High-contrast Tkinter widgets for the Windhawk-glass desktop.

The OS-managed Windows titlebar and DWM/Windhawk effects are left untouched.
Only ttk widgets and small Tk text/button surfaces receive stable opaque colors,
so text remains legible whether the wallpaper behind the window is bright or
very dark. The clam ttk theme is used for consistently colored *controls*;
this does not disable the native Windows glass effect on the top-level window.
"""
import tkinter as tk
from tkinter import ttk, font as tkfont

# Makerlab accent colors, supplied by the user.
AMBER = "#FAAD17"
TEAL = "#40A2AF"
WHITE = "#FFFFFF"

# A deep workspace backdrop contrasts with light, paper-like working cards.
# Avoid placing dark text directly on an unpredictable glass backdrop.
APP_BG = "#14252C"
CARD_BG = "#F2F8F8"
SURFACE = "#EDF5F4"
INPUT_BG = "#FFFFFF"
INK = "#17313B"
MUTED = "#45616A"
DEEP_TEAL = "#176A75"
BRIGHT_TEAL = "#81DEE4"
LIGHT_TEXT = "#F6FAFA"
LIGHT_MUTED = "#CFE2E5"
DIVIDER = "#B9D2D5"
AMBER_TINT = "#FFF2CB"
TEAL_TINT = "#E4F4F4"
DISABLED_BG = "#DCE7E7"
DISABLED_FG = "#52666D"

# Centralized action-button palette (v0.4.19).
# Applies to every RoundedButton kind (teal/amber/neutral/quiet), ttk.TButton,
# and AccentButton. Disabled buttons remain gray to indicate unavailable actions.
BUTTON_DEFAULT_BG = "#47B0BB"
BUTTON_HOVER_BG = "#DF9A19"
BUTTON_PRESSED_BG = "#C88714"
BUTTON_TEXT_FG = INK   # Dark label text is legible in both active colors.


def apply_theme(root):
    """Use reliable, readable widget colors without touching window opacity.

    The default native ttk theme can ignore color overrides under some Windows
    themes. Clam is only a control theme; it never changes the OS titlebar or
    the DWM backdrop controlled by Windhawk. Card surfaces are intentionally
    opaque to stop dark-on-dark and light-on-light text collisions.
    """
    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")

    style.configure(".", font=("Segoe UI", 10))
    style.configure("TFrame", background=APP_BG)
    style.configure("Card.TFrame", background=CARD_BG)
    style.configure("TLabel", background=CARD_BG, foreground=INK)
    style.configure("TLabelframe", background=CARD_BG, relief="solid",
                    borderwidth=1, bordercolor=DIVIDER, padding=2)
    style.configure("TLabelframe.Label", background=CARD_BG, foreground=DEEP_TEAL,
                    font=("Segoe UI", 10, "bold"))

    # Labels on the dark workspace use white/bright teal and a dark solid chip.
    style.configure("Toolbar.TLabel", background=APP_BG, foreground=LIGHT_TEXT,
                    font=("Segoe UI", 9, "bold"))
    style.configure("ToolbarHint.TLabel", background=APP_BG, foreground=LIGHT_MUTED,
                    font=("Segoe UI", 9))
    style.configure("Kicker.TLabel", background=APP_BG, foreground=BRIGHT_TEAL,
                    font=("Segoe UI", 9, "bold"))
    style.configure("Title.TLabel", background=APP_BG, foreground=LIGHT_TEXT,
                    font=("Segoe UI", 21, "bold"))
    style.configure("Subtitle.TLabel", background=APP_BG, foreground=LIGHT_MUTED,
                    font=("Segoe UI", 10))
    style.configure("Section.TLabel", background=APP_BG, foreground=BRIGHT_TEAL,
                    font=("Segoe UI", 10, "bold"))
    style.configure("Hint.TLabel", background=APP_BG, foreground=LIGHT_MUTED,
                    font=("Segoe UI", 9))

    # Control colors must be explicit on Windows glass/dark themes.
    style.configure("TEntry", padding=(8, 5), fieldbackground=INPUT_BG,
                    foreground=INK, bordercolor=DIVIDER, lightcolor=DIVIDER,
                    darkcolor=DIVIDER, insertcolor=INK)
    style.map("TEntry",
              foreground=[("disabled", DISABLED_FG), ("readonly", INK)],
              fieldbackground=[("disabled", DISABLED_BG), ("readonly", INPUT_BG),
                               ("!disabled", INPUT_BG)],
              bordercolor=[("focus", DEEP_TEAL)])
    style.configure("Value.TEntry", font=("Segoe UI", 13, "bold"),
                    padding=(9, 5), fieldbackground=INPUT_BG, foreground=INK,
                    bordercolor=DIVIDER)
    style.map("Value.TEntry",
              foreground=[("disabled", DISABLED_FG), ("readonly", INK)],
              fieldbackground=[("disabled", DISABLED_BG), ("readonly", INPUT_BG)])

    style.configure("TCombobox", padding=(7, 4), fieldbackground=INPUT_BG,
                    foreground=INK, background=TEAL_TINT, arrowcolor=DEEP_TEAL,
                    bordercolor=DIVIDER, lightcolor=DIVIDER, darkcolor=DIVIDER)
    style.map("TCombobox",
              fieldbackground=[("disabled", DISABLED_BG), ("readonly", INPUT_BG),
                               ("!disabled", INPUT_BG)],
              foreground=[("disabled", DISABLED_FG), ("readonly", INK)],
              background=[("disabled", DISABLED_BG), ("active", "#CAE6E9"),
                          ("readonly", TEAL_TINT)],
              arrowcolor=[("disabled", DISABLED_FG), ("readonly", DEEP_TEAL)],
              bordercolor=[("focus", DEEP_TEAL)])

    style.configure("TButton", font=("Segoe UI", 9, "bold"), padding=(11, 7),
                    background=BUTTON_DEFAULT_BG, foreground=BUTTON_TEXT_FG,
                    borderwidth=1, bordercolor=DIVIDER, relief="flat",
                    focuscolor=DEEP_TEAL)
    style.map("TButton",
              background=[("disabled", DISABLED_BG),
                          ("pressed", BUTTON_PRESSED_BG),
                          ("active", BUTTON_HOVER_BG),
                          ("!disabled", BUTTON_DEFAULT_BG)],
              foreground=[("disabled", DISABLED_FG),
                          ("!disabled", BUTTON_TEXT_FG)])
    style.configure("TScrollbar", background="#B5CDD0", troughcolor="#E0ECEC",
                    arrowcolor=INK, bordercolor=DIVIDER, relief="flat")
    style.map("TScrollbar", background=[("active", "#88B7BD")])
    style.configure("TSeparator", background=DIVIDER)

    style.configure("Treeview", font=("Segoe UI", 10), rowheight=31,
                    background=SURFACE, fieldbackground=SURFACE, foreground=INK,
                    bordercolor=DIVIDER, borderwidth=1, relief="flat")
    style.map("Treeview", background=[("selected", DEEP_TEAL)],
              foreground=[("selected", WHITE)])
    style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"),
                    foreground=INK, background="#CAE4E6", bordercolor=DIVIDER,
                    relief="flat", padding=(7, 8))
    style.map("Treeview.Heading", background=[("active", "#AAD5DA")])

    # Dropdown list and context menus have explicit contrast as well.
    root.option_add("*TCombobox*Listbox.background", INPUT_BG)
    root.option_add("*TCombobox*Listbox.foreground", INK)
    root.option_add("*TCombobox*Listbox.selectBackground", DEEP_TEAL)
    root.option_add("*TCombobox*Listbox.selectForeground", WHITE)
    root.option_add("*Menu.background", CARD_BG)
    root.option_add("*Menu.foreground", INK)
    root.option_add("*Menu.activeBackground", TEAL_TINT)
    root.option_add("*Menu.activeForeground", INK)
    return style


class AccentButton(tk.Button):
    """Legacy button with the same teal/amber hover behavior as RoundedButton.

    ``kind`` remains accepted for compatibility; all enabled actions now share
    one palette. Disabled actions keep their original gray appearance.
    """
    def __init__(self, master, *, kind="teal", **kwargs):
        self._hovered = False
        defaults = dict(
            bg=BUTTON_DEFAULT_BG, fg=BUTTON_TEXT_FG,
            activebackground=BUTTON_HOVER_BG,
            activeforeground=BUTTON_TEXT_FG,
            disabledforeground=DISABLED_FG, relief="flat", bd=0,
            highlightthickness=0, cursor="hand2", padx=15, pady=8,
            font=("Segoe UI", 10, "bold"),
        )
        defaults.update(kwargs)
        super().__init__(master, **defaults)
        self.bind("<Enter>", lambda _event: self._set_hover(True), add="+")
        self.bind("<Leave>", lambda _event: self._set_hover(False), add="+")
        self._update_enabled_color(self.cget("state"))

    def _set_hover(self, hovering):
        self._hovered = hovering
        self._update_enabled_color(self.cget("state"))

    def _update_enabled_color(self, state):
        if state == "disabled":
            super().configure(bg=DISABLED_BG, fg=BUTTON_TEXT_FG,
                              disabledforeground=DISABLED_FG, cursor="arrow")
        else:
            super().configure(
                bg=BUTTON_HOVER_BG if self._hovered else BUTTON_DEFAULT_BG,
                fg=BUTTON_TEXT_FG,
                activebackground=BUTTON_HOVER_BG,
                activeforeground=BUTTON_TEXT_FG,
                cursor="hand2",
            )

    def configure(self, cnf=None, **kwargs):
        result = super().configure(cnf, **kwargs)
        if "state" in kwargs:
            self._update_enabled_color(kwargs["state"])
        return result

    config = configure


def configure_readonly_text(widget, *, detail=False):
    """Stable dark-on-light copyable text on any glass/wallpaper."""
    widget.configure(
        background=SURFACE if detail else TEAL_TINT,
        foreground=INK, insertbackground=INK,
        selectbackground=DEEP_TEAL, selectforeground=WHITE,
        font=("Consolas", 10) if detail else ("Segoe UI", 10),
        relief="flat", highlightthickness=1,
        highlightbackground=DIVIDER, highlightcolor=TEAL,
    )


def configure_transfer_entry(widget):
    """Highlighted, copyable Odoo transfer number with consistent contrast."""
    widget.configure(
        bg=AMBER_TINT, readonlybackground=AMBER_TINT, fg="#684400",
        font=("Segoe UI", 14, "bold"), relief="solid", borderwidth=1,
        highlightthickness=1, highlightbackground=AMBER, highlightcolor=AMBER,
        selectbackground=DEEP_TEAL, selectforeground=WHITE,
    )


# ---------------------------------------------------------------------------
# Rounded cards and responsive buttons, entirely in Tkinter (no CSS or deps).
# Cards have opaque interiors so wallpaper/glass never washes out field text.
# No DWM / titlebar / window-alpha changes are performed.
# ---------------------------------------------------------------------------

def _paint_round_rect(canvas, left, top, right, bottom, radius, fill, outline=""):
    """Draw a rounded rectangle with solid native Tk canvas primitives."""
    r = max(2, min(int(radius), int((right - left) / 2), int((bottom - top) / 2)))
    x0, y0, x1, y1 = left, top, right, bottom
    c = canvas
    c.create_rectangle(x0 + r, y0, x1 - r, y1, fill=fill, outline="")
    c.create_rectangle(x0, y0 + r, x1, y1 - r, fill=fill, outline="")
    for xx, yy in ((x0, y0), (x1 - 2 * r, y0),
                   (x0, y1 - 2 * r), (x1 - 2 * r, y1 - 2 * r)):
        c.create_oval(xx, yy, xx + 2 * r, yy + 2 * r, fill=fill, outline="")
    if outline:
        # Lines and four quarter arcs leave the corners open/rounded.
        c.create_line(x0 + r, y0, x1 - r, y0, fill=outline)
        c.create_line(x0 + r, y1, x1 - r, y1, fill=outline)
        c.create_line(x0, y0 + r, x0, y1 - r, fill=outline)
        c.create_line(x1, y0 + r, x1, y1 - r, fill=outline)
        for xx, yy, start in (
            (x0, y0, 90), (x1 - 2 * r, y0, 0),
            (x0, y1 - 2 * r, 180), (x1 - 2 * r, y1 - 2 * r, 270),
        ):
            c.create_arc(xx, yy, xx + 2 * r, yy + 2 * r,
                         start=start, extent=90, style="arc", outline=outline)


class RoundedCard(tk.Frame):
    """Rounded outer panel, with a standard ttk content frame for form widgets.

    Use ``card.content`` as the parent of inputs and labels. The surrounding
    area is opaque and high contrast, while the OS-owned glass/titlebar remains
    entirely under Windows/Windhawk control.
    """
    def __init__(self, master, *, title="", radius=18, **kwargs):
        super().__init__(master, bg=APP_BG, bd=0, highlightthickness=0, **kwargs)
        self.radius = radius
        self.title_text = title
        self.surface_canvas = tk.Canvas(
            self, bd=0, bg=APP_BG, highlightthickness=0, takefocus=0,
        )
        self.surface_canvas.place(x=0, y=0, relwidth=1, relheight=1)
        top_space = 34 if title else 13
        self.content = ttk.Frame(self, style="Card.TFrame")
        self.content.pack(fill="both", expand=True, padx=15, pady=(top_space, 12))
        self.bind("<Configure>", self._render_card, add="+")

    def _render_card(self, event=None):
        width = self.winfo_width()
        height = self.winfo_height()
        if width <= 8 or height <= 8:
            return
        c = self.surface_canvas
        c.delete("all")
        _paint_round_rect(c, 1, 1, width-2, height-2, self.radius, CARD_BG, DIVIDER)
        if self.title_text:
            c.create_text(
                19, 17, text=self.title_text, anchor="w", fill=DEEP_TEAL,
                font=("Segoe UI", 10, "bold"),
            )


class RoundedButton(tk.Canvas):
    """Canvas-drawn button with hover/disabled/focus states and accessible keys.

    The interface deliberately supports the .config(text=..., state=...) calls
    already used by the application's Odoo/Lark business logic. Buttons expand
    with ``grid(sticky='ew')`` and can be rearranged on resize.
    """
    # Preserve existing kind= values for compatibility with main.py and
    # history_window.py, but give every enabled button the same color behavior:
    # default teal -> hover amber -> pressed darker amber, always dark text.
    _COLORS = {
        kind: (BUTTON_DEFAULT_BG, BUTTON_TEXT_FG,
               BUTTON_PRESSED_BG, BUTTON_HOVER_BG)
        for kind in ("teal", "amber", "neutral", "quiet")
    }

    def __init__(self, master, *, text="", command=None, state="normal",
                 kind="neutral", surface="card", radius=11, min_width=92,
                 height=39, **kwargs):
        self._label = str(text)
        self._command = command
        self._state = state
        self._kind = kind if kind in self._COLORS else "neutral"
        self._radius = radius
        self._surface_color = APP_BG if surface == "dark" else CARD_BG
        self._is_hover = False
        self._is_pressed = False
        self._is_focused = False
        self._font = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self._min_width = int(min_width)
        self._height = int(height)
        width = max(self._min_width, self._font.measure(self._label) + 30)
        super().__init__(
            master, bd=0, highlightthickness=0, relief="flat",
            bg=self._surface_color, takefocus=1,
            cursor="hand2" if state == "normal" else "arrow",
            width=width, height=height, **kwargs,
        )
        self.bind("<Configure>", self._render_button, add="+")
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<KeyRelease-space>", self._activate_key)
        self.bind("<KeyRelease-Return>", self._activate_key)
        self.bind("<FocusIn>", lambda _e: self._set_focus(True))
        self.bind("<FocusOut>", lambda _e: self._set_focus(False))
        self.after_idle(self._render_button)

    def _set_hover(self, hovering):
        self._is_hover = hovering
        self._render_button()

    def _set_focus(self, focused):
        self._is_focused = focused
        self._render_button()

    def _press(self, _event):
        if self._state == "normal":
            self.focus_set()
            self._is_pressed = True
            self._render_button()

    def _release(self, event):
        was_pressed = self._is_pressed
        self._is_pressed = False
        self._render_button()
        if (was_pressed and self._state == "normal"
                and 0 <= event.x <= self.winfo_width()
                and 0 <= event.y <= self.winfo_height()):
            self.invoke()

    def _activate_key(self, _event=None):
        self.invoke()
        return "break"

    def invoke(self):
        if self._state == "normal" and callable(self._command):
            return self._command()
        return None

    def _render_button(self, _event=None):
        if not self.winfo_exists():
            return
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 3 or h <= 3:
            return
        self.delete("all")
        base, fg, pressed, hover = self._COLORS[self._kind]
        if self._state != "normal":
            bg, fg = DISABLED_BG, DISABLED_FG
        elif self._is_pressed:
            bg = pressed
        elif self._is_hover:
            bg = hover
        else:
            bg = base
        border = DEEP_TEAL if self._is_focused and self._state == "normal" else DIVIDER
        _paint_round_rect(self, 2, 2, w-3, h-3, self._radius, bg, border)
        self.create_text(
            w/2, h/2, text=self._label, anchor="center", fill=fg,
            font=self._font, width=max(22, w-20), justify="center",
        )

    def configure(self, cnf=None, **kwargs):
        if cnf:
            kwargs.update(cnf)
        redraw = False
        if "text" in kwargs:
            self._label = str(kwargs.pop("text"))
            width = max(self._min_width, self._font.measure(self._label) + 30)
            kwargs.setdefault("width", width)
            redraw = True
        if "state" in kwargs:
            state = kwargs.pop("state")
            if state not in ("normal", "disabled"):
                raise ValueError("RoundedButton state must be normal or disabled")
            self._state = state
            kwargs["cursor"] = "hand2" if state == "normal" else "arrow"
            redraw = True
        if "command" in kwargs:
            self._command = kwargs.pop("command")
        result = super().configure(**kwargs)
        if redraw:
            self._render_button()
        return result

    config = configure

    def cget(self, key):
        if key == "text":
            return self._label
        if key == "state":
            return self._state
        if key == "command":
            return self._command
        return super().cget(key)
