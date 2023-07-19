import json
import datetime
import re
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor

from kivy.lang import Builder
from kivy.utils import get_color_from_hex
from kivy.core.window import Window
from kivy.clock import Clock
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.label import Label
from kivy.uix.codeinput import CodeInput
from kivy.uix.boxlayout import BoxLayout
from kivy.metrics import dp, sp

from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel
from kivymd.font_definitions import fonts as font_def

from pygments.styles import get_style_by_name
from pygments.lexers import CLexer
from pygments import styles
from catppuccin.flavour import Flavour as CatppuccinFlavour
import requests 

INBUILT_STYLES = list(styles.get_all_styles())
theme_string = "self.code_style.background_color = get_color_from_hex(CatppuccinFlavour.{}().base.hex)"


class Settings:
    def __init__(self):
        self.settings_file = "settings.json"
        with open(self.settings_file, "r") as file:
            self.data = json.loads(file.read())
            self.update(self.data)
            file.close()

    def update(self, data: dict):
        for key in data.keys():
            exec(f"self.{key} = data['{key}']")

    def write(self, value, key):
        self.data[value] = key
        with open(self.settings_file, "w") as file:
            json.dump(self.data, file)
            file.close()
        self.update(self.data)


class RobotariumCodeInput(CodeInput):
    _added_ = False

    def on_size(self, instance, value):
        self.app = MDApp.get_running_app()
        super(CodeInput, self).on_size(instance, value)
        self.app.update_line_box()

    def on_cursor(self, instance, cursor_position):
        self.app.update_line_box()
        super(CodeInput, self).on_cursor(instance, cursor_position)

    def on_scroll_y(self, instance, height):
        self.app.update_line_box()

    def keyboard_on_key_down(self, keyboard, keycode, text, modifiers):
        line = self._lines[self.cursor_row].strip()
        if keycode[1] == "enter":
            super(CodeInput, self).keyboard_on_key_down(
                keyboard, keycode, text, modifiers
            )
            if line.endswith(":"):
                self.insert_text("\t")

        elif (
            keycode[1] == "tab"
            and self.app.root.ids.suggestion_view.parent.opacity == 1
            and len(self.app.current_completions) != 0
        ):
            current_completion = self.app.current_completions[0]
            self.insert_text(current_completion.complete)
            if current_completion.type == "function":
                self.insert_text("()")
                self.cursor = (self.cursor[0] - 1, self.cursor[1])
        else:
            super(CodeInput, self).keyboard_on_key_down(
                keyboard, keycode, text, modifiers
            )
        Clock.schedule_once(lambda _: self.keyboard_features(keycode))

    def keyboard_features(self, keycode):
        line = self._lines[self.cursor_row]

        if len(line) == 0 or len(line) < self.cursor_col:
            return

        current_text = line[self.cursor_col - 1]

        if keycode[1] in ["9", "'"] and current_text in ["(", "'", '"']:
            self.insert_text((")" if current_text == "(" else current_text))
            self.cursor = (self.cursor[0] - 1, self.cursor[1])
            self._added_ = True

        elif (
            keycode[1] in ["0", "'"]
            and current_text in [")", "'", '"']
            and self._added_ == True
        ):
            self.do_backspace(mode="del")

        elif (
            keycode[1] == "backspace"
            and self._undo[-1]["undo_command"][2] in ["(", "'", '"']
            and len(line) != self.cursor_col
            and line[self.cursor_col] in ["'", '"', ")"]
        ):
            cursor = self.cursor
            self.do_cursor_movement("cursor_right")
            if cursor != self.cursor:
                self.do_backspace(mode="del")
        else:
            self._added_ = False


class Arduino:

    def __init__(self):
        self.executable = "arduino-cli"

    def init_uno(self):
        yield self.runcmd("{} config init".format(self.executable))
        yield self.runcmd("{} core update-index".format(self.executable))
        yield self.runcmd("{} core install arduino:avr".format(self.executable))

    def runcmd(self, cmd):
        try:
            output = subprocess.check_output(
                cmd, shell=True, stderr=subprocess.STDOUT, universal_newlines=True
            )
            return_code = 0
        except subprocess.CalledProcessError as e:
            output = e.output
            return_code = e.returncode
        return re.sub(r"\033\[(?:\d+;)*\d+m", "", output), return_code

    def get_device(self):
        output = self.runcmd("{} board list".format(self.executable))[0].split("\n")
        for count, line in enumerate(output):
            if line.strip() == "No boards found.":
                break
            elif "serial" in line:
                return line.split(" ")[0].strip()
        return None

    def compile(self, project):
        return self.runcmd(
            "{} compile --fqbn arduino:avr:uno {}".format(self.executable, project)
        )

    def run(self, project, device):
        print("{} upload -p {} --fqbn arduino:avr:uno {}".format(
                self.executable, device, project
            ))
        return self.runcmd(
            "{} upload -p {} --fqbn arduino:avr:uno {}".format(
                self.executable, device, project
            )
        )


