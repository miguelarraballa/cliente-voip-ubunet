"""
Wrapper sobre pyVoIP que gestiona registro SIP, llamadas salientes y entrantes.
Expone callbacks thread-safe para la UI.
"""
import struct
import threading
import logging
import traceback
import socket
import time
from enum import Enum, auto
from typing import Optional, Callable

import pyVoIP

import config
from audio import RTPAudio


def _local_ip() -> str:
    """Obtiene la IP local real (no loopback) mirando hacia el servidor SIP."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((config.SIP_SERVER, config.SIP_PORT))
        return s.getsockname()[0]
    except Exception:
        return "0.0.0.0"
    finally:
        s.close()

logger = logging.getLogger(__name__)

from pyVoIP.VoIP import VoIPPhone, CallState, InvalidStateError
from pyVoIP.VoIP import VoIPCall
from pyVoIP.SIP import InvalidAccountInfoError, SIPMessage, SIPParseError, SIPStatus
import pyVoIP.SIP as _pv_sip

try:
    from pyVoIP.SIP import RetryRequiredError
except ImportError:
    RetryRequiredError = RuntimeError

# ── Parches a pyVoIP ──────────────────────────────────────────────────────────

# Dict global: call_id → callable(status_code: int) para supervisar REFER/NOTIFY
_refer_callbacks: dict = {}

# 1) parse_message: responde a OPTIONS + termina llamadas en 4xx/5xx no manejados.
#    pyVoIP ignora OPTIONS con un "TODO: Add 400 Error" y no responde.
#    Además, solo maneja 200/404/503 como respuestas a INVITE; 488 y otros
#    errores dejan la llamada bloqueada en DIALING indefinidamente.
_orig_parse_message = _pv_sip.SIPClient.parse_message

def _patched_parse_message(self, message):
    if (message.type == _pv_sip.SIPMessageType.MESSAGE
            and message.method == "OPTIONS"):
        ok = self.gen_ok(message)
        self.out.sendto(ok.encode("utf8"), (self.server, self.port))
        return

    # NOTIFY para supervisión de transferencias (REFER)
    if (message.type == _pv_sip.SIPMessageType.MESSAGE
            and message.method == "NOTIFY"):
        event = str(message.headers.get("Event", "")).lower()
        if "refer" in event:
            try:
                ok = self.gen_ok(message)
                self.out.sendto(ok.encode("utf8"), (self.server, self.port))
            except Exception as _ne:
                logger.debug(f"Error respondiendo NOTIFY refer: {_ne}")
            call_id = message.headers.get("Call-ID", "")
            try:
                raw_body = getattr(message, "body", None) or b""
                body = raw_body.decode("utf-8", errors="replace") if isinstance(raw_body, bytes) else str(raw_body)
            except Exception:
                body = ""
            import re as _re_n
            m = _re_n.search(r"SIP/2\.0\s+(\d+)", body)
            if m:
                code = int(m.group(1))
                logger.info(f"NOTIFY refer: Call-ID={call_id} status={code}")
                cb = _refer_callbacks.get(call_id)
                if cb:
                    cb(code)
            return

    status = getattr(message, "status", None)
    method = getattr(message, "method", None)
    logger.info(f"parse_message recibido: method={method} status={status}")

    # pyVoIP solo maneja 200/404/503 como respuestas; cualquier otro 4xx/5xx
    # (p.ej. 488 Not Acceptable, 486 Busy, 403 Forbidden) cae en un TODO y
    # la llamada queda bloqueada en DIALING indefinidamente.
    if (message.type != _pv_sip.SIPMessageType.MESSAGE
            and status is not None
            and hasattr(status, "value")
            and status.value >= 400
            and status not in (_pv_sip.SIPStatus(404), _pv_sip.SIPStatus(503))):
        call_id = message.headers.get("Call-ID", "")
        if call_id and callable(self.callCallback) and hasattr(self.callCallback, "__self__"):
            phone = self.callCallback.__self__
            call = phone.calls.get(call_id)
            if call and call.state != CallState.ENDED:
                logger.info(f"Terminando llamada por {status} — enviando ACK")
                try:
                    ack = self.gen_ack(message)
                    self.out.sendto(ack.encode("utf8"), (self.server, self.port))
                except Exception as e:
                    logger.debug(f"ACK al error fallido: {e}")
                call.state = CallState.ENDED
                phone.calls.pop(call_id, None)

    _orig_parse_message(self, message)

_pv_sip.SIPClient.parse_message = _patched_parse_message


# 2b) VoIPPhone.call(): pyVoIP solo ofrece PCMU en el SDP.
#     Ubutel/PekePBX (España) requiere PCMA (G.711 A-law, payload 8).
#     Añadimos PCMA para que la negociación de codecs tenga éxito.
import pyVoIP.RTP as _pv_rtp

_orig_phone_call = VoIPPhone.call

def _patched_phone_call(self, number: str) -> VoIPCall:
    port = self.request_port()
    medias = {port: {
        0: _pv_rtp.PayloadType.PCMU,
        8: _pv_rtp.PayloadType.PCMA,
        101: _pv_rtp.PayloadType.EVENT,
    }}
    request, call_id, sess_id = self.sip.invite(
        number, medias, _pv_rtp.TransmitType.SENDRECV
    )
    self.calls[call_id] = VoIPCall(
        self, CallState.DIALING, request, sess_id, self.myIP,
        ms=medias, sendmode=self.sendmode,
    )
    return self.calls[call_id]

VoIPPhone.call = _patched_phone_call


# 2) invite(): el servidor PekePBX envía OPTIONS (keep-alive) mientras espera
#    la respuesta al INVITE. pyVoIP original hace recv() sin filtrar y explota
#    con SIPParseError al recibir un request en lugar de una response.
#    Este parche salta los requests intercalados respondiéndoles con 200 OK.
INVITE_RESPONSE_TIMEOUT = 30


def _respond_options_raw(sip_self, raw: bytes):
    """Responde a un OPTIONS sin usar SIPMessage (pyVoIP no puede parsear OPTIONS)."""
    import re as _re
    try:
        text = raw.decode("utf-8", errors="replace")
        def _h(name):
            m = _re.search(rf"^{name}:\s*(.+)$", text, _re.MULTILINE | _re.IGNORECASE)
            return m.group(1).strip() if m else ""
        resp = (
            "SIP/2.0 200 OK\r\n"
            f"Via: {_h('Via')}\r\n"
            f"From: {_h('From')}\r\n"
            f"To: {_h('To')}\r\n"
            f"Call-ID: {_h('Call-ID')}\r\n"
            f"CSeq: {_h('CSeq')}\r\n"
            "Allow: INVITE, ACK, BYE, CANCEL, OPTIONS\r\n"
            "Content-Length: 0\r\n\r\n"
        )
        sip_self.out.sendto(resp.encode("utf-8"), (sip_self.server, sip_self.port))
        logger.info("OPTIONS respondido con 200 OK")
    except Exception as e:
        logger.debug(f"Error respondiendo OPTIONS: {e}")


def _recv_sip_response(sip_self):
    """Lee del socket esperando una SIP response, saltando requests intercalados.
    Responde a OPTIONS (pyVoIP no puede parsear OPTIONS via SIPMessage).
    Lanza TimeoutError si no llega respuesta en INVITE_RESPONSE_TIMEOUT segundos."""
    sip_self.s.settimeout(INVITE_RESPONSE_TIMEOUT)
    try:
        while True:
            try:
                raw = sip_self.s.recv(8192)
            except socket.timeout:
                raise TimeoutError(
                    f"Sin respuesta del servidor tras {INVITE_RESPONSE_TIMEOUT}s"
                )
            # OPTIONS no puede parsearse con SIPMessage → manejar a mano
            if raw.lstrip().upper().startswith(b"OPTIONS "):
                _respond_options_raw(sip_self, raw)
                continue
            try:
                msg = SIPMessage(raw)
            except Exception as e:
                logger.warning(f"Mensaje no parseado: {e} | raw={raw[:60]}")
                continue
            if msg.type == _pv_sip.SIPMessageType.MESSAGE:
                logger.info(f"Request intercalado ({msg.method}) — 200 OK")
                try:
                    ok = sip_self.gen_ok(msg)
                    sip_self.out.sendto(ok.encode("utf8"), (sip_self.server, sip_self.port))
                except Exception:
                    pass
                continue
            logger.debug(f"Response recibida: {msg.status}")
            return msg
    finally:
        sip_self.s.settimeout(None)


def _patched_invite(self, number, ms, sendtype):
    branch = "z9hG4bK" + self.gen_call_id()[0:25]
    call_id = self.gen_call_id()
    sess_id = self.sessID.next()
    invite_str = self.gen_invite(number, str(sess_id), ms, sendtype, branch, call_id)

    with self.recvLock:
        logger.info(f"Enviando INVITE → sip:{number}@{self.server}")
        self.out.sendto(invite_str.encode("utf8"), (self.server, self.port))
        response = _recv_sip_response(self)
        logger.info(f"INVITE respuesta inicial: {response.status}")

        # Salir del loop en 401 (auth), 407 (proxy auth), 100 Trying, 180 Ringing
        while (
            response.status != SIPStatus(401)
            and response.status != SIPStatus(407)
            and response.status != SIPStatus(100)
            and response.status != SIPStatus(180)
        ) or response.headers["Call-ID"] != call_id:
            if not self.NSD:
                break
            logger.info(f"INVITE respuesta intermedia ignorada: {response.status}")
            self.parse_message(response)
            response = _recv_sip_response(self)
            logger.info(f"INVITE siguiente respuesta: {response.status}")

        if response.status in (SIPStatus(100), SIPStatus(180)):
            logger.info(f"INVITE aceptado con {response.status} — esperando 200 OK")
            return SIPMessage(invite_str.encode("utf8")), call_id, sess_id

        # Autenticación (401 WWW-Authenticate o 407 Proxy-Authenticate)
        ack = self.gen_ack(response)
        self.out.sendto(ack.encode("utf8"), (self.server, self.port))

        import re as _re, hashlib as _hs
        raw_resp = str(response.raw, "utf-8", errors="replace")
        try:
            nonce = response.authentication["nonce"]
            realm = response.authentication["realm"]
        except (KeyError, AttributeError, TypeError):
            nonce = _re.search(r'nonce="([^"]+)"', raw_resp).group(1)
            realm = _re.search(r'realm="([^"]+)"', raw_resp).group(1)

        # RFC 3261 §22.4: la uri del Digest DEBE ser la Request-URI del INVITE
        request_uri = f"sip:{number}@{self.server}"
        ha1 = _hs.md5(f"{self.username}:{realm}:{self.password}".encode()).hexdigest()
        ha2 = _hs.md5(f"INVITE:{request_uri}".encode()).hexdigest()
        response_hash = _hs.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()
        logger.debug(f"Auth: realm={realm} nonce={nonce} uri={request_uri} ha1={ha1[:8]}… response={response_hash[:8]}…")

        # 407 → Proxy-Authorization ; 401 → Authorization
        header_name = "Proxy-Authorization" if response.status == SIPStatus(407) else "Authorization"
        auth = (
            f'{header_name}: Digest username="{self.username}",realm="{realm}",'
            f'nonce="{nonce}",uri="{request_uri}",response="{response_hash}",'
            "algorithm=MD5\r\n"
        )
        invite_str = self.gen_invite(number, str(sess_id), ms, sendtype, branch, call_id)
        invite_str = invite_str.replace("\r\nContent-Length", f"\r\n{auth}Content-Length")
        logger.info(f"Enviando INVITE con auth ({header_name}) → sip:{number}@{self.server}")
        self.out.sendto(invite_str.encode("utf8"), (self.server, self.port))
        auth_response = _recv_sip_response(self)
        logger.info(f"INVITE auth respuesta: {auth_response.status}")
        if auth_response.status.value >= 400:
            logger.error(f"INVITE rechazado por el servidor: {auth_response.status}")
            raise Exception(f"INVITE rechazado: {auth_response.status}")
        return SIPMessage(invite_str.encode("utf8")), call_id, sess_id

_pv_sip.SIPClient.invite = _patched_invite


# 3) gen_ack: pyVoIP genera un tag aleatorio nuevo en el header To del ACK,
#    ignorando el tag que el servidor envió en el 200 OK. El servidor no
#    reconoce el diálogo → nunca acepta el ACK → retransmite el 200 OK →
#    agota el timer y envía BYE ~6s después.
#    Fix: usar los headers To/From tal como vienen en la respuesta (ya tienen
#    los tags correctos).
_orig_gen_ack = _pv_sip.SIPClient.gen_ack

def _patched_gen_ack(self, request):
    import pyVoIP as _pv
    import re as _re
    tag = self.tagLibrary.get(request.headers["Call-ID"], "")

    def _extract_uri(raw) -> str:
        if isinstance(raw, dict):
            raw = raw.get("raw", "")
        elif isinstance(raw, list):
            raw = raw[0].get("raw", "") if raw else ""
        m = _re.search(r"<([^>]+)>", str(raw))
        return m.group(1) if m else str(raw)

    # RFC 3261 §12.2.1.1: si hay Record-Route en el 200 OK, el ACK debe
    # incluir esos valores como Route (loose routing).
    # El proxy (192.168.255.254) no es alcanzable desde fuera, pero el ACK
    # se envía a ubcloud02.ubutel.eu:5060 que reconoce su propia IP interna
    # en el Route y reenvía el ACK al B2BUA interno (192.168.255.254:5062).
    # Sin el Route header, el proxy recibe el ACK pero no lo reenvía → BYE.
    record_route = request.headers.get("Record-Route")
    if record_route:
        # Con Record-Route + loose routing: Request-URI = Contact (destino final)
        contact = request.headers.get("Contact")
        request_uri = _extract_uri(contact) if contact else request.headers["To"]["raw"].strip("<").strip(">")
        route_header = f"Route: {record_route}\r\n"
    else:
        # Sin Record-Route: usar To URI como antes
        request_uri = request.headers["To"]["raw"].strip("<").strip(">")
        route_header = ""

    # Via: branch nuevo para ACK de 2xx (nueva transacción, RFC 3261 §13.2.2.4).
    # Para non-2xx (407 ACK): misma transacción, copiar Via del response.
    status_val = getattr(getattr(request, "status", None), "value", 0)
    if status_val == 200:
        new_branch = "z9hG4bK" + self.gen_call_id()[:8]
        via_line = f"Via: SIP/2.0/UDP {self.myIP}:{self.myPort};branch={new_branch}\r\n"
    else:
        via_line = self._gen_response_via_header(request)

    ack = f"ACK {request_uri} SIP/2.0\r\n"
    ack += via_line
    ack += "Max-Forwards: 70\r\n"
    ack += route_header
    # To: raw no incluye el tag (pyVoIP lo separa al parsear)
    to_raw = request.headers["To"]["raw"]
    to_tag = request.headers["To"].get("tag", "")
    if to_tag:
        ack += f"To: {to_raw};tag={to_tag}\r\n"
    else:
        ack += f"To: {to_raw}\r\n"
    # From: tag es el nuestro guardado en tagLibrary
    from_raw = request.headers["From"]["raw"]
    if tag:
        ack += f"From: {from_raw};tag={tag}\r\n"
    else:
        ack += f"From: {from_raw}\r\n"
    ack += f"Call-ID: {request.headers['Call-ID']}\r\n"
    ack += f"CSeq: {request.headers['CSeq']['check']} ACK\r\n"
    ack += f"User-Agent: pyVoIP {_pv.__version__}\r\n"
    ack += "Content-Length: 0\r\n\r\n"
    logger.info(
        f"ACK → {request_uri} | To-tag={to_tag} | From-tag={tag[:8] if tag else ''}"
        f" | Route={'sí' if route_header else 'no'}"
    )
    logger.debug(f"ACK completo:\n{ack}")
    return ack

_pv_sip.SIPClient.gen_ack = _patched_gen_ack


# 4) _callback_RESP_OK: pyVoIP tiene dos bugs que impiden enviar el ACK al 200 OK:
#
#    a) Race condition: el recv_loop puede procesar el 200 OK antes de que
#       VoIPPhone.call() haya guardado el VoIPCall en self.calls, por lo que
#       call_id not in self.calls → return sin enviar ACK.
#
#    b) Si VoIPCall.answered() lanza cualquier excepción (p.ej. KeyError al
#       procesar codec 101 sin rtpmap), gen_ack() nunca se llama porque está
#       DESPUÉS de answered() y la excepción la captura silenciosamente recv().
#
#    Fix: enviar el ACK ANTES de llamar a answered(), con un pequeño retry para
#    la race condition, y capturar explícitamente los errores de answered().

def _patched_callback_RESP_OK(self, request):
    call_id = request.headers["Call-ID"]
    logger.debug(
        f"200 OK — Call-ID={call_id} | "
        f"To={request.headers.get('To')} | "
        f"From={request.headers.get('From')} | "
        f"Contact={request.headers.get('Contact')} | "
        f"Record-Route={request.headers.get('Record-Route')}"
    )

    # Retry breve para la race condition (lock liberado pero call aún no guardado)
    if call_id not in self.calls:
        for _ in range(20):   # hasta 200 ms
            time.sleep(0.01)
            if call_id in self.calls:
                break

    # Enviar ACK siempre, independientemente del estado de self.calls
    try:
        ack = self.sip.gen_ack(request)
        self.sip.out.sendto(ack.encode("utf8"), (self.server, self.port))
    except Exception as _e:
        logger.error(f"Error enviando ACK al 200 OK: {_e}")

    if call_id not in self.calls:
        logger.warning(f"200 OK sin VoIPCall para Call-ID={call_id} — ACK enviado de todos modos")
        return

    try:
        self.calls[call_id].answered(request)
    except Exception as _e:
        logger.error(f"VoIPCall.answered() falló: {_e}\n{traceback.format_exc()}")

    # Guardar Record-Route del 200 OK en el request del diálogo para que
    # gen_bye pueda incluirlo como Route header (sin él el proxy no reenvía
    # el BYE al B2BUA interno y la llamada queda abierta en el interlocutor).
    rr = request.headers.get("Record-Route")
    if rr and call_id in self.calls:
        self.calls[call_id].request.headers["Record-Route"] = rr

VoIPPhone._callback_RESP_OK = _patched_callback_RESP_OK


# 5) RTPClient.encode_packet: pyVoIP bug — PCMA llama encode_pcmu (µ-law) en lugar
#    de encode_pcma (A-law). La solución completa es hacer encode_packet un
#    pass-through y pre-encodificar desde int16 en _start_audio, lo que además
#    evita la pérdida de calidad de int16→int8→codec.
import pyVoIP.RTP as _pv_rtp

# 5b) gen_bye: igual que el ACK, el BYE debe incluir Route del Record-Route
#     del 200 OK para que el proxy (Kamailio) reenvíe el BYE al B2BUA interno.
#     Sin Route, el proxy lo ignora → el interlocutor no recibe el BYE → llamada
#     queda abierta en su lado aunque nosotros ya hayamos colgado.

def _patched_gen_bye(self, request):
    import re as _re2
    import pyVoIP as _pv2
    tag = self.tagLibrary.get(request.headers["Call-ID"], "")

    # Request-URI: Contact del 200 OK (actualizado por answered() en el request)
    contact_raw = request.headers.get("Contact", "")
    m = _re2.search(r"<([^>]+)>", str(contact_raw))
    request_uri = m.group(1) if m else str(contact_raw).strip("<").strip(">")
    if not request_uri:
        request_uri = request.headers["To"]["raw"].strip("<").strip(">")

    new_branch = "z9hG4bK" + self.gen_call_id()[:8]
    bye  = f"BYE {request_uri} SIP/2.0\r\n"
    bye += f"Via: SIP/2.0/UDP {self.myIP}:{self.myPort};branch={new_branch}\r\n"
    bye += "Max-Forwards: 70\r\n"

    rr = request.headers.get("Record-Route")
    if rr:
        bye += f"Route: {rr}\r\n"

    fromH = request.headers["From"]["raw"]
    toH   = request.headers["To"]["raw"]
    if request.headers["From"]["tag"] == tag:
        bye += f"From: {fromH};tag={tag}\r\n"
        to_tag = request.headers["To"].get("tag", "")
        bye += (f"To: {toH};tag={to_tag}\r\n" if to_tag else f"To: {toH}\r\n")
    else:
        bye += f"To: {fromH};tag={request.headers['From']['tag']}\r\n"
        bye += f"From: {toH};tag={tag}\r\n"

    cseq = int(request.headers["CSeq"]["check"]) + 1
    bye += f"Call-ID: {request.headers['Call-ID']}\r\n"
    bye += f"CSeq: {cseq} BYE\r\n"
    bye += f"Contact: <sip:{self.username}@{self.myIP}:{self.myPort}>\r\n"
    bye += f"User-Agent: pyVoIP {_pv2.__version__}\r\n"
    bye += "Content-Length: 0\r\n\r\n"
    logger.info(f"BYE → {request_uri} | Route={'sí' if rr else 'no'}")
    return bye

_pv_sip.SIPClient.gen_bye = _patched_gen_bye


_pv_rtp.RTPClient.encode_packet = lambda self, payload: payload


# 6) RTPClient.trans: añade soporte de flag _stop_trans por instancia.
#    Sin este parche, trans() sigue enviando silencio desde pmout vacío
#    mientras nuestro mic_thread envía RTP directamente → dos streams con
#    distinto SSRC → el servidor confunde el flujo de audio.
import warnings as _warnings

def _patched_rtp_trans(self) -> None:
    while self.NSD:
        if getattr(self, "_stop_trans", False):
            return
        last_sent = time.monotonic_ns()
        payload = self.pmout.read()
        payload = self.encode_packet(payload)
        packet = b"\x80"
        packet += chr(int(self.preference)).encode("utf8")
        try:
            packet += self.outSequence.to_bytes(2, byteorder="big")
        except OverflowError:
            self.outSequence = 0
        try:
            packet += self.outTimestamp.to_bytes(4, byteorder="big")
        except OverflowError:
            self.outTimestamp = 0
        packet += self.outSSRC.to_bytes(4, byteorder="big")
        packet += payload
        try:
            self.sout.sendto(packet, (self.outIP, self.outPort))
        except OSError:
            _warnings.warn("RTP Packet failed to send!", RuntimeWarning, stacklevel=2)
        self.outSequence += 1
        self.outTimestamp += len(payload)
        delay = (1 / self.preference.rate) * 160
        sleep_time = max(0, delay - (time.monotonic_ns() - last_sent) / 1_000_000_000)
        time.sleep(sleep_time)

_pv_rtp.RTPClient.trans = _patched_rtp_trans
# ─────────────────────────────────────────────────────────────────────────────

# Tiempo máximo (segundos) que una llamada puede estar en estado DIALING/RINGING
# antes de considerarla fallida. Cubre el bug de pyVoIP que ignora respuestas 500
# a INVITE en lugar de terminar la llamada (TODO en SIP.py:913 de pyVoIP).
CALL_TIMEOUT_SECONDS = 60


class Status(Enum):
    DISCONNECTED = auto()
    CONNECTING = auto()
    REGISTERED = auto()
    INCOMING = auto()
    CALLING = auto()
    IN_CALL = auto()
    ERROR = auto()


LOCAL_SIP_PORT = 5080
RTP_PORT_LOW = 10000
RTP_PORT_HIGH = 10100


class SIPClient:
    def __init__(self):
        self._phone: Optional[VoIPPhone] = None
        self._status = Status.DISCONNECTED
        self._current_call: Optional[VoIPCall] = None
        self._audio = RTPAudio(local_port=10000)
        self._monitor_thread: Optional[threading.Thread] = None

        self._stop_monitor = threading.Event()

        # Callbacks — la UI los envuelve con after() para thread safety
        self.on_status_change: Optional[Callable[[Status], None]] = None
        self.on_incoming_call: Optional[Callable[[str], None]] = None  # caller_id
        self.on_call_ended: Optional[Callable[[], None]] = None
        # on_transfer_update(extension, status_code): 1xx=en curso, 200=confirmado, 4xx/5xx=error
        self.on_transfer_update: Optional[Callable[[str, int], None]] = None

        # ── Ajustes de audio (modificables en tiempo real desde la UI) ──────
        # El mic_thread los lee en cada paquete (20 ms) → aplican inmediatamente.
        self.noise_gate_dbfs: float = config.AUDIO_NOISE_GATE_DBFS
        self.echo_gate_rms:   int   = 1200
        self.echo_gate_factor: float = 0.08

    @property
    def status(self) -> Status:
        return self._status

    # ─── Ciclo de vida ───────────────────────────────────────────────────────────

    def connect(self):
        threading.Thread(target=self._connect_thread, daemon=True, name="sip-connect").start()

    def _connect_thread(self):
        self._set_status(Status.CONNECTING)
        try:
            my_ip = _local_ip()
            logger.info(f"IP local detectada: {my_ip}")
            self._phone = VoIPPhone(
                server=config.SIP_SERVER,
                port=config.SIP_PORT,
                username=config.SIP_USER,
                password=config.SIP_PASSWORD,
                myIP=my_ip,
                callCallback=self._incoming_call_handler,
                sipPort=LOCAL_SIP_PORT,
                rtpPortLow=RTP_PORT_LOW,
                rtpPortHigh=RTP_PORT_HIGH,
            )
            # El servidor PekePBX exige Min-Expires: 300.
            # pyVoIP usa 120 por defecto → servidor rechaza con 423 Interval Too Brief.
            self._phone.sip.default_expires = 300
            self._phone.start()
            self._set_status(Status.REGISTERED)
            logger.info("SIP registrado correctamente")
        except InvalidAccountInfoError as e:
            # Credenciales incorrectas (401/403 definitivo tras reintentos)
            logger.error(f"Credenciales SIP incorrectas: {e}")
            self._set_status(Status.ERROR)
        except RetryRequiredError as e:
            # El servidor devolvió 500 repetidamente durante el registro.
            # pyVoIP reintenta internamente pero acaba lanzando esto si persiste.
            logger.error(f"Servidor SIP respondió 500 durante registro: {e}")
            self._set_status(Status.ERROR)
        except TimeoutError as e:
            logger.error(f"Timeout de registro SIP: {e}")
            self._set_status(Status.ERROR)
        except Exception as e:
            logger.error(f"Error de conexión SIP: {e}")
            self._set_status(Status.ERROR)

    def disconnect(self):
        self._audio.stop()
        if self._phone:
            try:
                self._phone.stop()
            except Exception:
                pass
            self._phone = None
        self._current_call = None
        self._set_status(Status.DISCONNECTED)

    def reconnect(self):
        self.disconnect()
        time.sleep(1)
        self.connect()

    def _on_sip_fatal(self):
        """pyVoIP llama aquí cuando el registro falla demasiadas veces y cierra el socket."""
        logger.error("pyVoIP fatal: registro SIP fallido repetidamente — reconectando")
        self._phone = None
        self._set_status(Status.ERROR)
        time.sleep(5)
        self.connect()

    def _sip_socket_ok(self) -> bool:
        """Comprueba que el socket SIP sigue abierto y válido."""
        try:
            return bool(self._phone and self._phone.sip.s and self._phone.sip.s.fileno() != -1)
        except Exception:
            return False

    # ─── Llamadas ────────────────────────────────────────────────────────────────

    def make_call(self, number: str) -> bool:
        if self._status != Status.REGISTERED or not self._phone:
            return False
        if not self._sip_socket_ok():
            logger.warning("Socket SIP inválido antes de llamar — reconectando")
            threading.Thread(target=self.reconnect, daemon=True).start()
            return False
        try:
            self._stop_monitor = threading.Event()
            call = self._phone.call(number)
            self._current_call = call
            self._set_status(Status.CALLING)
            self._start_call_monitor(call, outgoing=True)
            return True
        except Exception as e:
            logger.error(f"Error al llamar a '{number}': {e}\n{traceback.format_exc()}")
            self._set_status(Status.REGISTERED)
            return False

    def answer(self):
        if self._current_call and self._status == Status.INCOMING:
            try:
                self._current_call.answer()
                self._set_status(Status.IN_CALL)
                self._start_audio(self._current_call)
            except Exception as e:
                logger.error(f"Error al contestar: {e}")

    def deny(self):
        self._stop_monitor.set()
        if self._current_call and self._status == Status.INCOMING:
            try:
                self._current_call.deny()
            except Exception:
                pass
            self._current_call = None
            self._set_status(Status.REGISTERED)

    def transfer(self, extension: str) -> bool:
        """
        Transferencia supervisada via REFER.
        Envía REFER al interlocutor y monitorea NOTIFYs hasta recibir 200 OK
        (extensión destino contestó) antes de colgar la llamada original.
        """
        if not self._current_call or self._status != Status.IN_CALL:
            return False

        call = self._current_call
        request = call.request
        sip = self._phone.sip
        import re as _re_t

        call_id = request.headers["Call-ID"]
        tag = sip.tagLibrary.get(call_id, "")

        # Request-URI: Contact del 200 OK (guardado por _patched_callback_RESP_OK)
        contact_raw = request.headers.get("Contact", "")
        m = _re_t.search(r"<([^>]+)>", str(contact_raw))
        request_uri = m.group(1) if m else str(contact_raw).strip("<").strip(">")
        if not request_uri:
            request_uri = request.headers["To"]["raw"].strip("<").strip(">")

        cseq = int(request.headers["CSeq"]["check"]) + 1
        from_raw = request.headers["From"]["raw"]
        to_raw   = request.headers["To"]["raw"]
        to_tag   = request.headers["To"].get("tag", "")
        rr       = request.headers.get("Record-Route")
        route_h  = f"Route: {rr}\r\n" if rr else ""

        new_branch = "z9hG4bK" + sip.gen_call_id()[:8]
        refer_to   = f"sip:{extension}@{config.SIP_SERVER}"

        refer  = f"REFER {request_uri} SIP/2.0\r\n"
        refer += f"Via: SIP/2.0/UDP {sip.myIP}:{sip.myPort};branch={new_branch}\r\n"
        refer += "Max-Forwards: 70\r\n"
        refer += route_h
        refer += f"From: {from_raw};tag={tag}\r\n"
        refer += (f"To: {to_raw};tag={to_tag}\r\n" if to_tag else f"To: {to_raw}\r\n")
        refer += f"Call-ID: {call_id}\r\n"
        refer += f"CSeq: {cseq} REFER\r\n"
        refer += f"Contact: <sip:{sip.username}@{sip.myIP}:{sip.myPort}>\r\n"
        refer += f"Refer-To: <{refer_to}>\r\n"
        refer += "Content-Length: 0\r\n\r\n"

        # Actualizar CSeq guardado para que BYE use el número correcto
        request.headers["CSeq"]["check"] = str(cseq)

        def _on_notify(code: int):
            if self.on_transfer_update:
                self.on_transfer_update(extension, code)
            if code == 200:
                _refer_callbacks.pop(call_id, None)
                # Pequeño retardo para que el 200 OK llegue al destino antes del BYE
                threading.Timer(0.8, self.hangup).start()
            elif code >= 400:
                _refer_callbacks.pop(call_id, None)

        _refer_callbacks[call_id] = _on_notify

        try:
            sip.out.sendto(refer.encode("utf8"), (sip.server, sip.port))
            logger.info(f"REFER enviado → {refer_to}")
            return True
        except Exception as e:
            logger.error(f"Error enviando REFER: {e}")
            _refer_callbacks.pop(call_id, None)
            return False

    def cancel_transfer(self):
        """Cancela la supervisión del REFER (no revierte la transferencia en curso)."""
        if self._current_call:
            call_id = self._current_call.request.headers.get("Call-ID", "")
            _refer_callbacks.pop(call_id, None)

    def hangup(self):
        self._stop_monitor.set()
        if self._current_call:
            try:
                self._current_call.hangup()
            except Exception:
                pass
        self._audio.stop()
        self._current_call = None
        if self._status not in (Status.DISCONNECTED, Status.ERROR):
            self._set_status(Status.REGISTERED)

    # ─── Callbacks internos ──────────────────────────────────────────────────────

    def _incoming_call_handler(self, call: VoIPCall):
        # Rechazar si ya hay una llamada activa
        if self._status not in (Status.REGISTERED, Status.DISCONNECTED, Status.ERROR):
            logger.info("Llamada entrante rechazada — ya hay una llamada activa")
            try:
                call.deny()
            except Exception:
                pass
            return

        self._stop_monitor = threading.Event()
        self._current_call = call
        caller = self._extract_caller(call)
        logger.info(f"Llamada entrante de: {caller}")
        self._set_status(Status.INCOMING)
        if self.on_incoming_call:
            self.on_incoming_call(caller)
        self._start_call_monitor(call, outgoing=False)

    def _start_call_monitor(self, call: VoIPCall, outgoing: bool):
        stop_event = self._stop_monitor

        def monitor():
            start_time = time.monotonic()
            reason = "ended"
            last_state = None

            while True:
                if stop_event.is_set():
                    logger.debug("Monitor detenido por hangup/deny")
                    reason = "hangup"
                    break

                state = call.state
                if state != last_state:
                    logger.info(f"Call state: {last_state} → {state}")
                    last_state = state

                if state == CallState.ANSWERED and self._status != Status.IN_CALL:
                    self._set_status(Status.IN_CALL)
                    if outgoing:
                        self._start_audio(call)

                elif state == CallState.ENDED:
                    break

                elif state in (CallState.DIALING, CallState.RINGING):
                    elapsed = time.monotonic() - start_time
                    if elapsed > CALL_TIMEOUT_SECONDS:
                        logger.warning(
                            f"Llamada en estado {state.value} tras {elapsed:.0f}s "
                            f"— posible error del servidor ignorado por pyVoIP. "
                            f"Forzando fin de llamada."
                        )
                        try:
                            call.hangup()
                        except Exception:
                            pass
                        reason = "timeout"
                        break

                time.sleep(0.3)

            # Cleanup único para todos los casos de salida
            if reason != "hangup":
                # hangup() ya limpió el estado; evitar doble callback
                self._audio.stop()
                self._current_call = None
                if self._status not in (Status.DISCONNECTED, Status.ERROR):
                    self._set_status(Status.REGISTERED)
                if self.on_call_ended:
                    self.on_call_ended()

        t = threading.Thread(target=monitor, daemon=True, name="call-monitor")
        t.start()

    @staticmethod
    def _find_audio_device(name: str, kind: str) -> int | None:
        """Busca el índice del dispositivo por nombre parcial (case-insensitive).
        kind: 'input' o 'output'. Retorna None para usar el dispositivo por defecto."""
        import sounddevice as sd
        if not name:
            return None
        name_lower = name.lower()
        key = "max_input_channels" if kind == "input" else "max_output_channels"
        for i, dev in enumerate(sd.query_devices()):
            if name_lower in dev["name"].lower() and dev[key] > 0:
                logger.info(f"Dispositivo {kind}: [{i}] {dev['name']}")
                return i
        logger.warning(f"Dispositivo {kind} '{name}' no encontrado — usando dispositivo por defecto")
        return None

    def _start_audio(self, call: VoIPCall):
        """Audio de la llamada activa.

        Mejoras:
        1. Bypass de trans() de pyVoIP: el mic_thread envía RTP directamente
           con el mismo socket/SSRC heredado → sin drift de timing entre dos
           loops de 20 ms independientes.
        2. Jitter buffer limitado (MAX_JITTER_BYTES) para evitar lag acumulado
           en pmin cuando el remoto envía ligeramente más rápido que consumimos.
        3. Echo gate: atenua el micro cuando el altavoz suena fuerte, reduciendo
           el eco acústico del altavoz sobre el micrófono.
        """
        import sounddevice as sd
        import numpy as np
        import audioop

        CHUNK            = 160
        RATE             = 8000
        MAX_JITTER_BYTES = CHUNK * 4   # 80 ms máx en buffer de recepción
        NOISE_GATE_HOLD  = 10          # paquetes (200 ms) de retención tras bajar umbral
        # self.noise_gate_dbfs, self.echo_gate_rms, self.echo_gate_factor
        # se leen en cada paquete → cambios aplicados inmediatamente desde la UI

        dev_in  = self._find_audio_device(config.AUDIO_INPUT,  "input")
        dev_out = self._find_audio_device(config.AUDIO_OUTPUT, "output")

        if not call.RTPClients:
            logger.error("Sin RTPClients — no se puede iniciar audio")
            return
        rtp_cli = call.RTPClients[0]
        codec   = rtp_cli.preference or _pv_rtp.PayloadType.PCMU
        pt      = int(codec)
        logger.info(f"Codec audio: {codec.name} (PT={pt})")

        # Parar trans() de pyVoIP y continuar desde su secuencia/timestamp
        for c in call.RTPClients:
            c._stop_trans = True
        time.sleep(0.055)
        rtp_seq  = rtp_cli.outSequence
        rtp_ts   = rtp_cli.outTimestamp
        rtp_ssrc = rtp_cli.outSSRC
        out_sock = rtp_cli.sout
        out_addr = (rtp_cli.outIP, rtp_cli.outPort)

        def encode_mic(s16: np.ndarray) -> bytes:
            raw = s16.astype(np.int16).tobytes()
            return audioop.lin2alaw(raw, 2) if codec == _pv_rtp.PayloadType.PCMA else audioop.lin2ulaw(raw, 2)

        def decode_rtp(u8: bytes) -> np.ndarray:
            s8  = audioop.bias(u8, 1, -128)
            s16 = audioop.lin2lin(s8, 1, 2)
            return np.frombuffer(s16, dtype="int16").reshape(-1, 1)

        def trim_pmin() -> None:
            pm = rtp_cli.pmin
            with pm.bufferLock:
                pos = pm.buffer.tell()
                pm.buffer.seek(0, 2)
                end = pm.buffer.tell()
                pm.buffer.seek(pos)
                excess = (end - pos) - MAX_JITTER_BYTES
            if excess > 0:
                with pm.bufferLock:
                    pm.buffer.seek(excess, 1)

        silence_pcm  = np.zeros((CHUNK, 1), dtype="int16")
        received_rms = 0  # compartida entre hilos (asignación atómica en CPython)

        def mic_thread():
            nonlocal rtp_seq, rtp_ts, received_rms
            hold = 0  # contador de paquetes de hold tras bajar del umbral
            try:
                with sd.InputStream(
                    samplerate=RATE, channels=1, dtype="int16",
                    blocksize=CHUNK, device=dev_in, latency="low",
                ) as stream:
                    while call.state == CallState.ANSWERED:
                        data, _ = stream.read(CHUNK)
                        rms = int(np.sqrt(np.mean(data.astype(np.int32) ** 2)))
                        ng_rms = int(32767 * 10 ** (self.noise_gate_dbfs / 20))

                        if received_rms > self.echo_gate_rms:
                            # Echo gate: interlocutor habla → atenuar micro
                            data = (data * self.echo_gate_factor).astype(np.int16)
                            hold = 0
                        elif rms > ng_rms:
                            hold = NOISE_GATE_HOLD
                        elif hold > 0:
                            hold -= 1
                        else:
                            data = np.zeros_like(data)

                        payload = encode_mic(data)
                        hdr = struct.pack(
                            "!BBHII",
                            0x80, pt,
                            rtp_seq & 0xFFFF,
                            rtp_ts  & 0xFFFFFFFF,
                            rtp_ssrc,
                        )
                        try:
                            out_sock.sendto(hdr + payload, out_addr)
                        except OSError:
                            pass
                        rtp_seq += 1
                        rtp_ts  += CHUNK
            except Exception as e:
                logger.error(f"Error audio mic: {e}")

        def speaker_thread():
            nonlocal received_rms
            try:
                with sd.OutputStream(
                    samplerate=RATE, channels=1, dtype="int16",
                    blocksize=CHUNK, device=dev_out, latency="low",
                ) as stream:
                    while call.state == CallState.ANSWERED:
                        trim_pmin()
                        rtp_u8 = call.read_audio(CHUNK, blocking=False)
                        if rtp_u8 and len(rtp_u8) == CHUNK:
                            pcm = decode_rtp(rtp_u8)
                            received_rms = int(
                                np.sqrt(np.mean(pcm.astype(np.int32) ** 2))
                            )
                            stream.write(pcm)
                        else:
                            received_rms = 0
                            stream.write(silence_pcm)
            except Exception as e:
                logger.error(f"Error audio altavoz: {e}")

        threading.Thread(target=mic_thread,     daemon=True, name="audio-mic").start()
        threading.Thread(target=speaker_thread, daemon=True, name="audio-spk").start()

    # ─── Utilidades ──────────────────────────────────────────────────────────────

    def _set_status(self, status: Status):
        self._status = status
        if self.on_status_change:
            self.on_status_change(status)

    def _extract_caller(self, call: VoIPCall) -> str:
        try:
            from_header = call.request.headers.get("From", {})
            if isinstance(from_header, dict):
                raw = from_header.get("raw", "")
            else:
                raw = str(from_header)
            import re
            m = re.search(r'"([^"]+)"', raw)
            if m:
                return m.group(1)
            m = re.search(r"sip:([^@>]+)", raw)
            if m:
                return m.group(1)
        except Exception:
            pass
        return "Desconocido"
