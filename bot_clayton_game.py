import sys
import threading
import time
import dlib
import ctypes
import numpy as np
import logging
import asyncio
from PyQt5.QtWidgets import QApplication, QMainWindow, QPushButton, QTextEdit, QVBoxLayout, QWidget, QLabel
from PyQt5.QtGui import QPalette, QColor, QFont
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from mss import mss
from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed
from pynput import keyboard, mouse
import pygetwindow as gw
import pyautogui
import random
import gc
import os

# Logging setup
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[logging.StreamHandler(sys.stdout)])  # Log to stdout

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

alt_pressed = False
stop_flag = threading.Event()
pause_flag = threading.Event()
click_event = threading.Event()
first_run = True
last_click_coords = (None, None)
home_click_counter = 0  # Добавляем счетчик кликов по "Home"

class LoadDetectorsThread(QThread):
    detectors_loaded = pyqtSignal(dict)

    def run(self):
        detectors = self.load_detectors()
        self.detectors_loaded.emit(detectors)

    def load_detectors(self):
        try:
            base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
            detectors = {
                "2": dlib.simple_object_detector(os.path.join(base_path, "2.svm")),
                "4": dlib.simple_object_detector(os.path.join(base_path, "4.svm")),
                "8": dlib.simple_object_detector(os.path.join(base_path, "8.svm")),
                "16": dlib.simple_object_detector(os.path.join(base_path, "16.svm")),
                "32": dlib.simple_object_detector(os.path.join(base_path, "32.svm")),
                "64": dlib.simple_object_detector(os.path.join(base_path, "64.svm")),
                "128": dlib.simple_object_detector(os.path.join(base_path, "128.svm")),
                "256": dlib.simple_object_detector(os.path.join(base_path, "256.svm")),
                "Play": dlib.simple_object_detector(os.path.join(base_path, "calyton_play.svm")),
                "Home": dlib.simple_object_detector(os.path.join(base_path, "calyton_home.svm"))
            }
            return detectors
        except Exception as e:
            logging.error(f"Error loading detectors: {e}")
            raise

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.detectors = None
        self.capture_thread = None
        self.last_detection_time = time.time()
        self.load_detectors_thread = LoadDetectorsThread()
        self.load_detectors_thread.detectors_loaded.connect(self.on_detectors_loaded)
        self.load_detectors_thread.start()

    def init_ui(self):
        self.setWindowTitle("Bot for playing '1024' in Cayton app (v1.06)")
        self.setGeometry(100, 100, 400, 350)
        self.center_window()

        self.start_button = QPushButton("Start", self)
        self.exit_button = QPushButton("Exit", self)
        self.log_text_edit = QTextEdit(self)
        self.log_text_edit.setReadOnly(True)
        self.hint_label = QLabel(self)

        hint_font_size = 10
        hint_text = f"""
            <span style="font-size:{hint_font_size}pt;">
                <b>Hint:</b> 
                <span style="color:#ffa318; font-weight:bold;">Alt + Space</span> (pause) | 
                <span style="color:#ffa318; font-weight:bold;">Alt + F2</span> (stop program)
            </span>
        """
        self.hint_label.setText(hint_text)

        button_font = QFont("Arial", 14, QFont.Bold)
        self.start_button.setFont(button_font)
        self.exit_button.setFont(button_font)

        log_font = QFont("Segoe UI", 10)
        self.log_text_edit.setFont(log_font)

        border_color = "#737373"

        button_style = f"""
            QPushButton {{
                background-color: #ffa81e;
                color: #313131;
                padding: 10px;
                border-radius: 10px;
                border: 1px solid {border_color};
            }}
            QPushButton:hover {{
                background-color: #fd951f;
            }}
            QPushButton:pressed {{
                background-color: #d97706;
            }}
        """
        exit_button_style = f"""
            QPushButton {{
                background-color: #da6201;
                color: #fcfcfc;
                padding: 10px;
                border-radius: 10px;
                border: 1px solid {border_color};
            }}
            QPushButton:hover {{
                background-color: #9d4a00;
            }}
            QPushButton:pressed {{
                background-color: #843e00;
            }}
        """
        log_style = f"""
            QTextEdit {{
                background-color: #373737;
                color: #D1D1D1;
                border: 2px solid {border_color};
                border-radius: 10px;
                padding: 5px;
            }}
        """

        self.start_button.setStyleSheet(button_style)
        self.exit_button.setStyleSheet(exit_button_style)
        self.log_text_edit.setStyleSheet(log_style)

        layout = QVBoxLayout()
        layout.addWidget(self.start_button)
        layout.addWidget(self.exit_button)
        layout.addWidget(self.log_text_edit)
        layout.addWidget(self.hint_label)

        central_widget = QWidget()
        central_widget.setLayout(layout)
        self.setCentralWidget(central_widget)

        self.start_button.clicked.connect(self.start_process)
        self.exit_button.clicked.connect(self.exit_program)

    def center_window(self):
        screen = QApplication.primaryScreen().availableGeometry()
        size = self.geometry()
        self.move((screen.width() - size.width()) // 2, (screen.height() - size.height()) // 2)

    def update_log(self, message):
        logging.info(f"Log: {message}")
        self.log_text_edit.append(message)
        self.log_text_edit.ensureCursorVisible()
        QApplication.processEvents()

    def on_detectors_loaded(self, detectors):
        self.detectors = detectors

    def start_process(self):
        self.update_log("Process started...")
        if self.detectors is None:
            self.update_log("Detectors not loaded yet.")
            return
        window = self.get_window_from_click()
        if window:
            global stop_flag, first_run, last_click_coords
            stop_flag.clear()
            first_run = True
            last_click_coords = (None, None)
            self.last_detection_time = time.time()
            self.capture_thread = threading.Thread(target=self.capture_and_process_loop, args=(window,), daemon=True)
            self.capture_thread.start()

    def stop_process(self):
        global stop_flag
        stop_flag.set()
        self.update_log("Process stopped.")
        gc.collect()

    def exit_program(self):
        global stop_flag
        stop_flag.set()
        self.update_log("Exiting program.")
        QApplication.quit()
        gc.collect()

    def get_window_from_click(self):
        self.update_log("Please click on the application window...")
        global click_event
        click_event.clear()
        click_event.wait()
        x, y = self.get_cursor_pos()
        self.update_log("Script started.")
        window = gw.getWindowsAt(x, y)
        if not window:
            self.update_log("Window not found at coordinates.")
            return None
        return window[0]

    def get_cursor_pos(self):
        cursor = POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(cursor))
        return cursor.x, cursor.y

    def capture_and_process_loop(self, window):
        global home_click_counter
        home_click_counter = 0  # Сбрасываем счетчик кликов по Home
        while not stop_flag.is_set():
            try:
                self.capture_and_process(window)
            except Exception as e:
                self.update_log(f"Error in capture_and_process: {e}")
                time.sleep(5)
                continue

    def capture_and_process(self, window):
        left, top, width, height = window.left, window.top, window.width, window.height
        monitor = {"top": top, "left": left, "width": width, "height": height}

        with mss() as sct:
            resize_factor = 1

            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = []

                while not stop_flag.is_set():
                    if pause_flag.is_set():
                        time.sleep(0.1)
                        continue

                    screenshot = np.array(sct.grab(monitor))
                    future = executor.submit(self.process_image, screenshot, left, top, resize_factor)
                    futures.append(future)

                    for future in as_completed(futures):
                        detections = future.result()
                        futures.remove(future)

                        if detections:
                            self.last_detection_time = time.time()

                        award_detections = [det for label, det in detections if label == 'Home']
                        play_detections = [det for label, det in detections if label == 'Play']
                        tile_detections = [det for label, det in detections if label in ["2", "4", "8", "16", "32", "64", "128", "256"]]

                        if award_detections:
                            global home_click_counter
                            home_click_counter += 1
                            for det in award_detections:
                                self.click_button(det, left, top, "Home")

                            # Проверяем, сколько раз подряд была нажата кнопка Home
                            if home_click_counter >= 5:
                                self.update_log("Timeout reached. Script execution stopped.")
                                self.stop_process()
                            continue

                        if play_detections:
                            home_click_counter = 0  # Сбрасываем счетчик, если нажата другая кнопка
                            for det in play_detections:
                                self.click_button(det, left, top, "Play")
                            continue

                        if tile_detections:
                            home_click_counter = 0  # Сбрасываем счетчик при нахождении плиток
                            directions = ['up', 'down', 'left', 'right']
                            random.shuffle(directions)
                            for direction in directions:
                                self.make_move(direction)
                                time.sleep(0.1)
                        else:
                            continue

                    if time.time() - self.last_detection_time > 20:
                        self.update_log("Nothing detected for 20 seconds. Stopping process.")
                        self.stop_process()
                        gc.collect()

    def process_image(self, screenshot, left, top, resize_factor):
        try:
            small_screenshot = Image.fromarray(screenshot).resize(
                (int(screenshot.shape[1] * resize_factor), int(screenshot.shape[0] * resize_factor))
            )
            small_screenshot_rgb = np.array(small_screenshot.convert("RGB"))

            detected_tiles = []

            for label, detector in self.detectors.items():
                detections = detector(small_screenshot_rgb)
                for det in detections:
                    detected_tiles.append((label, det))

            return detected_tiles
        except Exception as e:
            logging.error(f"Error in process_image: {e}")
            return []

    def click_button(self, detection, left, top, button_name):
        try:
            x_center = left + (detection.left() + detection.right()) // 2
            y_center = top + (detection.top() + detection.bottom()) // 2
            window = gw.getWindowsAt(left + 10, top + 10)
            if window:
                window = window[0]
                window.activate()
                time.sleep(1)
                pyautogui.moveTo(x_center, y_center)
                pyautogui.click()
                time.sleep(1)
                self.update_log(f"Button {button_name} clicked.")
        except Exception as e:
            logging.error(f"Error clicking button {button_name}: {e}")

    def make_move(self, direction):
        try:
            if direction == 'left':
                pyautogui.press('left')
            elif direction == 'right':
                pyautogui.press('right')
            elif direction == 'up':
                pyautogui.press('up')
            elif direction == 'down':
                pyautogui.press('down')
        except Exception as e:
            logging.error(f"Error executing move {direction}: {e}")

