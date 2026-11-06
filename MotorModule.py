import RPi.GPIO as GPIO
import time
from time import sleep
import config

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)


class Motor:
    """Tracao traseira (ponte H dupla) + direcao por servo."""

    def __init__(self, EnaA, In1A, In2A, EnaB, In1B, In2B, servoPin):
        self.EnaA, self.In1A, self.In2A = EnaA, In1A, In2A
        self.EnaB, self.In1B, self.In2B = EnaB, In1B, In2B

        for pin in (EnaA, In1A, In2A, EnaB, In1B, In2B, servoPin):
            GPIO.setup(pin, GPIO.OUT)

        self.pwmA = GPIO.PWM(self.EnaA, 100)
        self.pwmB = GPIO.PWM(self.EnaB, 100)
        self.pwmA.start(0)
        self.pwmB.start(0)

        self.servoPin = servoPin
        self.pwmServo = GPIO.PWM(self.servoPin, 50)
        self.pwmServo.start(0)

        self._parado = True         # True ate o primeiro comando de velocidade > 0
        self._kick_ate = 0.0        # instante em que o chute de partida acaba

        self._last_angle = None
        self.set_servo_angle(config.SERVO_CENTRO)

    # ---------------- SERVO ----------------
    def set_servo_angle(self, angle):
        angle = max(config.SERVO_MAX_ESQ, min(config.SERVO_MAX_DIR, angle))
        # so reescreve o duty se mudou de verdade -> mata o tremor do servo
        if self._last_angle is not None and \
           abs(angle - self._last_angle) < config.SERVO_DEADBAND_DEG:
            return
        self._last_angle = angle
        duty = (angle / 18.0) + 2.5
        self.pwmServo.ChangeDutyCycle(duty)

    def turn_to(self, turn):
        """turn em -1 (esquerda total) .. +1 (direita total)."""
        turn = max(-1.0, min(1.0, turn))
        if turn < 0:
            amplitude = config.SERVO_CENTRO - config.SERVO_MAX_ESQ
        else:
            amplitude = config.SERVO_MAX_DIR - config.SERVO_CENTRO
        self.set_servo_angle(config.SERVO_CENTRO + turn * amplitude)

    # ---------------- TRACAO ----------------
    @staticmethod
    def _duty(mag, min_duty, fator):
        """mag 0..1 -> duty% remapeado pra pular a zona morta do motor."""
        if mag <= 0.0:
            return 0.0
        d = min_duty + mag * (1.0 - min_duty)
        return max(0.0, min(100.0, d * fator * 100.0))

    def drive(self, speed):
        """speed em -1 .. +1."""
        speed = max(-1.0, min(1.0, speed))
        forward = speed >= 0
        mag = abs(speed)

        # chute de partida (nao bloqueante): ao sair do repouso, segura duty
        # alto por MOTOR_KICK_S; depois cai pro valor pedido.
        agora = time.time()
        if mag > 0.0:
            if self._parado and config.MOTOR_KICK_S > 0:
                self._kick_ate = agora + config.MOTOR_KICK_S
            self._parado = False
        else:
            self._parado = True

        duty_a = self._duty(mag, config.MOTOR_MIN_DUTY_A, config.MOTOR_FATOR_A)
        duty_b = self._duty(mag, config.MOTOR_MIN_DUTY_B, config.MOTOR_FATOR_B)
        if mag > 0.0 and agora < self._kick_ate:
            kick = config.MOTOR_KICK_DUTY * 100.0
            duty_a = max(duty_a, kick)
            duty_b = max(duty_b, kick)

        GPIO.output(self.In1A, GPIO.HIGH if forward else GPIO.LOW)
        GPIO.output(self.In2A, GPIO.LOW if forward else GPIO.HIGH)
        GPIO.output(self.In1B, GPIO.HIGH if forward else GPIO.LOW)
        GPIO.output(self.In2B, GPIO.LOW if forward else GPIO.HIGH)
        self.pwmA.ChangeDutyCycle(duty_a)
        self.pwmB.ChangeDutyCycle(duty_b)

    def move(self, speed=0.5, turn=0.0, t=0):
        self.turn_to(turn)
        self.drive(speed)
        if t:
            sleep(t)

    def stop(self, t=0):
        self._parado = True
        self.pwmA.ChangeDutyCycle(0)
        self.pwmB.ChangeDutyCycle(0)
        self.set_servo_angle(config.SERVO_CENTRO)
        if t:
            sleep(t)

    def cleanup(self):
        self.stop()
        sleep(0.2)
        self.pwmA.stop(); self.pwmB.stop(); self.pwmServo.stop()
        GPIO.cleanup()
