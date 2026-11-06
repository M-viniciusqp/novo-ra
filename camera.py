"""
camera.py - captura em thread separada.

Por que existe: no loop antigo, cap.read() bloqueava o programa inteiro
esperando o proximo frame (24-68ms por frame no log real) e, enquanto a
visao rodava, a camera ficava com frames velhos enfileirados no driver.
Aqui uma thread le a camera o tempo todo e guarda SO o frame mais novo;
o loop principal pega esse frame e processa em paralelo com a proxima
captura. O decode do MJPG e a espera da camera soltam o GIL, entao
captura e visao realmente andam juntas.
"""

import shutil
import subprocess
import threading
import time

import cv2

import config


def aplicar_controles_v4l2(dispositivo="/dev/video0"):
    """Aplica config.CAMERA_V4L2_CTRLS com v4l2-ctl. Nunca derruba o programa."""
    ctrls = getattr(config, "CAMERA_V4L2_CTRLS", [])
    if not ctrls:
        return
    if shutil.which("v4l2-ctl") is None:
        print("AVISO: v4l2-ctl nao encontrado (sudo apt install v4l-utils); "
              "controles de camera nao aplicados.")
        return
    for c in ctrls:
        try:
            r = subprocess.run(["v4l2-ctl", "-d", dispositivo, "-c", c],
                               capture_output=True, text=True, timeout=3)
            if r.returncode == 0:
                print(f"Camera: controle '{c}' aplicado.")
            else:
                print(f"AVISO: camera nao aceitou '{c}': "
                      f"{(r.stderr or r.stdout).strip()}")
        except Exception as e:           # timeout, permissao, etc
            print(f"AVISO: falhou aplicar '{c}': {e}")


def abrir_camera():
    aplicar_controles_v4l2()
    cap = cv2.VideoCapture(0, cv2.CAP_V4L2)

    # MJPG chega comprimido: ate 5-10x mais rapido que YUYV em USB.
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.CAMERA_RES[0])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.CAMERA_RES[1])
    cap.set(cv2.CAP_PROP_FPS, 30)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
    fourcc_str = "".join([chr((fourcc >> 8 * i) & 0xFF) for i in range(4)])
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    print(f"Camera aberta: {w}x{h} @ {fps:.0f}fps pedido, formato={fourcc_str}")
    if (w, h) != tuple(config.CAMERA_RES):
        print(f"AVISO: pedi {config.CAMERA_RES[0]}x{config.CAMERA_RES[1]} e a "
              f"camera entregou {w}x{h}; o frame e esticado pra "
              f"{config.CAMERA_RES[0]}x{config.CAMERA_RES[1]} no codigo. Se "
              f"ela so faz {w}x{h}, ponha isso em CAMERA_RES (e reajuste os "
              f"limites em pixel).")
    if fourcc_str.strip() != "MJPG":
        print("AVISO: a camera NAO aceitou MJPG. Rode "
              "'v4l2-ctl --list-formats-ext -d /dev/video0' pra ver o que ela suporta.")
    return cap


class CameraThread:
    """Le a camera numa thread e entrega sempre o frame mais recente."""

    def __init__(self):
        self.cap = abrir_camera()
        self._lock = threading.Lock()
        self._frame = None
        self._seq = 0              # numero do ultimo frame guardado
        self._seq_entregue = 0     # numero do ultimo frame entregue
        self._rodando = False
        self._thread = None
        self.falhas = 0            # leituras que falharam (diagnostico)

    def isOpened(self):
        return self.cap.isOpened()

    def start(self):
        self._rodando = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def _loop(self):
        while self._rodando:
            ok, frame = self.cap.read()
            if not ok:
                self.falhas += 1
                time.sleep(0.01)
                continue
            with self._lock:
                self._frame = frame
                self._seq += 1

    def read(self, timeout=0.5):
        """Bloqueia ate chegar um frame NOVO (nunca reentrega o mesmo).

        Retorna (ok, frame).
        """
        t0 = time.time()
        while time.time() - t0 < timeout:
            with self._lock:
                if self._seq != self._seq_entregue and self._frame is not None:
                    self._seq_entregue = self._seq
                    return True, self._frame
            time.sleep(0.001)
        return False, None

    def release(self):
        self._rodando = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self.cap.release()
