
import sys
import threading
import time

try:
    from pynput import keyboard, mouse
    from pynput.keyboard import Key, KeyCode, Controller as KeyboardController
    from pynput.mouse import Button, Controller as MouseController
except ImportError:
    print("pynput 라이브러리가 설치되어 있지 않습니다.")
    sys.exit(1)

SPECIAL_KEYS = {
    "esc": Key.esc, "space": Key.space, "enter": Key.enter, "return": Key.enter,
    "tab": Key.tab, "backspace": Key.backspace, "delete": Key.delete,
    "up": Key.up, "down": Key.down, "left": Key.left, "right": Key.right,
    "home": Key.home, "end": Key.end, "page_up": Key.page_up, "page_down": Key.page_down,
    "shift": Key.shift, "shift_r": Key.shift_r,
    "ctrl": Key.ctrl, "ctrl_r": Key.ctrl_r,
    "alt": Key.alt, "alt_r": Key.alt_r,
    "cmd": Key.cmd, "caps_lock": Key.caps_lock,
}
for i in range(1, 25):
    SPECIAL_KEYS[f"f{i}"] = getattr(Key, f"f{i}", None)
SPECIAL_KEYS = {k: v for k, v in SPECIAL_KEYS.items() if v is not None}

MOUSE_BUTTONS = {"left": Button.left, "right": Button.right, "middle": Button.middle}


def parse_key(key_str):
    if key_str is None:
        return None
    key_str = key_str.strip().lower()
    if key_str in SPECIAL_KEYS:
        return SPECIAL_KEYS[key_str]
    if len(key_str) == 1:
        return KeyCode.from_char(key_str)
    return None


def key_to_str(key):
    try:
        if isinstance(key, KeyCode):
            return key.char.lower() if key.char else None
        if isinstance(key, Key):
            return key.name
    except Exception:
        return None
    return None


class MacroConfig:
    def __init__(self):
        self.mode = "mouse"
        self.interval = 0.1
        self.start_key = "f6"
        self.stop_key = "f7"
        self.input_key = "a"
        self.mouse_button = "left"

    def status_text(self):
        return (
            "\n===== 현재 설정 =====\n"
            f" 모드           : {self.mode}\n"
            f" 속도(간격)     : {self.interval}초\n"
            f" 시작 단축키    : {self.start_key}\n"
            f" 중단 단축키    : {self.stop_key}\n"
            f" 키보드 입력 키 : {self.input_key}\n"
            f" 마우스 버튼    : {self.mouse_button}\n"
            "======================\n"
        )


config = MacroConfig()
config_lock = threading.Lock()
running = threading.Event()
stop_program = threading.Event()

mouse_controller = MouseController()
keyboard_controller = KeyboardController()

def macro_worker():
    while not stop_program.is_set():
        running.wait(timeout=0.2)
        if not running.is_set():
            continue

        with config_lock:
            mode = config.mode
            interval = config.interval
            input_key_str = config.input_key
            button_str = config.mouse_button

        if mode == "mouse":
            button = MOUSE_BUTTONS.get(button_str, Button.left)
            mouse_controller.click(button)
        else:
            key = parse_key(input_key_str)
            if key is not None:
                keyboard_controller.press(key)
                keyboard_controller.release(key)

        time.sleep(max(interval, 0.001))

def on_press(key):
    k = key_to_str(key)
    if k is None:
        return

    with config_lock:
        start_key = config.start_key
        stop_key = config.stop_key
        mode = config.mode

    if k == start_key and not running.is_set():
        running.set()
        print(f"\n[매크로 시작] 모드={mode}  (중단하려면 '{stop_key}' 키)\nmacro> ", end="", flush=True)
    elif k == stop_key and running.is_set():
        running.clear()
        print(f"\n[매크로 중단]\nmacro> ", end="", flush=True)


def hotkey_listener():
    with keyboard.Listener(on_press=on_press) as listener:
        while not stop_program.is_set():
            time.sleep(0.2)
        listener.stop()


