"""
teste_motores.py - acha a ZONA MORTA de cada motor (duty em que ele comeca a girar).

    python3 teste_motores.py

CUIDADO: as rodas TRASEIRAS GIRAM. Deixe o carro LEVANTADO (rodas no ar) ou
segure firme. Mantenha o dedo no Ctrl+C.

Como funciona: pra cada motor, sobe o duty de 10% a 100% em degraus de 5%.
Entre um degrau e outro o motor e FREADO e fica parado -- assim cada degrau
e uma PARTIDA de verdade (e e na partida que o atrito parado pega). Observe o
motor e anote em que % a roda comeca a girar sozinha. No fim, digite os dois
valores e o script imprime as linhas pra colar no config.py.
"""

import time
import RPi.GPIO as GPIO
from MotorModule import Motor
import config

PASSO = 5
TEMPO_ON = 1.0
TEMPO_OFF = 0.6
TEMPO_FREIO = 0.4


def frear(m):
    """Freio ATIVO da ponte H (IN1 = IN2, com ENABLE ligado), depois solta.

    Sem isso um motor leve (inercia alta) continua rodando de graca durante
    a pausa e o degrau seguinte nao e uma partida de verdade -- foi o que
    aconteceu na 1a versao: o A nunca parava, so o B (mais preso) parava.
    """
    for p in (m.In1A, m.In2A, m.In1B, m.In2B):
        GPIO.output(p, GPIO.HIGH)
    m.pwmA.ChangeDutyCycle(100)
    m.pwmB.ChangeDutyCycle(100)
    time.sleep(TEMPO_FREIO)
    m.drive(0.0)             # duty 0 e sentido pra frente de novo


def varrer(nome, pwm, parar):
    print(f"\n=== Motor {nome} === (anote a % em que a roda COMECA a girar)")
    time.sleep(1.0)
    for duty in range(10, 101, PASSO):
        print(f"  {nome}: {duty:3d}%", flush=True)
        pwm.ChangeDutyCycle(duty)
        time.sleep(TEMPO_ON)
        parar()
        time.sleep(TEMPO_OFF)


def main():
    m = Motor(config.ENA_A, config.IN1_A, config.IN2_A,
              config.ENA_B, config.IN3_B, config.IN4_B,
              config.SERVO_PIN)
    try:
        m.drive(0.0)            # so ajusta o sentido pra frente, duty 0
        parar = lambda: frear(m)
        varrer("A", m.pwmA, parar)
        varrer("B", m.pwmB, parar)

        print("\nEm que % o motor A comecou a girar? (Enter = nao girou/nao sei)")
        a = input("  A: ").strip()
        print("Em que % o motor B comecou a girar?")
        b = input("  B: ").strip()
        print("\nCole no config.py (uns 3 pontos acima do valor anotado, pra girar com folga):")
        for nome, v in (("A", a), ("B", b)):
            if v.isdigit():
                print(f"MOTOR_MIN_DUTY_{nome} = {min(1.0, (int(v) + 3) / 100):.2f}")
    except KeyboardInterrupt:
        print("\nInterrompido.")
    finally:
        m.cleanup()


if __name__ == '__main__':
    main()
