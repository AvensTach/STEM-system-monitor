import customtkinter as ctk
import psutil
import time
import threading
import os
import subprocess
import csv
import io
from collections import deque
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from plyer import notification

# Налаштування базової теми CustomTkinter
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class MonitorTab(ctk.CTkFrame):
    """Базовий клас, який створює окремі графіки для кожного пристрою (subplots)"""

    def __init__(self, parent, title, y_label, item_names, limit=100):
        super().__init__(parent, corner_radius=10)
        self.title = title
        self.y_label = y_label
        self.item_names = item_names

        self.histories = {name: deque([0] * 60, maxlen=60) for name in item_names}
        self.limits = {name: limit for name in item_names}

        # Координати для осі X: від 59 до 0 (щоб 0 був праворуч)
        self.x_data = list(range(59, -1, -1))

        # Динамічна висота залежно від кількості графіків
        fig_height = max(4.0, 2.5 * len(item_names))
        self.fig = Figure(figsize=(7, fig_height), dpi=100)

        self.axes = {}
        self.lines = {}

        colors = ['#4a90e2', '#e74c3c', '#2ecc71', '#f1c40f', '#9b59b6']

        for i, name in enumerate(item_names):
            ax = self.fig.add_subplot(len(item_names), 1, i + 1)
            ax.set_ylim(0, self.limits[name])

            # Перевертаємо вісь X (60 зліва, 0 справа)
            ax.set_xlim(60, 0)

            ax.set_ylabel(self.y_label)
            ax.set_title(name, fontsize=12, fontweight='bold')

            color = colors[i % len(colors)]
            line, = ax.plot(self.x_data, self.histories[name], color=color, linewidth=2)

            self.axes[name] = ax
            self.lines[name] = line

        self.fig.tight_layout(pad=2.0)

        self.canvas = FigureCanvasTkAgg(self.fig, self)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=15, pady=(15, 5))

        self.labels_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.labels_frame.pack(pady=(5, 15))

        self.value_labels = {}
        for name in item_names:
            lbl = ctk.CTkLabel(self.labels_frame, text=f"{name}: 0 {self.y_label}",
                               font=ctk.CTkFont(size=14, weight="bold"))
            lbl.pack(side="left", padx=15)
            # Зберігаємо лейбл у словник для оновлення
            self.value_labels[name] = lbl

        self.apply_theme(ctk.get_appearance_mode())

    def apply_theme(self, mode):
        bg_color = '#2b2b2b' if mode == 'Dark' else '#dbdbdb'
        text_color = 'white' if mode == 'Dark' else 'black'
        grid_color = '#444444' if mode == 'Dark' else '#b0b0b0'

        self.fig.patch.set_facecolor(bg_color)

        for ax in self.axes.values():
            ax.set_facecolor(bg_color)
            ax.tick_params(colors=text_color)
            ax.xaxis.label.set_color(text_color)
            ax.yaxis.label.set_color(text_color)
            ax.title.set_color(text_color)
            ax.grid(color=grid_color, linestyle='--', alpha=0.7)

            for spine in ax.spines.values():
                spine.set_color(grid_color)

        self.fig.canvas.draw_idle()

    def update_ui(self, values_dict):
        for name, val in values_dict.items():
            if name in self.histories:
                self.histories[name].append(val)
                self.lines[name].set_ydata(self.histories[name])
                self.value_labels[name].configure(text=f"{name}: {val:.1f} {self.y_label}")

                # Універсальна адаптивність: якщо значення перевищує ліміт, збільшуємо вісь Y на 20%
                if val > self.limits[name]:
                    self.limits[name] = val * 1.2
                    self.axes[name].set_ylim(0, self.limits[name])

        self.fig.canvas.draw_idle()

    def get_data(self):
        return {}


class CPUTab(MonitorTab):
    def __init__(self, parent):
        super().__init__(parent, "CPU", "%", ["Загальне CPU"])

    def get_data(self):
        return {"Загальне CPU": psutil.cpu_percent(interval=None)}


class RAMTab(MonitorTab):
    def __init__(self, parent):
        self.total_ram_gb = psutil.virtual_memory().total / (1024 ** 3)
        super().__init__(parent, "RAM", "ГБ", ["Використано"], limit=self.total_ram_gb)

    def get_data(self):
        return {"Використано": psutil.virtual_memory().used / (1024 ** 3)}