HELP_TEXT = """
사용 가능한 명령어
--------------------------------------------------------
  help                     이 도움말 표시
  status                   현재 설정 확인
  mode mouse               마우스 클릭 모드로 전환
  mode keyboard            키보드 입력 모드로 전환
  speed <초>               클릭/입력 간격 설정 (예: speed 0.05)
  startkey <키>            매크로 시작 단축키 설정 (예: startkey f6)
  stopkey <키>             매크로 중단 단축키 설정 (예: stopkey f7)
  key <키>                 키보드 모드에서 반복 입력할 키 설정 (예: key a)
  button <left|right|middle>  마우스 모드에서 클릭할 버튼 설정
  exit / quit              프로그램 종료
--------------------------------------------------------
* <키> 예시: a, b, 1, f1~f24, space, enter, esc, tab,
             up, down, left, right, shift, ctrl, alt 등
"""


def handle_command(line):
    parts = line.strip().split(maxsplit=1)
    if not parts:
        return
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd == "help":
        print(HELP_TEXT)

    elif cmd == "status":
        with config_lock:
            print(config.status_text())

    elif cmd == "mode":
        if arg in ("mouse", "keyboard"):
            with config_lock:
                config.mode = arg
            print(f"[설정 완료] 모드 -> {arg}")
        else:
            print("[오류] mode 뒤에는 mouse 또는 keyboard 를 입력하세요.")

    elif cmd == "speed":
        try:
            value = float(arg)
            if value <= 0:
                raise ValueError
            with config_lock:
                config.interval = value
            print(f"[설정 완료] 간격 -> {value}초")
        except ValueError:
            print("[오류] speed 뒤에는 0보다 큰 숫자를 입력하세요. (예: speed 0.1)")

    elif cmd == "startkey":
        if parse_key(arg) is None:
            print(f"[오류] '{arg}' 는 인식할 수 없는 키입니다.")
        else:
            with config_lock:
                config.start_key = arg.lower()
            print(f"[설정 완료] 시작 단축키 -> {arg.lower()}")
            _warn_if_conflict()

    elif cmd == "stopkey":
        if parse_key(arg) is None:
            print(f"[오류] '{arg}' 는 인식할 수 없는 키입니다.")
        else:
            with config_lock:
                config.stop_key = arg.lower()
            print(f"[설정 완료] 중단 단축키 -> {arg.lower()}")
            _warn_if_conflict()

    elif cmd == "key":
        if parse_key(arg) is None:
            print(f"[오류] '{arg}' 는 인식할 수 없는 키입니다.")
        else:
            with config_lock:
                config.input_key = arg.lower()
            print(f"[설정 완료] 키보드 입력 키 -> {arg.lower()}")
            _warn_if_conflict()

    elif cmd == "button":
        if arg in MOUSE_BUTTONS:
            with config_lock:
                config.mouse_button = arg
            print(f"[설정 완료] 마우스 버튼 -> {arg}")
        else:
            print("[오류] button 뒤에는 left, right, middle 중 하나를 입력하세요.")

    elif cmd in ("exit", "quit"):
        print("프로그램을 종료합니다...")
        stop_program.set()
        running.clear()

    else:
        print(f"[오류] 알 수 없는 명령어입니다: '{cmd}'  (help 입력 시 도움말 확인)")


def _warn_if_conflict():
    with config_lock:
        s, e, k, mode = config.start_key, config.stop_key, config.input_key, config.mode
    if s == e:
        print("[경고] 시작 단축키와 중단 단축키가 동일합니다. 서로 다르게 설정하세요.")
    if mode == "keyboard" and k in (s, e):
        print("[경고] 키보드 입력 키가 시작/중단 단축키와 같으면 매크로 동작 중\n"
              "       입력이 자동으로 시작/중단될 수 있습니다. 다른 키 사용을 권장합니다.")


def command_loop():
    print("=" * 56)
    print(" 자동 매크로 프로그램")
    print(f" 기본 단축키 : 시작={config.start_key} / 중단={config.stop_key}")
    print(" 'help' 입력 시 전체 명령어를 확인할 수 있습니다.")
    print("=" * 56)
    print(config.status_text())

    while not stop_program.is_set():
        try:
            line = input("macro> ")
        except (EOFError, KeyboardInterrupt):
            stop_program.set()
            running.clear()
            break
        handle_command(line)

def main():
    worker_thread = threading.Thread(target=macro_worker, daemon=True)
    listener_thread = threading.Thread(target=hotkey_listener, daemon=True)
    worker_thread.start()
    listener_thread.start()

    try:
        command_loop()
    finally:
        stop_program.set()
        running.clear()
        time.sleep(0.3)
        print("종료되었습니다.")


if __name__ == "__main__":
    main()