def on_press(key):
    global alt_pressed, stop_flag, pause_flag
    try:
        if key == keyboard.Key.alt_l or key == keyboard.Key.alt_r:
            alt_pressed = True
        if key == keyboard.Key.f2 and alt_pressed:
            stop_flag.set()
            main_window.update_log("Script stopped by user (ALT + F2).")
        if key == keyboard.Key.space and alt_pressed:
            if pause_flag.is_set():
                pause_flag.clear()
                main_window.update_log("Script resumed (ALT + Space).")
            else:
                pause_flag.set()
                main_window.update_log("Script paused (ALT + Space).")
    except Exception as e:
        logging.error(f"Error processing key press: {e}")
        main_window.update_log(f"Error processing key press: {e}")

def on_release(key):
    global alt_pressed
    if key == keyboard.Key.alt_l or key == keyboard.Key.alt_r:
        alt_pressed = False

def on_click(x, y, button, pressed):
    global click_event
    if pressed:
        click_event.set()

def main():
    global main_window
    app = QApplication(sys.argv)

    dark_palette = QPalette()
    dark_palette.setColor(QPalette.Window, QColor(33, 33, 33))
    dark_palette.setColor(QPalette.WindowText, Qt.white)
    dark_palette.setColor(QPalette.Base, QColor(25, 25, 25))
    dark_palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ToolTipBase, Qt.white)
    dark_palette.setColor(QPalette.ToolTipText, Qt.white)
    dark_palette.setColor(QPalette.Text, Qt.white)
    dark_palette.setColor(QPalette.Button, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ButtonText, Qt.white)
    dark_palette.setColor(QPalette.BrightText, Qt.red)
    dark_palette.setColor(QPalette.Link, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.HighlightedText, Qt.black)

    app.setPalette(dark_palette)

    main_window = MainWindow()
    main_window.show()

    keyboard_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    mouse_listener = mouse.Listener(on_click=on_click)

    keyboard_listener.start()
    mouse_listener.start()

    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