class DiskTab(MonitorTab):
    def __init__(self, parent):
        disk_io = psutil.disk_io_counters(perdisk=True)
        self.sys_names = list(disk_io.keys()) if disk_io else ["Диск"]

        # Отримуємо апаратні назви дисків
        hardware_mapping = self.get_hardware_names()

        self.sys_to_display = {}
        self.display_names = []

        for sys_name in self.sys_names:
            display_name = sys_name
            for hw_sys, hw_model in hardware_mapping.items():
                if hw_sys.upper() == sys_name.upper():
                    display_name = hw_model
                    break

            # Захист від однакових дисків у системі
            original_display = display_name
            counter = 1
            while display_name in self.display_names:
                display_name = f"{original_display} ({counter})"
                counter += 1

            self.sys_to_display[sys_name] = display_name
            self.display_names.append(display_name)

        super().__init__(parent, "Активність Дисків", "МБ/с", self.display_names, limit=20)
        self.last_io = disk_io
        self.last_time = time.time()

    def get_hardware_names(self):
        """Звертається до Windows (через PowerShell) для отримання моделей дисків"""
        mapping = {}
        if os.name == 'nt':
            try:
                cmd = 'powershell -NoProfile -Command "Get-CimInstance Win32_DiskDrive | Select-Object Name, Model | ConvertTo-Csv -NoTypeInformation"'
                # CREATE_NO_WINDOW (0x08000000) щоб не з'являлося чорне вікно
                output = subprocess.check_output(cmd, text=True, shell=True, creationflags=0x08000000)

                reader = csv.DictReader(io.StringIO(output.strip()))
                for row in reader:
                    name_raw = row['Name']
                    model = row['Model']
                    name_clean = name_raw.replace('\\\\.\\', '')
                    mapping[name_clean] = model
            except Exception as e:
                print(f"Помилка отримання назв дисків: {e}")
        return mapping

    def get_data(self):
        current_time = time.time()
        current_io = psutil.disk_io_counters(perdisk=True)
        results = {}

        for sys_name in self.sys_names:
            display_name = self.sys_to_display[sys_name]
            if sys_name in current_io and sys_name in self.last_io:
                bytes_now = current_io[sys_name].read_bytes + current_io[sys_name].write_bytes
                bytes_last = self.last_io[sys_name].read_bytes + self.last_io[sys_name].write_bytes

                mb_per_sec = ((bytes_now - bytes_last) / (current_time - self.last_time)) / (1024 * 1024)
                results[display_name] = max(0, mb_per_sec)

        self.last_io = current_io
        self.last_time = current_time
        return results


class NetworkTab(MonitorTab):
    def __init__(self, parent):
        super().__init__(parent, "Мережа", "Мбіт/с", ["Трафік"], limit=10)
        self.last_net = psutil.net_io_counters().bytes_sent + psutil.net_io_counters().bytes_recv
        self.last_time = time.time()

    def get_data(self):
        current_net = psutil.net_io_counters().bytes_sent + psutil.net_io_counters().bytes_recv
        current_time = time.time()

        bytes_per_sec = (current_net - self.last_net) / (current_time - self.last_time)
        # Перевід байтів у мегабіти (Mbps)
        mbps = (bytes_per_sec * 8) / 1_000_000

        self.last_net = current_net
        self.last_time = current_time
        return {"Трафік": max(0, mbps)}


class SystemMonitorApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Системний Монітор ресурсів")
        self.geometry("850x700")

        total_ram = psutil.virtual_memory().total / (1024 ** 3)
        self.thresholds = {
            "CPU": 80.0,
            "RAM": total_ram * 0.90,
            "Disk": 100.0,
            "Network": float('inf')
        }

        self.last_alert_time = {}

        self.create_widgets()
        self.update_data()

    def create_widgets(self):
        self.header_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.header_frame.pack(fill="x", padx=20, pady=(10, 0))

        self.title_label = ctk.CTkLabel(self.header_frame, text="Advanced STEM Monitor",
                                        font=ctk.CTkFont(size=24, weight="bold"))
        self.title_label.pack(side="left")

        self.theme_switch = ctk.CTkSwitch(self.header_frame, text="Темна тема", command=self.change_theme)
        self.theme_switch.pack(side="right")
        self.theme_switch.select()

        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=20, pady=20)

        tabs_setup = {
            "CPU": CPUTab,
            "RAM": RAMTab,
            "Disk": DiskTab,
            "Network": NetworkTab
        }

        self.tabs = {}
        for name, TabClass in tabs_setup.items():
            self.tabview.add(name)
            self.tabs[name] = TabClass(self.tabview.tab(name))
            self.tabs[name].pack(fill="both", expand=True)

    def change_theme(self):
        mode = "Dark" if self.theme_switch.get() == 1 else "Light"
        ctk.set_appearance_mode(mode)
        for tab in self.tabs.values():
            tab.apply_theme(mode)

    def check_thresholds(self, component, item_name, value):
        if component in self.thresholds and value >= self.thresholds[component]:
            current_time = time.time()
            alert_key = f"{component}_{item_name}"

            if current_time - self.last_alert_time.get(alert_key, 0) > 30:
                # Обираємо правильні одиниці виміру для сповіщень
                unit = "ГБ" if component == "RAM" else "МБ/с" if component == "Disk" else "Мбіт/с" if component == "Network" else "%"

                def send_alert():
                    try:
                        notification.notify(
                            title=f"Увага! Навантаження {component}",
                            message=f"[{item_name}] досягло {value:.1f}{unit}!",
                            app_name="System Monitor",
                            timeout=5
                        )
                    except Exception as e:
                        print(e)

                threading.Thread(target=send_alert, daemon=True).start()
                self.last_alert_time[alert_key] = current_time

    def update_data(self):
        for name, tab in self.tabs.items():
            values_dict = tab.get_data()
            tab.update_ui(values_dict)

            for item_name, val in values_dict.items():
                self.check_thresholds(name, item_name, val)

        self.after(1000, self.update_data)


if __name__ == "__main__":
    app = SystemMonitorApp()
    app.mainloop()