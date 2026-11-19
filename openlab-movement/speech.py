import platform
import queue
import shutil
import subprocess
import threading
import time
from datetime import datetime


class Voice:
    """Speaks on the computer that runs the game (or a speaker plugged into it).

    Uses the system text-to-speech: `say` on macOS, SAPI on Windows,
    espeak-ng / espeak / spd-say on Linux. say() never blocks the game.
    """

    def __init__(self, enabled=True, voice=None, rate=None, command=None, verbose=True):
        self.enabled = enabled
        self.verbose = verbose
        self._base = command or (self._system_command(voice, rate) if enabled else None)
        self._queue = queue.Queue()
        self._lock = threading.Lock()
        self._proc = None
        self._pending = 0
        if enabled and self._base is None:
            self._log("no text-to-speech found, phrases are only printed")
        threading.Thread(target=self._worker, daemon=True).start()

    @property
    def busy(self):
        return self._pending > 0

    def say(self, text, interrupt=False, skip_if_busy=False):
        with self._lock:
            speaking = self.enabled and self._base is not None
            if skip_if_busy and self._pending:
                return
            self._log(text)
            if not speaking:
                return
            if interrupt:
                self._stop_locked()
            self._pending += 1
            self._queue.put(text)

    def stop(self):
        with self._lock:
            self._stop_locked()

    def wait(self, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        while self._pending and (deadline is None or time.monotonic() < deadline):
            time.sleep(0.05)

    def _stop_locked(self):
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
            self._pending -= 1
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()

    def _worker(self):
        while True:
            text = self._queue.get()
            proc = None
            with self._lock:
                try:
                    proc = self._proc = subprocess.Popen(self._build(text), stdout=subprocess.DEVNULL,
                                                         stderr=subprocess.DEVNULL)
                except OSError as e:
                    self._log(f"text-to-speech failed: {e}")
            if proc is not None:
                proc.wait()
            with self._lock:
                self._proc = None
                self._pending = max(0, self._pending - 1)

    def _build(self, text):
        if self._base == "windows":
            text = text.replace("'", "''")
            return ["powershell", "-NoProfile", "-Command",
                    "Add-Type -AssemblyName System.Speech; "
                    f"(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('{text}')"]
        return [*self._base, text]

    @staticmethod
    def _system_command(voice, rate):
        system = platform.system()
        if system == "Darwin" and shutil.which("say"):
            cmd = ["say"]
            if voice is None:
                # English voice even if the Mac itself is set to another language
                voices = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
                voice = "Samantha" if "Samantha" in voices else None
            if voice:
                cmd += ["-v", voice]
            if rate:
                cmd += ["-r", str(rate)]
            return cmd
        if system == "Windows" and shutil.which("powershell"):
            return "windows"
        for name in ("espeak-ng", "espeak"):
            if shutil.which(name):
                cmd = [name]
                if voice:
                    cmd += ["-v", voice]
                if rate:
                    cmd += ["-s", str(rate)]
                return cmd
        if shutil.which("spd-say"):
            return ["spd-say", "--wait"]
        return None

    def _log(self, msg):
        if self.verbose:
            print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] [Voice] {msg}")
