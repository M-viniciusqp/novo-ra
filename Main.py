"""
main.py - loop principal do piloto autonomo.

Roda: python3 main.py
Sai:  tecla 'q' na janela, ou Ctrl+C

Responsabilidade deste arquivo: SO orquestrar.
Ele nao sabe processar imagem (isso e do vision.py), nao sabe calcular
correcao (controller.py), nao sabe falar com GPIO (MotorModule.py) e nao
sabe abrir camera (camera.py).
"""

import time
import cv2

import config
from camera import CameraThread
from vision import LaneVision
from controller import SteeringPID, speed_for
from MotorModule import Motor

DEBUG = False          # desligado = mais FPS = reacao mais rapida
JANELA_S = 2.0         # janela da telemetria


class Janela:
    """Estatisticas da janela de telemetria.

    O log antigo imprimia so o ULTIMO frame de cada 2s -- um instantaneo que
    nao diz se o carro esta firme ou zigue-zagueando. Aqui acumula a janela
    inteira, pra comparar uma corrida com a outra com numeros.
    """

    def __init__(self):
        self.zerar()

    def zerar(self):
        self.n = 0
        self.n_ok = 0
        self.soma_abs_erro = 0.0
        self.max_abs_erro = 0.0
        self.n_freio_fps = 0
        self.soma_speed = 0.0
        self.trocas_turn = 0          # inversoes de sinal do volante (zigue-zague)
        self._turn_ant = 0.0
        self.t_cam = self.t_vis = self.t_mot = 0.0
        self.pior_frame = 0.0         # maior tempo de um ciclo completo (s)

    def add(self, res, ok, turn, speed, freio_fps, t_cam, t_vis, t_mot, ciclo):
        self.n += 1
        self.n_ok += 1 if ok else 0
        a = abs(res.error)
        self.soma_abs_erro += a
        self.max_abs_erro = max(self.max_abs_erro, a)
        self.n_freio_fps += 1 if freio_fps else 0
        self.soma_speed += speed
        # so conta inversao quando o volante realmente se mexeu pros dois lados
        if abs(turn) > 0.10:
            if self._turn_ant * turn < 0:
                self.trocas_turn += 1
            self._turn_ant = turn
        self.t_cam += t_cam
        self.t_vis += t_vis
        self.t_mot += t_mot
        self.pior_frame = max(self.pior_frame, ciclo)


