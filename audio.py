"""
RTP audio handler: envía y recibe audio G.711 PCMU/PCMA sobre UDP.
Usa sounddevice para micrófono y altavoz.
"""
import socket
import struct
import threading
import audioop
import logging
import random
import collections
from typing import Optional

import sounddevice as sd
import numpy as np

logger = logging.getLogger(__name__)

SAMPLE_RATE = 8000
CHUNK_SAMPLES = 160       # 20 ms a 8 kHz
CHUNK_BYTES = CHUNK_SAMPLES * 2  # int16 → 2 bytes por muestra
JITTER_BUFFER_MAX = 12    # máx frames en buffer (~240 ms)

PAYLOAD_PCMU = 0
PAYLOAD_PCMA = 8


class RTPAudio:
    def __init__(self, local_port: int = 10000):
        self._local_port = local_port
        self._remote_ip: Optional[str] = None
        self._remote_port: Optional[int] = None
        self._payload_type: int = PAYLOAD_PCMU
        self._sock: Optional[socket.socket] = None
        self._running = False
        self._seq = random.randint(0, 0xFFFF)
        self._timestamp = random.randint(0, 0xFFFFFFFF)
        self._ssrc = random.randint(0, 0xFFFFFFFF)
        self._jitter: collections.deque = collections.deque(maxlen=JITTER_BUFFER_MAX)
        self._recv_thread: Optional[threading.Thread] = None
        self._stream: Optional[sd.Stream] = None

    @property
    def local_port(self) -> int:
        return self._local_port

    def start(self, remote_ip: str, remote_port: int, payload_type: int = PAYLOAD_PCMU):
        self._remote_ip = remote_ip
        self._remote_port = remote_port
        self._payload_type = payload_type
        self._running = True

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(("", self._local_port))
        self._sock.settimeout(0.1)

        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True, name="rtp-recv")
        self._recv_thread.start()

        self._stream = sd.Stream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=CHUNK_SAMPLES,
            callback=self._audio_callback,
        )
        self._stream.start()
        logger.info(f"Audio RTP: local :{self._local_port} → {remote_ip}:{remote_port} PT={payload_type}")

    def stop(self):
        self._running = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        logger.info("Audio RTP detenido")

    # ─── Audio callback (hilo de sounddevice) ───────────────────────────────────

    def _audio_callback(self, indata: np.ndarray, outdata: np.ndarray, frames, time_info, status):
        # Reproducción: extraer frame del jitter buffer
        if self._jitter:
            pcm = self._jitter.popleft()
            arr = np.frombuffer(pcm, dtype="int16")
            if len(arr) < frames:
                arr = np.concatenate([arr, np.zeros(frames - len(arr), dtype="int16")])
            outdata[:] = arr[:frames].reshape(-1, 1)
        else:
            outdata.fill(0)

        # Captura: micrófono → codificar → enviar RTP
        mic_pcm = indata.tobytes()
        if self._payload_type == PAYLOAD_PCMU:
            encoded = audioop.lin2ulaw(mic_pcm, 2)
        elif self._payload_type == PAYLOAD_PCMA:
            encoded = audioop.lin2alaw(mic_pcm, 2)
        else:
            encoded = mic_pcm
        self._send_rtp(encoded)

    # ─── Recepción RTP ──────────────────────────────────────────────────────────

    def _recv_loop(self):
        while self._running:
            try:
                data, _ = self._sock.recvfrom(2048)
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    logger.error(f"RTP recv: {e}")
                break

            if len(data) < 12:
                continue

            pt = data[1] & 0x7F
            payload = data[12:]

            try:
                if pt == PAYLOAD_PCMU:
                    pcm = audioop.ulaw2lin(payload, 2)
                elif pt == PAYLOAD_PCMA:
                    pcm = audioop.alaw2lin(payload, 2)
                else:
                    pcm = payload
            except Exception:
                continue

            self._jitter.append(pcm)

    # ─── Envío RTP ──────────────────────────────────────────────────────────────

    def _send_rtp(self, payload: bytes):
        if not self._sock or not self._remote_ip:
            return
        header = struct.pack(
            "!BBHII",
            0x80,
            self._payload_type & 0x7F,
            self._seq & 0xFFFF,
            self._timestamp & 0xFFFFFFFF,
            self._ssrc,
        )
        self._seq = (self._seq + 1) & 0xFFFF
        self._timestamp = (self._timestamp + CHUNK_SAMPLES) & 0xFFFFFFFF
        try:
            self._sock.sendto(header + payload, (self._remote_ip, self._remote_port))
        except Exception as e:
            if self._running:
                logger.debug(f"RTP send: {e}")
