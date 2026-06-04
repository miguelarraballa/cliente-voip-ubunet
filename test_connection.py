"""
Prueba de conectividad SIP. Carga la configuración desde .env.
Un 401 Unauthorized significa que el protocolo funciona (el servidor responde).
"""
import os
import socket
import ssl
import time
import uuid
from dotenv import load_dotenv

load_dotenv()

SERVER = os.getenv("SIP_SERVER", "")
PORT = int(os.getenv("SIP_PORT", "5060"))
USER = os.getenv("SIP_USER", "")
TIMEOUT = 5


def build_register(transport: str) -> str:
    branch = "z9hG4bK" + uuid.uuid4().hex[:8]
    call_id = uuid.uuid4().hex
    tag = uuid.uuid4().hex[:8]
    local_ip = "127.0.0.1"  # dummy, no importa para el test

    return (
        f"REGISTER sip:{SERVER} SIP/2.0\r\n"
        f"Via: SIP/2.0/{transport} {local_ip}:5080;branch={branch}\r\n"
        f"Max-Forwards: 70\r\n"
        f"From: <sip:{USER}@{SERVER}>;tag={tag}\r\n"
        f"To: <sip:{USER}@{SERVER}>\r\n"
        f"Call-ID: {call_id}\r\n"
        f"CSeq: 1 REGISTER\r\n"
        f"Contact: <sip:{USER}@{local_ip}:5080;transport={transport.lower()}>\r\n"
        f"Expires: 60\r\n"
        f"Content-Length: 0\r\n"
        f"\r\n"
    )


def test_udp():
    print("\n── TEST UDP ──────────────────────────────")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(TIMEOUT)
    msg = build_register("UDP").encode()
    try:
        sock.sendto(msg, (SERVER, PORT))
        print(f"  Enviado REGISTER por UDP a {SERVER}:{PORT}")
        data, addr = sock.recvfrom(4096)
        first_line = data.decode(errors="replace").split("\r\n")[0]
        print(f"  Respuesta: {first_line}")
        return True
    except socket.timeout:
        print("  Sin respuesta (timeout) — UDP probablemente no aceptado")
        return False
    except Exception as e:
        print(f"  Error: {e}")
        return False
    finally:
        sock.close()


def test_tcp():
    print("\n── TEST TCP ──────────────────────────────")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(TIMEOUT)
    msg = build_register("TCP").encode()
    try:
        sock.connect((SERVER, PORT))
        print(f"  Conexión TCP establecida a {SERVER}:{PORT}")
        sock.sendall(msg)
        print(f"  Enviado REGISTER por TCP")
        data = sock.recv(4096)
        first_line = data.decode(errors="replace").split("\r\n")[0]
        print(f"  Respuesta: {first_line}")
        return True
    except socket.timeout:
        print("  Sin respuesta (timeout)")
        return False
    except ConnectionRefusedError:
        print("  Conexión rechazada — TCP no aceptado en este puerto")
        return False
    except Exception as e:
        print(f"  Error: {e}")
        return False
    finally:
        sock.close()


def test_tls():
    print("\n── TEST TLS ──────────────────────────────")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    raw.settimeout(TIMEOUT)
    msg = build_register("TLS").encode()
    try:
        wrapped = ctx.wrap_socket(raw, server_hostname=SERVER)
        wrapped.connect((SERVER, PORT))
        print(f"  Handshake TLS completado con {SERVER}:{PORT}")
        print(f"  Protocolo: {wrapped.version()}, Cipher: {wrapped.cipher()[0]}")
        wrapped.sendall(msg)
        print(f"  Enviado REGISTER por TLS")
        data = wrapped.recv(4096)
        first_line = data.decode(errors="replace").split("\r\n")[0]
        print(f"  Respuesta: {first_line}")
        return True
    except ssl.SSLError as e:
        print(f"  Error SSL: {e}")
        return False
    except socket.timeout:
        print("  Sin respuesta (timeout)")
        return False
    except ConnectionRefusedError:
        print("  Conexión rechazada")
        return False
    except Exception as e:
        print(f"  Error: {e}")
        return False
    finally:
        try:
            raw.close()
        except:
            pass


if __name__ == "__main__":
    print(f"Probando conectividad SIP con {SERVER}:{PORT}")
    print("(Un '401 Unauthorized' significa que el protocolo funciona)\n")

    udp_ok = test_udp()
    tcp_ok = test_tcp()
    tls_ok = test_tls()

    print("\n── RESUMEN ───────────────────────────────")
    print(f"  UDP : {'✓ Responde' if udp_ok else '✗ No responde'}")
    print(f"  TCP : {'✓ Responde' if tcp_ok else '✗ No responde'}")
    print(f"  TLS : {'✓ Responde' if tls_ok else '✗ No responde'}")