class Robotarium(MDApp):

    current_project = "..\MyFirstSketch"
    medium_font = "fonts/Poppins-Medium.ttf"
    regular_font = "fonts/Poppins-Regular.ttf"
    icon_font = font_def[-1]["fn_regular"]

    def console_log(self, text):
        def _(__):
            wid = MDLabel(
                text=text,
                markup=True,
                adaptive_height=True,
            )
            wid.font_name = font_name = self.Settings.font
            self.root.ids.console_view.add_widget(wid)

        Clock.schedule_once(_)

    def run_project(self):
        self.console_log(
            "\n[color=#98c379][{}] COMPILING AND RUNNING[/color]".format(
                datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
            )
        )
        compile_code = self.arduino.compile(self.current_project)
        self.console_log(
            "\n"
            + compile_code[0]
            + (
                "\n[color=#00FF00]COMPILE SUCCESS[/color]\n"
                if compile_code[-1] == 0
                else "[color=#FF0000]COMPILE FAILED, check above errors![/color]\n"
            )
        )
        if compile_code[-1] != 0:
            return
        device = self.arduino.get_device()

        if compile_code[-1] == 0 and device is not None:
            self.console_log("[color=#00FF00]DEVICE FOUND : {} [/color]\n".format(device))
            run_output = self.arduino.run(self.current_project, device)
            self.console_log(
                run_output[0]
                + (
                    "\n[color=#00FF00]RAN SUCCESSFULLY[/color]\n"
                    if run_output[-1] == 0
                    else "\n[color=#e06c75]FAILED TO RUN, check above errors![/color]\n"
                )
            )
        else:
            self.console_log("[color=#84c1da]DEVICE NOT CONNECTED![/color]")

    def process_file(self, data):
        data_ = []
        for count, line in enumerate(data.split("\n")):
            data_.append(line)
        data_ = data_[:-1] if data_[-1].strip() == "" else data_
        return "\n".join(data_)

    def build(self):
        self.arduino = Arduino()
        self.Settings = Settings()
        self.theme_cls.theme_style = "Dark"
        self.theme_cls.accent_palette = "Blue"
        self.theme_cls.primary_palette = "Red"
        return Builder.load_file("main.kv")

    def on_start(self):
        self.init_threads()
        self.add_code_widget()
        self.open_project(self.current_project)

    def add_code_widget(self):
        self.code_widget = self.build_code_widget()
        self.root.ids.code_box.md_bg_color = self.code_style.background_color
        self.root.ids.code_box.add_widget(self.code_widget)
        self.root.ids.line_box.color = self.theme_cls.opposite_bg_light[:-1] + [0.5]
        self.root.ids.line_box.md_bg_color = self.code_style.background_color
        self.root.md_bg_color = self.code_style.background_color
        self.root.ids.line_box.font_name = self.code_widget.font_name
        self.root.ids.line_box.font_size = self.code_widget.font_size

    def open_project(self, project_path):
        file_name = project_path + "/" + os.path.basename(project_path) +  ".ino"
        self.code_widget.app = self
        self.current_file = file_name
        with open(file_name, "r") as file:
            self.code_widget.text = self.process_file(file.read())
            self.code_widget.cursor = (0, 0)
            file.close()

    def update_line_box(self):
        total_lines = len(self.code_widget._lines)
        cursor_row = self.code_widget.cursor_row + 1
        single_line_height = (
            self.code_widget.line_height + self.code_widget.line_spacing
        )
        total_widget_height = self.code_widget.height
        scroll_height = self.code_widget.scroll_y
        max_lines = int(total_widget_height / (single_line_height)) + 1

        top_line_index = int(scroll_height / single_line_height) + 1
        self.root.ids.line_box.width = dp(10) + max(
            self.code_widget.font_size * (len(str(total_lines)) - 1), dp(20)
        )
        bottom_line_index = top_line_index + max_lines

        if bottom_line_index > total_lines + 1:
            bottom_line_index -= bottom_line_index - total_lines - 1

        line_data = [str(i) for i in range(top_line_index, bottom_line_index)]

        if len(line_data) < max_lines:
            [line_data.append(" ") for i in range(max_lines - len(line_data))]

        if str(cursor_row) in line_data:
            line_data[
                line_data.index(str(cursor_row))
            ] = "[color=#FFFFFF]{}[/color]".format(str(cursor_row))

        self.root.ids.line_box.text = "\n".join(line_data)

    def init_threads(self):
        self.main_thread = ThreadPoolExecutor()

    def build_code_widget(self):
        self.code_style = get_style_by_name("catppuccin-mocha")
        # Background color for catppuccin
        if "background_color" not in vars(self.code_style).keys():
            if self.code_style.__name__ in [
                "LatteStyle",
                "FrappeStyle",
                "MacchiatoStyle",
                "MochaStyle",
            ]:
                exec(theme_string.format(self.code_style.__name__[:-5].lower()))

        return RobotariumCodeInput(
            style=self.code_style,
            background_color=[0, 0, 0, 0],
            do_wrap=False,
            auto_indent=True,
            scroll_distance=dp(20),
            line_spacing=0,
            font_size=self.Settings.font_size,
            font_name=self.Settings.font,
            lexer=CLexer(),
        )


Robotarium().run()