def main():
    print("Piloto autonomo: navegando ENTRE as faixas.")

    cam = CameraThread()
    if not cam.isOpened():
        print("Erro critico: camera nao abriu.")
        return
    cam.start()

    vision = LaneVision()
    pid = SteeringPID()
    motor = Motor(config.ENA_A, config.IN1_A, config.IN2_A,
                  config.ENA_B, config.IN3_B, config.IN4_B,
                  config.SERVO_PIN)

    jan = Janela()
    t_jan = time.time()
    t_ciclo = time.time()
    turn = 0.0
    speed = 0.0
    fps_medido = 30.0              # otimista ate a 1a medicao real
    frame_anterior_confiavel = True

    try:
        while True:
            t0 = time.time()
            ok, frame = cam.read()
            t1 = time.time()
            if not ok:
                motor.stop()
                print("Sem frame novo da camera (checa a alimentacao do Pi).")
                continue

            if frame.shape[1] != config.CAMERA_RES[0] or frame.shape[0] != config.CAMERA_RES[1]:
                frame = cv2.resize(frame, config.CAMERA_RES)
            res = vision.process(frame, debug=DEBUG)
            t2 = time.time()

            # ---------- maquina de estados ----------
            # IMPORTANTE: checa res.motivo=="ok", nao so res.valid.
            # res.valid fica True durante o "periodo de graca" mesmo em
            # frames de baixa confianca (ex: poucos_pontos), onde o erro
            # fica CONGELADO no ultimo valor bom. Se o PID rodar em cima
            # desse erro congelado e depois um frame fresco chegar com erro
            # bem diferente, o termo D ve isso como um salto violento e
            # dispara um esterco que nao tem nada a ver com a pista real.
            # Por isso, so roda o PID com leitura fresca de verdade.
            fresco = (res.valid and res.motivo == "ok" and
                      (res.found_left or res.found_right))
            freio_fps = False
            if fresco:
                if not frame_anterior_confiavel:
                    pid.marcar_retomada()   # evita o chute do D nesta transicao
                frame_anterior_confiavel = True

                turn = pid.update(res.error, res.heading)
                speed = speed_for(turn, res.curvature)

                # TRAVA DE SEGURANCA: se o FPS medido estiver abaixo do minimo
                # seguro pra velocidade configurada, o codigo reduz sozinho.
                if fps_medido < config.FPS_MINIMO_SEGURO:
                    freio_fps = True
                    fator_freio = max(0.35, fps_medido / config.FPS_MINIMO_SEGURO)
                    speed *= fator_freio
            elif vision.lost_frames <= config.MAX_FRAMES_PERDIDO:
                # perdeu agora (ou leitura degradada): NAO congela o esterco
                # velho (isso trava o carro numa curva errada). Decai em
                # direcao ao reto, bem devagar.
                frame_anterior_confiavel = False
                turn *= 0.85
                speed = config.VELOCIDADE_PERDIDO
            else:
                turn, speed = 0.0, 0.0
                pid.reset()

            motor.move(speed, turn)
            t3 = time.time()

            jan.add(res, fresco, turn, speed, freio_fps,
                    t1 - t0, t2 - t1, t3 - t2, t3 - t_ciclo)
            t_ciclo = t3

            # ---------- telemetria ----------
            agora = time.time()
            if agora - t_jan >= JANELA_S:
                dt = agora - t_jan
                fps_medido = jan.n / dt
                n = max(1, jan.n)

                # status honesto: "OK" so quando a leitura E fresca de verdade.
                if res.motivo == "ok":
                    status = "OK"
                elif res.valid:
                    status = f"DEGRADADO({res.motivo})"
                else:
                    status = f"PERDIDO({res.motivo})"
                lado = res.lado_continuo or "?"
                trava = "TRAVADO" if res.travado else "livre"

                print(f"FPS {fps_medido:.1f} (pior ciclo {1000*jan.pior_frame:.0f}ms) | "
                      f"leitura OK {100*jan.n_ok/n:.0f}% | "
                      f"|erro| medio {jan.soma_abs_erro/n:.2f} max {jan.max_abs_erro:.2f} | "
                      f"zigue-zague {jan.trocas_turn/dt:.1f}/s | "
                      f"vel media {jan.soma_speed/n:.2f} | "
                      f"freio-FPS {100*jan.n_freio_fps/n:.0f}%")
                print(f"  agora -> erro {res.error:+.2f} turn {turn:+.2f} pts {res.n_pontos} "
                      f"| {status}")
                print(f"  termos -> P {pid.last_p:+.2f}  I {pid.last_i:+.2f}  "
                      f"D {pid.last_d:+.2f}  FF {pid.last_ff:+.2f}")
                print(f"  lado -> continua={lado} ({trava}) taxa E {res.taxa_e:.2f} "
                      f"D {res.taxa_d:.2f} vies {res.sinal:+.2f}")
                print(f"  gargalo -> camera(espera) {1000*jan.t_cam/n:.0f}ms  "
                      f"visao {1000*jan.t_vis/n:.0f}ms  motor {1000*jan.t_mot/n:.0f}ms  "
                      f"(por frame)")
                jan.zerar()
                t_jan = time.time()

            if DEBUG and res.debug_view is not None:
                cv2.imshow("Visao", res.debug_view)
                cv2.imshow("Mascara", res.debug_mask)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break

    except KeyboardInterrupt:
        print("\nParada de emergencia.")
    finally:
        motor.cleanup()
        cam.release()
        cv2.destroyAllWindows()
        print("Desligado com seguranca.")


if __name__ == '__main__':
    main()
